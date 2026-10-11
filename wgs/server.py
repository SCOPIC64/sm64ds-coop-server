"""Run the lobby and relay in one process managed by Windows Game Server."""
import argparse
import asyncio
import ipaddress
import json
import os
from pathlib import Path
import signal
import socket
import sys
import threading
import time


def configuration():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('-port', '--relay-port', type=int, default=41234)
    parser.add_argument('-maxplayers', '--max-players', type=int, default=16)
    parser.add_argument('--lobby-port', type=int, default=8091)
    parser.add_argument('--config', default='server.json')
    parser.add_argument('--check-config', action='store_true')
    args = parser.parse_args()
    try:
        cfg = json.loads(Path(args.config).read_text(encoding='utf-8-sig'))
        if not isinstance(cfg, dict):
            raise ValueError('configuration must be a JSON object')
        unknown = set(cfg) - {'bind', 'relay_public_host'}
        if unknown:
            raise ValueError('unknown configuration keys: ' + ', '.join(sorted(unknown)))
        bind = str(ipaddress.IPv4Address(cfg.get('bind', '0.0.0.0')))
        host = str(cfg['relay_public_host']).strip()
        if not host or len(host) > 253 or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-' for c in host):
            raise ValueError('relay_public_host must be an IPv4 address or DNS hostname without a port')
        if host == '0.0.0.0':
            raise ValueError('relay_public_host must be reachable by clients, not 0.0.0.0')
        if not all(1 <= p <= 65535 for p in (args.relay_port, args.lobby_port)):
            raise ValueError('ports must be between 1 and 65535')
        if not 2 <= args.max_players <= 16:
            raise ValueError('max players must be between 2 and 16')
    except (OSError, ValueError, KeyError) as exc:
        parser.error(str(exc))
    os.environ.update({
        'LISTEN_ADDR': bind, 'LISTEN_PORT': str(args.lobby_port),
        'RELAY_ADDR': '%s:%d' % (host, args.relay_port),
        'MAX_SEATS': str(args.max_players), 'GAME_MAX_PLAYERS': str(args.max_players),
        'TRUST_XFF': '0', 'SM64DS_RELAY_MAX_CHILDREN': str(args.max_players - 1),
        'SM64DS_RELAY_RATE_PPS': '240', 'SM64DS_RELAY_RATE_BURST': '240',
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
    transport = None
    worker = None
    try:
        transport, protocol = await loop.create_datagram_endpoint(
            lambda: relay.RelayProtocol(relay.DEFAULT_IDLE_S),
            local_addr=(bind, args.relay_port), family=socket.AF_INET)
        worker = threading.Thread(target=httpd.serve_forever, daemon=True)
        worker.start()
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
              % (bind, args.lobby_port, host, args.relay_port, args.max_players), flush=True)
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
        if transport is not None:
            transport.close()
        if worker is not None:
            httpd.shutdown()
            worker.join(timeout=5)
        httpd.server_close()
        print('Server stopped.', flush=True)


def main():
    args, bind, host = configuration()
    if args.check_config:
        print('Configuration OK: lobby TCP %d, relay UDP %d, advertised %s:%d, %d players'
              % (args.lobby_port, args.relay_port, host, args.relay_port, args.max_players))
        return 0
    try:
        asyncio.run(serve(args, bind, host))
        return 0
    except (OSError, RuntimeError) as exc:
        print('Server startup/runtime error: %s' % exc, file=sys.stderr, flush=True)
        return 1


if __name__ == '__main__':
    sys.exit(main())
