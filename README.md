# MineDock

MineDock is a self-hosted Minecraft Java server management panel for Debian 13. It runs directly on Linux with Python, Java and systemd, without Docker. The web interface is in German and uses BexoGames branding.

## Project status

An initial working panel is deployed in a Debian 13 LXC container behind a separate Apache HTTPS reverse proxy. Panel installation, login and service operation have been verified. Minecraft gameplay and real Fabric/Forge/NeoForge installation have not yet been validated end to end.

**CurseForge integration is implemented but awaiting suitable API access.** Current authenticated requests for Minecraft modpack metadata return HTTP 403. The presence of a stored key is not proof of valid API access. No successful live CurseForge import is claimed.

## Features

- Create, configure, start, stop, restart and archive Minecraft servers.
- Install Vanilla, upload a runnable server JAR, or import a CurseForge file link or manifest ZIP.
- Resolve Fabric, Forge and NeoForge loaders from a CurseForge manifest.
- Upload, enable, disable and remove mods; show missing files for manual upload.
- View console output, send commands and edit configuration files while a server is stopped.
- Create and download backups of stopped servers.
- One administrator account, password hashing, session authentication and CSRF protection.
- Configurable RAM budget and a dedicated non-root systemd service.

## CurseForge API integration

See [CurseForge integration and API application notes](docs/CURSEFORGE.md) for the implementation and intended use.

Imports search the Minecraft modpack catalog, resolve pinned file metadata and download files from the API-provided URLs. API keys are sent in headers and remain on the operator's server. Missing download URLs lead to a manual download/upload workflow; the importer does not construct alternative CDN URLs to bypass unavailable downloads. No mod files, API credentials, server worlds or production configuration are included in this repository.

A manifest export is not a complete offline server pack. It still requires API access to resolve and fetch its referenced mods. Client-only mods may need to be removed manually. Importing a client pack does not reproduce private server plugins or custom server-side content.

## Installation

Read the [German installation and operations guide](docs/INSTALLATION.de.md), including the RAM limits and current limitations, before running:

```bash
sudo bash deploy/install.sh
```

The installer targets Debian 13, installs Java 21 and Python dependencies, and prompts for an administrator password and optional CurseForge key. It does not configure your firewall or Apache automatically. Configure HTTPS through your own reverse proxy before using the panel remotely.

A key replacement helper validates the Minecraft modpack lookup before updating the stored value:

```bash
sudo /opt/minedock/.venv/bin/python deploy/set_curseforge_key.py
```

The helper does not restart the service. Stop managed Minecraft servers and wait for imports to finish before restarting MineDock.

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

This is an early single-administrator project. It does not isolate individual Minecraft servers from each other. Uploaded JARs and mods execute as the service user and must be trusted. There is no automatic in-place modpack upgrade, backup restoration UI, role management or automatic Minecraft restart after a host reboot. Larger ZIPs and downloads are subject to documented limits.

The repository uses the GNU General Public License v3.0; see [LICENSE](LICENSE). MineDock is not affiliated with Mojang, Microsoft, CurseForge or Overwolf.
