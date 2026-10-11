# Windows Game Server (WGS)

This launcher runs the HTTP lobby and UDP relay in one process for
[WGS](https://wgsserver.com/manual). No ROM or game executable is required.
WGS runs the services on your Windows PC, which must stay on while hosting.

## Build

Use Python 3.10 or newer on Windows, install PyInstaller (`python -m pip install
pyinstaller`), then run `./wgs/build.ps1` from PowerShell. Copy the **whole**
`wgs/dist/sm64ds-server` directory into the WGS server installation directory.
The executable depends on its adjacent `_internal` directory.

## Configure WGS

Create or edit a custom game plugin with executable `sm64ds-server.exe`,
Steam App ID `0`, game port `41234`, query port `8091`, and max players `16`.
The query-port field records the HTTP lobby port; this service does not implement
Steam queries, RCON, or WGS player counts. Set the server's custom arguments to
`--lobby-port 8091`. WGS supplies `-port` and `-maxplayers` itself. If you change
the query-port field, change `--lobby-port` too. Install the files manually;
there is no SteamCMD download for this server.

Edit `server.json` in that directory:

```json
{"bind": "0.0.0.0", "relay_public_host": "YOUR-SERVER-IP-OR-DNS"}
```

For LAN use, replace the hostname with the server PC's LAN IPv4 address. For
internet use, use its public IPv4 address or DNS name. Do not include a port;
the launcher uses WGS's game port. `127.0.0.1` works only on the same PC.

Click **Start** in WGS. Its console should show `READY`. Check
`http://127.0.0.1:8091/port/lobby/health` and test UDP from a second machine:

```
python relay/test_client.py remote-check --host YOUR-SERVER-IP --count 20
```

WGS can stop the process normally. Sending `stop` through the console also
shuts down both services. Sessions are stored in memory and disappear at stop.
Automatic start/restart are optional WGS settings. Both services fail together
if either port is already occupied, so WGS cannot report a partially started
server as running.

For internet clients, the router/firewall must route TCP `8091` and UDP `41234`
to this PC. CGNAT may require a public address from the ISP or a separate host.
This direct configuration ignores forwarded-IP headers. For HTTPS, use the
documented Docker/Caddy deployment or configure a suitable proxy separately.
Hosting these services does not finish the game's public lobby menu or select
the server in game clients; see the root README's integration status.

## Test

`python -m unittest discover -s tests -p test_wgs.py -v` exercises the source
launcher. Set `WGS_SERVER_EXE` to the absolute built executable path to run the
same checks against the packaged Windows app. Checks include real HTTP room
creation, bidirectional UDP forwarding, shutdown and port-conflict cleanup.
