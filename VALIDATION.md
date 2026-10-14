# Validation status

## Repository snapshot check

On 14 October 2026, all 49 automated tests passed on Windows with Python 3.12. The installation shell script passed Bash syntax validation. A Starlette test-client deprecation warning remains. Private deployment addresses, local access files and generated test artifacts were excluded from the snapshot.

## Verified before repository preparation

- Debian 13 LXC installation, systemd service running as a non-root user and panel login behind an Apache HTTPS reverse proxy.
- Local browser checks of authentication, navigation, server creation with a test JAR, settings, mod upload/toggle, file viewing and backup download.
- Desktop and mobile layout checks; no JavaScript or CSP errors in the checked browser flow.
- Automated checks for authentication, CSRF, upload/archive safety, staged imports, missing mods, hash checking and process arguments use simulated downloads/processes.
- Separate tests cover trusted reverse-proxy headers, provider-specific download errors and validated API-key replacement.

## Not yet verified end to end

- A real Minecraft server launch through MineDock and an in-game connection.
- Live Fabric, Forge or NeoForge installation through the importer.
- A complete CurseForge modpack import.

The repository contains no real server data, private reference screenshots, QA credentials or deployment access keys. Test credentials in the test suite are synthetic. The published template retains generic host defaults rather than copying the private deployment configuration.
