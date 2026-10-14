#!/usr/bin/env python3
"""Validate and replace only the CurseForge key; never restart or print secrets."""
import getpass
import os
from pathlib import Path
import re
import sys
import tempfile
import httpx


def replace_key(text, key):
    if not key or key != key.strip() or any(ord(c) < 33 or ord(c) > 126 for c in key):
        raise ValueError('Schluessel ist leer oder enthaelt Leerraum/ungueltige Zeichen.')
    pattern = re.compile(r'^CURSEFORGE_API_KEY=[^\r\n]*$', re.MULTILINE)
    if len(pattern.findall(text)) != 1:
        raise ValueError('Konfiguration hat nicht genau einen CURSEFORGE_API_KEY-Eintrag.')
    quoted = key.replace('\\', '\\\\').replace('"', '\\"')
    return pattern.sub(lambda _: 'CURSEFORGE_API_KEY="' + quoted + '"', text)


def validate_key(key):
    url = 'https://api.curseforge.com/v1/mods/search?gameId=432&classId=4471&slug=complex-cobblemon'
    with httpx.Client(timeout=30, follow_redirects=False) as client:
        response = client.get(url, headers={'x-api-key': key, 'User-Agent': 'MineDock/0.1'})
    if response.status_code != 200:
        content_type = response.headers.get('content-type', '').lower()
        message = f'CurseForge-Test: HTTP {response.status_code}. Konfiguration unveraendert.'
        if response.status_code in (401,403):
            message += ' Schluesselstatus und Minecraft-API-Berechtigung in der Entwicklerkonsole bzw. beim CurseForge-Support pruefen.'
            if 'text/html' in content_type:
                message += ' Die Antwort ist HTML; auch eine vorgeschaltete Zugriffssperre kommt infrage.'
        raise ValueError(message)
    try:
        data = response.json()['data']
        found = isinstance(data, list) and any(isinstance(item, dict) and item.get('slug') == 'complex-cobblemon' for item in data)
    except (ValueError, KeyError, TypeError):
        found = False
    if not found:
        raise ValueError('API-Antwort enthaelt nicht das erwartete Modpack. Konfiguration unveraendert.')


def main():
    if os.geteuid() != 0 or not sys.stdin.isatty():
        raise ValueError('Bitte als root direkt in einer interaktiven Container-Konsole starten.')
    target = Path('/etc/minedock/minedock.env')
    original = target.read_text(encoding='utf-8')
    key = getpass.getpass('CurseForge-API-Schluessel neu einfuegen (Eingabe verborgen): ').strip()
    updated = replace_key(original, key)
    validate_key(key)
    print('API-Test erfolgreich: Modpack gefunden.')
    if target.read_text(encoding='utf-8') != original:
        raise ValueError('Konfiguration wurde zwischenzeitlich geaendert. Bitte erneut ausfuehren.')
    descriptor, temporary = tempfile.mkstemp(prefix='.minedock-key-', dir=target.parent)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(updated)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        Path(temporary).unlink(missing_ok=True)
    print('Nur der API-Schluessel wurde gespeichert; Admin-Passwort und andere Einstellungen bleiben erhalten.')
    print('Vor dem Neustart alle in MineDock laufenden Minecraft-Server stoppen und laufende Imports abwarten.')
    print('Danach ausfuehren: systemctl restart minedock')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except ValueError as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
    except (OSError, UnicodeError, httpx.HTTPError):
        print('Netzwerk-/Dateifehler; keine Geheimnisse ausgegeben. Dienst wurde nicht neu gestartet.', file=sys.stderr)
        sys.exit(1)
