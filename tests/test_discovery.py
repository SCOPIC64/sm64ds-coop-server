"""Windows key-store identity, bounded signed discovery, and URL validation."""
import base64
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
from wgs.discovery import Discovery, WindowsSigner, lobby_origin


class Origins(unittest.TestCase):
    def test_origins(self):
        self.assertEqual(lobby_origin('https://example.trycloudflare.com/'), 'https://example.trycloudflare.com')
        for url in ('http://example.com', 'https://user:pass@example.com', 'https://example.com/path', 'https://example.com/#x', 'https://example.com/?q=1', None):
            with self.subTest(url=url), self.assertRaises(ValueError):
                lobby_origin(url)


@unittest.skipUnless(sys.platform == 'win32', 'Windows key store')
class WindowsDiscovery(unittest.TestCase):
    def test_identity_persists_without_exporting_private_key(self):
        one = WindowsSigner();two = WindowsSigner()
        try:
            self.assertEqual(one.public_key(), two.public_key())
            blob = base64.b64decode(one.public_key())
            self.assertEqual(len(blob), 276)
            self.assertEqual(blob[0], 6)  # PUBLICKEYBLOB, never PRIVATEKEYBLOB.
            self.assertEqual(blob[8:12], b'RSA1')
            self.assertEqual(len(one.sign(b'nonce and public lobby URL')), 256)
        finally:
            one.close();two.close()

    def test_discovery_is_bounded_and_follows_tunnel_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            manifest=Path(folder)/'tunnel.json'
            manifest.write_text(json.dumps({'lobby_url':'https://first.trycloudflare.com'}))
            discovery=Discovery(manifest)
            try:
                request=b'SMDC'+os.urandom(16);address=('127.0.0.1',50000)
                with mock.patch('wgs.discovery.time.monotonic', return_value=1000):
                    reply=discovery.response(request,address)
                    self.assertEqual(reply[:20],b'SMDS'+request[4:])
                    self.assertIn(b'first.trycloudflare.com',reply[20:-256])
                    self.assertLess(len(reply),788)
                    manifest.write_text(json.dumps({'lobby_url':'https://second.trycloudflare.com'}))
                    self.assertIn(b'second.trycloudflare.com',discovery.response(request,address)[20:-256])
                    self.assertIsNotNone(discovery.response(request,address))
                    self.assertIsNone(discovery.response(request,address))
                self.assertIsNone(discovery.response(b'SMDC'+b'x'*10000,address))
                manifest.write_text('{"lobby_url":"http://private.example"}')
                self.assertIsNone(discovery.response(request,('127.0.0.1',50001)))
            finally:
                discovery.close()
