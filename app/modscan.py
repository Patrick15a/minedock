"""Conservative, offline mod-side inspection. No mod code is executed."""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import time
import tomllib
import zipfile

from . import core

RULESET = json.loads(Path(__file__).with_name('mod_rules.json').read_text(encoding='utf-8'))
REVISION = RULESET['revision']
MAX_METADATA = 256 * 1024
MAX_NESTED = 32 * 1024**2


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def manifest_key(manifest):
    identity = {'name': manifest.get('name'), 'version': manifest.get('version'),
                'minecraft': manifest.get('minecraft'),
                'files': sorted((int(f['projectID']), int(f['fileID'])) for f in manifest['files'])}
    return hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def read_json(data):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Doppelte JSON-Schluessel')
            result[key] = value
        return result
    return json.loads(data, object_pairs_hook=unique)


def ids(values):
    if not isinstance(values, (list, dict)) or any(not isinstance(v, str) or not re.fullmatch(r'[a-zA-Z0-9_.-]{1,100}', v) for v in values):
        raise ValueError('Ungueltige Mod-IDs')
    return set(values)


def read_entry(archive, name, limit=MAX_METADATA):
    matches = [i for i in archive.infolist() if i.filename == name]
    if len(matches) != 1:
        raise ValueError('Metadaten fehlen oder sind doppelt')
    info = matches[0]
    if info.file_size > limit or info.flag_bits & 1 or info.file_size > max(info.compress_size, 1) * 1000:
        raise ValueError('Metadatenlimit')
    with archive.open(info) as source:
        data = source.read(limit + 1)
    if len(data) > limit:
        raise ValueError('Metadatenlimit')
    return data


def metadata(source, family, budget=None, depth=0):
    budget = budget if budget is not None else [64 * 1024**2, 128]
    if depth > 3 or budget[1] <= 0:
        raise ValueError('Verschachtelungslimit')
    budget[1] -= 1
    with zipfile.ZipFile(source) as archive:
        if len(archive.infolist()) > 20000:
            raise ValueError('Zu viele JAR-Eintraege')
        names = set(archive.namelist())
        nested = []
        if family == 'fabric' and 'fabric.mod.json' in names:
            data = read_json(read_entry(archive, 'fabric.mod.json'))
            if data.get('schemaVersion') != 1 or data.get('environment', '*') not in ('*', 'client', 'server'):
                raise ValueError('Unbekanntes Fabric-Schema')
            own_ids = ids([data['id']]) | ids(data.get('provides', []))
            required = ids(data.get('depends', {}))
            client = data.get('environment') == 'client'
            nested = [j['file'] for j in data.get('jars', [])]
            reason = 'fabric.mod.json kennzeichnet diese Mod ausdrücklich als client-only.' if client else ''
        elif family in ('forge', 'neoforge'):
            filename = 'META-INF/neoforge.mods.toml' if family == 'neoforge' and 'META-INF/neoforge.mods.toml' in names else 'META-INF/mods.toml'
            if filename not in names:
                manifest = read_entry(archive, 'META-INF/MANIFEST.MF').decode('utf-8') if 'META-INF/MANIFEST.MF' in names else ''
                if re.search(r'^FMLModType: LIBRARY\s*$', manifest, re.M):
                    return {'ids': [], 'primary': [], 'requires': [], 'client': False, 'readable': True,
                            'reason': 'Vom Loader als Bibliothek gekennzeichnet; keine Client-Einstufung.'}
                raise ValueError('Keine unterstützten Loader-Metadaten')
            data = tomllib.loads(read_entry(archive, filename).decode('utf-8-sig'))
            own_ids = ids([m['modId'] for m in data['mods']])
            if not own_ids:
                raise ValueError('Keine Mod-ID')
            required = set()
            for entries in data.get('dependencies', {}).values():
                for dep in entries:
                    side = dep.get('side', 'BOTH')
                    if side not in ('CLIENT', 'SERVER', 'BOTH'):
                        raise ValueError('Unbekannte Abhaengigkeitsseite')
                    mandatory = dep.get('mandatory', True) if family == 'forge' else dep.get('type', 'required') == 'required'
                    if mandatory and side != 'CLIENT':
                        required |= ids([dep['modId']])
            # displayTest and dependency.side do NOT declare the whole mod client-only.
            client, reason = False, ''
            if 'META-INF/jarjar/metadata.json' in names:
                nested = [j['path'] for j in read_json(read_entry(archive, 'META-INF/jarjar/metadata.json'))['jars']]
        else:
            raise ValueError('Keine unterstützten Loader-Metadaten')
        primary = sorted(own_ids)
        for name in nested:
            if not isinstance(name, str) or PurePosixPath(name).is_absolute() or '..' in PurePosixPath(name).parts or '\\' in name:
                raise ValueError('Ungueltiger eingebetteter JAR-Pfad')
            blob = read_entry(archive, name, min(MAX_NESTED, budget[0]))
            budget[0] -= len(blob)
            try:
                child = metadata(io.BytesIO(blob), family, budget, depth + 1)
            except ValueError as exc:
                # Ordinary shaded libraries do not contain loader metadata.
                if str(exc) != 'Keine unterstützten Loader-Metadaten':
                    raise
                continue
            own_ids |= set(child['ids'])
            if not child['client']:
                required |= set(child['requires'])
        return {'ids': sorted(own_ids), 'primary': primary, 'requires': sorted(required),
                'client': client, 'reason': reason, 'readable': True}


def inspect(path, family):
    try:
        return metadata(path, family)
    except (ValueError, KeyError, TypeError, AttributeError, IndexError, UnicodeError, OSError, zipfile.BadZipFile, RuntimeError, NotImplementedError, RecursionError):
        return {'ids': [], 'primary': [], 'requires': [], 'client': False, 'readable': False,
                'reason': 'Metadaten fehlen, sind unlesbar oder nicht unterstützt; keine automatische Einstufung.'}


def override_key(row, family):
    return family + ':' + (','.join(row['primary']) if row['primary'] else 'sha256:' + row['sha256'])


def profile_candidates(cfg, rows):
    available = {r['sha256'] for r in rows.values()}
    candidates, notes = {}, []
    reference = cfg.get('mod_server_reference', {})
    # Only original manifest JARs are subject to a pack comparison, never later custom uploads.
    refs = []
    if reference.get('keep'):
        refs.append(reference)
    for profile in RULESET.get('profiles', []):
        if cfg.get('mod_manifest_key') == profile['manifest_key']:
            refs.append(profile)
    for reference in refs:
        if not set(reference['keep']).issubset(available):
            notes.append('Serverpack-Abgleich wartet: Serverdateien fehlen oder unterscheiden sich vom Referenzpaket.')
            continue  # Incomplete/different server assembly is not an authoritative comparison.
        for name, row in rows.items():
            source = cfg.get('mod_sources', {}).get(name, {})
            if source.get('sha256') != row['sha256'] or row['sha256'] in reference['keep']:
                continue
            allowed = reference.get('exclude')
            if allowed is not None and [source.get('project'), source.get('file')] not in allowed:
                continue
            candidates[name] = 'Serverpack-Abgleich: ' + reference['label'] + ' enthält diese Datei nicht.'
    return candidates, ' '.join(dict.fromkeys(notes))


def scan(directory, cfg, log=lambda message: None):
    """Call under the manager lock or in its exclusive per-server job, while stopped."""
    mods = directory / 'mods'
    if directory.is_symlink() or mods.is_symlink():
        raise ValueError('Das Mod-Verzeichnis darf kein Symlink sein.')
    rows = {}
    family = cfg.get('loader', '').split('-', 1)[0]
    previous = cfg.get('mod_scan', {})
    deadline = time.monotonic() + 60
    paths = sorted(mods.iterdir()) if mods.exists() else []
    if len(paths) > 3000:
        raise ValueError('Zu viele Dateien für die automatische Mod-Prüfung (maximal 3000).')
    for path in paths:
        if path.is_symlink() and (path.name.endswith('.jar') or path.name.endswith('.jar.disabled')):
            raise ValueError('Verknüpfte Mod-Datei: bitte Symlink vor der Prüfung entfernen.')
        if path.is_symlink() or not path.is_file() or not (path.name.endswith('.jar') or path.name.endswith('.jar.disabled')):
            continue
        if path.stat().st_size > 512 * 1024**2 or time.monotonic() > deadline:
            raise ValueError('Mod-Prüfung überschreitet Größen- oder Zeitlimit; keine Datei wurde deaktiviert.')
        name = path.name.removesuffix('.disabled')
        if name in rows:
            raise ValueError('Mod ist gleichzeitig aktiv und deaktiviert vorhanden: ' + name)
        sha = digest(path)
        old = previous.get(name, {})
        if old.get('sha256') == sha and old.get('family') == family and old.get('revision') == REVISION:
            details = {k: old[k] for k in ('ids', 'primary', 'requires', 'client', 'readable', 'metadata_reason')}
            details['reason'] = details.pop('metadata_reason')
        else:
            details = inspect(path, family)
        rows[name] = {**details, 'metadata_reason': details['reason'], 'sha256': sha,
                      'family': family, 'revision': REVISION, 'enabled': path.name.endswith('.jar')}
    profiles, note = profile_candidates(cfg, rows)
    candidates = {}
    overrides = cfg.setdefault('mod_overrides', {})
    for name, row in rows.items():
        row['key'] = override_key(row, family)
        row['override'] = overrides.get(row['key'], 'auto')
        row['status'] = 'unknown' if not row['readable'] else 'unchecked'
        row['reason'] = row['metadata_reason'] or 'Keine eindeutige Client-Kennzeichnung; Datei bleibt unverändert.'
        reason = profiles.get(name) or (row['metadata_reason'] if row['client'] else '')
        for rule in RULESET.get('rules', []):
            if (family == rule['loader'] and cfg.get('version') == rule['minecraft']
                    and row['sha256'] == rule['sha256'] and rule['mod_id'] in row['ids']):
                reason = rule['reason']
        if reason:
            candidates[name] = reason
            row['status'], row['reason'] = 'client', reason
        if row['override'] != 'auto':
            row['status'] = 'manual'
            row['reason'] = 'Manuelle Entscheidung: ' + ('aktiv lassen.' if row['override'] == 'allow' else 'deaktiviert lassen.')
    removals = {name for name in candidates if rows[name]['override'] == 'auto' and rows[name]['readable']}
    for name in candidates:
        if not rows[name]['readable'] and rows[name]['override'] == 'auto':
            rows[name]['status'] = 'conflict'
            rows[name]['reason'] += ' Automatik ausgesetzt: eigene Mod-IDs und Abhängigkeiten sind nicht lesbar.'
    for name in list(removals):
        if rows[name]['enabled'] and len((name + '.disabled').encode('utf-8')) > 255:
            removals.remove(name)
            rows[name]['status'], rows[name]['reason'] = 'conflict', 'Dateiname ist für eine sichere Deaktivierung zu lang.'
    # Fixed point: retaining one candidate may require retaining another candidate.
    while True:
        retained = [r for n, r in rows.items() if n not in removals and r['enabled']]
        unknown = any(not r['readable'] for r in retained)
        needed = {dep for r in retained for dep in r['requires']}
        blocked = {n for n in removals if unknown or needed.intersection(rows[n]['ids'])}
        if not blocked:
            break
        for name in blocked:
            rows[name]['status'] = 'conflict'
            rows[name]['reason'] = (candidates[name] + ' Automatik ausgesetzt: ' +
                ('Abhängigkeiten anderer aktiver Dateien sind nicht vollständig lesbar.' if unknown else
                 'Eine verbleibende Mod benötigt diese Mod oder eine enthaltene Bibliothek.'))
        removals -= blocked
    renamed = []
    try:
        for name, row in rows.items():
            disable = name in removals or row['override'] == 'disable'
            if disable and row['enabled']:
                source, target = mods / name, mods / (name + '.disabled')
                # Linux filesystems have a 255-byte component limit.
                if len(target.name.encode('utf-8')) > 255 or target.exists() or target.is_symlink():
                    row['status'], row['reason'] = 'conflict', 'Zieldatei für die Deaktivierung ist nicht verfügbar.'
                    continue
                source.rename(target)
                renamed.append((source, target))
                row['enabled'] = False
                log('[MineDock] Mod-Prüfung: ' + name + ' deaktiviert. ' + row['reason'])
            elif row['override'] == 'auto' and not row['enabled'] and row['status'] not in ('client', 'conflict'):
                row['reason'] += ' Bereits deaktivierte Dateien werden nicht automatisch aktiviert.'
    except BaseException:
        for source, target in reversed(renamed):
            target.rename(source)
        raise
    cfg['mod_scan'] = rows
    cfg['mod_scan_summary'] = {'checked': len(rows), 'disabled': sum(not r['enabled'] for r in rows.values()),
                               'conflicts': sum(r['status'] == 'conflict' for r in rows.values()), 'revision': REVISION, 'note': note}
    return rows


def run(sid, manager):
    cfg = core.get(sid)
    scan(core.folder(sid), cfg, lambda message: manager.log(sid, message))
    core.save(cfg)
    return cfg


def server_inventory(path):
    """Read and hash only JAR entries; never extract/execute server-pack scripts."""
    with zipfile.ZipFile(path) as archive:
        entries = archive.infolist()
        if len(entries) > 20000 or sum(e.file_size for e in entries) > 2 * 1024**3:
            raise ValueError('Serverpack überschreitet das Prüflimit.')
        roots, hashes, seen = set(), [], set()
        for entry in entries:
            p = PurePosixPath(entry.filename)
            if (p.is_absolute() or '..' in p.parts or '\\' in entry.filename or entry.filename in seen
                    or entry.flag_bits & 1 or (entry.external_attr >> 16) & 0o170000 == 0o120000):
                raise ValueError('Unzulässiger Serverpack-Eintrag.')
            seen.add(entry.filename)
            if p.parent.name != 'mods' or p.suffix != '.jar':
                continue
            if entry.file_size > 512 * 1024**2 or entry.file_size > max(entry.compress_size, 1) * 1000:
                raise ValueError('Serverpack-JAR überschreitet das Prüflimit.')
            roots.add(p.parent.as_posix())
            with archive.open(entry) as source:
                hashes.append(hashlib.file_digest(source, 'sha256').hexdigest())
        if len(roots) != 1 or not hashes:
            raise ValueError('Serverpack hat keine eindeutige vollständige Mod-Liste.')
        return sorted(set(hashes))
