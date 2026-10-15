# MineDock

MineDock is a self-hosted Minecraft Java server management panel for Debian 13. It runs directly on Linux with Python, Java and systemd, without Docker. The web interface is in German and uses BexoGames branding.

## Project status

An initial working panel is deployed in a Debian 13 LXC container behind a separate Apache HTTPS reverse proxy. Panel installation, login and service operation have been verified. Minecraft gameplay and real Fabric/Forge/NeoForge installation have not yet been validated end to end.

## Features

- Create, configure, start, stop, restart, archive and permanently delete Minecraft servers.
- Install Vanilla, upload a runnable server JAR, or import a CurseForge file link or manifest ZIP.
- Resolve Fabric, Forge and NeoForge loaders from a CurseForge manifest.
- Upload, enable, disable and remove mods; show missing files for manual upload.
- View console output, send commands and edit configuration files while a server is stopped.
- Create and download backups of stopped servers.
- User management with administrator, manager, operator and viewer roles and per-server assignments.
- Account password changes through the sidebar profile name, session revocation, password hashing and CSRF protection.
- Configurable RAM budget and a dedicated non-root systemd service.

## CurseForge API key

A CurseForge API key is required to use the CurseForge integration. **The API key must never be shared with anyone or published.**

See [CurseForge API key](docs/CURSEFORGE.md).

## Installation

Read the [installation and operations guide](docs/INSTALLATION.md), including the RAM limits and current limitations, before running:

```bash
sudo bash deploy/install.sh
```

The installer targets Debian 13, installs Java 21 and Python dependencies, and prompts for an administrator password and optional CurseForge key. It does not configure your firewall or Apache automatically. Configure HTTPS through your own reverse proxy before using the panel remotely.

A key replacement helper validates the Minecraft modpack lookup before updating the stored value:

```bash
sudo /opt/minedock/.venv/bin/python deploy/set_curseforge_key.py
```

The helper does not restart the service. Stop managed Minecraft servers and wait for imports to finish before restarting MineDock.

## Users and updates

See the [roles and permissions guide](docs/USERS.md). The existing administrator is migrated automatically, keeping the current password. Role changes, disabled accounts and password changes invalidate existing sessions.

For an existing installation, stop managed Minecraft servers and wait for imports, then run from the new release directory:

```bash
sudo /opt/minedock/.venv/bin/python deploy/update.py
```

The updater requires unchanged dependencies, backs up the application and database, and restores both if the new service fails its startup check. Existing environment settings, systemd limits and server files are preserved.

## Development

Python 3.11 or later:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.lock
.venv/bin/pip install pytest
.venv/bin/python -m pytest -q
```

Tests use temporary data and mocked external downloads/processes. See [validation status](VALIDATION.md).

## Limitations

This is an early project. It does not isolate individual Minecraft servers from each other. Uploaded JARs and mods execute as the service user and must be trusted. There is no automatic in-place modpack upgrade, backup restoration UI or automatic Minecraft restart after a host reboot. Larger ZIPs and downloads are subject to documented limits.

The repository uses the GNU General Public License v3.0; see [LICENSE](LICENSE). MineDock is not affiliated with Mojang, Microsoft, CurseForge or Overwolf.
