"""Configuration writes never trade recoverable data for false completion."""
import json
from pathlib import Path

import pytest

from src.backend import settings
from src.core import user_config


@pytest.fixture
def config_root(monkeypatch, tmp_path):
    for kind in ('DATA', 'CONFIG', 'HISTORY', 'LOG', 'PLOT', 'CACHE', 'RUNTIME', 'MIGRATION'):
        monkeypatch.setenv(f'VANTAGE_{kind}_DIR', str(tmp_path / kind.lower()))
    user_config.save_settings({'onboarding_completed': False})
    user_config.save_provider_config({'selected_provider': 'local', 'providers': {'local': {
        'base_url': 'https://provider.example/v1', 'api_key': 'synthetic-key', 'model': 'model',
    }}})
    user_config.save_migration_state({'completed': False})
    return tmp_path


@pytest.mark.parametrize('loader,name', [(user_config.load_settings, 'settings.json'),
                                       (user_config.load_provider_config, 'providers.json'),
                                       (user_config.load_migration_state, 'migration.json')])
def test_corrupt_configuration_read_preserves_original_bytes(tmp_path, loader, name):
    path = tmp_path / name
    original = b'{"recoverable_secret":"synthetic", broken'
    path.write_bytes(original)
    with pytest.raises(user_config.ConfigurationReadError, match='preserved'):
        loader(path)
    assert path.read_bytes() == original


def test_atomic_write_failure_retains_old_complete_json(monkeypatch, tmp_path):
    path = tmp_path / 'settings.json'
    user_config.save_settings({'theme': 'dark'}, path)
    original = path.read_bytes()
    def fail_replace(*_args):
        raise OSError('synthetic replace failure')
    monkeypatch.setattr(user_config.os, 'replace', fail_replace)
    with pytest.raises(OSError):
        user_config.save_settings({'theme': 'light'}, path)
    assert path.read_bytes() == original
    assert list(tmp_path.iterdir()) == [path]


def test_onboarding_provider_failure_does_not_commit_completed_or_damage_files(monkeypatch, config_root):
    paths = [user_config.get_settings_file(), user_config.get_providers_file(), user_config.get_migration_state_file()]
    previous = {p: p.read_bytes() for p in paths}
    def fail_save(_payload):
        assert user_config.load_settings()['onboarding_completed'] is False
        raise OSError('synthetic provider failure')
    monkeypatch.setattr(settings, 'save_provider_config', fail_save)
    with pytest.raises(OSError, match='synthetic provider failure'):
        settings.complete_automation_onboarding({'skip_chat_setup': False, 'selected_provider': 'local', 'model': 'new'})
    assert {p: p.read_bytes() for p in paths} == previous
    assert user_config.load_settings()['onboarding_completed'] is False


def test_onboarding_completion_is_the_last_write(monkeypatch, config_root):
    saved_provider = settings.save_provider_config
    saved_settings = settings.save_settings
    order = []
    def provider_write(payload):
        assert user_config.load_settings()['onboarding_completed'] is False
        order.append('provider')
        return saved_provider(payload)
    def settings_write(payload):
        assert user_config.load_provider_config()['providers']['local']['model'] == 'new'
        order.append('settings')
        return saved_settings(payload)
    monkeypatch.setattr(settings, 'save_provider_config', provider_write)
    monkeypatch.setattr(settings, 'save_settings', settings_write)
    result = settings.complete_automation_onboarding({'skip_chat_setup': False, 'selected_provider': 'local', 'model': 'new'})
    assert result['completed'] is True
    assert order == ['provider', 'settings']


@pytest.mark.parametrize("new_destination", ["https://another.example/v1", "invalid-destination"])
def test_settings_destination_change_requires_explicit_credential_choice(config_root, new_destination):
    from fastapi import HTTPException
    original = user_config.get_providers_file().read_bytes()
    with pytest.raises(HTTPException) as caught:
        settings.update_automation_settings({'provider_config': {'providers': {'local': {
            'base_url': new_destination, 'api_key': ' ******** ',
        }}}})
    assert caught.value.status_code == 422
    assert user_config.get_providers_file().read_bytes() == original
    settings.update_automation_settings({'provider_config': {'providers': {'local': {
        'base_url': new_destination, 'api_key': '',
    }}}})
    assert user_config.load_provider_config()['providers']['local']['api_key'] == ''


def test_onboarding_destination_change_keeps_old_key_on_validation_failure(config_root):
    from fastapi import HTTPException
    original = user_config.get_providers_file().read_bytes()
    with pytest.raises(HTTPException):
        settings.complete_automation_onboarding({'skip_chat_setup': False, 'selected_provider': 'local',
                                               'base_url': 'https://another.example/v1'})
    assert user_config.get_providers_file().read_bytes() == original
    assert user_config.load_settings()['onboarding_completed'] is False


def test_config_api_returns_typed_recovery_error_without_rewriting(config_root):
    from fastapi.testclient import TestClient
    from src.server import app
    path = user_config.get_providers_file()
    original = b'{"api_key":"synthetic", broken'
    path.write_bytes(original)
    client = TestClient(app, base_url='http://127.0.0.1', client=('127.0.0.1', 12345))
    response = client.get('/api/v1/settings')
    assert response.status_code == 503
    assert response.json()['code'] == 'configuration_unreadable'
    assert response.json()['original_preserved'] is True
    assert 'synthetic' not in response.text
    assert path.read_bytes() == original


def test_onboarding_incomplete_provider_cannot_claim_completion(config_root):
    from fastapi import HTTPException
    user_config.save_provider_config({'providers': {}})
    paths = [user_config.get_settings_file(), user_config.get_providers_file(), user_config.get_migration_state_file()]
    previous = {p: p.read_bytes() for p in paths}
    with pytest.raises(HTTPException) as caught:
        settings.complete_automation_onboarding({'skip_chat_setup': False, 'selected_provider': 'new', 'model': 'model'})
    assert caught.value.status_code == 422
    assert {p: p.read_bytes() for p in paths} == previous
    assert settings.complete_automation_onboarding({'skip_chat_setup': True})['completed'] is True
