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
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def init():
    with connect() as conn:
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('CREATE TABLE IF NOT EXISTS servers (id TEXT PRIMARY KEY, config TEXT NOT NULL)')


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


init()
