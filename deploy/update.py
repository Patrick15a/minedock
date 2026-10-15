#!/usr/bin/env python3
"""Update an existing Debian installation; run with its virtualenv as root."""
from __future__ import annotations

from contextlib import closing

import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path


def copy_database(source, destination):
    with closing(sqlite3.connect(source)) as src, closing(sqlite3.connect(destination)) as dst:
        src.backup(dst)


def preserve_menu(old_index, new_index):
    old = old_index.read_text(encoding='utf-8')
    match = re.search(r'<div class="app-menu">(.*?)</div>', old, re.S)
    if match:
        links = ''.join(re.findall(r'<a\b[^>]*>.*?</a>', match.group(1), re.S))
        if links:
            html = new_index.read_text(encoding='utf-8')
            html = html.replace('<div class="app-menu">', '<div class="app-menu">' + links, 1)
            new_index.write_text(html, encoding='utf-8')


def perform_update(source, install, data, backup, control, healthy):
    """No server directories or service/environment settings are modified."""
    database = data / 'panel.sqlite3'
    db_stat = database.stat()
    backup.mkdir(mode=0o700, parents=True, exist_ok=False)
    shutil.copytree(install / 'app', backup / 'app')
    staged = Path(tempfile.mkdtemp(prefix='.app-update-', dir=install))
    previous = staged.with_name(staged.name + '-previous')
    stopped = swapped = db_saved = False
    try:
        shutil.copytree(source / 'app', staged, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        staged.chmod(0o755)
        for entry in staged.rglob('*'):
            entry.chmod(0o755 if entry.is_dir() else 0o644)
        preserve_menu(install / 'app/static/index.html', staged / 'static/index.html')
        for file in staged.rglob('*.py'):
            compile(file.read_bytes(), str(file), 'exec')
        control('stop')
        stopped = True
        copy_database(database, backup / 'panel.sqlite3')
        db_saved = True
        os.rename(install / 'app', previous)
        try:
            os.rename(staged, install / 'app')
        except BaseException:
            os.rename(previous, install / 'app')
            raise
        swapped = True
        control('start')
        if not healthy():
            raise RuntimeError('Der neue Dienst hat die Startpruefung nicht bestanden.')
    except BaseException:
        if stopped:
            control('stop')
            if swapped:
                shutil.rmtree(install / 'app')
                os.rename(previous, install / 'app')
            if db_saved:
                for suffix in ('-wal', '-shm'):
                    database.with_name(database.name + suffix).unlink(missing_ok=True)
                fd, restore_name = tempfile.mkstemp(prefix='.panel-update-restore-', dir=data)
                os.close(fd)
                restored = Path(restore_name)
                shutil.copyfile(backup / 'panel.sqlite3', restored)
                os.chmod(restored, db_stat.st_mode & 0o777)
                if hasattr(os, 'chown'):
                    os.chown(restored, db_stat.st_uid, db_stat.st_gid)
                os.replace(restored, database)
            control('start')
        raise
    finally:
        if staged.exists():
            shutil.rmtree(staged)
    if previous.exists():
        shutil.rmtree(previous)
    return backup


def main():
    if not hasattr(os, 'geteuid') or os.geteuid() != 0:
        raise RuntimeError('Bitte als root mit /opt/minedock/.venv/bin/python ausfuehren.')
    import fcntl
    lock = open('/run/minedock-update.lock', 'w')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    source = Path(__file__).resolve().parent.parent
    install = Path('/opt/minedock')
    data = Path('/var/lib/minedock')
    for path in (install, install / 'app', data, data / 'panel.sqlite3'):
        if path.is_symlink() or not path.exists():
            raise RuntimeError('Unerwarteter Installationspfad: ' + str(path))
    if (source / 'requirements.lock').read_bytes() != (install / 'requirements.lock').read_bytes():
        raise RuntimeError('Abhaengigkeiten unterscheiden sich; dieses Update benoetigt eine manuelle Pruefung.')
    import psutil
    pid = int(subprocess.check_output(['systemctl', 'show', 'minedock', '-p', 'MainPID', '--value'], text=True).strip())
    if pid <= 0:
        raise RuntimeError('MineDock muss fuer die Vorpruefung laufen.')
    process = psutil.Process(pid)
    env = process.environ()
    if Path(env.get('MINEDOCK_DATA', '')).resolve() != data:
        raise RuntimeError('Abweichendes Datenverzeichnis; Update wurde nicht begonnen.')
    if process.children(recursive=True):
        raise RuntimeError('Zuerst die von MineDock verwalteten Minecraft-Server stoppen und Installationen abwarten.')
    port = int(env.get('MINEDOCK_PORT', '8080'))
    host = env.get('MINEDOCK_BIND', '0.0.0.0')
    if host == '0.0.0.0':
        host = '127.0.0.1'
    backup = Path('/var/backups/minedock') / time.strftime('update-%Y%m%d-%H%M%S')
    backup.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    def control(action):
        subprocess.run(['systemctl', action, 'minedock'], check=True)
    def healthy():
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        for _ in range(30):
            try:
                with opener.open(f'http://{host}:{port}/', timeout=2) as response:
                    if response.status == 200:
                        with closing(sqlite3.connect(data / 'panel.sqlite3')) as db:
                            return bool(db.execute("SELECT 1 FROM users WHERE active=1 AND role='admin'").fetchone())
            except (OSError, sqlite3.Error):
                pass
            time.sleep(1)
        return False
    print('MineDock wird kurz angehalten. Konfiguration und Minecraft-Dateien bleiben erhalten.', flush=True)
    result = perform_update(source, install, data, backup, control, healthy)
    shutil.copy2('/etc/minedock/minedock.env', result / 'minedock.env')
    os.chmod(result / 'minedock.env', 0o600)
    print('Update erfolgreich. Sicherung: ' + str(result))
    print('Im Browser neu laden und mit dem bisherigen Admin-Passwort anmelden.')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print('Update fehlgeschlagen: ' + str(exc), file=sys.stderr)
        sys.exit(1)
