# Installation and operations

MineDock is a self-hosted Minecraft Java panel for **Debian 13, without Docker**, with user roles and a configurable shared Minecraft memory budget. It runs as a Python/FastAPI application with a German web interface. Authentication, server data and Java processes stay on your host.

## Interface

The interface uses BexoGames branding, a dark theme and green accents. The public version does not include a link to a private infrastructure panel.

## Features

- Create, start, gracefully stop, restart, archive and permanently delete servers.
- Install Vanilla versions or upload a runnable server JAR.
- Import CurseForge file links (a specific `/files/ID` version) and manifest ZIP exports.
- Install Fabric, Forge and NeoForge from the manifest, including mods and supported overrides.
- List files that require manual downloading and accept uploads, checking hashes when provided by CurseForge.
- Upload, enable, disable and remove mods.
- Configure RAM, Java version, port, description, game mode, difficulty, player limit and whitelist.
- View the latest 1,200 console lines and send commands; updates poll every 3.5 seconds.
- Edit configuration files up to 1 MiB while the server is stopped.
- Create and download backups of stopped servers.
- Manage users, roles and server assignments; change your own password through the profile name at the bottom of the sidebar.
- Password hashing, HttpOnly sessions, CSRF protection, login throttling, bounded uploads and archive path validation.

## Install on Debian 13

The installer adds Python, Java 21 and a systemd service. It does **not** automatically configure the firewall or an existing web server. Run it from the extracted project directory:

```bash
sudo bash deploy/install.sh
```

The installer asks for an administrator password and a CurseForge API key. The initial username is **admin**; there is no default password. A CurseForge API key is required for the CurseForge integration. **Never share the key with anyone or publish it.** You can skip it during installation and add it later.

| Purpose | Path |
|---|---|
| Application | `/opt/minedock` |
| Configuration | `/etc/minedock/minedock.env` (root, mode 0600) |
| Database | `/var/lib/minedock/panel.sqlite3` |
| Server data | `/var/lib/minedock/servers/<ID>` |
| Backups | `/var/lib/minedock/backups` |

```bash
sudo systemctl status minedock
sudo journalctl -u minedock -n 100 --no-pager
```

## Proxmox: separate Minecraft and Apache containers

MineDock runs in the Debian 13 Minecraft container. Apache2 terminates HTTPS in the web server container and forwards requests to MineDock over the internal HTTP connection.

The service listens on **all IPv4 interfaces, port 8080**, by default (`MINEDOCK_BIND="0.0.0.0"`). Access is not restricted to the web server's IP address, and the installer does not change firewall rules. Use one worker: process management and sessions live in that process.

### Minecraft container

Set the actual source IP of the Apache container in `/etc/minedock/minedock.env`:

```ini
MINEDOCK_BIND="0.0.0.0"
MINEDOCK_PORT="8080"
MINEDOCK_PROXY_IPS="APACHE_CONTAINER_IP"
MINEDOCK_SECURE_COOKIE="1"
```

Replace `APACHE_CONTAINER_IP`. `MINEDOCK_PROXY_IPS` controls which peers may supply trusted forwarded HTTPS and client-IP headers. Other clients can still reach the port. When NAT is involved, use the source IP seen by the Minecraft container.

Stop managed Minecraft servers and wait for imports before restarting the panel:

```bash
sudo systemctl restart minedock
```

For an existing installation, review any intended systemd unit changes before copying `deploy/minedock.service` to `/etc/systemd/system/minedock.service`. Preserve your own RAM limits and other settings, then run `sudo systemctl daemon-reload` if the unit changed.

### Apache web server container

The `deploy/apache2.conf` template uses a dedicated domain at the URL root. Replace `panel.example.com`, `MINECRAFT_CONTAINER_IP` and the certificate paths. DNS and certificates are managed on the web server. Do not overwrite an existing infrastructure manager virtual host.

```bash
sudo a2enmod proxy proxy_http headers ssl
sudo cp deploy/apache2.conf /etc/apache2/sites-available/minedock.conf
```

Edit the copied file with valid domain, backend and certificate settings before enabling it:

```bash
sudo a2ensite minedock.conf
sudo apache2ctl configtest
sudo systemctl reload apache2
```

Use your existing certificate renewal process. `ProxyPreserveHost` preserves the panel domain, and Apache sets `X-Forwarded-Proto` to HTTPS. The upload limit is 513 MiB including multipart overhead. The console uses HTTP polling and does not require a WebSocket module.

Open the panel through its HTTPS domain. Minecraft clients connect to the individual game TCP ports. The supplied configuration does not add an IP allowlist to the backend port.

### Optional SSH tunnel test

For an HTTP-only test, set `MINEDOCK_SECURE_COOKIE="0"` and restart the service after stopping managed servers. Port 8080 remains reachable through the container IP by default. If you want loopback-only access for this test, also set `MINEDOCK_BIND="127.0.0.1"`. On your computer:

```bash
ssh -L 8080:127.0.0.1:8080 USER@MINECRAFT-CONTAINER
```

Open `http://localhost:8080`. Restore `MINEDOCK_SECURE_COOKIE="1"` and your intended bind address before returning to normal reverse-proxy operation.

## Create your first server

1. Sign in and choose **Server erstellen** (Create server).
2. Select a CurseForge file link, ZIP export, Vanilla version or your own JAR.
3. Assign RAM and a port, and choose Java to match the Minecraft/modpack version.
4. Read the Minecraft EULA and accept it if you agree. Starting is blocked until acceptance.
5. Watch installation progress in the console. Download missing mods and upload them in the **Mods** tab.
6. Start the server. The Java process may be running while Minecraft is still loading; the `Done` message indicates that the game is ready.

A CurseForge export must contain `manifest.json` at the ZIP root. Traditional server packs with arbitrary startup scripts are not a supported import format. Only overrides in `mods`, `config`, `defaultconfigs`, `kubejs`, `scripts`, `resourcepacks` and `datapacks` are imported. Bundled worlds and arbitrary root files are excluded. Client-only mods cannot always be detected automatically; disable them in the mod list before starting when necessary.

An uploaded server JAR must support direct execution with `java -jar ... nogui`. Use a CurseForge manifest to install Forge or NeoForge loaders.

## Java and memory

Java 21 is installed by default. Older modpacks may need Java 8 or 17; newer versions may require other Java releases. Install the required JREs from a trusted source and add their absolute paths to the host configuration. Example systemd environment-file settings:

```ini
MINEDOCK_JAVA='{"21":"/usr/lib/jvm/java-21-openjdk-amd64/bin/java","17":"/opt/java17/bin/java"}'
MINEDOCK_MEMORY_MB="32768"
```

These paths must exist on your host. Only configured Java versions are offered in the panel. Stop managed servers before reconfiguring the service.

Before starting a server, MineDock checks its `-Xmx` value plus 768 MiB of process overhead against the shared budget. This is reservation accounting, not an individual cgroup limit. By default, systemd also limits the **entire panel and its Java child processes** to 32 GiB (`MemoryMax`). Native Java allocations and mods can exceed the heap; the kernel may terminate processes when the limit is reached. Leave enough additional memory for the host and other services. If the machine has only 32 GiB in total, reduce both the budget and `MemoryMax`. Minecraft has no automatic start or crash-restart loop.

## Operations and current limitations

- Roles and server assignments control panel access. Minecraft processes are not isolated into separate system users or containers. Administrators and managers must be trusted. Uploaded mods and JARs execute as the service user and can access its data.
- The service runs without root and writes to its own data directory. Java processes belong to the service and stop gracefully during normal panel shutdown. After a panel or host restart, start Minecraft servers **manually**. Minecraft also writes logs in its server directory; the panel's console buffer and sessions are lost on restart.
- Install a modpack update as a **new server**. Existing worlds are not overwritten by an automatic in-place upgrade.
- Archived servers retain their files. The UI does not currently restore archived management records. You can still inspect an archived server and download an existing backup when your role allows it.
- ZIP limits: 512 MiB compressed, 2 GiB extracted and 20,000 entries. Each downloaded file is limited to 512 MiB. Large packs may exceed these limits.
- Server backups do not contain the panel database or API key. For a complete migration, separately back up `/var/lib/minedock` and `/etc/minedock` while the service is stopped.
- Backup restoration is not available through the website. With the service stopped, extract a trusted backup into a **new temporary directory**, inspect it and copy back the required files. Save the existing server directory first and keep ownership assigned to `minedock`.
- Panel installation and HTTPS login have been verified in Debian 13 LXC. Real Minecraft launches, external loader installations and complete CurseForge imports still require end-to-end validation.

## Development and tests

Python 3.11 or later:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.lock
.venv/bin/pip install pytest
.venv/bin/python -m pytest -q
```

Tests use temporary data and simulated downloads/Java processes. They do not contact CurseForge. Never point tests at real server data.

## Users and roles

See [users, permissions and deletion](USERS.md). The existing administrator is migrated on first startup. Accounts and password hashes then live in the database; the installation hash does not reset a password changed there.

## Upgrade

Stop all Minecraft servers managed by MineDock and wait for running imports. Leave the panel service running for preflight checks. From the extracted new release directory:

```bash
sudo /opt/minedock/.venv/bin/python deploy/update.py
```

The updater checks the existing installation and unchanged dependencies, backs up the application and database under `/var/backups/minedock`, and replaces the application code. If the new service fails its startup check, it restores the old code and database. Existing environment settings, systemd configuration, memory limits, private menu links and Minecraft files are preserved. Backups are accessible only to root. Reload the browser and sign in again afterward.

## Technical references

- [CurseForge REST API](https://docs.curseforge.com/rest-api/)
- [API keys for CurseForge file downloads](https://blog.curseforge.com/introducing-api-key-authentication-for-curseforge-file-downloads/)
- [Fabric server installation](https://wiki.fabricmc.net/install)
- [NeoForge server installation](https://docs.neoforged.net/user/docs/server/)
- [Apache reverse proxy](https://httpd.apache.org/docs/2.4/mod/mod_proxy.html)
- [Apache RequestHeader](https://httpd.apache.org/docs/2.4/mod/mod_headers.html)
