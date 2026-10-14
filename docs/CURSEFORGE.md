# CurseForge integration

## Intended use

MineDock is a self-hosted administration panel for Minecraft Java servers. Initial use is a single privately operated installation with one administrator. API calls are initiated when the administrator imports a pinned modpack version or a CurseForge manifest. The panel does not run a background catalog crawler or a public mod download mirror.

The implementation searches Minecraft modpacks (`gameId=432`, `classId=4471`), reads project/file metadata, obtains download URLs and installs referenced files locally. File hashes are checked when provided by the API. API keys are stored on the host and are not passed to Java child processes or returned to the browser.

## Access and distribution

- A key with appropriate access to public Minecraft metadata is required. A console profile-management key serves a different API.
- Operator applications for third-party access are reviewed by CurseForge; approval is not guaranteed.
- API/CDN denial is surfaced to the administrator. Authentication restrictions are not bypassed.
- When a mod's API response has no download URL, the panel links to its CurseForge page and requires a manual upload. Missing required files block server startup.
- When a modpack has no download URL, the operator is directed to obtain and upload its export manually. Manifest-referenced mods still need API access.
- Downloaded content is used on the operator's server. This repository does not redistribute mods, modpacks or worlds.

## Current validation

The panel and simulated import flows have been tested. Live metadata requests currently return HTTP 403 with the keys tried by the operator. A working live CurseForge import and gameplay test remain pending.

## Draft project description for the API application

> MineDock is a self-hosted Minecraft Java server management panel for Debian Linux, running without Docker. Its initial use is a private installation with a single administrator. We request access to Minecraft modpack and file metadata so the administrator can import a specific CurseForge modpack version, resolve its referenced mods and download permitted files directly from CurseForge to the local server. API requests are user-initiated; there is no background catalog crawling or public download mirror. The application uses API-provided download URLs, verifies available hashes and presents missing or unavailable downloads for manual handling. API credentials are kept on the host. Live CurseForge import validation is pending approval of suitable API access.

Review the description against the actual intended deployment before submitting. The repository URL can be included after the repository has been published; this document is not an application submission or an approval.

## References

- [API access application](https://support.curseforge.com/support/solutions/articles/9000208346-about-the-curseforge-api-and-how-to-apply-for-a-key)
- [REST API reference](https://docs.curseforge.com/rest-api/)
- [CDN API-key authentication](https://blog.curseforge.com/introducing-api-key-authentication-for-curseforge-file-downloads/)
