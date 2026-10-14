import os
import tempfile

os.environ['MINEDOCK_DATA'] = tempfile.mkdtemp(prefix='minedock-tests-')
os.environ['MINEDOCK_SECURE_COOKIE'] = '0'

import pytest
from fastapi.testclient import TestClient
from app import core, main, installer, runtime


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(core, 'ROOT', tmp_path)
    monkeypatch.setattr(core, 'DB', tmp_path / 'panel.sqlite3')
    monkeypatch.setattr(core, 'PASSWORD_HASH', core.hash_password('test-passphrase-123'))
    monkeypatch.setattr(core, 'CF_KEY', 'test-api-key')
    for directory in ('servers', 'uploads', 'backups'):
        (tmp_path / directory).mkdir()
    core.init()
    manager = runtime.Manager()
    monkeypatch.setattr(main, 'manager', manager)
    monkeypatch.setattr(installer, 'manager', manager)
    main.sessions.clear()
    main.attempts.clear()
    with TestClient(main.app) as client:
        yield client, manager


@pytest.fixture
def client(env):
    client, _ = env
    reply = client.post('/api/login', json={'username':'admin', 'password':'test-passphrase-123'})
    assert reply.status_code == 200
    client.headers['x-csrf-token'] = reply.json()['csrf']
    return client


@pytest.fixture
def config():
    return dict(name='Testwelt', port=25565, memory_mb=4096, java='21', eula=True,
                max_players=20, difficulty='normal', gamemode='survival', motd='Unsere Welt', whitelist=False)


@pytest.fixture
def sid(client, config):
    response = client.post('/api/servers', json=config)
    assert response.status_code == 200, response.text
    return response.json()['id']
