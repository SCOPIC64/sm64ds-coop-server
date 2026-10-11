"""Direct launches must not trust arbitrary forwarding headers."""
import importlib.util
import os
from pathlib import Path
import unittest
from unittest.mock import patch


class Defaults(unittest.TestCase):
    def test_direct_client_cannot_choose_its_rate_limit_identity(self):
        source = Path(__file__).resolve().parents[1] / 'lobby/app/server.py'
        spec = importlib.util.spec_from_file_location('lobby_defaults', source)
        server = importlib.util.module_from_spec(spec)
        with patch.dict(os.environ, {}, clear=True):
            spec.loader.exec_module(server)
        handler = object.__new__(server.Handler)
        handler.client_address = ('192.0.2.10', 1234)
        handler.headers = {'X-Forwarded-For': '198.51.100.99'}
        self.assertEqual(handler.client_host(), '192.0.2.10')
        self.assertEqual(server.RELAY_ADDR, '127.0.0.1:41234')


if __name__ == '__main__':
    unittest.main()
