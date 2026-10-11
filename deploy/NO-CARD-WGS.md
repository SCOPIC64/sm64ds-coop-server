# Free public connection with WGS

This setup runs the server on your Windows PC through Playit's free UDP
tunnel and Cloudflare's free HTTPS Quick Tunnel. Friends see the public proxy
addresses. Your PC must remain on and connected while they play. These free
services do not provide a dedicated always-on machine or an uptime guarantee.

## One-time server setup

1. Create a free Playit account and verify it. Download the signed Windows
   console agent from [the official releases](https://github.com/playit-cloud/playit-agent/releases).
   Version 0.17.1 supports the command-line setup used here.
2. Start it with `playit.exe --stdout --secret_path playit-secret.txt start`.
   Open its claim URL, approve the agent, and give it a game-server name.
3. In the Playit dashboard, create a **UDP**, one-port tunnel on the **Free
   Network**. Describe the actual SM64DS game server and review its usage
   conditions. Set **Local IP** to `127.0.0.1`, **Local Port** to `41234`, and
   **Proxy Protocol** to `None`. Record its public hostname and assigned port.
4. Download `cloudflared-windows-amd64.exe` from
   [Cloudflare's official releases](https://github.com/cloudflare/cloudflared/releases).
   Rename it `cloudflared.exe`. Put it, `playit.exe`, and the agent's
   `playit-secret.txt` in a private folder outside your repository, preferably
   under `%LOCALAPPDATA%\SM64DS-Coop-Server\tunnels`. Restrict that folder to
   your Windows account and SYSTEM. Do not distribute its secret or logs.
5. Build the server with `./wgs/build.ps1`, and copy its entire output directory
   into the WGS installation. Set the WGS executable to `sm64ds-server.exe`,
   game port to `41234`, maximum players to `7`, and custom arguments to
   `--lobby-port 8091`.
6. Configure `server.json` using your public **Playit** endpoint and private
   tool paths, as in this example. The advertised port can differ from the
   local game port. Do not put your home address in this file.

```json
{
  "bind": "127.0.0.1",
  "relay_public_host": "YOUR-TUNNEL.tun.ply.gg",
  "relay_public_port": 40000,
  "discovery_manifest": "C:/PRIVATE-TUNNELS/tunnel.json",
  "tunnel_tools": "C:/PRIVATE-TUNNELS"
}
```

7. Stop any copy of the agent started in step 2. Click **Start** in WGS.
   WGS now owns both tunnel programs. Wait for `READY` and then
   `Public lobby tunnel ready`. WGS's **Stop** stops the tunnels too.
8. Export the discovery **public** key on the server's Windows account:
   `python -c "from wgs.discovery import WindowsSigner; s=WindowsSigner(); print(s.public_key()); s.close()"`.
   The RSA private key stays non-exportable in that account's Windows key
   store. Keep the same Windows account when restarting the server.
9. Run `deploy/install-client-profile.ps1` with `-RelayAddress` set to your
   public Playit hostname and port, `-DiscoveryKey` set to that public key,
   and `-GameFolder` set to the game folder. Optionally provide `-LobbyUrl`
   from the private `tunnel.json` to verify the HTTPS health endpoint first.
10. Give friends the updated game executable and its `server-profile.json`.
    Each game creates `%APPDATA%\SM64DS-Coop\server.txt`, encrypted separately
    for its own Windows account. Do not copy your encrypted TXT to friends.
    No ROM, saves, agent secret, logs, or server private files belong in that
    distribution.

## Playing

1. Server owner: start **SERVER** in WGS and wait for both readiness messages.
2. Host: open the updated game, choose **Host**, choose a save slot and
   character, and select **Create lobby**.
3. Share the six-character room code with friends.
4. Each friend: choose **Join**, enter the room code, choose a character, and
   select **Join lobby**. No address or port entry is needed.
5. Host: select **Start game** when everyone has joined. A room holds at most
   seven players, including the host. Other rooms have their own session keys.

## Automatic address changes and privacy

The Playit endpoint remains the saved entry point while the tunnel exists.
When Cloudflare restarts, WGS publishes its new HTTPS origin in a local file.
Before creating or joining a room, the game asks the Playit relay for that
origin with a fresh random challenge. It verifies an RSA-2048/SHA-256
signature against the saved server public key before sending any lobby
credentials over ordinary HTTPS. The response contains only a public proxy
origin. Altered replies and replies for another challenge are rejected.

The server restarts failed tunnel processes. If WGS restarts, existing rooms
are lost; players create or join a new room. They keep the same profile and
do not re-enter network settings. Deleting/recreating the Playit tunnel or
changing the Windows signing identity requires distributing a new profile.

DPAPI protects the saved TXT using a Windows account key, outside source and
the executable. It does not make a connected public relay address impossible
to discover. Players can inspect their traffic and see Playit and Cloudflare;
the tunnel providers also necessarily know their origin. Normal play never
advertises the server owner's home IP or opens a direct fallback route.
