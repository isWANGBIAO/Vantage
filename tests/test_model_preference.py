import pytest
from fastapi import HTTPException
from src.backend import providers
from src.core import user_config


@pytest.fixture
def configured(monkeypatch, tmp_path):
    for kind in ('DATA', 'CONFIG', 'HISTORY', 'LOG', 'PLOT', 'CACHE', 'RUNTIME', 'MIGRATION'):
        monkeypatch.setenv(f'VANTAGE_{kind}_DIR', str(tmp_path / kind.lower()))
    user_config.save_provider_config({'selected_provider': 'glm', 'providers': {
        'glm': {'base_url': 'https://glm.invalid/v1', 'api_key': 'synthetic-glm', 'model': 'glm'},
        'deepseek': {'base_url': 'https://deepseek.invalid/v1', 'api_key': 'synthetic-secret',
                     'model': 'old', 'models': ['old', 'DeepSeek-V4-Flash-0731']},
        'disabled': {'enabled': False, 'model': 'disabled'},
        'incomplete': {'model': 'incomplete'},
    }, 'sampling_defaults': {'temperature': 0.8}})
    return user_config.load_provider_config()


def test_selection_persists_and_preserves_other_configuration(configured):
    result = providers.update_model_preference({'provider_route': 'deepseek', 'model': 'DeepSeek-V4-Flash-0731'})
    expected = configured
    expected['selected_provider'] = 'deepseek'
    expected['providers']['deepseek']['model'] = 'DeepSeek-V4-Flash-0731'
    expected['providers']['deepseek']['models'] = ['DeepSeek-V4-Flash-0731', 'old']
    assert user_config.load_provider_config() == expected
    assert result == {'provider_route': 'deepseek', 'model': 'DeepSeek-V4-Flash-0731'}


@pytest.mark.parametrize('payload', [
    {'provider_route': 'missing', 'model': 'glm'},
    {'provider_route': 'disabled', 'model': 'disabled'},
    {'provider_route': 'incomplete', 'model': 'incomplete'},
    {'provider_route': 'deepseek', 'model': 'unconfigured'},
    {'provider_route': 'deepseek', 'model': ''},
    {'provider_route': 'deepseek', 'model': 'old', 'api_key': 'must-not-change'},
])
def test_invalid_selection_does_not_write(configured, payload):
    with pytest.raises(HTTPException) as error:
        providers.update_model_preference(payload)
    assert error.value.status_code == 422
    assert user_config.load_provider_config() == configured


def test_failed_atomic_save_keeps_previous_selection(configured, monkeypatch):
    def fail(*args):
        raise OSError('synthetic failure')
    monkeypatch.setattr(user_config.os, 'replace', fail)
    with pytest.raises(OSError):
        providers.update_model_preference({'provider_route': 'deepseek', 'model': 'old'})
    assert user_config.load_provider_config() == configured
