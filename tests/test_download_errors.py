import httpx
import pytest
from app import core, installer


@pytest.mark.parametrize('host,label', [
    ('api.curseforge.com', 'CurseForge-API verweigert'),
    ('edge.forgecdn.net', 'CurseForge-Dateidownload'),
    ('meta.fabricmc.net', 'Download von meta.fabricmc.net verweigert'),
])
@pytest.mark.parametrize('status', [401, 403])
def test_denied_download_identifies_provider_without_disclosing_secrets(monkeypatch, host, label, status):
    secret = 'test-secret-not-for-error-output'
    monkeypatch.setattr(core, 'CF_KEY', secret)
    real_client = httpx.Client
    transport = httpx.MockTransport(lambda request: httpx.Response(status, text=secret))
    monkeypatch.setattr(installer.httpx, 'Client', lambda **kw: real_client(transport=transport, **kw))
    with pytest.raises(ValueError) as error:
        installer.fetch(f'https://{host}/file?token={secret}')
    message = str(error.value)
    assert label in message and f'HTTP {status}' in message
    assert secret not in message
    if host == 'meta.fabricmc.net':
        assert 'CurseForge' not in message


def test_redirect_failure_reports_final_host(monkeypatch):
    real_client = httpx.Client
    def respond(request):
        if request.url.host == 'edge.forgecdn.net':
            return httpx.Response(302, headers={'location': 'https://mediafilez.forgecdn.net/file'})
        return httpx.Response(403)
    transport = httpx.MockTransport(respond)
    monkeypatch.setattr(installer.httpx, 'Client', lambda **kw: real_client(transport=transport, **kw))
    with pytest.raises(ValueError, match='mediafilez.forgecdn.net'):
        installer.fetch('https://edge.forgecdn.net/file')
