from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(os.getenv('MINEDOCK_DATA', './data')).resolve()
ROOT.mkdir(parents=True, exist_ok=True)
for name in ('servers', 'uploads', 'backups'):
    (ROOT / name).mkdir(exist_ok=True)
DB = ROOT / 'panel.sqlite3'
LOCK = threading.RLock()
JAVA = json.loads(os.getenv('MINEDOCK_JAVA', '{"21":"/usr/bin/java"}'))
BUDGET_MB = int(os.getenv('MINEDOCK_MEMORY_MB', '32768'))
CF_KEY = os.getenv('CURSEFORGE_API_KEY', '')
SECURE = os.getenv('MINEDOCK_SECURE_COOKIE', '1') == '1'
PASSWORD_HASH = os.getenv('MINEDOCK_PASSWORD_HASH', '')


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()
    return f'{salt}:{digest}'


def verify_password(password: str, encoded: str) -> bool:
    try:
        salt, expected = encoded.split(':')
        actual = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


@contextmanager
def connect():
    conn = sqlite3.connect(DB, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def init():
    with connect() as conn:
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('CREATE TABLE IF NOT EXISTS servers (id TEXT PRIMARY KEY, config TEXT NOT NULL)')
        conn.execute('''CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY, username TEXT NOT NULL UNIQUE COLLATE NOCASE,
            password_hash TEXT NOT NULL, role TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1, session_version INTEGER NOT NULL DEFAULT 1)''')
        if 'all_servers' not in {r['name'] for r in conn.execute('PRAGMA table_info(users)')}:
            conn.execute('ALTER TABLE users ADD COLUMN all_servers INTEGER NOT NULL DEFAULT 0')
        conn.execute('''CREATE TABLE IF NOT EXISTS server_access (
            user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            server_id TEXT NOT NULL REFERENCES servers(id) ON DELETE CASCADE,
            PRIMARY KEY(user_id, server_id))''')
        conn.execute('CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
        if not conn.execute("SELECT 1 FROM metadata WHERE key='users_migrated'").fetchone():
            if conn.execute('SELECT 1 FROM users').fetchone():
                conn.execute("INSERT INTO metadata VALUES ('users_migrated', '1')")
            elif PASSWORD_HASH:
                conn.execute('INSERT INTO users (id, username, password_hash, role) VALUES (?, ?, ?, ?)',
                             (secrets.token_hex(8), 'admin', PASSWORD_HASH, 'admin'))
                conn.execute("INSERT INTO metadata VALUES ('users_migrated', '1')")


def rows():
    with connect() as conn:
        return [json.loads(r['config']) for r in conn.execute('SELECT config FROM servers ORDER BY rowid DESC')]


def get(sid):
    if not re.fullmatch(r'[a-f0-9]{16}', sid):
        raise ValueError('Ungültige Server-ID.')
    with connect() as conn:
        row = conn.execute('SELECT config FROM servers WHERE id=?', (sid,)).fetchone()
    if not row:
        raise ValueError('Server nicht gefunden.')
    return json.loads(row['config'])


def save(config):
    with LOCK, connect() as conn:
        conn.execute('INSERT INTO servers VALUES (?, ?) ON CONFLICT(id) DO UPDATE SET config=excluded.config',
                     (config['id'], json.dumps(config)))


def folder(sid):
    get(sid)
    return ROOT / 'servers' / sid


def safe_path(root: Path, relative: str) -> Path:
    if not relative or '\\' in relative or ':' in relative or '\x00' in relative:
        raise ValueError('Ungültiger Dateipfad.')
    candidate = root / relative
    if any(p == '..' for p in Path(relative).parts) or Path(relative).is_absolute():
        raise ValueError('Pfad außerhalb des Servers.')
    if not candidate.resolve().is_relative_to(root.resolve()):
        raise ValueError('Pfad außerhalb des Servers.')
    for p in [candidate, *candidate.parents]:
        if p == root.parent:
            break
        if p.is_symlink():
            raise ValueError('Symbolische Links sind nicht erlaubt.')
    return candidate


def child_env():
    """Do not pass the panel's credentials into Java child processes."""
    keep = ('PATH', 'HOME', 'LANG', 'LC_ALL', 'TMPDIR', 'JAVA_HOME', 'SYSTEMROOT')
    return {key: os.environ[key] for key in keep if key in os.environ}


ROLES = {'admin': 'Administrator', 'manager': 'Verwalter', 'operator': 'Operator', 'viewer': 'Betrachter'}


def user_by_name(username):
    with connect() as conn:
        row = conn.execute('SELECT * FROM users WHERE username=?', (username.lower(),)).fetchone()
    return dict(row) if row else None


def user_by_id(uid):
    with connect() as conn:
        row = conn.execute('SELECT * FROM users WHERE id=?', (uid,)).fetchone()
    return dict(row) if row else None


def has_all_servers(user):
    return user['role'] in ('admin', 'manager') or (user['role'] == 'operator' and bool(user.get('all_servers', False)))


def public_user(user):
    with connect() as conn:
        assigned = [r[0] for r in conn.execute('SELECT server_id FROM server_access WHERE user_id=? ORDER BY server_id', (user['id'],))]
    return {key: user[key] for key in ('id', 'username', 'role')} | {'active': bool(user['active']), 'server_ids': assigned, 'all_servers': has_all_servers(user)}


def users():
    with connect() as conn:
        found = [dict(r) for r in conn.execute('SELECT * FROM users ORDER BY username')]
    return [public_user(user) for user in found]


def write_user(username, role, active, server_ids, password=None, uid=None, actor_id=None, all_servers=False):
    username = username.lower()
    if not re.fullmatch(r'[a-z0-9][a-z0-9_.-]{2,31}', username) or role not in ROLES:
        raise ValueError('Ungültiger Benutzername oder Rolle.')
    if password is not None and not 14 <= len(password) <= 1024:
        raise ValueError('Das Passwort muss zwischen 14 und 1024 Zeichen lang sein.')
    if uid is None and password is None:
        raise ValueError('Ein Passwort ist erforderlich.')
    all_servers = role == 'operator' and bool(all_servers)
    encoded = hash_password(password) if password is not None else None
    with LOCK, connect() as conn:
        conn.execute('BEGIN IMMEDIATE')
        old = conn.execute('SELECT * FROM users WHERE id=?', (uid,)).fetchone() if uid else None
        if uid and not old:
            raise ValueError('Benutzer nicht gefunden.')
        if uid == actor_id and (not active or role != 'admin'):
            raise ValueError('Das eigene Administratorkonto darf nicht deaktiviert oder herabgestuft werden.')
        if old and old['role'] == 'admin' and old['active'] and (not active or role != 'admin'):
            if conn.execute("SELECT COUNT(*) FROM users WHERE role='admin' AND active=1").fetchone()[0] <= 1:
                raise ValueError('Mindestens ein aktiver Administrator muss erhalten bleiben.')
        assigned = sorted(set(server_ids)) if role not in ('admin', 'manager') else []
        for sid in assigned:
            if not conn.execute('SELECT 1 FROM servers WHERE id=?', (sid,)).fetchone():
                raise ValueError('Ein zugewiesener Server existiert nicht mehr.')
        if conn.execute('SELECT 1 FROM users WHERE username=? AND id<>?', (username, uid or '')).fetchone():
            raise ValueError('Dieser Benutzername ist bereits vergeben.')
        if old:
            conn.execute('UPDATE users SET username=?, role=?, active=?, password_hash=?, all_servers=?, session_version=session_version+1 WHERE id=?',
                         (username, role, int(active), encoded or old['password_hash'], int(all_servers), uid))
        else:
            uid = secrets.token_hex(8)
            conn.execute('INSERT INTO users (id, username, password_hash, role, active, all_servers) VALUES (?, ?, ?, ?, ?, ?)',
                         (uid, username, encoded, role, int(active), int(all_servers)))
        conn.execute('DELETE FROM server_access WHERE user_id=?', (uid,))
        conn.executemany('INSERT INTO server_access VALUES (?, ?)', [(uid, sid) for sid in assigned])
    return public_user(user_by_id(uid))


def delete_user(uid, confirmation, actor_id):
    with LOCK, connect() as conn:
        conn.execute('BEGIN IMMEDIATE')
        user = conn.execute('SELECT * FROM users WHERE id=?', (uid,)).fetchone()
        if not user or confirmation != user['username']:
            raise ValueError('Benutzernamen zur Bestätigung exakt eingeben.')
        if uid == actor_id:
            raise ValueError('Das eigene Konto kann hier nicht gelöscht werden.')
        if user['role'] == 'admin' and user['active']:
            if conn.execute("SELECT COUNT(*) FROM users WHERE role='admin' AND active=1").fetchone()[0] <= 1:
                raise ValueError('Mindestens ein aktiver Administrator muss erhalten bleiben.')
        conn.execute('DELETE FROM users WHERE id=?', (uid,))


def change_password(uid, current, new):
    if not 14 <= len(new) <= 1024:
        raise ValueError('Das neue Passwort muss zwischen 14 und 1024 Zeichen lang sein.')
    with LOCK, connect() as conn:
        conn.execute('BEGIN IMMEDIATE')
        user = conn.execute('SELECT * FROM users WHERE id=?', (uid,)).fetchone()
        if not user or not verify_password(current, user['password_hash']):
            raise ValueError('Das bisherige Passwort stimmt nicht.')
        conn.execute('UPDATE users SET password_hash=?, session_version=session_version+1 WHERE id=?', (hash_password(new), uid))


def grant_server(uid, sid):
    with LOCK, connect() as conn:
        conn.execute('INSERT OR IGNORE INTO server_access VALUES (?, ?)', (uid, sid))


init()
