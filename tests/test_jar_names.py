import io
import json
import zipfile

import pytest

from app import core, installer


ANIMALS = "nocube's_villagers_sell_animals_1.2.0_forge_1.19.2.jar"
FARMERS = "nocube's_farmers_compats_1.0.0_Forge_1.19.2.jar"


def jar_bytes():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        archive.writestr('META-INF/MANIFEST.MF', 'Manifest-Version: 1.0\n')
    return buffer.getvalue()


def write_pack(path, refs):
    manifest = {'manifestType': 'minecraftModpack', 'manifestVersion': 1,
                'name': 'Filename regression', 'minecraft': {'version': '1.19.2',
                'modLoaders': [{'id': 'forge-43.2.6', 'primary': True}]},
                'files': refs, 'overrides': 'overrides'}
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('manifest.json', json.dumps(manifest))


@pytest.mark.parametrize('name', [ANIMALS, FARMERS, 'mod, extra & more!.jar',
                                  'Bäume-日本語-1.0.jar', 'a' * 242 + '.jar',
                                  'é' * 121 + '.jar'])
def test_valid_jar_names_are_preserved(name):
    assert installer.filename(name) == name


@pytest.mark.parametrize('name', ['../escape.jar', '/absolute.jar', 'mods/nested.jar',
    'mods\\nested.jar', 'C:drive.jar', 'bad\x00.jar', 'bad\n.jar', 'bad\t.jar',
    'bad\u202e.jar', 'bad\u2028.jar', 'bad\ud800.jar', 'bad?.jar', 'bad*.jar',
    'bad|.jar', 'bad<.jar', 'bad>.jar', 'bad".jar', 'a' * 243 + '.jar',
    'é' * 122 + '.jar', 'file.zip', 'file.JAR', '.jar', '', None, 123])
def test_unsafe_or_oversized_jar_names_are_rejected(name):
    with pytest.raises(ValueError, match='Ungültiger JAR-Dateiname'):
        installer.filename(name)


def test_import_passes_entry_47_with_apostrophe(client, sid, tmp_path, monkeypatch, env):
    archive = tmp_path / 'regression.zip'
    refs = [{'projectID': i + 1, 'fileID': i + 101} for i in range(46)]
    refs += [{'projectID': 664014, 'fileID': 4454534}, {'projectID': 99, 'fileID': 999}]
    write_pack(archive, refs)
    downloaded = []
    def cf(route):
        project = int(route.split('/')[1])
        name = ANIMALS if project == 664014 else FARMERS if project == 99 else f'mod-{project}.jar'
        return {'fileName': name, 'downloadUrl': 'https://edge.forgecdn.net/example.jar'}
    def fetch(url, destination, **kwargs):
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(jar_bytes())
        downloaded.append(destination.name)
    monkeypatch.setattr(installer, 'cf', cf)
    monkeypatch.setattr(installer, 'fetch', fetch)
    monkeypatch.setattr(installer, 'install_loader', lambda *args: ['-jar', 'server.jar'])
    installer.install(sid, 'zip', archive)
    assert downloaded[46:] == [ANIMALS, FARMERS]
    assert len(list((core.folder(sid) / 'mods').iterdir())) == 48
    assert (core.folder(sid) / 'mods' / ANIMALS).read_bytes() == jar_bytes()
    assert core.get(sid)['installed'] is True
    assert any('[Import 47/48]' in entry['text'] and ANIMALS in entry['text'] for entry in env[1].logs[sid])


@pytest.mark.parametrize('name', [ANIMALS, FARMERS, 'a' * 242 + '.jar'])
def test_upload_toggle_and_delete_special_and_long_names(client, sid, name):
    assert client.post(f'/api/servers/{sid}/upload?kind=server', files={'file': ('server.jar', jar_bytes())}).status_code == 200
    assert client.post(f'/api/servers/{sid}/upload?kind=mod', files={'file': (name, jar_bytes())}).status_code == 200
    assert client.post(f'/api/servers/{sid}/mods', json={'name': name, 'action': 'toggle'}).status_code == 200
    disabled = name + '.disabled'
    assert (core.folder(sid) / 'mods' / disabled).exists()
    assert client.post(f'/api/servers/{sid}/mods', json={'name': disabled, 'action': 'toggle'}).status_code == 200
    assert client.post(f'/api/servers/{sid}/mods', json={'name': name, 'action': 'remove'}).status_code == 200
    assert client.get(f'/api/servers/{sid}/mods').json() == []


def test_missing_download_keeps_original_name_for_manual_upload(client, sid, tmp_path, monkeypatch):
    archive = tmp_path / 'manual.zip'
    write_pack(archive, [{'projectID': 664014, 'fileID': 4454534}])
    def cf(route):
        if '/files/' in route:
            return {'fileName': ANIMALS, 'downloadUrl': None}
        return {'links': {'websiteUrl': 'https://www.curseforge.com/minecraft/mc-mods/villagers-sell-animals'}}
    monkeypatch.setattr(installer, 'cf', cf)
    monkeypatch.setattr(installer, 'install_loader', lambda *args: ['-jar', 'server.jar'])
    installer.install(sid, 'zip', archive)
    assert core.get(sid)['missing'][0]['name'] == ANIMALS
    assert client.post(f'/api/servers/{sid}/upload?kind=mod', files={'file': (ANIMALS, jar_bytes())}).status_code == 200
    assert core.get(sid)['missing'] == []


def test_invalid_provider_name_reports_file_and_preserves_live_directory(client, sid, tmp_path, monkeypatch):
    archive = tmp_path / 'bad.zip'
    write_pack(archive, [{'projectID': 664014, 'fileID': 4454534}])
    monkeypatch.setattr(installer, 'cf', lambda route: {'fileName': '../bad\n.jar'})
    with pytest.raises(ValueError) as error:
        installer.install(sid, 'zip', archive)
    assert '[Import 1/1]' in str(error.value)
    assert '664014' in str(error.value) and '4454534' in str(error.value)
    assert '../bad\\n.jar' in str(error.value)
    assert '\n' not in str(error.value)
    assert list(core.folder(sid).iterdir()) == []
    assert not core.get(sid)['installed']
