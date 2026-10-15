import io
import json
import zipfile

import pytest

from app import core, installer, modscan


def jar(metadata=None, family='fabric', extra=None):
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w') as z:
        if metadata is not None:
            name = 'fabric.mod.json' if family == 'fabric' else 'META-INF/neoforge.mods.toml' if family == 'neoforge' else 'META-INF/mods.toml'
            z.writestr(name, json.dumps(metadata) if isinstance(metadata, dict) else metadata)
        for name, blob in (extra or {}).items():
            z.writestr(name, blob)
    return out.getvalue()


def fabric(id, side='*', depends=None, **extra):
    return dict(schemaVersion=1, id=id, version='1.0', environment=side, depends=depends or {}, **extra)


def fixture(tmp_path, files, loader='fabric-0.16'):
    mods = tmp_path / 'mods'
    mods.mkdir()
    for name, blob in files.items():
        (mods / name).write_bytes(blob)
    return {'loader': loader, 'version': '1.19.2'}


def test_fabric_client_only_and_dual_side(tmp_path):
    cfg = fixture(tmp_path, {'client.jar': jar(fabric('client', 'client')), 'both.jar': jar(fabric('both'))})
    result = modscan.scan(tmp_path, cfg)
    assert (tmp_path / 'mods/client.jar.disabled').exists()
    assert (tmp_path / 'mods/both.jar').exists()
    assert result['client.jar']['status'] == 'client'
    assert modscan.scan(tmp_path, cfg)['client.jar']['enabled'] is False


@pytest.mark.parametrize('loader', ['forge-43.2.6', 'neoforge-21.1', 'custom'])
def test_fabric_metadata_never_classifies_other_loaders(tmp_path, loader):
    cfg = fixture(tmp_path, {'client.jar': jar(fabric('client', 'client'))}, loader)
    assert modscan.scan(tmp_path, cfg)['client.jar']['status'] == 'unknown'
    assert (tmp_path / 'mods/client.jar').exists()


def test_dependency_closure_retains_client_candidates(tmp_path):
    cfg = fixture(tmp_path, {'a.jar': jar(fabric('a', 'client', {'b':'*'})),
                            'b.jar': jar(fabric('b', 'client')),
                            'server.jar': jar(fabric('server', '*', {'a':'*'}))})
    rows = modscan.scan(tmp_path, cfg)
    assert rows['a.jar']['status'] == rows['b.jar']['status'] == 'conflict'
    assert len(list((tmp_path / 'mods').glob('*.jar'))) == 3


def test_nested_library_dependency_protects_outer_client(tmp_path):
    client = jar(fabric('client', 'client', jars=[{'file':'nested/lib.jar'}]),
                 extra={'nested/lib.jar': jar(fabric('lib'))})
    cfg = fixture(tmp_path, {'client.jar':client, 'server.jar':jar(fabric('server', depends={'lib':'*'}))})
    assert modscan.scan(tmp_path, cfg)['client.jar']['status'] == 'conflict'


def test_unknown_active_file_blocks_automatic_removal(tmp_path):
    cfg = fixture(tmp_path, {'client.jar':jar(fabric('client', 'client')), 'broken.jar':b'broken'})
    assert modscan.scan(tmp_path, cfg)['client.jar']['status'] == 'conflict'
    assert (tmp_path / 'mods/client.jar').exists()


@pytest.mark.parametrize('blob', [
    '{"schemaVersion":1,"id":"x","environment":"client","environment":"*"}',
    '{bad json', json.dumps(fabric('x', 'invalid')),
    json.dumps(dict(fabric('x', 'client'), schemaVersion=999)),
    json.dumps(fabric('x', 'client', jars=[{'file':'../escape.jar'}])),
    ' ' * (modscan.MAX_METADATA + 1),
], ids=['duplicate','broken','side','schema','nested-path','size'])
def test_ambiguous_or_oversized_metadata_remains_active(tmp_path, blob):
    cfg = fixture(tmp_path, {'mod.jar':jar(blob)})
    assert modscan.scan(tmp_path, cfg)['mod.jar']['status'] == 'unknown'
    assert (tmp_path / 'mods/mod.jar').exists()


@pytest.mark.parametrize('family', ['forge','neoforge'])
def test_display_test_is_not_client_side_declaration(tmp_path, family):
    text = 'modLoader="javafml"\n[[mods]]\nmodId="example"\ndisplayTest="IGNORE_ALL_VERSION"\n'
    cfg = fixture(tmp_path, {'both.jar':jar(text, family)}, family + '-1')
    assert modscan.scan(tmp_path, cfg)['both.jar']['status'] == 'unchecked'


@pytest.mark.parametrize('side,blocked', [('CLIENT',False),('SERVER',True),('BOTH',True)])
@pytest.mark.parametrize('family', ['forge','neoforge'])
def test_forge_dependency_side_and_exact_rules(tmp_path, monkeypatch, side, blocked, family):
    client = jar('[[mods]]\nmodId="client"\n',family)
    server = jar(f'[[mods]]\nmodId="server"\n[[dependencies.server]]\nmodId="client"\nmandatory=true\ntype="required"\nside="{side}"\n',family)
    cfg = fixture(tmp_path, {'client.jar':client, 'server.jar':server},family+'-1')
    rule = {'loader':family,'minecraft':'1.19.2','sha256':modscan.digest(tmp_path/'mods/client.jar'),'mod_id':'client','reason':'Verified test rule'}
    monkeypatch.setattr(modscan,'RULESET',{'rules':[rule]})
    rows=modscan.scan(tmp_path,cfg)
    assert rows['client.jar']['enabled'] == blocked
    assert rows['client.jar']['status'] == ('conflict' if blocked else 'client')


def test_rules_are_bound_to_bytes_and_minecraft_version(tmp_path, monkeypatch):
    cfg = fixture(tmp_path, {'client.jar':jar(fabric('client'))})
    rule={'loader':'fabric','minecraft':'1.19.2','sha256':'0'*64,'mod_id':'client','reason':'rule'}
    monkeypatch.setattr(modscan,'RULESET',{'rules':[rule]})
    assert modscan.scan(tmp_path,cfg)['client.jar']['enabled']
    rule['sha256']=modscan.digest(tmp_path/'mods/client.jar');rule['minecraft']='1.20'
    assert modscan.scan(tmp_path,cfg)['client.jar']['enabled']


def test_profile_requires_exact_manifest_inventory_and_provenance(tmp_path, monkeypatch):
    cfg=fixture(tmp_path, {'server.jar':jar(fabric('server')), 'extra.jar':jar(fabric('extra'))})
    keep=modscan.digest(tmp_path/'mods/server.jar')
    sha=modscan.digest(tmp_path/'mods/extra.jar')
    profile={'manifest_key':'exact','keep':[keep],'exclude':[[1,2]],'label':'test'}
    monkeypatch.setattr(modscan,'RULESET',{'profiles':[profile]})
    cfg['mod_sources']={'extra.jar':{'project':1,'file':2,'sha256':sha}}
    assert modscan.scan(tmp_path,cfg)['extra.jar']['enabled']
    cfg['mod_manifest_key']='exact';profile['keep']=['0'*64]
    assert modscan.scan(tmp_path,cfg)['extra.jar']['enabled']
    profile['keep']=[keep];cfg['mod_sources']['extra.jar']['sha256']='0'*64
    assert modscan.scan(tmp_path,cfg)['extra.jar']['enabled']
    cfg['mod_sources']['extra.jar']['sha256']=sha
    assert not modscan.scan(tmp_path,cfg)['extra.jar']['enabled']


def test_server_reference_preserves_custom_uploads(tmp_path):
    cfg=fixture(tmp_path, {'server.jar':jar(fabric('server')), 'custom.jar':jar(fabric('custom'))})
    cfg['mod_server_reference']={'keep':[modscan.digest(tmp_path/'mods/server.jar')],'label':'test'}
    assert modscan.scan(tmp_path,cfg)['custom.jar']['enabled']


def test_duplicate_active_and_disabled_files_are_not_overwritten(tmp_path):
    blob=jar(fabric('client','client'))
    cfg=fixture(tmp_path,{'mod.jar':blob,'mod.jar.disabled':blob})
    with pytest.raises(ValueError,match='gleichzeitig'):
        modscan.scan(tmp_path,cfg)
    assert (tmp_path/'mods/mod.jar').read_bytes()==blob
    assert (tmp_path/'mods/mod.jar.disabled').read_bytes()==blob


def installed(sid,loader='fabric-0.16'):
    cfg=core.get(sid);cfg.update(installed=True,loader=loader,version='1.19.2',launch=['-jar','server.jar'])
    core.save(cfg)


def test_upload_disable_manual_override_persists_across_rename_and_version(client,sid):
    installed(sid)
    upload=lambda name,blob:client.post(f'/api/servers/{sid}/upload?kind=mod',files={'file':(name,blob)})
    assert upload('client.jar',jar(fabric('client','client'))).status_code==200
    assert (core.folder(sid)/'mods/client.jar.disabled').exists()
    assert client.post(f'/api/servers/{sid}/mods',json={'name':'client.jar.disabled','action':'toggle'}).status_code==200
    assert client.post(f'/api/servers/{sid}/mods/scan').status_code==200
    assert (core.folder(sid)/'mods/client.jar').exists()
    assert client.post(f'/api/servers/{sid}/mods',json={'name':'client.jar','action':'remove'}).status_code==200
    new=fabric('client','client');new['version']='2.0'
    assert upload('renamed.jar',jar(new)).status_code==200
    assert (core.folder(sid)/'mods/renamed.jar').exists()
    row=client.get(f'/api/servers/{sid}/mods').json()[0]
    assert row['assessment']['override']=='allow'
    assert client.post(f'/api/servers/{sid}/mods',json={'name':'renamed.jar','action':'automatic'}).status_code==200
    assert (core.folder(sid)/'mods/renamed.jar.disabled').exists()


def test_scan_refuses_running_or_archived_server(client,sid,env,monkeypatch):
    installed(sid)
    monkeypatch.setattr(env[1],'running',lambda sid:True)
    assert client.post(f'/api/servers/{sid}/mods/scan').status_code==400
    monkeypatch.setattr(env[1],'running',lambda sid:False)
    cfg=core.get(sid);cfg['archived']=True;core.save(cfg)
    assert client.post(f'/api/servers/{sid}/mods/scan').status_code==400


def test_scan_get_is_read_only_and_details_not_in_overview(client,sid):
    installed(sid)
    root=core.folder(sid)/'mods';root.mkdir();(root/'client.jar').write_bytes(jar(fabric('client','client')))
    assert client.get(f'/api/servers/{sid}/mods').status_code==200
    assert (root/'client.jar').exists()
    assert client.post(f'/api/servers/{sid}/mods/scan').status_code==200
    row=client.get('/api/overview').json()['servers'][0]
    assert 'mod_scan' not in row and 'mod_sources' not in row and row['mod_scan_summary']['checked']==1


def test_import_scans_override_jars(client,sid,tmp_path,monkeypatch):
    archive=tmp_path/'pack.zip'
    manifest={'manifestType':'minecraftModpack','manifestVersion':1,'name':'test','version':'1',
              'minecraft':{'version':'1.19.2','modLoaders':[{'id':'fabric-0.16','primary':True}]},'files':[]}
    with zipfile.ZipFile(archive,'w') as z:
        z.writestr('manifest.json',json.dumps(manifest))
        z.writestr('overrides/mods/client.jar',jar(fabric('client','client')))
    monkeypatch.setattr(installer,'install_loader',lambda *args:['-jar','server.jar'])
    installer.install(sid,'zip',archive)
    assert (core.folder(sid)/'mods/client.jar.disabled').exists()
    assert core.get(sid)['mod_scan']['client.jar']['status']=='client'


def test_upload_completes_profile_reference(client,sid):
    installed(sid)
    blob=jar(fabric('client'))
    server_blob=jar(fabric('server'))
    import hashlib
    cfg=core.get(sid)
    cfg['mod_sources']={'client.jar':{'project':1,'file':2}}
    cfg['mod_server_reference']={'keep':[hashlib.sha256(server_blob).hexdigest()],'label':'exact'}
    core.save(cfg)
    assert client.post(f'/api/servers/{sid}/upload?kind=mod',files={'file':('client.jar',blob)}).status_code==200
    assert (core.folder(sid)/'mods/client.jar').exists()
    assert client.post(f'/api/servers/{sid}/upload?kind=mod',files={'file':('server.jar',server_blob)}).status_code==200
    assert (core.folder(sid)/'mods/client.jar.disabled').exists()


def test_server_inventory_never_extracts_scripts(tmp_path):
    path=tmp_path/'server.zip'
    blob=jar(fabric('server'))
    with zipfile.ZipFile(path,'w') as z:
        z.writestr('pack/mods/server.jar',blob)
        z.writestr('pack/start.sh','this must never execute')
    import hashlib
    assert modscan.server_inventory(path)==[hashlib.sha256(blob).hexdigest()]
    assert not (tmp_path/'pack').exists()


@pytest.mark.parametrize('bad', ['../mods/bad.jar','/mods/bad.jar','one/mods/a.jar'])
def test_ambiguous_or_traversing_server_pack_rejected(tmp_path,bad):
    path=tmp_path/'server.zip'
    with zipfile.ZipFile(path,'w') as z:
        z.writestr('pack/mods/server.jar',b'jar')
        z.writestr(bad,b'jar')
    with pytest.raises(ValueError):modscan.server_inventory(path)


def test_server_pack_api_checks_identity_and_falls_back(client,sid,tmp_path,monkeypatch,env):
    cfg={}
    monkeypatch.setattr(installer,'cf',lambda route:{'id':2,'modId':999,'isServerPack':True})
    installer.attach_server_reference(sid,cfg,tmp_path,1,2)
    assert 'mod_server_reference' not in cfg
    assert any('nicht verfügbar' in x['text'] for x in env[1].logs[sid])


def test_forge_library_does_not_block_profile(tmp_path):
    lib=jar(extra={'META-INF/MANIFEST.MF':'Manifest-Version: 1.0\nFMLModType: LIBRARY\n'})
    cfg=fixture(tmp_path,{'library.jar':lib},'forge-43')
    assert modscan.scan(tmp_path,cfg)['library.jar']['readable']


def test_unrenamable_candidate_keeps_its_dependencies(tmp_path):
    long_name='x'*247+'.jar'
    cfg=fixture(tmp_path,{long_name:jar(fabric('long','client',{'dependency':'*'})),
                          'dependency.jar':jar(fabric('dependency','client'))})
    rows=modscan.scan(tmp_path,cfg)
    assert rows[long_name]['status']=='conflict'
    assert rows['dependency.jar']['enabled']


def test_serverpack_upload_saves_reference_and_scans(client,sid):
    installed(sid)
    server_blob=jar(fabric('server'))
    client_blob=jar(fabric('extra'))
    cfg=core.get(sid);cfg['mod_sources']={'extra.jar':{'project':1,'file':2}};core.save(cfg)
    for name,blob in [('server.jar',server_blob),('extra.jar',client_blob)]:
        assert client.post(f'/api/servers/{sid}/upload?kind=mod',files={'file':(name,blob)}).status_code==200
    archive=io.BytesIO()
    with zipfile.ZipFile(archive,'w') as z:
        z.writestr('mods/server.jar',server_blob)
        z.writestr('start.sh','must not run')
    assert client.post(f'/api/servers/{sid}/upload?kind=serverpack',files={'file':('server.zip',archive.getvalue())}).status_code==200
    assert (core.folder(sid)/'mods/extra.jar.disabled').exists()
    assert not (core.folder(sid)/'start.sh').exists()
