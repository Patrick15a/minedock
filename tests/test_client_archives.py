import json
import zipfile

import pytest

from app import core, installer


def write_pack(path, refs):
    manifest = {'manifestType': 'minecraftModpack', 'manifestVersion': 1,
                'name': 'Client archive regression', 'minecraft': {'version': '1.19.2',
                'modLoaders': [{'id': 'forge-43.2.6', 'primary': True}]},
                'files': refs, 'overrides': 'overrides'}
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('manifest.json', json.dumps(manifest))


@pytest.mark.parametrize('class_id', [12, 6552])
@pytest.mark.parametrize('download_url', [None, 'https://edge.forgecdn.net/client.zip'])
def test_confirmed_client_archives_are_skipped_even_if_required(client, sid, tmp_path, monkeypatch, env, class_id, download_url):
    archive = tmp_path / 'pack.zip'
    write_pack(archive, [{'projectID': 476719, 'fileID': 4280802, 'required': True}])
    def cf(route):
        if '/files/' in route:
            return {'fileName': 'Ore Variants v2.6.zip', 'downloadUrl': download_url}
        return {'id': 476719, 'gameId': 432, 'classId': class_id}
    def unexpected_download(*args, **kwargs):
        pytest.fail('Client archive must not be downloaded')
    monkeypatch.setattr(installer, 'cf', cf)
    monkeypatch.setattr(installer, 'fetch', unexpected_download)
    monkeypatch.setattr(installer, 'install_loader', lambda *args: ['-jar', 'server.jar'])
    installer.install(sid, 'zip', archive)
    assert core.get(sid)['installed'] is True
    assert core.get(sid)['missing'] == []
    assert not (core.folder(sid) / 'mods').exists()
    log = '\n'.join(row['text'] for row in env[1].logs[sid])
    assert 'Ore Variants v2.6.zip' in log and 'übersprungen' in log
    assert '1 Client-Ressourcen-/Shaderpaket(e)' in log


@pytest.mark.parametrize('metadata', [
    {'id': 476719, 'gameId': 432, 'classId': 6},
    {'id': 476719, 'gameId': 432, 'classId': 17},
    {'id': 476719, 'gameId': 432, 'classId': 6945},
    {'id': 476719, 'gameId': 432, 'classId': None},
    {'id': 476719, 'gameId': 1, 'classId': 12},
    {'id': 1, 'gameId': 432, 'classId': 12},
    {},
])
def test_unconfirmed_zip_is_not_silently_skipped(client, sid, tmp_path, monkeypatch, metadata):
    archive = tmp_path / 'pack.zip'
    write_pack(archive, [{'projectID': 476719, 'fileID': 4280802}])
    monkeypatch.setattr(installer, 'cf', lambda route: {'fileName': 'unknown.zip'} if '/files/' in route else metadata)
    with pytest.raises(ValueError) as error:
        installer.install(sid, 'zip', archive)
    message = str(error.value)
    assert '[Import 1/1]' in message and '476719' in message and '4280802' in message
    assert 'unknown.zip' in message and 'nicht übersprungen' in message
    assert not core.get(sid)['installed']
    assert list(core.folder(sid).iterdir()) == []


def test_jar_does_not_require_extra_project_request(monkeypatch):
    def fail(route):
        pytest.fail('Unnecessary project request for JAR')
    monkeypatch.setattr(installer, 'cf', fail)
    assert installer.client_archive_type(1, {'fileName': "nocube's_mod.jar"}) is None


def test_all_213_entries_continue_past_three_resource_packs(client, sid, tmp_path, monkeypatch, env):
    # Real resource project/file IDs and positions; other files are synthetic.
    resources = {62: (476719, 4280802, 'Ore Variants v2.6.zip'),
                 119: (567347, 4073619, 'Minecolonies Refreshed.zip'),
                 166: (468836, 3582548, 'Created Simple Storage Network.zip')}
    refs = [{'projectID': i + 1, 'fileID': i + 1000, 'required': True} for i in range(213)]
    for index, (project, file_id, name) in resources.items():
        refs[index] = {'projectID': project, 'fileID': file_id, 'required': True}
    by_project = {project: name for project, _, name in resources.values()}
    archive = tmp_path / 'all.zip'
    write_pack(archive, refs)
    downloaded = []
    def cf(route):
        project = int(route.split('/')[1])
        if '/files/' not in route:
            assert project in by_project
            return {'id': project, 'gameId': 432, 'classId': 12}
        return {'fileName': by_project.get(project, f'mod-{project}.jar'),
                'downloadUrl': 'https://edge.forgecdn.net/fixture'}
    def fetch(url, destination, **kwargs):
        assert destination.suffix == '.jar'
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b'simulated mod')
        downloaded.append(destination.name)
    monkeypatch.setattr(installer, 'cf', cf)
    monkeypatch.setattr(installer, 'fetch', fetch)
    monkeypatch.setattr(installer, 'install_loader', lambda *args: ['-jar', 'server.jar'])
    installer.install(sid, 'zip', archive)
    assert len(downloaded) == 210
    assert core.get(sid)['installed'] is True and core.get(sid)['missing'] == []
    log = '\n'.join(row['text'] for row in env[1].logs[sid])
    assert '[Import 213/213]' in log and '3 Client-Ressourcen-/Shaderpaket(e)' in log
    for name in by_project.values():
        assert name in log
        assert not (core.folder(sid) / 'mods' / name).exists()
