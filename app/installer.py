from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import time
import unicodedata
import zipfile
from pathlib import Path
from urllib.parse import quote, urlparse, urljoin

import httpx

from . import core
from .runtime import manager

MAX_FILE = 512 * 1024 * 1024
TRUSTED = {'api.curseforge.com', 'edge.forgecdn.net', 'mediafilez.forgecdn.net', 'media.forgecdn.net',
           'piston-meta.mojang.com', 'piston-data.mojang.com', 'launchermeta.mojang.com',
           'launcher.mojang.com', 'meta.fabricmc.net', 'maven.minecraftforge.net', 'maven.neoforged.net'}


def validate_url(url):
    parsed = urlparse(url)
    if parsed.scheme != 'https' or parsed.hostname not in TRUSTED or parsed.port not in (None, 443) or parsed.username or parsed.password:
        raise ValueError('Download-Host ist nicht freigegeben.')
    return parsed.hostname


def fetch(url, destination=None, limit=MAX_FILE, expected=None):
    deadline = time.monotonic() + 600
    with httpx.Client(timeout=45, follow_redirects=False) as client:
        for _ in range(6):
            host = validate_url(url)
            headers = {'User-Agent': 'MineDock/0.1'}
            if host == 'api.curseforge.com' or host.endswith('.forgecdn.net'):
                if core.CF_KEY:
                    headers['x-api-key'] = core.CF_KEY
            with client.stream('GET', url, headers=headers) as response:
                if response.is_redirect:
                    url = urljoin(url, response.headers['location'])
                    continue
                if response.status_code in (401, 403):
                    status = response.status_code
                    if host == 'api.curseforge.com':
                        raise ValueError(f'CurseForge-API verweigert den Zugriff (HTTP {status}). '
                                         'API-Schlüssel und dessen Berechtigung in der CurseForge-Entwicklerkonsole prüfen; '
                                         'nach einer Schlüsseländerung MineDock neu starten.')
                    if host.endswith('.forgecdn.net'):
                        raise ValueError(f'CurseForge-Dateidownload von {host} verweigert (HTTP {status}). '
                                         'Downloadfreigabe und API-Schlüssel prüfen. '
                                         'Bei einem Modpack kann alternativ ein CurseForge-Export als ZIP hochgeladen werden; '
                                         'enthaltene Mods benötigen weiterhin API-Zugriff.')
                    raise ValueError(f'Download von {host} verweigert (HTTP {status}). '
                                     'Freigabe beim Downloadanbieter prüfen.')
                if response.status_code >= 400:
                    raise ValueError(f'Download von {host} fehlgeschlagen (HTTP {response.status_code}).')
                content = bytearray()
                size = 0
                hashes = {name: hashlib.new(name) for name in ('sha1', 'md5', 'sha256')}
                if destination:
                    destination.parent.mkdir(parents=True, exist_ok=True)
                stream = destination.open('wb') if destination else None
                try:
                    for chunk in response.iter_bytes(65536):
                        size += len(chunk)
                        if size > limit or time.monotonic() > deadline:
                            raise ValueError('Download überschreitet Größen- oder Zeitlimit.')
                        for digest in hashes.values():
                            digest.update(chunk)
                        if stream:
                            stream.write(chunk)
                        else:
                            content.extend(chunk)
                    if expected and hashes[expected[0]].hexdigest().lower() != expected[1].lower():
                        raise ValueError('Prüfsumme des Downloads stimmt nicht überein.')
                except BaseException:
                    if stream:
                        stream.close()
                        destination.unlink(missing_ok=True)
                    raise
                finally:
                    if stream:
                        stream.close()
                return bytes(content) if not destination else size
        raise ValueError('Zu viele Download-Weiterleitungen.')


def get_json(url):
    return json.loads(fetch(url, limit=10 * 1024 * 1024))


def cf(path):
    if not core.CF_KEY:
        raise ValueError('CURSEFORGE_API_KEY fehlt. In /etc/minedock/minedock.env hinterlegen und Dienst neu starten.')
    return get_json('https://api.curseforge.com/v1/' + path)['data']


def file_hash(info):
    for algo, name in ((1, 'sha1'), (2, 'md5')):
        for entry in info.get('hashes', []):
            if entry['algo'] == algo:
                return (name, entry['value'])
    return None


def filename(value):
    # Keep the original basename: missing-file uploads must match it exactly.
    # Reserve nine bytes for the .disabled suffix on 255-byte filesystems.
    if (not isinstance(value, str) or len(value) <= 4 or not value.endswith('.jar')
            or any(c in '<>:"/\\|?*' or unicodedata.category(c).startswith('C')
                   or c in '\u2028\u2029' for c in value)
            or len(value.encode('utf-8')) > 246):
        display = repr(value[:240]) if isinstance(value, str) else type(value).__name__
        raise ValueError(f'Ungültiger JAR-Dateiname {display}. '
                         'Erwartet wird ein einzelner .jar-Dateiname ohne Pfad oder Steuerzeichen '
                         '(maximal 246 UTF-8-Bytes).')
    return value


def client_archive_type(project, file_info):
    # A modpack manifest also lists client resource/shader archives. Do not
    # infer their role from the extension alone or from the optional flag.
    name = file_info.get('fileName')
    if not isinstance(name, str) or not name.lower().endswith('.zip'):
        return None
    project_info = cf(f'mods/{project}')
    classes = {12: 'Client-Ressourcenpaket', 6552: 'Client-Shaderpaket'}
    if (project_info.get('id') == project and project_info.get('gameId') == 432
            and project_info.get('classId') in classes):
        return classes[project_info['classId']]
    raise ValueError(f'ZIP-Datei {name[:240]!r} ist laut CurseForge kein bestätigtes '
                     'Client-Ressourcen- oder Shaderpaket. Dieser Dateityp wird '
                     'im Serverimport nicht unterstützt; die Datei wurde nicht übersprungen.')


def inspect_zip(archive):
    with zipfile.ZipFile(archive) as zf:
        infos = zf.infolist()
        if len(infos) > 20000 or sum(i.file_size for i in infos) > 2 * 1024**3:
            raise ValueError('ZIP ist zu groß (max. 2 GB entpackt / 20.000 Einträge).')
        seen = set()
        for info in infos:
            name = info.orig_filename.rstrip('/')
            core.safe_path(Path('/zip-root').resolve(), name)
            if name in seen or stat.S_ISLNK(info.external_attr >> 16) or info.flag_bits & 1:
                raise ValueError('ZIP enthält doppelte, verknüpfte oder verschlüsselte Einträge.')
            seen.add(name)
            if info.file_size > MAX_FILE or info.file_size > max(info.compress_size, 1) * 1000:
                raise ValueError('ZIP-Eintrag überschreitet das Größenlimit.')
        if 'manifest.json' not in seen:
            raise ValueError('CurseForge-Export mit manifest.json im ZIP-Hauptverzeichnis erforderlich. Server-Packs mit Startskripten werden nicht automatisch ausgeführt.')
        if zf.getinfo('manifest.json').file_size > 2 * 1024 * 1024:
            raise ValueError('Manifest zu groß.')
        manifest = json.loads(zf.read('manifest.json'))
        if manifest.get('manifestType') != 'minecraftModpack' or manifest.get('manifestVersion') != 1:
            raise ValueError('Kein unterstütztes CurseForge-Modpack.')
        if not isinstance(manifest.get('files'), list) or len(manifest['files']) > 3000:
            raise ValueError('Ungültige Mod-Liste.')
        return manifest


def extract_overrides(archive, manifest, destination):
    override = manifest.get('overrides', 'overrides')
    core.safe_path(destination, override)
    prefix = override.rstrip('/') + '/'
    allowed = {'mods', 'config', 'defaultconfigs', 'kubejs', 'scripts', 'resourcepacks', 'datapacks'}
    with zipfile.ZipFile(archive) as zf:
        for item in zf.infolist():
            if not item.filename.startswith(prefix) or item.is_dir():
                continue
            relative = item.filename[len(prefix):]
            if relative.split('/')[0] not in allowed:
                continue
            target = core.safe_path(destination, relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(item) as source, target.open('wb') as output:
                shutil.copyfileobj(source, output, length=65536)


def token(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-zA-Z0-9_.+\-]{1,100}', value):
        raise ValueError('Ungültige Minecraft-/Loader-Version.')
    return value


def run_installer(sid, java, jar, directory):
    if os.name != 'posix' or not os.path.isfile(java):
        raise ValueError('Loader-Installation benötigt Linux und die konfigurierte Java-Version.')
    log = directory / 'installer.log'
    with log.open('wb') as output:
        process = subprocess.Popen([java, '-Xmx1024M', '-jar', str(jar), '--installServer'], cwd=directory,
                                   stdout=output, stderr=subprocess.STDOUT, start_new_session=True, env=core.child_env())
        try:
            code = process.wait(timeout=900)
        except subprocess.TimeoutExpired:
            import signal
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
            raise ValueError('Loader-Installation hat das Zeitlimit überschritten.')
    with log.open('rb') as stream:
        stream.seek(max(0, log.stat().st_size - 16000))
        manager.log(sid, stream.read().decode('utf8', errors='replace'))
    if code:
        raise ValueError(f'Loader-Installer fehlgeschlagen (Exit-Code {code}). Java-Version und Konsole prüfen.')


def install_loader(sid, cfg, directory, version, loader):
    version = token(version)
    if loader == 'vanilla':
        versions = get_json('https://piston-meta.mojang.com/mc/game/version_manifest_v2.json')
        entry = next((v for v in versions['versions'] if v['id'] == version), None)
        if not entry:
            raise ValueError('Minecraft-Version nicht gefunden.')
        server = get_json(entry['url']).get('downloads', {}).get('server')
        if not server:
            raise ValueError('Für diese Version ist keine Server-JAR verfügbar.')
        fetch(server['url'], directory / 'server.jar', expected=('sha1', server['sha1']))
        return ['-jar', 'server.jar']
    family, number = loader.split('-', 1)
    number = token(number)
    if family == 'fabric':
        installers = get_json('https://meta.fabricmc.net/v2/versions/installer')
        installer = token(next(v['version'] for v in installers if v.get('stable')))
        fetch(f'https://meta.fabricmc.net/v2/versions/loader/{version}/{number}/{installer}/server/jar', directory / 'server.jar')
        return ['-jar', 'server.jar']
    if family == 'forge':
        full = f'{version}-{number}'
        url = f'https://maven.minecraftforge.net/net/minecraftforge/forge/{full}/forge-{full}-installer.jar'
        argfile = f'libraries/net/minecraftforge/forge/{full}/unix_args.txt'
    elif family == 'neoforge':
        full = number
        url = f'https://maven.neoforged.net/releases/net/neoforged/neoforge/{full}/neoforge-{full}-installer.jar'
        argfile = f'libraries/net/neoforged/neoforge/{full}/unix_args.txt'
    else:
        raise ValueError('Unterstützte Loader: Vanilla, Fabric, Forge und NeoForge.')
    jar = directory / 'loader-installer.jar'
    fetch(url, jar)
    run_installer(sid, core.JAVA[cfg['java']], jar, directory)
    if (directory / argfile).is_file():
        return ['@' + argfile]
    legacy = list(directory.glob(f'forge-{full}*.jar')) if family == 'forge' else []
    legacy = [p for p in legacy if 'installer' not in p.name]
    if len(legacy) == 1:
        return ['-jar', legacy[0].name]
    raise ValueError('Kein unterstützter Startpfad nach Loader-Installation gefunden.')


def properties(cfg, directory):
    lines = {'server-port': cfg['port'], 'max-players': cfg['max_players'], 'motd': cfg['motd'],
             'difficulty': cfg['difficulty'], 'gamemode': cfg['gamemode'], 'online-mode': 'true',
             'white-list': str(cfg['whitelist']).lower(), 'enable-rcon': 'false', 'enable-query': 'false'}
    path = directory / 'server.properties'
    old = path.read_text(encoding='utf8', errors='replace').splitlines() if path.exists() else []
    old = [line for line in old if line.split('=', 1)[0].strip() not in lines]
    def escape(value):
        value = str(value).replace('\\', '\\\\')
        output = ''
        for char in value:
            if ord(char) < 128:
                output += char
            else:
                encoded = char.encode('utf-16-be')
                output += ''.join('\\u' + encoded[i:i+2].hex() for i in range(0, len(encoded), 2))
        return output
    path.write_text('\n'.join(old + [f'{key}={escape(value)}' for key, value in lines.items()]) + '\n', encoding='utf8')


def install(sid, mode, source=None, version=None):
    cfg = core.get(sid)
    directory = core.folder(sid)
    if cfg.get('installed'):
        raise ValueError('Bereits installiert. Modpack-Versionen als neuen Server installieren; bestehende Welten bleiben erhalten.')
    if any(directory.iterdir()):
        raise ValueError('Serververzeichnis ist nicht leer. Für den Import bitte einen neuen Server anlegen.')
    stage = core.ROOT / 'uploads' / (sid + '-stage')
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir()
    try:
        missing = []
        pack_name = 'Vanilla'
        if mode == 'vanilla':
            loader = 'vanilla'
        else:
            if mode == 'curseforge':
                match = re.fullmatch(r'https://(?:www\.)?curseforge\.com/minecraft/modpacks/([a-z0-9-]+)/files/(\d+)/?', source or '')
                if not match:
                    raise ValueError('Bitte einen CurseForge-Dateilink mit /files/DATEI-ID verwenden, damit die Version feststeht.')
                slug, file_id = match.groups()
                matches = cf('mods/search?gameId=432&classId=4471&slug=' + quote(slug))
                mod = next((m for m in matches if m['slug'] == slug), None)
                if not mod:
                    raise ValueError('Modpack nicht gefunden.')
                info = cf(f"mods/{mod['id']}/files/{file_id}")
                url = info.get('downloadUrl')
                if not url:
                    raise ValueError('Dieses Modpack muss manuell heruntergeladen und als ZIP importiert werden.')
                source = stage / 'modpack.zip'
                fetch(url, source, expected=file_hash(info))
            manifest = inspect_zip(source)
            pack_name = str(manifest.get('name', 'Modpack'))[:100]
            version = manifest['minecraft']['version']
            loaders = manifest['minecraft']['modLoaders']
            loader = next((l['id'] for l in loaders if l.get('primary')), loaders[0]['id'])
            extract_overrides(source, manifest, stage)
            skipped_client_archives = 0
            for index, ref in enumerate(manifest['files']):
                project, file_id = int(ref['projectID']), int(ref['fileID'])
                if project <= 0 or file_id <= 0:
                    raise ValueError('Ungültige CurseForge-Datei-ID.')
                info = cf(f'mods/{project}/files/{file_id}')
                try:
                    archive_type = client_archive_type(project, info)
                    if archive_type:
                        skipped_client_archives += 1
                        manager.log(sid, f'[Import {index + 1}/{len(manifest["files"])}] '
                                         f'{info["fileName"][:240]!r}: {archive_type} '
                                         'übersprungen (nur für Minecraft-Clients).')
                        continue
                    name = filename(info.get('fileName'))
                except ValueError as exc:
                    raise ValueError(f'[Import {index + 1}/{len(manifest["files"])}] '
                                     f'CurseForge-Projekt {project}, Datei {file_id}: {exc}') from exc
                manager.log(sid, f'[Import {index + 1}/{len(manifest["files"])}] {name}')
                target = core.safe_path(stage, 'mods/' + name)
                if info.get('downloadUrl'):
                    fetch(info['downloadUrl'], target, expected=file_hash(info))
                else:
                    project_info = cf(f'mods/{project}')
                    website = project_info.get('links', {}).get('websiteUrl', '')
                    if not re.fullmatch(r'https://(?:www\.)?curseforge\.com/minecraft/mc-mods/[a-zA-Z0-9_-]+', website):
                        website = 'https://www.curseforge.com/minecraft/search?search=' + str(project)
                    missing.append({'name': name, 'project': project, 'file': file_id, 'hash': file_hash(info),
                                    'url': website + ('/files/' + str(file_id) if '?' not in website else '')})
            if skipped_client_archives:
                manager.log(sid, f'[MineDock] {skipped_client_archives} Client-Ressourcen-/Shaderpaket(e) '
                                 'übersprungen. Sie werden auf den Minecraft-Clients verwendet.')
        manager.log(sid, f'[MineDock] Installiere {loader} für Minecraft {version}.')
        launch = install_loader(sid, cfg, stage, version, loader)
        properties(cfg, stage)
        (stage / 'modpack.zip').unlink(missing_ok=True)
        # Promote the entire staged installation on the same filesystem; no partial live tree.
        directory.rmdir()
        try:
            stage.rename(directory)
        except BaseException:
            directory.mkdir(exist_ok=True)
            raise
        cfg.update(installed=True, launch=launch, loader=loader, version=version, pack=pack_name, missing=missing)
        core.save(cfg)
        if missing:
            manager.log(sid, f'[MineDock] {len(missing)} Datei(en) müssen manuell hochgeladen werden. Start bleibt gesperrt.')
    finally:
        shutil.rmtree(stage, ignore_errors=True)
        if mode == 'zip' and source:
            Path(source).unlink(missing_ok=True)
