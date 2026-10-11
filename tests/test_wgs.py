"""Exercise the managed process; WGS_SERVER_EXE also tests a packaged build."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def free_port(kind):
    with socket.socket(socket.AF_INET, kind) as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


class ManagedServer(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.config = Path(self.tmp.name) / 'server.json'
        self.config.write_text(json.dumps({'bind': '127.0.0.1', 'relay_public_host': '127.0.0.1'}))
        self.log = open(Path(self.tmp.name) / 'output.log', 'w+b')
        self.addCleanup(self.log.close)
        self.http = free_port(socket.SOCK_STREAM)
        self.udp = free_port(socket.SOCK_DGRAM)
        exe = os.environ.get('WGS_SERVER_EXE')
        self.cmd = ([exe] if exe else [sys.executable, '-m', 'wgs.server']) + [
            '--config', str(self.config), '-port', str(self.udp),
            '-maxplayers', '16', '--lobby-port', str(self.http)]

    def start(self):
        proc = subprocess.Popen(self.cmd, cwd=ROOT, stdin=subprocess.PIPE,
                                stdout=self.log, stderr=subprocess.STDOUT)
        def cleanup():
            if proc.poll() is None:
                proc.kill()
            proc.wait(timeout=10)
            proc.stdin.close()
        self.addCleanup(cleanup)
        return proc

    def health(self):
        with urllib.request.urlopen('http://127.0.0.1:%d/port/lobby/health' % self.http, timeout=1) as response:
            return json.load(response)

    def post(self, verb, body):
        req = urllib.request.Request('http://127.0.0.1:%d/port/lobby/%s' % (self.http, verb),
              data=json.dumps(body).encode(), headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=3) as response:
            return json.load(response)

    def test_lobby_relay_and_shutdown(self):
        proc = self.start()
        deadline = time.monotonic() + 20
        while True:
            try:
                health = self.health()
                break
            except OSError:
                if proc.poll() is not None or time.monotonic() > deadline:
                    self.log.seek(0)
                    self.fail('Server not ready: ' + self.log.read().decode(errors='replace'))
                time.sleep(.1)
        self.assertTrue(health['ok'])
        self.assertEqual(health['dial_max'], 16)
        room = self.post('create', {'v': 4, 'nick': 'wgs-check'})
        self.assertTrue(room['token'])
        self.post('leave', {'v': 4, 'room': room['room'], 'token': room['token']})
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as parent, socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as child:
            for role, sock in enumerate((parent, child)):
                sock.settimeout(3)
                sock.connect(('127.0.0.1', self.udp))
                sock.send(b'SMRC' + bytes((1, role, 0, 0)) + b'WGSCHECK')
                self.assertEqual(sock.recv(64), b'SMRA' + bytes((1, 0, 0, 0)) + b'WGSCHECK')
            parent.send(b'parent payload')
            self.assertEqual(child.recv(64), b'parent payload')
            child.send(b'child payload')
            self.assertEqual(parent.recv(64), b'child payload')
        proc.stdin.write(b'stop\n')
        proc.stdin.flush()
        self.assertEqual(proc.wait(timeout=10), 0)
        # A WGS stop/restart must release both listening sockets.
        for kind, port in ((socket.SOCK_STREAM, self.http), (socket.SOCK_DGRAM, self.udp)):
            with socket.socket(socket.AF_INET, kind) as sock:
                if sys.platform != 'win32':
                    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                sock.bind(('127.0.0.1', port))

    def test_invalid_config_exits(self):
        self.config.write_text('{"relay_public_host":"0.0.0.0"}')
        self.assertNotEqual(self.start().wait(timeout=20), 0)

    def test_udp_conflict_does_not_leave_lobby_running(self):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as occupied:
            if sys.platform == 'win32':
                occupied.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            occupied.bind(('127.0.0.1', self.udp))
            self.assertNotEqual(self.start().wait(timeout=20), 0)
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
                listener.bind(('127.0.0.1', self.http))

    def test_http_conflict_does_not_start_relay(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as occupied:
            occupied.bind(('127.0.0.1', self.http))
            occupied.listen()
            self.assertNotEqual(self.start().wait(timeout=20), 0)
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as listener:
                listener.bind(('127.0.0.1', self.udp))


if __name__ == '__main__':
    unittest.main()
