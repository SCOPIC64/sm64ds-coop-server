# Upstream provenance

Source repository: https://github.com/SCOPIC64/sm64ds-coop-port
Source revision: dd14d6bef1040b82c4d2ea74e65c532630f50343

Copied files:
- `port/tools/lobby/app/server.py` → `lobby/app/server.py`
- `port/tools/lobby/test_*.py` → `lobby/test_*.py`
- `port/tools/relay/relay.py` → `relay/relay.py`
- `port/tools/relay/test_client.py` → `relay/test_client.py`
- `LICENSE` → `LICENSE`

Adaptations: the lobby defaults to a local relay rather than the upstream
operator's public address, and direct launches no longer trust forwarded IP
headers. The test harness explicitly emulates a trusted reverse proxy. Its stale
health assertion is updated from protocol 3 to the server's existing protocol 4.
The unit harness makes event timestamps use the simulated sweep clock, avoiding
an upstream timeout-test dependence on machine uptime.
The supplied Compose stack requires the operator's relay address, preserves
the API routes and wire format, and serves the blank page through Caddy.
Original MIT copyright and license terms are retained.
