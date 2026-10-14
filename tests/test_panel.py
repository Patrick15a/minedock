import hashlib
import io
import json
import os
import stat
import tarfile
import time
import types
import zipfile
from pathlib import Path
from unittest.mock import Mock

import pytest
from app import core, main, installer, runtime


def jar():
    data = io.BytesIO()
    with zipfile.ZipFile(data, 'w') as archive:
        archive.writestr('META-INF/MANIFEST.MF', 'Manifest-Version: 1.0\n')
    return data.getvalue()


def pack(path, extra=None, files=None):
    manifest = {'manifestType':'minecraftModpack', 'manifestVersion':1, 'name':'Testpack',
                'minecraft':{'version':'1.21.1','modLoaders':[{'id':'fabric-0.16.5','primary':True}]},
                'files':files or [], 'overrides':'overrides'}
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('manifest.json',json.dumps(manifest))
        for name, content in (extra or {}).items():
            info = zipfile.ZipInfo()
            info.filename = name
            archive.writestr(info, content)
    return manifest


def wait_job(manager, sid):
    deadline = time.monotonic() + 5
    while manager.jobs[sid]['state'] == 'running' and time.monotonic() < deadline:
        time.sleep(.01)
    assert manager.jobs[sid]['state'] != 'running'


def test_login_auth_csrf_and_logout(env, config):
    client, _ = env
    assert client.get('/api/overview').status_code == 401
    assert client.post('/api/login',json={'username':'admin','password':'wrong'}).status_code == 401
    reply = client.post('/api/login',json={'username':'admin','password':'test-passphrase-123'})
    assert 'HttpOnly' in reply.headers['set-cookie'] and 'SameSite=strict' in reply.headers['set-cookie']
    csrf = reply.json()['csrf']
    assert client.post('/api/servers',json=config).status_code == 403
    client.headers['x-csrf-token'] = csrf
    assert client.post('/api/servers',json=config,headers={'origin':'https://evil.example'}).status_code == 403
    assert client.post('/api/logout').status_code == 200
    assert client.get('/api/overview').status_code == 401


def test_login_rate_limit(env):
    client, _ = env
    for _ in range(8):
        assert client.post('/api/login',json={'username':'admin','password':'bad'}).status_code == 401
    assert client.post('/api/login',json={'username':'admin','password':'test-passphrase-123'}).status_code == 429


def test_body_limit(env):
    client, _ = env
    response = client.post('/api/login',content='a' * (2 * 1024**2 + 1),headers={'content-type':'application/json'})
    assert response.status_code == 413


def test_port_budget_and_settings_validation(client, config, sid):
    assert client.post('/api/servers',json=config).status_code == 400
    assert client.post('/api/servers',json={**config,'port':25566,'memory_mb':32768}).status_code == 400
    assert client.put(f'/api/servers/{sid}',json={**config,'motd':'hello\nserver-port=1'}).status_code == 422
    assert client.put(f'/api/servers/{sid}',json={**config,'java':'999'}).status_code == 400
    assert client.put(f'/api/servers/{sid}',json={**config,'name':'Neue Welt'}).status_code == 200
    assert core.get(sid)['name'] == 'Neue Welt'


def test_upload_custom_and_mod_lifecycle(client, sid):
    assert client.post(f'/api/servers/{sid}/upload?kind=server',files={'file':('server.jar',jar())}).status_code == 200
    assert core.get(sid)['launch'] == ['-jar','server.jar']
    response = client.post(f'/api/servers/{sid}/upload?kind=mod',files={'file':('example.jar',jar())})
    assert response.status_code == 200
    assert client.post(f'/api/servers/{sid}/upload?kind=mod',files={'file':('example.jar',jar())}).status_code == 400
    assert client.post(f'/api/servers/{sid}/mods',json={'name':'example.jar','action':'toggle'}).status_code == 200
    assert client.get(f'/api/servers/{sid}/mods').json()[0]['enabled'] is False
    assert client.post(f'/api/servers/{sid}/mods',json={'name':'example.jar.disabled','action':'remove'}).status_code == 200
    assert client.get(f'/api/servers/{sid}/mods').json() == []


@pytest.mark.parametrize('path', ['../secret','/root/secret','foo/../../secret','C:/data','foo\\bar'])
def test_paths_cannot_escape(tmp_path, path):
    with pytest.raises(ValueError):
        core.safe_path(tmp_path,path)


@pytest.mark.parametrize('entry', ['../escape.jar', '/absolute.jar', 'overrides/../../escape.jar','overrides\\evil.jar'])
def test_zip_traversal_rejected(tmp_path, entry):
    path = tmp_path / 'pack.zip'
    pack(path, {entry:'bad'})
    with pytest.raises(ValueError):
        installer.inspect_zip(path)


def test_zip_symlink_rejected(tmp_path):
    path = tmp_path / 'pack.zip'; pack(path)
    with zipfile.ZipFile(path,'a') as archive:
        link = zipfile.ZipInfo('overrides/mods/link')
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(link, '/etc/passwd')
    with pytest.raises(ValueError):
        installer.inspect_zip(path)


def test_import_is_staged_and_failure_keeps_live_empty(client,sid,tmp_path,monkeypatch):
    path = tmp_path / 'failed.zip'; pack(path,{'overrides/config/test.json':'{}'})
    def fail(*args):
        raise ValueError('Simulierter Loaderfehler')
    monkeypatch.setattr(installer,'install_loader',fail)
    with pytest.raises(ValueError,match='Loaderfehler'):
        installer.install(sid,'zip',path)
    assert list(core.folder(sid).iterdir()) == []
    assert core.get(sid)['installed'] is False


def test_import_preserves_overrides_and_missing_downloads(client,sid,tmp_path,monkeypatch):
    path = tmp_path / 'pack.zip'
    data = jar(); digest = hashlib.sha1(data).hexdigest()
    pack(path, {'overrides/config/test.json':'{}','overrides/eula.txt':'eula=true','overrides/world/level.dat':'no'},
         [{'projectID':1,'fileID':2}])
    def mock_cf(route):
        if route == 'mods/1':
            return {'links':{'websiteUrl':'https://www.curseforge.com/minecraft/mc-mods/example'}}
        return {'fileName':'manual.jar','downloadUrl':None,'hashes':[{'algo':1,'value':digest}]}
    monkeypatch.setattr(installer,'cf',mock_cf)
    monkeypatch.setattr(installer,'install_loader',lambda *args: ['-jar','server.jar'])
    installer.install(sid,'zip',path)
    assert core.get(sid)['installed'] is True
    assert (core.folder(sid) / 'config/test.json').is_file()
    assert not (core.folder(sid) / 'eula.txt').exists()
    assert not (core.folder(sid) / 'world').exists()
    assert len(core.get(sid)['missing']) == 1
    assert client.post(f'/api/servers/{sid}/action/start').status_code == 400
    bad = io.BytesIO()
    with zipfile.ZipFile(bad,'w') as zf: zf.writestr('bad','bad')
    assert client.post(f'/api/servers/{sid}/upload?kind=mod',files={'file':('manual.jar',bad.getvalue())}).status_code == 400
    assert client.post(f'/api/servers/{sid}/upload?kind=mod',files={'file':('manual.jar',data)}).status_code == 200
    assert core.get(sid)['missing'] == []


def test_async_import_errors_reported(client,sid,env,monkeypatch):
    manager = env[1]
    def fail(*args): raise ValueError('Download fehlgeschlagen')
    monkeypatch.setattr(installer,'install',fail)
    assert client.post(f'/api/servers/{sid}/install',json={'mode':'vanilla','version':'1.21.1'}).status_code == 200
    wait_job(manager,sid)
    assert manager.jobs[sid]['state'] == 'error'
    assert 'Download fehlgeschlagen' in client.get(f'/api/servers/{sid}/logs').text


def test_zip_upload_job_keeps_source_path(client,sid,env,tmp_path,monkeypatch):
    source = tmp_path/'source.zip'; pack(source)
    monkeypatch.setattr(installer,'install_loader',lambda *args: ['-jar','server.jar'])
    response = client.post(f'/api/servers/{sid}/upload?kind=modpack',files={'file':('pack.zip',source.read_bytes())})
    assert response.status_code == 200
    wait_job(env[1],sid)
    assert env[1].jobs[sid]['state'] == 'done', env[1].jobs[sid]
    assert core.get(sid)['installed'] is True


def test_busy_server_blocks_mutations(client,sid,config,env):
    env[1].jobs[sid] = {'state':'running','label':'Test'}
    assert client.put(f'/api/servers/{sid}',json=config).status_code == 400
    assert client.post(f'/api/servers/{sid}/action/archive').status_code == 400
    assert client.post(f'/api/servers/{sid}/backup').status_code == 400
    env[1].jobs[sid]['state'] = 'done'


def test_editor_blocks_escape_and_runtime_arguments(client,sid):
    directory = core.folder(sid)
    (directory / 'config').mkdir()
    (directory / 'config/options.toml').write_text('value=1')
    (directory / 'user_jvm_args.txt').write_text('-Xmx1G')
    assert client.get(f'/api/servers/{sid}/file',params={'path':'../panel.sqlite3'}).status_code == 400
    assert client.get(f'/api/servers/{sid}/file',params={'path':'user_jvm_args.txt'}).status_code == 400
    assert client.put(f'/api/servers/{sid}/file',json={'path':'config/options.toml','content':'value=2'}).status_code == 200
    assert (directory / 'config/options.toml').read_text() == 'value=2'


def test_backup_is_scoped_to_server(client,sid,env):
    (core.folder(sid)/'world').mkdir()
    (core.folder(sid)/'world/level.dat').write_bytes(b'world-test')
    assert client.post(f'/api/servers/{sid}/backup').status_code == 200
    wait_job(env[1],sid)
    backups = client.get(f'/api/servers/{sid}/backups').json()
    assert len(backups) == 1
    response = client.get(f'/api/servers/{sid}/backups/{backups[0]["name"]}')
    with tarfile.open(fileobj=io.BytesIO(response.content)) as archive:
        assert archive.extractfile(sid+'/world/level.dat').read() == b'world-test'
        assert not any('sqlite3' in n for n in archive.getnames())


def test_archive_retains_files_and_releases_port(client,sid,config):
    (core.folder(sid)/'keep.txt').write_text('keep')
    assert client.post(f'/api/servers/{sid}/action/archive').status_code == 200
    assert (core.folder(sid)/'keep.txt').read_text() == 'keep'
    assert client.post('/api/servers',json=config).status_code == 200
    assert client.put(f'/api/servers/{sid}',json=config).status_code == 400


@pytest.mark.parametrize('url',['http://api.curseforge.com/v1/mods','https://127.0.0.1/private','https://api.curseforge.com.evil.test/','https://api.curseforge.com:8443/','https://user@api.curseforge.com/'])
def test_download_allowlist(url):
    with pytest.raises(ValueError): installer.validate_url(url)


def test_child_environment_has_no_secrets(monkeypatch):
    monkeypatch.setenv('CURSEFORGE_API_KEY','secret')
    monkeypatch.setenv('MINEDOCK_PASSWORD_HASH','secret')
    assert 'CURSEFORGE_API_KEY' not in core.child_env()
    assert 'MINEDOCK_PASSWORD_HASH' not in core.child_env()


def test_memory_budget_blocks_overcommit(client,sid,config,env,monkeypatch):
    manager = env[1]
    first = core.get(sid); first.update(installed=True,launch=['-jar','server.jar'],memory_mb=24000); core.save(first)
    sid2 = client.post('/api/servers',json={**config,'port':25566,'memory_mb':10000}).json()['id']
    second = core.get(sid2); second.update(installed=True,launch=['-jar','server.jar']); core.save(second)
    manager.processes[sid] = types.SimpleNamespace(poll=lambda: None)
    monkeypatch.setattr(runtime,'os',types.SimpleNamespace(name='posix'))
    with pytest.raises(ValueError,match='RAM-Budget'): manager.start(sid2)
    manager.processes.clear()


def test_runtime_spawns_argument_list_without_shell(client,sid,env,monkeypatch):
    manager = env[1]
    cfg = core.get(sid); cfg.update(installed=True,launch=['-jar','server.jar']); core.save(cfg)
    monkeypatch.setattr(runtime,'os',types.SimpleNamespace(name='posix',path=types.SimpleNamespace(isfile=lambda _:True)))
    monkeypatch.setattr(runtime.psutil,'virtual_memory',lambda: types.SimpleNamespace(available=64*1024**3))
    process = Mock(); process.poll.return_value = None
    popen = Mock(return_value=process)
    monkeypatch.setattr(runtime.subprocess,'Popen',popen)
    monkeypatch.setattr(runtime.threading,'Thread',Mock())
    manager.start(sid)
    args, kwargs = popen.call_args
    assert args[0] == [core.JAVA['21'],'-Xms512M','-Xmx4096M','-jar','server.jar','nogui']
    assert kwargs.get('shell',False) is False
    assert 'CURSEFORGE_API_KEY' not in kwargs['env']
    manager.command(sid,'list')
    process.stdin.write.assert_called_with('list\n')
    with pytest.raises(ValueError): manager.command(sid,'list\nstop')
    manager.processes.clear()


def test_properties_unicode_and_managed_port(client,sid,config):
    directory = core.folder(sid)
    (directory/'server.properties').write_text('server-port=1234\nlevel-name=world\n')
    installer.properties({**config,'motd':'Grüße 🌍'},directory)
    text = (directory/'server.properties').read_text()
    assert text.count('server-port=') == 1 and 'server-port=25565' in text
    assert 'level-name=world' in text
    assert '\\u00fc' in text and '\\ud83c\\udf0d' in text


def test_static_security_headers(client):
    response = client.get('/')
    assert response.status_code == 200
    assert 'frame-ancestors' in response.headers['content-security-policy']
    assert client.get('/static/app.js').status_code == 200
    assert client.get('/api/overview').headers['cache-control'] == 'no-store'
