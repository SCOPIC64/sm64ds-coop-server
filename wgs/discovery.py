"""Signed discovery of the current HTTPS lobby over the public game relay.

The Windows user owns a non-exported RSA key in the Windows key store.
Only its public key is distributed. No game credentials travel over UDP.
"""
import base64
import ctypes
from ctypes import wintypes as W
import json
from pathlib import Path
import sys
import time
from urllib.parse import urlsplit


class WindowsSigner:
    def __init__(self, name='SM64DS-Coop-Discovery-v1'):
        if sys.platform != 'win32':
            raise RuntimeError('WGS tunnel discovery requires Windows')
        self.api = ctypes.WinDLL('advapi32', use_last_error=True)
        signatures = {
            'CryptAcquireContextW': ([ctypes.POINTER(ctypes.c_size_t), W.LPCWSTR, W.LPCWSTR, W.DWORD, W.DWORD], W.BOOL),
            'CryptGenKey': ([ctypes.c_size_t, W.DWORD, W.DWORD, ctypes.POINTER(ctypes.c_size_t)], W.BOOL),
            'CryptGetUserKey': ([ctypes.c_size_t, W.DWORD, ctypes.POINTER(ctypes.c_size_t)], W.BOOL),
            'CryptExportKey': ([ctypes.c_size_t, ctypes.c_size_t, W.DWORD, W.DWORD, ctypes.c_void_p, ctypes.POINTER(W.DWORD)], W.BOOL),
            'CryptCreateHash': ([ctypes.c_size_t, W.DWORD, ctypes.c_size_t, W.DWORD, ctypes.POINTER(ctypes.c_size_t)], W.BOOL),
            'CryptHashData': ([ctypes.c_size_t, ctypes.c_void_p, W.DWORD, W.DWORD], W.BOOL),
            'CryptSignHashW': ([ctypes.c_size_t, W.DWORD, W.LPCWSTR, W.DWORD, ctypes.c_void_p, ctypes.POINTER(W.DWORD)], W.BOOL),
            'CryptDestroyHash': ([ctypes.c_size_t], W.BOOL),
            'CryptDestroyKey': ([ctypes.c_size_t], W.BOOL),
            'CryptReleaseContext': ([ctypes.c_size_t, W.DWORD], W.BOOL),
        }
        for function, (arguments, result) in signatures.items():
            fn = getattr(self.api, function); fn.argtypes = arguments; fn.restype = result
        self.provider = ctypes.c_size_t()
        if not self.api.CryptAcquireContextW(ctypes.byref(self.provider), name, None, 24, 0):
            if ctypes.get_last_error() & 0xffffffff != 0x80090016:
                raise ctypes.WinError(ctypes.get_last_error())
            self.ok(self.api.CryptAcquireContextW(ctypes.byref(self.provider), name, None, 24, 8))
        self.key = ctypes.c_size_t()
        if not self.api.CryptGetUserKey(self.provider, 2, ctypes.byref(self.key)):
            # Do not request CRYPT_EXPORTABLE: private material stays in Windows.
            self.ok(self.api.CryptGenKey(self.provider, 2, 2048 << 16, ctypes.byref(self.key)))

    @staticmethod
    def ok(success):
        if not success:
            raise ctypes.WinError(ctypes.get_last_error())

    def public_key(self):
        size = W.DWORD()
        self.ok(self.api.CryptExportKey(self.key, 0, 6, 0, None, ctypes.byref(size)))
        data = ctypes.create_string_buffer(size.value)
        self.ok(self.api.CryptExportKey(self.key, 0, 6, 0, data, ctypes.byref(size)))
        return base64.b64encode(data.raw[:size.value]).decode('ascii')

    def sign(self, data):
        digest = ctypes.c_size_t()
        self.ok(self.api.CryptCreateHash(self.provider, 0x800c, 0, 0, ctypes.byref(digest)))
        try:
            self.ok(self.api.CryptHashData(digest, data, len(data), 0))
            size = W.DWORD(256); signature = ctypes.create_string_buffer(256)
            self.ok(self.api.CryptSignHashW(digest, 2, None, 0, signature, ctypes.byref(size)))
            if size.value != 256:
                raise RuntimeError('Discovery requires an RSA-2048 signature')
            return signature.raw
        finally:
            self.api.CryptDestroyHash(digest)

    def close(self):
        self.api.CryptDestroyKey(self.key)
        self.api.CryptReleaseContext(self.provider, 0)


def lobby_origin(url):
    if not isinstance(url, str) or len(url) > 300:
        raise ValueError('Invalid lobby origin')
    parts = urlsplit(url)
    local = parts.scheme == 'http' and parts.hostname == '127.0.0.1'
    if (parts.scheme != 'https' and not local) or not parts.hostname or parts.path not in ('', '/') or parts.query or parts.fragment or parts.username or parts.password:
        raise ValueError('Discovery must advertise a public HTTPS origin')
    if not all(c in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-:' for c in parts.netloc):
        raise ValueError('Invalid lobby hostname')
    if parts.port is not None and not 1 <= parts.port <= 65535:
        raise ValueError('Invalid lobby port')
    return url.rstrip('/')


class Discovery:
    def __init__(self, manifest):
        self.manifest = Path(manifest)
        self.signer = WindowsSigner()
        self.window = 0
        self.total = 0
        self.clients = {}

    def response(self, packet, address):
        if len(packet) != 20 or packet[:4] != b'SMDC':
            return None
        window = int(time.monotonic())
        if window != self.window:
            self.window = window; self.total = 0; self.clients.clear()
        count = self.clients.get(address, 0)
        if self.total >= 32 or count >= 3:
            return None
        self.total += 1; self.clients[address] = count + 1
        try:
            if self.manifest.stat().st_size > 2048:
                return None
            data = json.loads(self.manifest.read_text(encoding='utf-8-sig'))
            url = lobby_origin(data['lobby_url'])
            body = b'SMDS' + packet[4:] + json.dumps({'lobby_url': url}, separators=(',', ':')).encode('ascii')
            return body + self.signer.sign(body)
        except (OSError, ValueError, KeyError, TypeError):
            # The tunnel may still be starting; do not send a stale fallback.
            return None

    def close(self):
        self.signer.close()
