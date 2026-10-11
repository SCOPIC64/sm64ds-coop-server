"""Exercise the managed process; WGS_SERVER_EXE also tests a packaged build."""
import asyncio
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest import mock
import urllib.request

from wgs.server import ConsoleOutput, serve

ROOT = Path(__file__).resolve().parents[1]


def free_port(kind):
    with socket.socket(socket.AF_INET, kind) as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


class BlockingConsole:
    encoding = 'utf-8'

    def __init__(self):
        self.entered = threading.Event()
        self.release = threading.Event()

    def write(self, text):
        self.entered.set()
        self.release.wait(10)
        return len(text)

    def flush(self):
        pass


class ConsoleChecks(unittest.IsolatedAsyncioTestCase):
    def test_blocked_output_has_bounded_memory(self):
        sink = BlockingConsole()
        output = ConsoleOutput(sink, capacity=4, chunk_size=16)
        try:
            output.write('block writer')
            self.assertTrue(sink.entered.wait(2))
            started = time.monotonic()
            for _ in range(1000):
                output.write('x' * 64)
                output.flush()
            self.assertLess(time.monotonic() - started, 1)
            self.assertEqual(output.queue.qsize(), 4)
            self.assertGreater(output.dropped_chunks, 0)
            self.assertTrue(all(len(chunk) <= 16 for chunk in output.queue.queue))
        finally:
            output.stop()
            sink.release.set()
            output.worker.join(timeout=2)
        self.assertFalse(output.worker.is_alive())

    def test_closed_console_does_not_raise(self):
        sink = io.StringIO()
        sink.close()
        output = ConsoleOutput(sink)
        output.write('manager detached')
        output.worker.join(timeout=2)
        self.assertFalse(output.worker.is_alive())
        self.assertTrue(output.closed)
        self.assertEqual(output.write('still running'), 13)

    async def test_blocked_console_keeps_lobby_and_relay_alive(self):
        sink = BlockingConsole()
        args = SimpleNamespace(lobby_port=free_port(socket.SOCK_STREAM),
                               relay_port=free_port(socket.SOCK_DGRAM), max_players=16)
        loop = asyncio.get_running_loop()
        task = None
        with mock.patch('sys.stdout', sink), mock.patch('sys.stdin', io.StringIO()):
            task = asyncio.create_task(serve(args, '127.0.0.1', '127.0.0.1'))
            try:
                self.assertTrue(await asyncio.to_thread(sink.entered.wait, 3))
                url = 'http://127.0.0.1:%d/port/lobby/health' % args.lobby_port

                def health():
                    with urllib.request.urlopen(url, timeout=2) as response:
                        return json.load(response)

                self.assertTrue((await asyncio.to_thread(health))['ok'])
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as parent, \
                        socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as child:
                    for role, sock in enumerate((parent, child)):
                        sock.bind(('127.0.0.1', 0))
                        sock.setblocking(False)
                        await loop.sock_sendto(sock, b'SMRC' + bytes((1, role, 0, 0))
                                               + b'WGSTALL1', ('127.0.0.1', args.relay_port))
                        ack, _ = await asyncio.wait_for(loop.sock_recvfrom(sock, 64), 2)
                        self.assertEqual(ack, b'SMRA' + bytes((1, 0, 0, 0)) + b'WGSTALL1')
                    await loop.sock_sendto(parent, b'parent payload', ('127.0.0.1', args.relay_port))
                    payload, _ = await asyncio.wait_for(loop.sock_recvfrom(child, 64), 2)
                    self.assertEqual(payload, b'parent payload')
                    await loop.sock_sendto(child, b'child payload', ('127.0.0.1', args.relay_port))
                    payload, _ = await asyncio.wait_for(loop.sock_recvfrom(parent, 64), 2)
                    self.assertEqual(payload, b'child payload')
                self.assertFalse(sink.release.is_set())
            finally:
                if task is not None:
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
                sink.release.set()


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

    def wait_for_health(self, proc):
        deadline = time.monotonic() + 20
        while True:
            try:
                return self.health()
            except OSError:
                if proc.poll() is not None or time.monotonic() > deadline:
                    self.log.seek(0)
                    self.fail('Server not ready: ' + self.log.read().decode(errors='replace'))
                time.sleep(.1)

    def test_lobby_relay_and_shutdown(self):
        proc = self.start()
        health = self.wait_for_health(proc)
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

    def test_closed_udp_peer_does_not_stop_new_connections(self):
        proc = self.start()
        self.wait_for_health(proc)

        def join(sock, code, role):
            sock.settimeout(2)
            sock.connect(('127.0.0.1', self.udp))
            sock.send(b'SMRC' + bytes((1, role, 0, 0)) + code)
            self.assertEqual(sock.recv(64), b'SMRA' + bytes((1, 0, 0, 0)) + code)

        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as parent:
            join(parent, b'WGSCLOSE', 0)
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as departed:
                join(departed, b'WGSCLOSE', 1)
            # Forwarding to a now-closed localhost port elicits ICMP errors on
            # Windows. A live HTTP socket alone would miss a dead UDP reader.
            for _ in range(5):
                parent.send(b'payload after peer quit')
                time.sleep(.1)
            self.assertTrue(self.health()['ok'])
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as fresh_parent, \
                    socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as fresh_child:
                join(fresh_parent, b'WGSFRESH', 0)
                join(fresh_child, b'WGSFRESH', 1)
                fresh_parent.send(b'still forwarding')
                self.assertEqual(fresh_child.recv(64), b'still forwarding')
        proc.stdin.write(b'stop\n')
        proc.stdin.flush()
        self.assertEqual(proc.wait(timeout=10), 0)

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
