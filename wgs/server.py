"""Run the lobby and relay in one process managed by Windows Game Server."""
import argparse
import asyncio
import ipaddress
import io
import json
import os
from pathlib import Path
import queue
import signal
import socket
import sys
import threading
import time


class ConsoleOutput:
    """Keep a slow manager's output pipe off the server's event loop."""

    def __init__(self, stream, capacity=128, chunk_size=4096):
        self.stream = stream
        self.queue = queue.Queue(maxsize=capacity)
        self.chunk_size = chunk_size
        self.dropped_chunks = 0
        self.closed = False
        try:
            self.fd = stream.fileno()
        except (AttributeError, OSError, ValueError, io.UnsupportedOperation):
            self.fd = None
        self._stopping = threading.Event()
        self.worker = threading.Thread(target=self._write_output, daemon=True)
        self.worker.start()

    @property
    def encoding(self):
        return getattr(self.stream, 'encoding', 'utf-8')

    def write(self, text):
        for start in range(0, len(text), self.chunk_size):
            if self.closed:
                self.dropped_chunks += 1
                continue
            try:
                self.queue.put_nowait(text[start:start + self.chunk_size])
            except queue.Full:
                self.dropped_chunks += 1
        return len(text)

    def flush(self):
        # The worker flushes writes; print(..., flush=True) must never wait
        # for WGS to consume its pipe.
        pass

    def stop(self):
        self.closed = True
        self._stopping.set()
        if threading.current_thread() is not self.worker:
            self.worker.join(timeout=.2)

    def _write_output(self):
        while not self._stopping.is_set() or not self.queue.empty():
            try:
                text = self.queue.get(timeout=.1)
            except queue.Empty:
                continue
            try:
                if self.fd is None:
                    self.stream.write(text)
                    self.stream.flush()
                else:
                    # No BufferedWriter lock in a daemon at interpreter exit.
                    # WGS can keep this OS pipe blocked after Stop forever.
                    data = text.encode(self.encoding or 'utf-8', errors='replace')
                    while data:
                        written = os.write(self.fd, data)
                        if written <= 0:
                            raise OSError('Console pipe closed')
                        data = data[written:]
            except (OSError, ValueError):
                # A detached/closed manager console does not stop networking.
                self.stop()
                return


def disable_udp_connreset(sock):
    if sys.platform != 'win32':
        return
    # Python's socket.ioctl only accepts a small list of commands. Use
    # Winsock directly for SIO_UDP_CONNRESET = _WSAIOW(IOC_VENDOR, 12).
    # A closed client sends ICMP PORT_UNREACHABLE; otherwise Windows turns
    # that into a receive error which stops asyncio's Proactor UDP reader.
    import ctypes
    winsock = ctypes.WinDLL('ws2_32.dll')
    ioctl = winsock.WSAIoctl
    ioctl.argtypes = [ctypes.c_size_t, ctypes.c_uint32, ctypes.c_void_p,
                      ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint32,
                      ctypes.POINTER(ctypes.c_uint32), ctypes.c_void_p,
                      ctypes.c_void_p]
    ioctl.restype = ctypes.c_int
    disabled = ctypes.c_int(0)  # BOOL, not Python's one-byte ctypes.c_bool.
    returned = ctypes.c_uint32()
    if ioctl(sock.fileno(), 0x9800000C, ctypes.byref(disabled),
             ctypes.sizeof(disabled), None, 0, ctypes.byref(returned), None, None):
        raise OSError(winsock.WSAGetLastError(), 'Could not disable UDP connection resets')


def configuration():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('-port', '--relay-port', type=int, default=41234)
    parser.add_argument('-maxplayers', '--max-players', type=int, default=7)
    parser.add_argument('--lobby-port', type=int, default=8091)
    parser.add_argument('--config', default='server.json')
    parser.add_argument('--check-config', action='store_true')
    args = parser.parse_args()
    try:
        cfg = json.loads(Path(args.config).read_text(encoding='utf-8-sig'))
        if not isinstance(cfg, dict):
            raise ValueError('configuration must be a JSON object')
        unknown = set(cfg) - {'bind', 'relay_public_host', 'relay_public_port', 'discovery_manifest', 'tunnel_tools'}
        if unknown:
            raise ValueError('unknown configuration keys: ' + ', '.join(sorted(unknown)))
        bind = str(ipaddress.IPv4Address(cfg.get('bind', '0.0.0.0')))
        host = str(cfg['relay_public_host']).strip()
        if not host or len(host) > 253 or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-' for c in host):
            raise ValueError('relay_public_host must be an IPv4 address or DNS hostname without a port')
        if host == '0.0.0.0':
            raise ValueError('relay_public_host must be reachable by clients, not 0.0.0.0')
        public_port = cfg.get('relay_public_port', args.relay_port)
        if isinstance(public_port, bool) or not isinstance(public_port, int) or not 1 <= public_port <= 65535:
            raise ValueError('relay_public_port must be an integer between 1 and 65535')
        args.relay_public_port = public_port
        args.discovery_manifest = cfg.get('discovery_manifest')
        if args.discovery_manifest is not None and (not isinstance(args.discovery_manifest, str) or not args.discovery_manifest):
            raise ValueError('discovery_manifest must name the local tunnel address file')
        args.tunnel_tools = cfg.get('tunnel_tools')
        if args.tunnel_tools is not None:
            if not isinstance(args.tunnel_tools, str) or not args.tunnel_tools or not args.discovery_manifest or bind != '127.0.0.1':
                raise ValueError('outbound tunnels require loopback binding and a discovery manifest')
        if not all(1 <= p <= 65535 for p in (args.relay_port, args.lobby_port)):
            raise ValueError('ports must be between 1 and 65535')
        if not 2 <= args.max_players <= 16:
            raise ValueError('max players must be between 2 and 16')
        # Older WGS saved entries used 16. Enforce the service's seven-player
        # cap even until that entry is updated, including the host.
        args.max_players = min(args.max_players, 7)
    except (OSError, ValueError, KeyError) as exc:
        parser.error(str(exc))
    os.environ.update({
        'LISTEN_ADDR': bind, 'LISTEN_PORT': str(args.lobby_port),
        'RELAY_ADDR': '%s:%d' % (host, args.relay_public_port),
        'MAX_SEATS': str(args.max_players), 'GAME_MAX_PLAYERS': str(args.max_players),
        'TRUST_XFF': '0', 'SM64DS_RELAY_MAX_CHILDREN': str(args.max_players - 1),
        # Parent forwards six peers' 30 Hz pose updates as well as its own
        # updates and inputs. 240 packets/s is insufficient for seven seats.
        'SM64DS_RELAY_RATE_PPS': '600', 'SM64DS_RELAY_RATE_BURST': '600',
    })
    return args, bind, host


async def serve(args, bind, host):
    # These modules read environment settings at import time.
    from lobby.app import server as lobby
    from relay import relay

    loop = asyncio.get_running_loop()
    stop = asyncio.Event()
    lobby.Handler.timeout = lobby.HANDLER_TIMEOUT_S
    httpd = lobby.Server((bind, args.lobby_port), lobby.Handler)
    original_stdout = sys.stdout
    output = ConsoleOutput(original_stdout)
    sys.stdout = output
    transport = None
    discovery = None
    tunnels = None
    raw_socket = None
    worker = None
    try:
        raw_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        disable_udp_connreset(raw_socket)
        raw_socket.setblocking(False)
        raw_socket.bind((bind, args.relay_port))
        try:
            raw_socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1 << 20)
            raw_socket.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 1 << 20)
        except OSError:
            pass
        if getattr(args, 'discovery_manifest', None):
            from wgs.discovery import Discovery
            discovery = Discovery(args.discovery_manifest)
        if getattr(args, 'tunnel_tools', None):
            from wgs.tunnels import Tunnels
            tunnels = Tunnels(args.tunnel_tools, args.discovery_manifest, args.lobby_port)

        class ManagedRelay(relay.RelayProtocol):
            def datagram_received(self, data, addr):
                if discovery is not None and data[:4] == b'SMDC':
                    response = discovery.response(data, addr)
                    if response is not None:
                        self.transport.sendto(response, addr)
                    return
                super().datagram_received(data, addr)

        transport, protocol = await loop.create_datagram_endpoint(
            lambda: ManagedRelay(relay.DEFAULT_IDLE_S),
            sock=raw_socket)
        raw_socket = None  # The transport now owns and closes this socket.
        candidate = threading.Thread(target=httpd.serve_forever, daemon=True)
        candidate.start()
        worker = candidate
        if tunnels is not None:
            tunnels.start()
        threading.Thread(target=lobby.reaper, daemon=True).start()

        def request_stop(*_):
            loop.call_soon_threadsafe(stop.set)

        def read_commands():
            # EOF is normal when a manager supplies no interactive console.
            if sys.stdin is not None:
                for line in sys.stdin:
                    if line.strip().lower() in ('stop', 'quit', 'exit'):
                        request_stop()
                        return

        for name in ('SIGINT', 'SIGTERM'):
            signal.signal(getattr(signal, name), request_stop)
        threading.Thread(target=read_commands, daemon=True).start()
        print('READY lobby=http://%s:%d/port/lobby/health relay=%s:%d players=%d'
              % (bind, args.lobby_port, host, getattr(args, 'relay_public_port', args.relay_port), args.max_players), flush=True)
        last_stats = time.monotonic()
        while not stop.is_set():
            try:
                await asyncio.wait_for(stop.wait(), timeout=relay.SWEEP_INTERVAL_S)
            except asyncio.TimeoutError:
                pass
            if not worker.is_alive() or transport.is_closing():
                raise RuntimeError('a server service stopped unexpectedly')
            now = time.monotonic()
            protocol.sweep(now)
            if now - last_stats >= relay.DEFAULT_STATS_S:
                print(protocol.stats_line(), flush=True)
                last_stats = now
    finally:
        if tunnels is not None:
            tunnels.close()
        if raw_socket is not None:
            raw_socket.close()
        if transport is not None:
            transport.close()
        if discovery is not None:
            discovery.close()
        if worker is not None:
            httpd.shutdown()
            worker.join(timeout=5)
        httpd.server_close()
        print('Server stopped. Console chunks dropped: %d' % output.dropped_chunks,
              flush=True)
        sys.stdout = original_stdout
        output.stop()


def main():
    args, bind, host = configuration()
    if args.check_config:
        print('Configuration OK: lobby TCP %d, relay UDP %d, advertised %s:%d, %d players'
              % (args.lobby_port, args.relay_port, host, args.relay_public_port, args.max_players))
        return 0
    try:
        asyncio.run(serve(args, bind, host))
        return 0
    except (OSError, RuntimeError) as exc:
        print('Server startup/runtime error: %s' % exc, file=sys.stderr, flush=True)
        return 1


if __name__ == '__main__':
    sys.exit(main())
