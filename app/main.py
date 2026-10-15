from __future__ import annotations

import hashlib
import os
import re
import secrets
import shutil
import sqlite3
import tarfile
import threading
import time
import zipfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

import psutil
from fastapi import Depends, FastAPI, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from . import core, installer, modscan
from .runtime import manager

STATIC = Path(__file__).parent / 'static'
sessions = {}
attempts = {}
auth_lock = threading.Lock()
DUMMY_PASSWORD_HASH = core.hash_password(secrets.token_urlsafe(32))


@asynccontextmanager
async def lifespan(app):
    core.init()
    if not any(u['role'] == 'admin' and u['active'] for u in core.users()):
        raise RuntimeError('Kein aktiver Administrator vorhanden. Erstinstallation mit deploy/configure.py vorbereiten.')
    yield
    manager.shutdown()


app = FastAPI(title='MineDock', docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)


class BodyLimit:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        limit = 513 * 1024**2 if scope['path'].endswith('/upload') else 2 * 1024**2
        total = 0
        async def limited():
            nonlocal total
            message = await receive()
            total += len(message.get('body', b''))
            if total > limit:
                raise HTTPException(413, 'Upload zu groß.')
            return message
        await self.app(scope, limited, send)


app.add_middleware(BodyLimit)


@app.middleware('http')
async def security(request, call_next):
    if request.url.path.startswith('/api/') and request.url.path != '/api/login':
        try:
            info = auth(request)
            authorize_request(request, info)
        except HTTPException as exc:
            return JSONResponse({'detail': exc.detail}, status_code=exc.status_code, headers={'Cache-Control':'no-store'})
    if request.method not in ('GET', 'HEAD', 'OPTIONS'):
        origin = request.headers.get('origin')
        expected = str(request.base_url).rstrip('/')
        if origin and origin != expected:
            return JSONResponse({'detail': 'Fremder Ursprung abgewiesen.'}, status_code=403)
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
    if request.url.path.startswith('/api') or request.url.path == '/':
        response.headers['Cache-Control'] = 'no-store'
    elif request.url.path in ('/static/app.js', '/static/style.css'):
        response.headers['Cache-Control'] = 'no-cache'
    return response


@app.exception_handler(RequestValidationError)
async def validation_error(request, exc):
    # Do not reflect password values from validation failures into API responses.
    return JSONResponse({'detail': [{k: error[k] for k in ('type', 'loc', 'msg')} for error in exc.errors()]}, status_code=422)


@app.exception_handler(ValueError)
async def value_error(request, exc):
    return JSONResponse({'detail': str(exc)}, status_code=400)


@app.exception_handler(zipfile.BadZipFile)
async def invalid_archive(request, exc):
    return JSONResponse({'detail': 'Die ZIP-Datei ist beschädigt oder hat ein ungültiges Format.'}, status_code=400)


def auth(request: Request):
    session_id = request.cookies.get('minedock')
    with auth_lock:
        session = sessions.get(session_id)
        if not session or session['expires'] < time.monotonic():
            sessions.pop(session_id, None)
            raise HTTPException(401, 'Bitte anmelden.')
        if request.method not in ('GET', 'HEAD') and not secrets.compare_digest(request.headers.get('x-csrf-token', ''), session['csrf']):
            raise HTTPException(403, 'Sitzungsschutz fehlgeschlagen. Seite neu laden.')
        user = core.user_by_id(session.get('user_id'))
        if not user or not user['active'] or user['session_version'] != session.get('version'):
            sessions.pop(session_id, None)
            raise HTTPException(401, 'Die Anmeldung ist abgelaufen oder die Kontorechte wurden geändert.')
        return {**session, 'user': core.public_user(user)}


def authorize_request(request, info):
    user = info['user']
    path, method = request.url.path, request.method
    if path in ('/api/session', '/api/logout', '/api/account/password'):
        return
    if path == '/api/overview' and method == 'GET':
        return
    if user['role'] == 'admin':
        return
    if path == '/api/servers' and method == 'POST' and user['role'] == 'manager':
        return
    match = re.fullmatch(r'/api/servers/([a-f0-9]{16})(.*)', path)
    if match:
        sid, suffix = match.groups()
        if sid not in user['server_ids']:
            raise HTTPException(404, 'Server nicht gefunden.')
        if user['role'] == 'manager':
            return
        if method == 'GET' and suffix in ('/logs', '/mods'):
            return
        if user['role'] == 'operator' and method == 'POST' and suffix in ('/action/start', '/action/stop', '/action/restart', '/command'):
            return
    raise HTTPException(403, 'Für diese Aktion fehlen die Berechtigungen.')


class Login(BaseModel):
    username: str = Field(max_length=100)
    password: str = Field(max_length=1024)


@app.post('/api/login')
def login(body: Login, request: Request, response: Response):
    peer = request.client.host if request.client else 'local'
    now = time.monotonic()
    with auth_lock:
        for key in list(attempts):
            if attempts[key]['until'] < now:
                del attempts[key]
        record = attempts.setdefault(peer, {'until': now + 300, 'count': 0})
        if record['count'] >= 8 or len(attempts) > 10000:
            raise HTTPException(429, 'Zu viele Anmeldeversuche. In fünf Minuten erneut versuchen.')
        record['count'] += 1
    user = core.user_by_name(body.username)
    valid = core.verify_password(body.password, user['password_hash'] if user else DUMMY_PASSWORD_HASH)
    if not valid or not user or not user['active']:
        raise HTTPException(401, 'Benutzername oder Passwort falsch.')
    sid = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(32)
    with auth_lock:
        attempts.pop(peer, None)
        for key in list(sessions):
            if sessions[key]['expires'] < now:
                del sessions[key]
        if len(sessions) >= 50:
            sessions.pop(next(iter(sessions)))
        sessions[sid] = {'csrf': csrf, 'expires': now + 12 * 3600, 'user_id': user['id'], 'version': user['session_version']}
    response.set_cookie('minedock', sid, httponly=True, secure=core.SECURE, samesite='strict', max_age=43200)
    return {'csrf': csrf, 'user': core.public_user(user)}


@app.get('/api/session')
def session(info=Depends(auth)):
    return {'csrf': info['csrf'], 'username': info['user']['username'], 'user': info['user']}


@app.post('/api/logout')
def logout(request: Request, response: Response, _=Depends(auth)):
    with auth_lock:
        sessions.pop(request.cookies.get('minedock'), None)
    response.delete_cookie('minedock')
    return {'ok': True}


class Settings(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    port: int = Field(ge=1024, le=65535)
    memory_mb: int = Field(ge=1024, le=32768)
    java: str = '21'
    max_players: int = Field(default=20, ge=1, le=500)
    motd: str = Field(default='Ein neuer Minecraft-Server', max_length=120)
    difficulty: Literal['peaceful', 'easy', 'normal', 'hard'] = 'normal'
    gamemode: Literal['survival', 'creative', 'adventure', 'spectator'] = 'survival'
    whitelist: bool = False
    eula: bool = False

    @field_validator('name', 'motd')
    @classmethod
    def one_line(cls, value):
        if not value.strip() or any(ord(c) < 32 for c in value):
            raise ValueError('Nur einzeiliger Text erlaubt.')
        return value.strip()


def validate_settings(body, sid=None):
    if body.java not in core.JAVA:
        raise ValueError('Java-Version nicht konfiguriert.')
    if body.memory_mb + 768 > core.BUDGET_MB:
        raise ValueError('RAM inklusive 768 MB Reserve überschreitet das Serverbudget.')
    if any(s['id'] != sid and not s.get('archived') and s['port'] == body.port for s in core.rows()):
        raise ValueError('Port wird bereits von einem anderen Server verwendet.')


def editable(sid):
    manager.idle(sid)
    cfg = core.get(sid)
    if cfg.get('archived'):
        raise ValueError('Dieser Server ist archiviert.')
    return cfg


@app.get('/api/overview')
def overview(info=Depends(auth)):
    user = info['user']
    servers = [manager.snapshot(s) for s in core.rows() if user['role'] == 'admin' or s['id'] in user['server_ids']]
    memory = psutil.virtual_memory()
    return {'servers': servers, 'user': user, 'host': {'memory_total_mb': round(memory.total / 1048576),
            'memory_available_mb': round(memory.available / 1048576), 'budget_mb': core.BUDGET_MB,
            'reserved_mb': sum(s['memory_mb'] + 768 for s in servers if s['state'] == 'running'),
            'disk_free_gb': round(shutil.disk_usage(core.ROOT).free / 1024**3, 1),
            'java_versions': list(core.JAVA), 'curseforge_configured': bool(core.CF_KEY),
            'linux': os.name == 'posix'}}


@app.post('/api/servers')
def create_server(body: Settings, info=Depends(auth)):
    with manager.lock:
        validate_settings(body)
        sid = secrets.token_hex(8)
        cfg = {**body.model_dump(), 'id': sid, 'installed': False, 'archived': False, 'missing': [],
               'pack': 'Noch nicht installiert', 'loader': '', 'version': '', 'launch': []}
        (core.ROOT / 'servers' / sid).mkdir()
        core.save(cfg)
        if info['user']['role'] != 'admin':
            core.grant_server(info['user']['id'], sid)
    return manager.snapshot(cfg)


@app.put('/api/servers/{sid}')
def update_server(sid: str, body: Settings, _=Depends(auth)):
    with manager.lock:
        cfg = editable(sid)
        validate_settings(body, sid)
        cfg.update(body.model_dump())
        if cfg['installed']:
            installer.properties(cfg, core.folder(sid))
        core.save(cfg)
    return manager.snapshot(cfg)


class InstallRequest(BaseModel):
    mode: Literal['vanilla', 'curseforge']
    source: str | None = Field(default=None, max_length=500)
    version: str | None = Field(default=None, max_length=100)


@app.post('/api/servers/{sid}/install')
def install_server(sid: str, body: InstallRequest, _=Depends(auth)):
    with manager.lock:
        cfg = editable(sid)
        if cfg['installed']:
            raise ValueError('Server ist bereits installiert.')
        manager.submit(sid, 'Serverinstallation', lambda: installer.install(sid, body.mode, body.source, body.version))
    return {'ok': True}


@app.post('/api/servers/{sid}/action/{action}')
def action_server(sid: str, action: Literal['start', 'stop', 'restart', 'archive'], _=Depends(auth)):
    core.get(sid)
    if action == 'start':
        manager.start(sid)
    elif action == 'stop':
        manager.stop(sid)
    elif action == 'restart':
        manager.stop(sid)
        manager.start(sid)
    else:
        with manager.lock:
            cfg = editable(sid)
            cfg['archived'] = True
            core.save(cfg)
    return {'ok': True}


class Command(BaseModel):
    command: str = Field(min_length=1, max_length=1000)


@app.post('/api/servers/{sid}/command')
def command(sid: str, body: Command, _=Depends(auth)):
    core.get(sid)
    manager.command(sid, body.command)
    return {'ok': True}


@app.get('/api/servers/{sid}/logs')
def logs(sid: str, after: int = 0, _=Depends(auth)):
    core.get(sid)
    with manager.lock:
        return {'lines': [l for l in manager.logs[sid] if l['id'] > after], 'cursor': manager.sequence[sid]}


@app.post('/api/servers/{sid}/upload')
def upload(sid: str, file: UploadFile, kind: Literal['modpack', 'mod', 'server', 'serverpack'] = 'mod', _=Depends(auth)):
    # UploadFile is spooled to disk by Starlette; the ASGI and reverse-proxy limits bound total input.
    target = core.ROOT / 'uploads' / secrets.token_hex(16)
    try:
        size = 0
        with target.open('wb') as stream:
            while chunk := file.file.read(65536):
                size += len(chunk)
                if size > installer.MAX_FILE:
                    raise HTTPException(413, 'Maximal 512 MB pro Datei.')
                stream.write(chunk)
        with manager.lock:
            cfg = editable(sid)
            directory = core.folder(sid)
            if kind == 'modpack':
                if cfg['installed']:
                    raise ValueError('Modpack-Import benötigt einen neuen Server.')
                installer.inspect_zip(target)
                manager.submit(sid, 'Modpack-Import', lambda source=target: installer.install(sid, 'zip', source))
                target = None
            elif kind == 'serverpack':
                if not cfg['installed'] or not cfg.get('mod_sources'):
                    raise ValueError('Eine Serverpack-Referenz benötigt einen mit dieser MineDock-Version importierten Modpack-Server.')
                cfg['mod_server_reference'] = {'keep': modscan.server_inventory(target),
                    'label': 'hochgeladenes Serverpack'}
                core.save(cfg)
                modscan.run(sid, manager)
            else:
                name = installer.filename(file.filename or '')
                if not zipfile.is_zipfile(target):
                    raise ValueError('Keine gültige JAR-Datei.')
                if kind == 'server':
                    if cfg['installed']:
                        raise ValueError('Server-JAR nur bei einem neuen Server hochladen.')
                    destination = directory / 'server.jar'
                    cfg.update(installed=True, launch=['-jar', 'server.jar'], pack='Eigener Server', loader='custom', version='Manuell')
                    installer.properties(cfg, directory)
                else:
                    if not cfg['installed']:
                        raise ValueError('Zuerst eine Serverinstallation durchführen.')
                    destination = core.safe_path(directory, 'mods/' + name)
                    for missing in cfg['missing']:
                        if missing['name'] == name and missing.get('hash'):
                            algo, expected = missing['hash']
                            with target.open('rb') as stream:
                                actual = hashlib.file_digest(stream, algo).hexdigest()
                            if actual.lower() != expected.lower():
                                raise ValueError('Datei-Prüfsumme stimmt nicht mit CurseForge überein.')
                    cfg['missing'] = [m for m in cfg['missing'] if m['name'] != name]
                if destination.exists() or (kind == 'mod' and destination.with_name(name + '.disabled').exists()):
                    raise ValueError('Datei existiert bereits, gegebenenfalls deaktiviert. Bestehende Mod zum Ersetzen zuerst entfernen.')
                destination.parent.mkdir(parents=True, exist_ok=True)
                target.replace(destination)
                if kind == 'mod':
                    source = cfg.get('mod_sources', {}).get(name)
                    if source is not None:
                        source['sha256'] = modscan.digest(destination)
                core.save(cfg)
                if kind == 'mod':
                    modscan.run(sid, manager)
    finally:
        file.file.close()
        if target:
            target.unlink(missing_ok=True)
    return {'ok': True}


@app.get('/api/servers/{sid}/mods')
def mods(sid: str, _=Depends(auth)):
    with manager.lock:
        cfg = core.get(sid)
        root = core.folder(sid) / 'mods'
        if root.is_symlink():
            raise ValueError('Das Mod-Verzeichnis darf kein Symlink sein.')
        result = []
        for p in sorted(root.iterdir()) if root.exists() else []:
            if p.is_file() and not p.is_symlink() and (p.name.endswith('.jar') or p.name.endswith('.jar.disabled')):
                assessment = cfg.get('mod_scan', {}).get(p.name.removesuffix('.disabled'), {})
                result.append({'name': p.name, 'enabled': p.suffix == '.jar',
                    'size_mb': round(p.stat().st_size / 1048576, 2),
                    'assessment': {k: assessment[k] for k in ('status', 'reason', 'override') if k in assessment}})
        return result


@app.post('/api/servers/{sid}/mods/scan')
def scan_mods(sid: str, _=Depends(auth)):
    with manager.lock:
        editable(sid)
        modscan.run(sid, manager)
    return {'ok': True}



class ModAction(BaseModel):
    name: str = Field(max_length=255)
    action: Literal['toggle', 'remove', 'automatic']


@app.post('/api/servers/{sid}/mods')
def mod_action(sid: str, body: ModAction, _=Depends(auth)):
    with manager.lock:
        cfg = editable(sid)
        name = body.name.removesuffix('.disabled')
        installer.filename(name)
        path = core.safe_path(core.folder(sid), 'mods/' + body.name)
        if not path.is_file():
            raise ValueError('Mod-Datei nicht gefunden.')
        family = cfg.get('loader', '').split('-', 1)[0]
        row = {**modscan.inspect(path, family), 'sha256': modscan.digest(path)}
        key = modscan.override_key(row, family)
        overrides = cfg.setdefault('mod_overrides', {})
        if body.action == 'remove':
            path.unlink()
            cfg.get('mod_scan', {}).pop(name, None)
            cfg.get('mod_sources', {}).pop(name, None)
        elif body.action == 'automatic':
            overrides.pop(key, None)
        else:
            enabling = body.name.endswith('.disabled')
            destination = path.with_name(name if enabling else name + '.disabled')
            if destination.exists():
                raise ValueError('Zieldatei existiert bereits.')
            path.rename(destination)
            overrides[key] = 'allow' if enabling else 'disable'
        core.save(cfg)
        modscan.run(sid, manager)
    return {'ok': True}



EXTENSIONS = {'.properties', '.json', '.toml', '.yml', '.yaml', '.txt', '.cfg', '.conf'}


def config_file(sid, path):
    result = core.safe_path(core.folder(sid), path)
    if result.suffix not in EXTENSIONS or result.name in ('eula.txt', 'unix_args.txt', 'user_jvm_args.txt') or 'libraries' in result.parts:
        raise ValueError('Diese Datei ist im Konfigurationseditor nicht verfügbar.')
    if not result.is_file() or result.stat().st_size > 1024**2:
        raise ValueError('Datei fehlt oder ist größer als 1 MB.')
    return result


@app.get('/api/servers/{sid}/files')
def files(sid: str, _=Depends(auth)):
    root = core.folder(sid)
    found = []
    for directory, dirs, names in os.walk(root, followlinks=False):
        dirs[:] = [d for d in dirs if d not in ('libraries', 'world', 'world_nether', 'world_the_end', 'logs', '.git') and not (Path(directory) / d).is_symlink()]
        for name in names:
            relative = (Path(directory) / name).relative_to(root).as_posix()
            try:
                config_file(sid, relative)
                found.append(relative)
            except ValueError:
                pass
            if len(found) >= 1000:
                return sorted(found)
    return sorted(found)


@app.get('/api/servers/{sid}/file')
def file_read(sid: str, path: str, _=Depends(auth)):
    return {'content': config_file(sid, path).read_text(encoding='utf8', errors='replace')}


class FileEdit(BaseModel):
    path: str = Field(max_length=500)
    content: str = Field(max_length=1024**2)


@app.put('/api/servers/{sid}/file')
def file_write(sid: str, body: FileEdit, _=Depends(auth)):
    with manager.lock:
        editable(sid)
        if body.path == 'server.properties':
            raise ValueError('Server-Eigenschaften bitte über Einstellungen bearbeiten.')
        path = config_file(sid, body.path)
        path.write_text(body.content, encoding='utf8')
    return {'ok': True}


@app.post('/api/servers/{sid}/backup')
def backup(sid: str, _=Depends(auth)):
    with manager.lock:
        editable(sid)
        name = sid + '-' + time.strftime('%Y%m%d-%H%M%S') + '-' + secrets.token_hex(3) + '.tar.gz'
        destination = core.ROOT / 'backups' / name
        def build():
            part = destination.with_suffix('.partial')
            try:
                def regular(info):
                    return info if info.isfile() or info.isdir() else None
                with tarfile.open(part, 'w:gz') as archive:
                    archive.add(core.folder(sid), arcname=sid, filter=regular)
                part.replace(destination)
            finally:
                part.unlink(missing_ok=True)
        manager.submit(sid, 'Backup erstellen', build)
    return {'ok': True}


@app.get('/api/servers/{sid}/backups')
def backups(sid: str, _=Depends(auth)):
    core.get(sid)
    return [{'name': p.name, 'size_mb': round(p.stat().st_size / 1048576, 1)}
            for p in sorted((core.ROOT / 'backups').glob(sid + '-*.tar.gz'), reverse=True)]


@app.get('/api/servers/{sid}/backups/{name}')
def download_backup(sid: str, name: str, _=Depends(auth)):
    core.get(sid)
    if not re.fullmatch(sid + r'-[0-9]{8}-[0-9]{6}-[a-f0-9]{6}\.tar\.gz', name):
        raise HTTPException(404)
    path = core.safe_path(core.ROOT / 'backups', name)
    if not path.is_file():
        raise HTTPException(404)
    return FileResponse(path, filename=name)


class UserSettings(BaseModel):
    username: str = Field(pattern=r'^[A-Za-z0-9][A-Za-z0-9_.-]{2,31}$')
    role: Literal['admin', 'manager', 'operator', 'viewer']
    active: bool = True
    server_ids: list[str] = Field(default_factory=list, max_length=1000)
    password: str | None = Field(default=None, min_length=14, max_length=1024)


class Confirmation(BaseModel):
    confirmation: str = Field(min_length=1, max_length=100)


class PasswordChange(BaseModel):
    current_password: str = Field(max_length=1024)
    new_password: str = Field(min_length=14, max_length=1024)


@app.get('/api/users')
def list_users(_=Depends(auth)):
    return {'users': core.users(), 'roles': core.ROLES}


@app.post('/api/users')
def create_user(body: UserSettings, info=Depends(auth)):
    return core.write_user(**body.model_dump(), actor_id=info['user']['id'])


@app.put('/api/users/{uid}')
def update_user(uid: str, body: UserSettings, info=Depends(auth)):
    return core.write_user(**body.model_dump(), uid=uid, actor_id=info['user']['id'])


@app.delete('/api/users/{uid}')
def remove_user(uid: str, body: Confirmation, info=Depends(auth)):
    core.delete_user(uid, body.confirmation, info['user']['id'])
    return {'ok': True}


@app.post('/api/account/password')
def password_change(body: PasswordChange, info=Depends(auth)):
    core.change_password(info['user']['id'], body.current_password, body.new_password)
    return {'ok': True}


@app.delete('/api/servers/{sid}')
def delete_server(sid: str, body: Confirmation, _=Depends(auth)):
    with manager.lock, core.LOCK:
        manager.idle(sid)
        cfg = core.get(sid)
        if body.confirmation != cfg['name']:
            raise ValueError('Servernamen zur Bestätigung exakt eingeben.')
        directory = core.safe_path(core.ROOT, 'servers/' + sid)
        stage = core.safe_path(core.ROOT, 'uploads/' + sid + '-stage')
        backup_root = core.safe_path(core.ROOT, 'backups')
        backup_paths = []
        for path in backup_root.glob(sid + '-*'):
            if re.fullmatch(re.escape(sid) + r'-[0-9]{8}-[0-9]{6}-[a-f0-9]{6}\.tar\.(?:gz|partial)', path.name):
                backup_paths.append(core.safe_path(backup_root, path.name))
        try:
            for root in (directory, stage):
                if root.exists():
                    shutil.rmtree(root)
            for path in backup_paths:
                path.unlink(missing_ok=True)
            with core.connect() as conn:
                conn.execute('DELETE FROM servers WHERE id=?', (sid,))
        except (OSError, sqlite3.Error):
            raise ValueError('Löschen nicht vollständig abgeschlossen. Berechtigungen und Datenträger prüfen und das Löschen erneut ausführen.') from None
        manager.processes.pop(sid, None)
        manager.jobs.pop(sid, None)
        manager.logs.pop(sid, None)
        manager.sequence.pop(sid, None)
    return {'ok': True}


@app.get('/')
def index():
    html = (STATIC / 'index.html').read_text(encoding='utf-8')
    for name in ('app.js', 'style.css'):
        version = hashlib.sha256((STATIC / name).read_bytes()).hexdigest()[:16]
        pattern = r'(/static/' + re.escape(name) + r')(?:\?v=[a-zA-Z0-9_-]+)?(?=[\"\'])'
        html = re.sub(pattern, lambda match: match.group(1) + '?v=' + version, html)
    return HTMLResponse(html, headers={'Cache-Control': 'no-store'})


app.mount('/static', StaticFiles(directory=STATIC), name='static')
