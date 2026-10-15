from contextlib import closing

import importlib.util
import sqlite3
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location('update_release', Path(__file__).parents[1] / 'deploy/update.py')
update = importlib.util.module_from_spec(spec)
spec.loader.exec_module(update)


@pytest.fixture
def release(tmp_path):
    source, install, data = [tmp_path / name for name in ('release', 'installed', 'data')]
    for root, label in ((source, 'new'), (install, 'old')):
        (root / 'app/static').mkdir(parents=True)
        (root / 'app/main.py').write_text(f"VERSION = '{label}'", encoding='utf-8')
        links = '<a href="https://panel.example.test/">Private panel</a>' if label == 'old' else ''
        (root / 'app/static/index.html').write_text('<div class="app-menu">' + links + '<span>MineDock</span></div>', encoding='utf-8')
    data.mkdir()
    (data / 'servers/world').mkdir(parents=True)
    (data / 'servers/world/level.dat').write_bytes(b'preserve-world')
    (install / 'requirements.lock').write_text('same dependencies')
    with closing(sqlite3.connect(data / 'panel.sqlite3')) as db, db:
        db.execute('CREATE TABLE original (value TEXT)')
        db.execute("INSERT INTO original VALUES ('preserve')")
    return source, install, data, tmp_path / 'backup'


def test_update_preserves_world_and_menu_and_creates_backup(release):
    source, install, data, backup = release
    actions = []
    update.perform_update(*release, actions.append, lambda: True)
    assert actions == ['stop', 'start']
    assert "'new'" in (install / 'app/main.py').read_text()
    assert "'old'" in (backup / 'app/main.py').read_text()
    assert 'https://panel.example.test/' in (install / 'app/static/index.html').read_text()
    assert (data / 'servers/world/level.dat').read_bytes() == b'preserve-world'
    with closing(sqlite3.connect(backup / 'panel.sqlite3')) as db, db:
        assert db.execute('SELECT value FROM original').fetchone()[0] == 'preserve'
    assert not list(install.glob('.app-update-*'))


def test_failed_start_restores_code_and_database(release):
    source, install, data, backup = release
    actions = []
    def unhealthy():
        with closing(sqlite3.connect(data / 'panel.sqlite3')) as db, db:
            db.execute('CREATE TABLE migrated (value TEXT)')
            db.execute("UPDATE original SET value='changed'")
        return False
    with pytest.raises(RuntimeError, match='Startpruefung'):
        update.perform_update(*release, actions.append, unhealthy)
    assert actions == ['stop', 'start', 'stop', 'start']
    assert "'old'" in (install / 'app/main.py').read_text()
    with closing(sqlite3.connect(data / 'panel.sqlite3')) as db, db:
        assert db.execute('SELECT value FROM original').fetchone()[0] == 'preserve'
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='migrated'").fetchone()
    assert (data / 'servers/world/level.dat').read_bytes() == b'preserve-world'
    assert not list(install.glob('.app-update-*'))


def test_invalid_release_does_not_stop_service(release):
    source, install, data, backup = release
    (source / 'app/main.py').write_text('invalid python !!!')
    actions = []
    with pytest.raises(SyntaxError):
        update.perform_update(*release, actions.append, lambda: True)
    assert actions == []
    assert "'old'" in (install / 'app/main.py').read_text()


def test_backup_failure_restarts_unchanged_service(release, monkeypatch):
    actions = []
    def fail(*args):
        raise OSError('disk full')
    monkeypatch.setattr(update, 'copy_database', fail)
    with pytest.raises(OSError, match='disk full'):
        update.perform_update(*release, actions.append, lambda: True)
    assert actions == ['stop', 'stop', 'start']
    assert "'old'" in (release[1] / 'app/main.py').read_text()


def test_swap_failure_restores_original_app(release, monkeypatch):
    real_rename = update.os.rename
    def fail_staged(src, dst):
        if Path(src).name.startswith('.app-update-') and not str(src).endswith('-previous'):
            raise OSError('rename failed')
        return real_rename(src, dst)
    monkeypatch.setattr(update.os, 'rename', fail_staged)
    with pytest.raises(OSError, match='rename failed'):
        update.perform_update(*release, lambda action: None, lambda: True)
    assert "'old'" in (release[1] / 'app/main.py').read_text()
    assert not list(release[1].glob('.app-update-*'))
