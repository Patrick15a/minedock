import json
import os
import types
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from app import core, main

PASSWORD = 'temporary-test-password-123'


def make_user(admin, sid, role='viewer', username='member', active=True):
    reply=admin.post('/api/users',json={'username':username,'password':PASSWORD,'role':role,'active':active,'server_ids':[sid]})
    assert reply.status_code==200,reply.text
    return reply.json()


def sign_in(user):
    client=TestClient(main.app)
    reply=client.post('/api/login',json={'username':user['username'],'password':PASSWORD})
    assert reply.status_code==200,reply.text
    client.headers['x-csrf-token']=reply.json()['csrf']
    return client


def test_legacy_admin_migration_preserves_password_and_servers(client,sid,monkeypatch):
    initial=core.user_by_name('admin')
    assert core.verify_password('test-passphrase-123',initial['password_hash'])
    core.change_password(initial['id'],'test-passphrase-123',PASSWORD)
    monkeypatch.setattr(core,'PASSWORD_HASH',core.hash_password('different-environment-password'))
    core.init()
    assert len(core.users())==1
    assert core.verify_password(PASSWORD,core.user_by_name('admin')['password_hash'])
    assert core.get(sid)['name']=='Testwelt'


@pytest.mark.parametrize('role',['manager','operator','viewer'])
def test_non_admin_sees_only_assigned_servers_and_cannot_probe_others(client,sid,config,role):
    other=client.post('/api/servers',json={**config,'name':'Private world','port':25566}).json()['id']
    user=make_user(client,sid,role)
    member=sign_in(user)
    data=member.get('/api/overview').json()
    assert [s['id'] for s in data['servers']]==[sid]
    for method,path,body in [
        ('GET','logs',None),('GET','mods',None),('GET','files',None),('GET','file?path=server.properties',None),
        ('GET','backups',None),('GET','backups/secret.tar.gz',None),
        ('POST','install',{'mode':'vanilla','version':'1.21.1'}),('POST','action/start',None),
        ('POST','command',{'command':'stop'}),('PUT','file',{'path':'x.txt','content':'bad'}),
        ('POST','backup',None),('POST','mods',{'name':'x.jar','action':'remove'}),
    ]:
        assert member.request(method,f'/api/servers/{other}/{path}',json=body).status_code==404,path
    assert member.put(f'/api/servers/{other}',json=config).status_code==404
    assert member.request('DELETE',f'/api/servers/{other}',json={'confirmation':'Private world'}).status_code==404
    assert member.post(f'/api/servers/{other}/upload?kind=server',content=b'invalid multipart').status_code==404
    assert member.get('/api/users').status_code==403
    assert member.post('/api/users',json={'username':'hacker','role':'admin','password':PASSWORD}).status_code==403
    assert member.put('/api/users/'+user['id'],json={**user,'role':'admin'}).status_code==403
    member.close()


@pytest.mark.parametrize('role',['operator','viewer'])
def test_readers_cannot_access_files_backups_or_modify_assigned_servers(client,sid,config,role):
    user=make_user(client,sid,role)
    member=sign_in(user)
    assert member.get(f'/api/servers/{sid}/logs').status_code==200
    assert member.get(f'/api/servers/{sid}/mods').status_code==200
    for method,path,body in [('GET','files',None),('GET','file?path=x.txt',None),('GET','backups',None),('GET','backups/x.tar.gz',None),('POST','backup',None),('POST','action/archive',None),('POST','install',{'mode':'vanilla','version':'1.21.1'}),('POST','mods',{'name':'x.jar','action':'remove'}),('PUT','file',{'path':'x.txt','content':'bad'})]:
        assert member.request(method,f'/api/servers/{sid}/{path}',json=body).status_code==403,path
    assert member.post('/api/servers',json={**config,'port':25566}).status_code==403
    assert member.put(f'/api/servers/{sid}',json=config).status_code==403
    assert member.post(f'/api/servers/{sid}/upload',content=b'invalid multipart').status_code==403
    assert member.request('DELETE',f'/api/servers/{sid}',json={'confirmation':'Testwelt'}).status_code==403
    member.close()


def test_operator_can_operate_but_viewer_cannot(client,sid,env,monkeypatch):
    calls=[]
    monkeypatch.setattr(env[1],'start',lambda target:calls.append(('start',target)))
    monkeypatch.setattr(env[1],'stop',lambda target:calls.append(('stop',target)))
    monkeypatch.setattr(env[1],'command',lambda target,value:calls.append(('command',target,value)))
    for role in ('operator','viewer'):
        user=make_user(client,sid,role,role)
        member=sign_in(user)
        for action in ('start','stop','restart'):
            assert member.post(f'/api/servers/{sid}/action/{action}').status_code==(200 if role=='operator' else 403)
        assert member.post(f'/api/servers/{sid}/command',json={'command':'list'}).status_code==(200 if role=='operator' else 403)
        member.close()
    assert len(calls)==5


def test_manager_creates_assigned_server_and_edits_it(client,sid,config):
    manager=sign_in(make_user(client,sid,'manager'))
    reply=manager.post('/api/servers',json={**config,'port':25566})
    assert reply.status_code==200,reply.text
    created=reply.json()['id']
    assert created in manager.get('/api/session').json()['user']['server_ids']
    assert manager.put(f'/api/servers/{created}',json={**config,'name':'Changed','port':25566}).status_code==200
    manager.close()


@pytest.mark.parametrize('change',[{'active':False},{'role':'operator'},{'server_ids':[]},{'password':'new-test-passphrase-456'}])
def test_user_changes_revoke_existing_sessions(client,sid,change):
    user=make_user(client,sid)
    member=sign_in(user)
    assert client.put('/api/users/'+user['id'],json={**user,**change}).status_code==200
    assert member.get('/api/overview').status_code==401
    member.close()


def test_password_change_revokes_all_sessions_and_old_password(client,sid):
    user=make_user(client,sid)
    first,second=sign_in(user),sign_in(user)
    assert first.post('/api/account/password',json={'current_password':'wrong','new_password':'new-test-passphrase-456'}).status_code==400
    assert first.post('/api/account/password',json={'current_password':PASSWORD,'new_password':'new-test-passphrase-456'}).status_code==200
    assert first.get('/api/session').status_code==401
    assert second.get('/api/session').status_code==401
    assert first.post('/api/login',json={'username':'member','password':PASSWORD}).status_code==401
    assert first.post('/api/login',json={'username':'member','password':'new-test-passphrase-456'}).status_code==200
    first.close();second.close()


def test_user_delete_revokes_session_retains_server_and_no_hashes_returned(client,sid):
    user=make_user(client,sid)
    member=sign_in(user)
    assert 'password_hash' not in client.get('/api/users').text
    assert 'session_version' not in member.get('/api/session').text
    assert client.request('DELETE','/api/users/'+user['id'],json={'confirmation':'member'}).status_code==200
    assert member.get('/api/session').status_code==401
    assert core.get(sid)
    with core.connect() as conn:
        assert not conn.execute('SELECT 1 FROM server_access WHERE user_id=?',(user['id'],)).fetchone()
    member.close()


def test_last_admin_and_self_protected(client,sid):
    admin=client.get('/api/session').json()['user']
    assert client.put('/api/users/'+admin['id'],json={**admin,'role':'viewer'}).status_code==400
    assert client.put('/api/users/'+admin['id'],json={**admin,'active':False}).status_code==400
    assert client.request('DELETE','/api/users/'+admin['id'],json={'confirmation':'admin'}).status_code==400
    with pytest.raises(ValueError,match='Mindestens'):
        core.write_user('admin','viewer',True,[],uid=admin['id'],actor_id='other')
    with pytest.raises(ValueError,match='Mindestens'):
        core.delete_user(admin['id'],'admin','other')


def test_user_validation_and_atomic_assignments(client,sid):
    user=make_user(client,sid)
    assert client.post('/api/users',json={'username':'MEMBER','role':'viewer','password':PASSWORD}).status_code==400
    assert client.post('/api/users',json={'username':'new','role':'root','password':PASSWORD}).status_code==422
    assert client.put('/api/users/'+user['id'],json={**user,'username':'renamed','server_ids':['0'*16]}).status_code==400
    assert core.user_by_id(user['id'])['username']=='member'
    assert core.public_user(core.user_by_id(user['id']))['server_ids']==[sid]
    disabled=make_user(client,sid,'viewer','disabled',False)
    assert client.post('/api/login',json={'username':disabled['username'],'password':PASSWORD}).status_code==401


def test_server_delete_removes_only_target_and_backups(client,sid,config):
    user=make_user(client,sid,'manager')
    member=sign_in(user)
    other=client.post('/api/servers',json={**config,'port':25566}).json()['id']
    (core.folder(sid)/'world').mkdir(); (core.folder(sid)/'world/level.dat').write_bytes(b'world')
    (core.folder(other)/'keep.txt').write_text('keep')
    backup=core.ROOT/'backups'/f'{sid}-20261014-220000-abcdef.tar.gz';backup.write_bytes(b'backup')
    keep=core.ROOT/'backups'/f'{other}-20261014-220000-abcdef.tar.gz';keep.write_bytes(b'keep')
    assert member.request('DELETE',f'/api/servers/{sid}',json={'confirmation':'wrong'}).status_code==400
    assert backup.exists() and (core.folder(sid)/'world/level.dat').exists()
    assert member.post(f'/api/servers/{sid}/action/archive').status_code==200
    assert member.request('DELETE',f'/api/servers/{sid}',json={'confirmation':'Testwelt'}).status_code==200
    assert not (core.ROOT/'servers'/sid).exists() and not backup.exists()
    assert (core.folder(other)/'keep.txt').read_text()=='keep' and keep.exists()
    assert sid not in core.public_user(core.user_by_id(user['id']))['server_ids']
    assert client.post('/api/servers',json=config).status_code==200
    member.close()


@pytest.mark.parametrize('busy',['process','job'])
def test_running_or_busy_server_cannot_be_deleted(client,sid,env,busy):
    manager=env[1]
    if busy=='process': manager.processes[sid]=types.SimpleNamespace(poll=lambda:None)
    else: manager.jobs[sid]={'state':'running'}
    try:
        response=client.request('DELETE',f'/api/servers/{sid}',json={'confirmation':'Testwelt'})
        assert response.status_code==400
        assert core.folder(sid).exists()
    finally:
        manager.processes.clear();manager.jobs.clear()


def test_delete_failure_keeps_record_for_retry(client,sid,monkeypatch):
    with monkeypatch.context() as m:
        m.setattr(main.shutil,'rmtree',lambda *a,**kw: (_ for _ in ()).throw(PermissionError()))
        assert client.request('DELETE',f'/api/servers/{sid}',json={'confirmation':'Testwelt'}).status_code==400
    assert core.get(sid)
    assert client.request('DELETE',f'/api/servers/{sid}',json={'confirmation':'Testwelt'}).status_code==200


def test_delete_rejects_linked_backup_before_removing_world(client,sid,tmp_path):
    sentinel=tmp_path/'outside.txt';sentinel.write_text('keep')
    backup=core.ROOT/'backups'/f'{sid}-20261014-220000-abcdef.tar.gz'
    try:
        backup.symlink_to(sentinel)
    except OSError:
        pytest.skip('Symlink creation unavailable on this platform')
    response=client.request('DELETE',f'/api/servers/{sid}',json={'confirmation':'Testwelt'})
    assert response.status_code==400
    assert core.folder(sid).exists() and sentinel.read_text()=='keep'


def test_new_endpoints_require_csrf(client,sid):
    client.headers.pop('x-csrf-token')
    assert client.post('/api/users',json={'username':'new','password':PASSWORD,'role':'viewer'}).status_code==403
    assert client.request('DELETE',f'/api/servers/{sid}',json={'confirmation':'Testwelt'}).status_code==403


def test_password_validation_does_not_reflect_input(client):
    reply=client.post('/api/users',json={'username':'new','role':'viewer','password':'shortsecret'})
    assert reply.status_code==422
    assert 'shortsecret' not in reply.text
