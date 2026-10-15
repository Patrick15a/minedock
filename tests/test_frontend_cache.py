import hashlib
import re

from app import main


def test_html_references_content_versioned_assets(client):
    response=client.get('/')
    assert response.headers['cache-control']=='no-store'
    for name in ('app.js','style.css'):
        version=hashlib.sha256((main.STATIC/name).read_bytes()).hexdigest()[:16]
        assert f'/static/{name}?v={version}' in response.text
        asset=client.get(f'/static/{name}?v={version}')
        assert asset.status_code==200 and asset.headers['cache-control']=='no-cache'


def test_version_changes_after_static_update_without_restart(client,tmp_path,monkeypatch):
    (tmp_path/'index.html').write_text('<script src="/static/app.js?v=old"></script><link href="/static/style.css">')
    (tmp_path/'app.js').write_text('first')
    (tmp_path/'style.css').write_text('body{}')
    monkeypatch.setattr(main,'STATIC',tmp_path)
    before=client.get('/').text
    (tmp_path/'app.js').write_text('second')
    after=client.get('/').text
    assert before!=after and '?v=old' not in after
    assert hashlib.sha256(b'second').hexdigest()[:16] in after
    assert after.count('?v=')==2


def test_static_template_is_versioned_for_frontend_only_updates(client):
    html=(main.STATIC/'index.html').read_text(encoding='utf-8')
    for name in ('app.js','style.css'):
        version=hashlib.sha256((main.STATIC/name).read_bytes()).hexdigest()[:16]
        assert f'/static/{name}?v={version}' in html

