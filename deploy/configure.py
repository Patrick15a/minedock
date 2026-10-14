#!/usr/bin/env python3
"""Interactive host configuration. No credentials are accepted in command arguments."""
import getpass
import hashlib
import json
import os
import secrets
from pathlib import Path

if os.geteuid() != 0:
    raise SystemExit('Bitte mit sudo ausführen.')
target = Path('/etc/minedock/minedock.env')
if target.exists():
    raise SystemExit('Konfiguration existiert bereits. Für Änderungen sudoedit /etc/minedock/minedock.env verwenden.')
password = getpass.getpass('Neues Admin-Passwort (mindestens 14 Zeichen): ')
if len(password) < 14 or password != getpass.getpass('Passwort wiederholen: '):
    raise SystemExit('Passwörter stimmen nicht überein oder sind zu kurz.')
salt = secrets.token_hex(16)
encoded = salt + ':' + hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()
key = getpass.getpass('CurseForge-API-Schlüssel (optional, Eingabe verborgen): ').strip()
if any(c in key for c in '\n\r\x00'):
    raise SystemExit('Ungültiger Schlüssel.')
def quoted(value):
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"'
values = {'MINEDOCK_PASSWORD_HASH': encoded, 'CURSEFORGE_API_KEY': key,
          'MINEDOCK_DATA': '/var/lib/minedock', 'MINEDOCK_MEMORY_MB': '32768',
          'MINEDOCK_JAVA': json.dumps({'21': '/usr/lib/jvm/java-21-openjdk-amd64/bin/java'}),
          'MINEDOCK_SECURE_COOKIE': '1', 'MINEDOCK_BIND': '0.0.0.0',
          'MINEDOCK_PORT': '8080', 'MINEDOCK_PROXY_IPS': '127.0.0.1'}
# Do not assume the host's global Java default was changed by installing Java 21.
java_candidates = [p for p in Path('/usr/lib/jvm').glob('java-21-openjdk-*/bin/java') if p.is_file()]
if len(java_candidates) != 1:
    raise SystemExit('Java-21-Pfad nicht eindeutig gefunden. Installation von openjdk-21-jre-headless prüfen.')
values['MINEDOCK_JAVA'] = json.dumps({'21': str(java_candidates[0])})
target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, 'w') as stream:
    for name, value in values.items():
        stream.write(name + '=' + quoted(value) + '\n')
print('Konfiguration gespeichert. Benutzername: admin. Passwort und API-Schlüssel werden nicht ausgegeben.')
