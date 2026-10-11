# SM64DS Co-op Server

A deliberately blank website, the SM64DS lobby API, and its UDP relay.

The repository contains everything needed to run these services on an online
Linux server with Docker Compose. GitHub Pages can publish `site/index.html`,
but it cannot execute the Python lobby or accept UDP game traffic. Publishing
the blank page alone does **not** bring multiplayer online.

## Blank GitHub Pages website

This public repository uses **Settings → Pages → GitHub Actions** as its
source. The **Blank website** workflow publishes only `site/`. It contains an
empty page with no visible content, analytics, requests, buttons, or scripts.
Changes to `site/` on `main` publish automatically. The workflow can also be
run manually from Actions.

The normal project URL is `https://scopic64.github.io/sm64ds-coop-server/`;
the workflow reports the actual deployed URL. The blank page is static. The
lobby API and UDP relay still require a separate online server.

## Run on Windows with WGS

See [the WGS setup guide](wgs/README.md) for the combined Windows lobby and
relay executable, custom plugin settings, and LAN/internet networking.
For a free setup without card verification or router forwarding, follow
[the Playit and Cloudflare WGS guide](deploy/NO-CARD-WGS.md).

## Run the actual server online

Use an online Linux host with Docker Engine and the Compose plugin, a public
IPv4 address, and inbound TCP 80/443 plus UDP 41234. No game ROM or assets are
needed on the host. GitHub-hosted Actions runners are used only for tests and
page publication, not as a persistent multiplayer host.

1. Clone this repository on the host:
   `git clone https://github.com/SCOPIC64/sm64ds-coop-server.git`, then
   `cd sm64ds-coop-server`.
2. Copy `.env.example` to `.env`. Set `SITE_ADDRESS` to a DNS name pointing
   directly at the host. Set `RELAY_PUBLIC_ADDR` to that host's public IPv4
   address or DNS name, followed by `:41234`.
3. Run `docker compose config --quiet`, then `docker compose up -d --build`.
4. Check `docker compose ps` and
   `curl --fail https://YOUR-DOMAIN/port/lobby/health`.
5. From another machine, verify the UDP route:
   `python relay/test_client.py remote-check --host YOUR-SERVER --count 20`.

The website remains blank. The API is under `/port/lobby/`; Caddy terminates
HTTPS and passes those requests to the lobby. UDP 41234 goes directly to the
relay. For a local smoke test only, use `SITE_ADDRESS=:80` and
`RELAY_PUBLIC_ADDR=127.0.0.1:41234`.

`docker compose up -d --build` installs subsequent source updates after a pull.
`docker compose down` stops the services. Rooms and relay sessions live only
in memory and are lost on restart. TLS certificates persist in Docker volumes.
Logs are capped. The lobby has no published host port and trusts forwarding
headers only behind this stack's Caddy. A direct Python launch ignores them.
Do not put an unconfigured forwarding proxy between clients and this Caddy;
that would make clients share the proxy's rate limit identity.

## Game integration status

The online game menu creates or joins separate rooms using a saved server
profile, with seven players per room including the host. Each match gets its
own relay session key. The deployment and WGS process both enforce that cap.
The underlying protocol retains its existing compatibility limits.

See [the complete setup and playing steps](deploy/SETUP.md). Hosting both
services on an external VM keeps players' connections away from the home
computer's public address. The client saves a Windows DPAPI encrypted text
file in AppData; its key is managed by Windows, not stored in source. The
public relay address remains visible to a player inspecting their own traffic.
Server deployment and distribution of its public profile are required before
the new menu can connect. This repository contains no home IP or game ROM.
The [free WGS tunnel setup](deploy/NO-CARD-WGS.md) instead keeps the PC as the
server while proxying both public connections. Authenticated discovery lets
the game find a restarted Cloudflare tunnel automatically. Its RSA private
key remains in the server owner's Windows key store; public profiles contain
only the public relay endpoint and the server's public identity key.

## Checks

No Python packages are needed:

```sh
python lobby/test_units.py
python lobby/test_client.py selftest
python lobby/test_security.py
python relay/test_client.py selftest
python -m unittest discover -s tests -v
```

CI also builds and launches the Docker stack, checks the actual blank page and
proxy, creates/leaves a lobby room, and sends packets through the relay. Tests
run temporary local servers and stop them afterward. They do not prove a public
server is deployed or that two game clients have completed an online session.

## Source and license

The lobby, relay and their protocol tests are extracted from
[SCOPIC64/sm64ds-coop-port](https://github.com/SCOPIC64/sm64ds-coop-port),
commit `dd14d6bef1040b82c4d2ea74e65c532630f50343`, under its MIT license.
See `UPSTREAM.md` for provenance and changes, and `LICENSE` for the original
copyright notice.
