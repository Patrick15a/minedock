# Validation status

## Repository snapshot check

On 15 October 2026, all 127 automated tests passed on Windows with Python 3.12. The installation shell script passed Bash syntax validation. A Starlette test-client deprecation warning remains. Private deployment addresses, local access files and generated test artifacts were excluded from the snapshot.

## Verified before repository preparation

- Debian 13 LXC installation, systemd service running as a non-root user and panel login behind an Apache HTTPS reverse proxy.
- Local browser checks of authentication, navigation, server creation with a test JAR, settings, mod upload/toggle, file viewing and backup download.
- Desktop and mobile layout checks; no JavaScript or CSP errors in the checked browser flow.
- Automated checks for authentication, CSRF, upload/archive safety, staged imports, missing mods, hash checking and process arguments use simulated downloads/processes.
- Separate tests cover trusted reverse-proxy headers, provider-specific download errors and validated API-key replacement.

## User management and deletion

- Automated coverage includes migration of the existing administrator, role and server assignment enforcement, session revocation, last-admin protection, password changes, and password redaction in validation errors.
- Deletion tests cover running/busy servers, exact name confirmation, owned backup cleanup, symlink rejection and retry after filesystem failure.
- Headless Chrome checks cover account creation, assignments, viewer restrictions, password change and re-login, mobile layout, and typed server deletion. No JavaScript errors occurred.
- Five updater tests cover successful replacement, database/code rollback, syntax rejection, failed backup and failed directory replacement.
- The user reports that the role update is installed in the production container.
- Browser regression checks cover no timed user-list requests or refresh button, no loading flashes while idle, keyboard focus, updates after account changes and page reloads, sidebar profile navigation, preservation of password drafts, and delayed responses after navigation.
- The subsequent sidebar/profile and polling fix is awaiting deployment.

## CurseForge filename regression

- The local Create a Colony 1.0.6 manifest contains 213 entries. Entry 47 references project 664014, file 4454534 (NoCube's Villagers Sell Animals).
- The old filename allowlist rejected apostrophes in this mod's JAR and in NoCube's Farmers Compats. All 180 JAR basenames from the local matching server pack pass the revised validation. No pack content is included in the repository.
- 37 new regression cases cover original names with apostrophes and Unicode, UTF-8 filename limits, traversal and control-character rejection, the entry-47 import path, manual missing-file uploads, and mod enable/disable/removal including long names.
- Downloads and loader execution in import tests are simulated. The full live pack import remains to be retried after deploying this fix.

## Mixed mod/resource manifests

- Create a Colony 1.0.6 includes resource pack entries at positions 63, 120 and 167: Ore Variants, Minecolonies Refreshed and Created Simple Storage Network.
- 13 regression cases verify confirmed resource/shader archives are skipped without downloading or blocking startup, including entries marked required and files without download URLs. Unknown archives, mismatched projects and other games still produce explicit errors.
- A simulated 213-entry import completes with 210 mod files and three logged client resource pack skips. A separate offline run using the actual local ZIP also passes manifest validation and copies its overrides, with simulated metadata, downloads and loader execution. Real downloads and Forge execution remain outside these tests.

## Not yet verified end to end

- A real Minecraft server launch through MineDock and an in-game connection.
- Live Fabric, Forge or NeoForge installation through the importer.
- A complete CurseForge modpack import.

The repository contains no real server data, private reference screenshots, QA credentials or deployment access keys. Test credentials in the test suite are synthetic. The published template retains generic host defaults rather than copying the private deployment configuration.
