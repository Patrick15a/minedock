import httpx
import pytest
from deploy import set_curseforge_key as updater


def test_replace_key_preserves_other_settings_and_quotes():
    original = 'MINEDOCK_PASSWORD_HASH="unchanged"\nCURSEFORGE_API_KEY="old"\nMINEDOCK_MEMORY_MB="24576"\n'
    result = updater.replace_key(original, '$abc"\\xyz')
    assert result.splitlines()[0] == original.splitlines()[0]
    assert result.splitlines()[2] == original.splitlines()[2]
    assert 'CURSEFORGE_API_KEY="$abc\\"\\\\xyz"' in result


@pytest.mark.parametrize('text,key', [
    ('OTHER="value"\n', 'valid'),
    ('CURSEFORGE_API_KEY="a"\nCURSEFORGE_API_KEY="b"\n', 'valid'),
    ('CURSEFORGE_API_KEY="a"\n', 'bad\nkey'),
])
def test_rejects_ambiguous_config_or_invalid_key(text, key):
    with pytest.raises(ValueError):
        updater.replace_key(text, key)


@pytest.mark.parametrize('status,data,success', [
    (403, {'error':'secret-reflected-value'}, False),
    (200, {'data': []}, False),
    (200, {'data': [{'slug':'complex-cobblemon'}]}, True),
])
def test_validation_requires_actual_pack_and_keeps_response_private(monkeypatch, status, data, success):
    original = httpx.Client
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=data)
    monkeypatch.setattr(updater.httpx, 'Client', lambda **kw: original(transport=httpx.MockTransport(respond), **kw))
    if success:
        updater.validate_key('secret-reflected-value')
    else:
        with pytest.raises(ValueError) as error:
            updater.validate_key('secret-reflected-value')
        assert 'secret-reflected-value' not in str(error.value)
    assert len(requests) == 1
    assert requests[0].url.host == 'api.curseforge.com'
    assert requests[0].headers['x-api-key'] == 'secret-reflected-value'
