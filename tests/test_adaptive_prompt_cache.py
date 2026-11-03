"""Synthetic adaptive-layout state tests; no model or private workbook access."""
import importlib
import json
from pathlib import Path
import subprocess
import sys

import pytest


DAY = 86400


def arrange(units, path, now=100):
    try:
        module = importlib.import_module('src.utils.adaptive_prompt_cache')
    except ModuleNotFoundError:
        pytest.fail('adaptive prompt cache state engine is missing')
    return module.arrange_prompt_units(units, state_path=path, now=now)


def unit(key, text=None, **extra):
    return dict(id=key, text=key if text is None else text, **extra)


def test_initial_order_and_unchanged_order_ignore_input_reordering(tmp_path):
    path = tmp_path / 'state.json'
    units = [unit('a'), unit('b'), unit('clock', always_volatile=True),
             unit('new-day', initial_stable=False)]
    first = arrange(units, path)
    assert first['stable'] == ['a', 'b']
    assert first['volatile'] == ['clock', 'new-day']
    second = arrange(list(reversed(units)), path, 200)
    assert second['stable'] == first['stable']
    assert second['volatile'] == first['volatile']


def test_any_old_record_change_is_demoted_without_reordering_other_stable_units(tmp_path):
    path = tmp_path / 'state.json'
    arrange([unit('a'), unit('old'), unit('b')], path)
    result = arrange([unit('a'), unit('old', 'current value'), unit('b')], path, 200)
    assert result['stable'] == ['a', 'b']
    assert result['volatile'] == ['old']
    assert result['metadata']['demoted_unit_count'] == 1
    again = arrange([unit('a'), unit('old', 'newest value'), unit('b')], path, 300)
    assert again['stable'] == ['a', 'b']
    assert again['volatile'] == ['old']


def test_new_records_start_volatile_and_deleted_records_are_removed(tmp_path):
    path = tmp_path / 'state.json'
    arrange([unit('a'), unit('deleted')], path)
    result = arrange([unit('a'), unit('new')], path, 200)
    assert result['stable'] == ['a']
    assert result['volatile'] == ['new']
    assert result['metadata']['new_unit_count'] == 1
    assert result['metadata']['deleted_unit_count'] == 1
    assert len(json.loads(path.read_text())['units']) == 2


def test_promotion_requires_three_distinct_observations_and_a_full_quiet_day(tmp_path):
    path = tmp_path / 'state.json'
    units = [unit('a'), unit('candidate', initial_stable=False),
             unit('clock', always_volatile=True)]
    arrange(units, path, 100)
    assert arrange(units, path, 101)['volatile'] == ['candidate', 'clock']
    assert arrange(units, path, 102)['volatile'] == ['candidate', 'clock']
    result = arrange(units, path, 100 + DAY)
    assert result['stable'] == ['a', 'candidate']
    assert result['volatile'] == ['clock']
    assert result['metadata']['promoted_unit_count'] == 1


def test_repeated_same_timestamp_and_backward_clock_cannot_fake_stability(tmp_path):
    path = tmp_path / 'state.json'
    units = [unit('candidate', initial_stable=False)]
    arrange(units, path, 100)
    for _ in range(5):
        assert arrange(units, path, 100)['stable'] == []
    assert arrange(units, path, 1)['stable'] == []
    # One fresh observation after a day still does not satisfy three samples.
    assert arrange(units, path, 100 + DAY)['stable'] == []
    assert arrange(units, path, 101 + DAY)['stable'] == ['candidate']


def test_promotion_is_batched_and_changed_promoted_record_returns_to_tail(tmp_path):
    path = tmp_path / 'state.json'
    base = [unit('a'), unit('one', initial_stable=False)]
    arrange(base, path, 100)
    arrange(base, path, 200)
    result = arrange(base, path, 100 + DAY)
    assert result['stable'] == ['a', 'one']
    two = base + [unit('two')]
    arrange(two, path, 101 + DAY)
    arrange(two, path, 102 + DAY)
    result = arrange(two, path, 103 + DAY)
    assert 'two' in result['volatile']
    changed = [unit('a'), unit('one', 'edited again'), unit('two')]
    result = arrange(changed, path, 200 + DAY)
    assert result['stable'] == ['a']
    assert set(result['volatile']) == {'one', 'two'}
    assert 'one' not in arrange(changed, path, 201 + DAY)['stable']


def test_individually_eligible_units_wait_for_the_next_archive_batch(tmp_path):
    path = tmp_path / 'state.json'
    units = [unit('one', initial_stable=False), unit('two', initial_stable=False)]
    arrange(units, path, 100)
    edited = [units[0], unit('two', 'current value', initial_stable=False)]
    arrange(edited, path, 200)
    arrange(edited, path, 300)
    first_batch = arrange(edited, path, DAY + 100)
    assert first_batch['stable'] == ['one']
    assert first_batch['volatile'] == ['two']
    # Two is now individually eligible, but the archive batch is too recent.
    assert arrange(edited, path, DAY + 201)['volatile'] == ['two']
    next_batch = arrange(edited, path, 2 * DAY + 100)
    assert next_batch['stable'] == ['one', 'two']
    assert next_batch['volatile'] == []


def test_state_contains_fingerprints_not_text_ids_paths_or_unknown_fields(tmp_path):
    path = tmp_path / 'state.json'
    arrange([unit('PRIVATE_IDENTIFIER', 'PRIVATE_TEXT',
                  secret='PRIVATE_SECRET', filename='PRIVATE_PATH')], path)
    content = path.read_text()
    assert 'PRIVATE' not in content
    payload = json.loads(content)
    assert payload['schema_version'] == 1
    assert all(len(key) == 64 for key in payload['units'])
    assert all(len(value['hash']) == 64 for value in payload['units'].values())


@pytest.mark.parametrize('raw', ['{broken', '[]', '{"schema_version":999}',
                               '{"schema_version":1,"units":{}}'])
def test_corrupt_state_reinitializes_with_all_current_units(tmp_path, raw):
    path = tmp_path / 'state.json'
    path.write_text(raw)
    result = arrange([unit('current'), unit('volatile', initial_stable=False)], path)
    assert result['stable'] == ['current']
    assert result['volatile'] == ['volatile']
    assert result['metadata']['state'] == 'reset'
    assert json.loads(path.read_text())['schema_version'] == 1


def test_storage_failure_keeps_every_current_unit_and_only_enum_metadata(tmp_path, monkeypatch):
    module = importlib.import_module('src.utils.adaptive_prompt_cache')
    def fail(*_args, **_kwargs):
        raise OSError('PRIVATE_SECRET')
    monkeypatch.setattr(module, 'atomic_write_json', fail)
    result = arrange([unit('a'), unit('b', initial_stable=False)], tmp_path / 'state.json')
    assert result['stable'] == ['a']
    assert result['volatile'] == ['b']
    assert result['metadata']['state'] == 'unavailable'
    assert 'PRIVATE' not in json.dumps(result)


def test_linked_state_or_parent_is_rejected_without_writing_target(tmp_path):
    target = tmp_path / 'target.json'
    target.write_text('PRIVATE_ORIGINAL')
    link = tmp_path / 'linked.json'
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip('symlink creation unavailable')
    result = arrange([unit('a')], link)
    assert result['metadata']['state'] == 'unavailable'
    assert target.read_text() == 'PRIVATE_ORIGINAL'
    outside = tmp_path / 'outside'
    outside.mkdir()
    directory = tmp_path / 'linked-directory'
    directory.symlink_to(outside, target_is_directory=True)
    assert arrange([unit('b')], directory / 'state.json')['metadata']['state'] == 'unavailable'
    assert not list(outside.iterdir())


def test_duplicate_ids_and_invalid_observation_time_are_programming_errors(tmp_path):
    with pytest.raises(ValueError):
        arrange([unit('duplicate'), unit('duplicate')], tmp_path / 'state.json')
    for stamp in (float('nan'), -1, True):
        with pytest.raises(ValueError):
            arrange([unit('a')], tmp_path / 'state.json', stamp)


def test_missing_nested_cache_directories_are_created_safely(tmp_path):
    path = tmp_path / 'cache' / 'layout' / 'state.json'
    result = arrange([unit('a')], path)
    assert result['metadata']['state'] == 'initialized'
    assert path.is_file()


def test_linked_lock_is_rejected_without_touching_target(tmp_path):
    target = tmp_path / 'outside.lock'
    target.write_bytes(b'')
    link = tmp_path / '.context.lock'
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip('symlink creation unavailable')
    result = arrange([unit('a')], tmp_path / 'state.json')
    assert result['metadata']['state'] == 'unavailable'
    assert target.read_bytes() == b''


def test_oversized_state_is_reset_without_loading_or_retaining_unknown_content(tmp_path):
    module = importlib.import_module('src.utils.adaptive_prompt_cache')
    path = tmp_path / 'state.json'
    with path.open('wb') as handle:
        handle.seek(module.MAX_STATE_BYTES)
        handle.write(b'X')
    result = arrange([unit('a')], path)
    assert result['metadata']['state'] == 'reset'
    assert path.stat().st_size < 2000


def test_real_processes_serialize_state_without_partial_json_or_lost_units(tmp_path):
    script = '''import json,sys,time
from src.utils.adaptive_prompt_cache import arrange_prompt_units
value=arrange_prompt_units([dict(id='shared',text='same')],state_path=sys.argv[1])
print(json.dumps(value['metadata']))
'''
    path = tmp_path / 'state.json'
    children = [subprocess.Popen([sys.executable, '-c', script, str(path)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(4)]
    try:
        for child in children:
            stdout, stderr = child.communicate(timeout=15)
            assert child.returncode == 0, stderr
            assert json.loads(stdout)['state'] in {'initialized', 'ready'}
        payload = json.loads(path.read_text())
        assert len(payload['stable']) == len(payload['units']) == 1
        assert payload['volatile'] == []
    finally:
        for child in children:
            if child.poll() is None:
                child.kill(); child.wait(timeout=5)
