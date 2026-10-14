from fastapi.testclient import TestClient
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware
from app import core, main


def test_trusted_apache_https_login(env, monkeypatch):
    monkeypatch.setattr(core, 'SECURE', True)
    wrapped = ProxyHeadersMiddleware(main.app, trusted_hosts=['10.0.0.2'])
    with TestClient(wrapped, base_url='http://panel.example.test', client=('10.0.0.2', 12345)) as proxy:
        reply = proxy.post('/api/login', json={'username':'admin','password':'test-passphrase-123'},
                           headers={'origin':'https://panel.example.test','x-forwarded-proto':'https','x-forwarded-for':'10.0.0.3'})
        assert reply.status_code == 200, reply.text
        assert 'Secure' in reply.headers['set-cookie']


def test_direct_client_allowed_but_cannot_forge_https(env):
    wrapped = ProxyHeadersMiddleware(main.app, trusted_hosts=['10.0.0.2'])
    with TestClient(wrapped, base_url='http://panel.example.test', client=('10.0.0.3', 12345)) as direct:
        headers = {'origin':'https://panel.example.test','x-forwarded-proto':'https'}
        credentials = {'username':'admin','password':'test-passphrase-123'}
        assert direct.post('/api/login', json=credentials, headers=headers).status_code == 403
        assert direct.get('/').status_code == 200
        assert direct.post('/api/login', json=credentials, headers={'origin':'http://panel.example.test'}).status_code == 200
