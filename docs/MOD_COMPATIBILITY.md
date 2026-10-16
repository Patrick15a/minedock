# Automatic mod compatibility checks

MineDock checks mods after a manifest import, after mod uploads/removals or policy changes, and immediately before starting Minecraft. Existing servers can be checked with **Mods jetzt pruefen** in the Mods tab while stopped. Reading the mod list never changes files.

A confirmed candidate is renamed from `.jar` to `.jar.disabled`. Files are not deleted. The UI displays the evidence, unresolved dependency conflicts and manual decisions. Unknown files remain unchanged; a successful scan is not a guarantee that a modpack will start.

## Evidence and scope

- **Fabric:** the root `fabric.mod.json` must use supported schema version 1 and explicitly declare `environment: "client"`. Client entrypoints, client mixins or client classes alone are insufficient. Fabric metadata is only used for Fabric servers.
- **Forge / NeoForge:** parse `mods.toml` or `neoforge.mods.toml` for mod IDs and required dependencies on BOTH/SERVER. `displayTest` and a dependency's `side` do not classify the whole mod as client-only. Forge library JARs declaring `FMLModType: LIBRARY` are retained as libraries.
- **Server-pack reference:** for CurseForge file-link imports, MineDock tries the exact file's `serverPackFileId`. It validates project/file identity and the provider checksum, then hashes the server pack's mod JARs without extracting or executing its scripts. A manifest-ZIP import can be given an optional server-pack ZIP through the Mods tab. This is a comparison reference, not a replacement installer: server configs and extra server-only JARs are not automatically copied from it.
- **Complete comparison required:** every reference server JAR must be present byte-for-byte. Until then the UI explains that files are missing or differ. Only files tracked as part of the original manifest import are eligible for exclusion; later custom additions are preserved. Missing-download uploads receive their import provenance when their required checksum has been verified.
- **Pack profiles:** the initial profile covers Create a Colony 1.0.6, Minecraft 1.19.2 / Forge 43.2.6. It binds the exact manifest identity, the SHA-256 hashes of all 180 server JARs and 30 excluded CurseForge project/file pairs. It is not a global blacklist of those projects. Pre-update imports lack this provenance, so they do not silently acquire this profile by name alone.
- **Reviewed file rules:** `app/mod_rules.json` also supports rules bound to loader, Minecraft version, mod ID and exact SHA-256. No broad filename-based or unbounded project-wide exclusions are shipped. Rules update with a MineDock release; there is no remote executable rule feed.

If CurseForge's server pack is unavailable, metadata and bundled profiles still work. ZIP-only imports cannot automatically identify a generic CurseForge server-pack pairing from the manifest alone; supply the reference ZIP when needed. A reference that contains only an installer and no complete `mods` directory is not used.

## Dependencies and manual choices

Required dependencies are checked across the remaining active mods, including mod IDs and dependencies in declared nested JARs. Retention propagates through dependency chains. If an active file's metadata cannot be understood, automated removals are deferred. Metadata declarations cannot cover undeclared runtime dependencies or every legacy/custom loader.

Use **Aktivieren** or **Deaktivieren** to save a manual decision. It is scoped to the server, loader and declared mod IDs, so ordinary filename/version changes preserve the decision. When IDs cannot be read, it is scoped to the exact file hash. **Automatik verwenden** clears that decision and runs the scanner again. Already disabled files are never automatically re-enabled, even when a rule disappears or a dependency conflict is discovered.

Only administrators and managers may upload references, run a manual scan or change these decisions. Viewers and operators can read the results. An operator's normal start action includes the same pre-start check as an administrator's start.

Checks run while the Minecraft server is stopped. JAR content is inspected as ZIP data; no mod code is executed for detection. Metadata, archive nesting and archive sizes are bounded. Symlinks, duplicate active/disabled filenames and unsafe reference archives are rejected. A scan reads/hashes files locally; it makes no network requests during server startup.

## Maintaining rules

For a new exact-file rule, add an object to `rules` with `loader`, `minecraft`, `mod_id`, `sha256`, and a concise German `reason`. Verify the claim against the author's documentation or a matching server distribution, document that evidence in an additional `evidence` field, add a regression test, and increment `revision` to invalidate metadata caches. Never infer client-only status from a name or from a crash alone.

For a pack profile, record `manifest_key`, a complete SHA-256 `keep` inventory, an `exclude` list of `[projectID, fileID]` pairs, `label`, and `evidence`. Keep the scope exact and test changed/incomplete packs. No mod binaries are distributed in this repository.

## Sources

- [Fabric metadata specification](https://docs.fabricmc.net/develop/loader/fabric-mod-json)
- [Forge sides and display tests](https://docs.minecraftforge.net/en/1.19.x/concepts/sides/)
- [NeoForge mod files and dependency sides](https://docs.neoforged.net/docs/gettingstarted/modfiles/)
- [CurseForge API file metadata](https://docs.curseforge.com/rest-api/)
