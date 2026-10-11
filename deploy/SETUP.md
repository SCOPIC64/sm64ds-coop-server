# Private home IP, public relay, seven players per room

Run the lobby and relay together on an external VM. Every game, including the
host's game, connects to that VM. This arrangement does not require home router
port forwarding or publish the home computer's address to the other players.
The VM's public address is visible in network traffic. Encryption protects the
saved settings at rest; it cannot make a destination invisible to its own client.

## 1. Create the hosting account

An external host is required; GitHub Pages and the repository cannot execute
this server. One option is [Oracle Always Free](https://www.oracle.com/cloud/free/).
Oracle requires identity/card verification. Free capacity can be unavailable,
and idle free VMs can be reclaimed. Do not upgrade to a paid plan without
checking its charges. See [Oracle's current limits](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm).

1. Sign up yourself; keep billing information, passwords and MFA codes private.
2. In Compute, choose **Create instance**, Ubuntu 24.04, and an **Always Free
   eligible** shape. Use one VM with a public IPv4 and retain its SSH key locally.
3. In its network security list/group, allow inbound TCP 80 and 443 and UDP
   41234. Keep SSH restricted to your administration address.
4. Give the VM a DNS hostname pointing to its public IPv4. A domain you control
   is preferable. A service such as sslip.io can supply an IP-based hostname;
   this contains only the VM's public IP, never your home IP.
5. Tell the assistant the VM's hostname and your local SSH key file path, not
   the key contents. Account verification must be completed by you.

## 2. Deploy (assistant can perform this after SSH is available)

1. Connect with SSH as the VM's administrator.
2. Install Docker Engine and its Compose plugin using the
   [official Ubuntu instructions](https://docs.docker.com/engine/install/ubuntu/).
3. Clone `https://github.com/SCOPIC64/sm64ds-coop-server.git` on the VM.
4. In the repository run `sudo bash deploy/start-server.sh YOUR-RELAY-HOSTNAME`.
5. Confirm `docker compose ps` shows healthy services and
   `curl --fail https://YOUR-RELAY-HOSTNAME/port/lobby/health` reports `dial_max:7`.
6. From a different computer, run
   `python relay/test_client.py remote-check --host YOUR-RELAY-HOSTNAME --count 20`.
   HTTP health alone does not prove UDP reaches the server.

## 3. Set up the game once

1. Install the game build with online lobby support.
2. Run `deploy/install-client-profile.ps1` with `-LobbyUrl
   https://YOUR-RELAY-HOSTNAME`, `-RelayAddress YOUR-RELAY-HOSTNAME:41234`, and
   `-GameFolder` pointing to the game folder.
3. The script writes `%APPDATA%\SM64DS-Coop\server.txt`. Its content is Base64
   text containing a Windows DPAPI encrypted blob. The key belongs to the
   Windows user account and is absent from both source repositories.
4. `server-profile.json` next to the game is a distribution profile containing
   the public VM endpoint. Include it in the game package. On first launch,
   each player's game creates their own encrypted AppData copy automatically.
   Do not distribute your encrypted AppData file: it is tied to your account.
5. There is no direct connection fallback in the online menu. A missing or
   invalid profile produces a setup message instead of using a home address.

## 4. Play

1. Open `sm64ds coop.exe`. The Host/Join menus use the saved server automatically.
2. Host: select **Host**, a save slot, and a character, then **Create lobby**.
3. Share the six-character **room code** with your friends.
4. Friends: select **Join**, enter that room code, select a character, then
   **Join lobby**. They never enter an IP or port.
5. Once everyone is listed, the host chooses **Start game**. At least two
   players must be present. The limit is seven total, including the host.
6. Different hosts create different rooms and relay session keys. Players
   choose a room; they are not placed in one shared global game.
7. Leave with **Leave lobby**, or quit the game. The host leaving closes that
   room. Live rooms exist in memory and disappear when the server restarts.

Windows DPAPI and HTTPS are standard protection, not a secret custom cipher.
A player controlling their own PC can inspect the public relay endpoint.
The home IP is protected by the external relay architecture.
