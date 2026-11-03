"""Synthetic fidelity tests for adaptive ordering; no local records are read."""
from copy import deepcopy
import hashlib
import importlib
import json

import pytest


def module():
    try:
        return importlib.import_module('src.utils.adaptive_prompt_layout')
    except ModuleNotFoundError:
        pytest.fail('adaptive prompt layout is not implemented')


def balanced(sheets=None, **metadata):
    payload = {'file_name': 'synthetic.xlsx', 'sheet_count': 1, 'total_rows': 2,
        'sheets': sheets if sheets is not None else [{'name': 'Assets',
            'columns': ['Name', 'Amount'], 'rows': [['A', 1], ['B', 2]],
            'row_count': 2, 'non_null_counts': {'Name': 2, 'Amount': 2}}], **metadata}
    return '## Balance Sheet Data (JSON)\n\n```json\n' + json.dumps(payload) + '\n```'


def arguments(tmp_path):
    return dict(prompt_sections=['Personal synthetic instructions', '# Goals\n\nSynthetic goal'],
        time_payload={'columns': ['date', 'metric'],
            'rows': [['2025-01-01', 1], ['2026-11-01', 2]],
            'column_meta': {'metric': {'unit': 'synthetic'}},
            'date_range': {'start': '2025-01-01', 'end': '2026-11-03'},
            'estimated_tokens': 800, 'included_row_count': 3, 'unknown_time_field': [7]},
        balance_summary=balanced(), future_planned_rows='Future synthetic text',
        current_day_payload={'current_day': ['2026-11-03', 3],
            'latest_values': {'metric': {'date': '2026-11-03', 'value': 3}},
            'non_null_counts': {'metric': 3}, 'unknown_current_field': 'preserve'},
        runtime_context_summary='Runtime synthetic clock', state_path=tmp_path/'layout.json', now=100000)


def blocks(text, language):
    marker = '```' + language + '\n'
    values = []
    start = 0
    while marker in text[start:]:
        begin = text.index(marker, start) + len(marker)
        end = text.index('\n```', begin)
        values.append(text[begin:end])
        start = end + 4
    return values


def records(text):
    language = schema(text).get('record_fence', 'jsonl')
    return [json.loads(line) for block in blocks(text, language) for line in block.splitlines() if line]


def schema(text):
    return json.loads(blocks(text, 'json')[0])


def dynamic(text):
    return json.loads(blocks(text.split('## Dynamic Context (JSON)\n\n',1)[1], 'json')[0])


def capture_arrangement(monkeypatch, adapter):
    calls = []
    def arrange(units, **kwargs):
        calls.append(deepcopy(units))
        return {'stable': [u['id'] for u in units if u.get('initial_stable', True) and not u.get('always_volatile')],
            'volatile': [u['id'] for u in units if not u.get('initial_stable', True) or u.get('always_volatile')],
            'metadata': {'state': 'ready', 'stable_unit_count': 4}}
    monkeypatch.setattr(adapter, 'arrange_prompt_units', arrange)
    return calls


def test_fidelity_preserves_all_rows_markdown_schema_and_unknown_metadata(tmp_path, monkeypatch):
    adapter = module()
    calls = capture_arrangement(monkeypatch, adapter)
    args = arguments(tmp_path)
    before = deepcopy(args)
    text = adapter.build_adaptive_prompt(**args)
    assert args == before
    for document in args['prompt_sections']:
        assert text.count(document) == 1
    sources = schema(text)['sources']
    time_code = next(k for k,v in sources.items() if v['kind'] == 'time')
    balance_code = next(k for k,v in sources.items() if v['kind'] == 'balance')
    assert [r[1] for r in records(text) if r[0] == time_code] == [
        ['2025-01-01',1], ['2026-11-01',2], ['2026-11-03',3]]
    assert [r[1] for r in records(text) if r[0] == balance_code] == [['A',1],['B',2]]
    assert sources[time_code]['columns'] == ['date','metric']
    assert sources[time_code]['column_meta'] == {'metric': {'unit':'synthetic'}}
    tail = dynamic(text)
    assert tail['time_metadata']['unknown_time_field'] == [7]
    assert tail['time_metadata']['included_row_count'] == 3
    assert tail['current_day_metadata']['unknown_current_field'] == 'preserve'
    assert tail['current_day_metadata']['current_day_reference'] == {'source':'t','index':2}
    assert tail['balance_metadata']['file_name'] == 'synthetic.xlsx'
    assert tail['balance_metadata']['sheets'][0]['metadata']['row_count'] == 2
    assert text.index('Runtime synthetic clock') > text.index('## Mutable Context')
    assert text.count('Future synthetic text') == 1
    assert len({u['id'] for u in calls[0]}) == len(calls[0])
    assert all(len(u['id']) == 64 for u in calls[0])


def test_old_date_and_finance_value_edits_keep_identity_not_content_hash(tmp_path, monkeypatch):
    adapter = module()
    calls = capture_arrangement(monkeypatch, adapter)
    args = arguments(tmp_path)
    adapter.build_adaptive_prompt(**args)
    args['time_payload']['rows'][0][1] = 900
    args['balance_summary'] = balanced([{'name': 'Assets', 'columns': ['Name','Amount'],
        'rows': [['A', 901], ['B',2]], 'row_count': 2}])
    text = adapter.build_adaptive_prompt(**args)
    old = {u['id']: u['text'] for u in calls[0]}
    new = {u['id']: u['text'] for u in calls[1]}
    changed = {key for key in old.keys() & new.keys() if old[key] != new[key]}
    assert len(changed) >= 2
    assert {u['id'] for u in calls[0] if '2025-01-01' in u['text']} == {
        u['id'] for u in calls[1] if '2025-01-01' in u['text']}
    assert ['2025-01-01', 900] in [r[1] for r in records(text)]
    assert ['A', 901] in [r[1] for r in records(text)]
    assert ['A', 1] not in [r[1] for r in records(text)]


def test_duplicate_days_sheets_and_finance_anchors_are_not_merged(tmp_path, monkeypatch):
    adapter = module()
    calls = capture_arrangement(monkeypatch, adapter)
    args = arguments(tmp_path)
    args['time_payload']['rows'] = [['2025-01-01',1], ['2025-01-01',2]]
    args['balance_summary'] = balanced([{'name':'Assets','columns':['ID','Name','Amount'],
        'rows': [['same','A',1], ['same','A',1], [None,None,3]]},
        {'name':'Assets','columns':['ID','Name','Amount'],'rows':[['same','A',1]]}])
    text = adapter.build_adaptive_prompt(**args)
    assert len(records(text)) == 7
    assert len({u['id'] for u in calls[0]}) == len(calls[0])
    assert [r[1] for r in records(text)].count(['same','A',1]) == 3


def test_cross_day_does_not_make_an_existing_row_a_new_unit(tmp_path, monkeypatch):
    adapter = module()
    calls = capture_arrangement(monkeypatch, adapter)
    args = arguments(tmp_path)
    adapter.build_adaptive_prompt(**args)
    old_id = next(u['id'] for u in calls[0] if '2026-11-03' in u['text'] and '["t",' in u['text'])
    args['time_payload']['rows'].append(args['current_day_payload']['current_day'])
    args['current_day_payload']['current_day'] = ['2026-11-04',4]
    adapter.build_adaptive_prompt(**args)
    new_ids = [u['id'] for u in calls[1] if '2026-11-03' in u['text'] and '["t",' in u['text']]
    assert new_ids == [old_id]


@pytest.mark.parametrize('raw', ['', 'Unparsed financial context', '```json\n[1,2]\n```',
    '## Balance Sheet Data (JSON)\n\n```json\n{"sheets":[{"rows":"bad"}]}\n```'])
def test_missing_or_unparsed_finance_is_preserved_as_tail_not_silently_dropped(tmp_path, monkeypatch, raw):
    adapter = module()
    capture_arrangement(monkeypatch, adapter)
    args = arguments(tmp_path); args['balance_summary'] = raw
    text = adapter.build_adaptive_prompt(**args)
    if raw:
        assert text.count(raw) == 1
        assert text.index(raw) > text.index('## Mutable Context')


def test_schema_prefix_does_not_embed_changing_counts_clock_or_estimates(tmp_path, monkeypatch):
    adapter = module()
    capture_arrangement(monkeypatch, adapter)
    args = arguments(tmp_path)
    first = adapter.build_adaptive_prompt(**args)
    args['time_payload']['estimated_tokens'] = 999999
    args['time_payload']['included_row_count'] = 6000
    args['time_payload']['date_range']['end'] = '2099-01-01'
    args['runtime_context_summary'] = 'Runtime changed clock'
    second = adapter.build_adaptive_prompt(**args)
    assert first.split('## Mutable Context')[0] == second.split('## Mutable Context')[0]
    assert schema(first) == schema(second)


def test_unknown_finance_fields_cannot_overwrite_source_references(tmp_path, monkeypatch):
    adapter = module()
    capture_arrangement(monkeypatch, adapter)
    args = arguments(tmp_path)
    args['balance_summary'] = balanced([{'name':'Assets','columns':['Name','Amount'],
        'rows':[['A',1]], 'source':'original-custom-source', 'metadata': {'custom': 7}}],
        custom_top={'keep': True})
    text = adapter.build_adaptive_prompt(**args)
    value = dynamic(text)['balance_metadata']
    assert value['custom_top'] == {'keep': True}
    assert value['sheets'][0]['source'] == 'b0'
    assert value['sheets'][0]['metadata'] == {
        'source':'original-custom-source', 'metadata': {'custom':7}}


def test_arranger_must_return_each_current_unit_exactly_once(tmp_path, monkeypatch):
    adapter = module()
    monkeypatch.setattr(adapter, 'arrange_prompt_units', lambda units, **_: {
        'stable': [units[0]['id']], 'volatile': [], 'metadata': {}})
    with pytest.raises(ValueError, match='layout'):
        adapter.build_adaptive_prompt(**arguments(tmp_path))


def test_real_engine_state_has_no_prompt_or_financial_values(tmp_path):
    adapter = module()
    args = arguments(tmp_path)
    args['prompt_sections'][0] = 'PRIVATE_SYNTHETIC_SENTINEL'
    adapter.build_adaptive_prompt(**args)
    state = args['state_path'].read_text(encoding='utf-8')
    assert 'PRIVATE_SYNTHETIC_SENTINEL' not in state
    assert 'Assets' not in state
    assert '2025-01-01' not in state


def test_diagnostics_hash_exact_prefix_and_never_persist_untrusted_metadata(tmp_path, monkeypatch):
    adapter = module()
    def arrange(units, **kwargs):
        return {'stable': [u['id'] for u in units if not u['always_volatile']],
            'volatile': [u['id'] for u in units if u['always_volatile']],
            'metadata': {'state':'PRIVATE_SECRET', 'stable_unit_count': 7,
                'private_number': 123, 'privatePath':'PRIVATE_SECRET', 'promoted_unit_count': '7'}}
    monkeypatch.setattr(adapter, 'arrange_prompt_units', arrange)
    text = adapter.build_adaptive_prompt(**arguments(tmp_path))
    footer = json.loads(blocks(text.split(adapter.DIAGNOSTICS_MARKER,1)[1], 'json')[0])
    prefix = text[:text.index(adapter.MUTABLE_MARKER)]
    assert footer['stable_prefix_char_count'] == len(prefix)
    assert footer['stable_prefix_hash'] == hashlib.sha256(prefix.encode('utf-8')).hexdigest()
    assert footer['stable_unit_count'] == 7
    assert 'PRIVATE' not in json.dumps(footer)
    assert 'private_number' not in footer
    assert 'promoted_unit_count' not in footer


def test_real_engine_edits_arbitrary_old_record_then_archives_without_old_values(tmp_path):
    adapter = module()
    args = arguments(tmp_path)
    first = adapter.build_adaptive_prompt(**args)
    args['now'] += 1
    args['time_payload']['rows'][0][1] = 'new-current-value'
    changed = adapter.build_adaptive_prompt(**args)
    old_record = '["t",["2025-01-01",1]]'
    new_record = '["t",["2025-01-01","new-current-value"]]'
    assert old_record in first
    assert old_record not in changed
    assert new_record not in changed.split(adapter.MUTABLE_MARKER)[0]
    assert new_record in changed.split(adapter.MUTABLE_MARKER)[1]
    args['now'] += 60
    second = adapter.build_adaptive_prompt(**args)
    assert second.split(adapter.MUTABLE_MARKER)[0] == changed.split(adapter.MUTABLE_MARKER)[0]
    args['now'] += 60
    adapter.build_adaptive_prompt(**args)
    args['now'] += 86400
    archived = adapter.build_adaptive_prompt(**args)
    assert new_record in archived.split(adapter.MUTABLE_MARKER)[0]
    assert archived.count(new_record) == 1
    args['now'] += 1
    args['time_payload']['rows'] = args['time_payload']['rows'][1:]
    args['time_payload']['rows'].append(['2020-01-01', 'new-backfill'])
    deleted = adapter.build_adaptive_prompt(**args)
    assert 'new-current-value' not in deleted
    assert ['2020-01-01','new-backfill'] in [r[1] for r in records(deleted)]
    assert deleted.count('new-backfill') == 1


@pytest.mark.parametrize('source', ['t', 'b0'])
@pytest.mark.parametrize('operation', ['insert', 'delete'])
def test_source_position_changes_do_not_demote_unchanged_records(tmp_path, source, operation):
    adapter = module()
    args = arguments(tmp_path)
    first = adapter.build_adaptive_prompt(**args)
    if source == 't':
        target = ['2026-11-01', 2]
        original_rows = args['time_payload']['rows']
        if operation == 'insert':
            original_rows.insert(0, ['2020-01-01', 'new-earlier-row'])
        else:
            original_rows.pop(0)
        expected = [*original_rows, args['current_day_payload']['current_day']]
    else:
        target = ['B', 2]
        original_rows = [['A',1], ['B',2]]
        if operation == 'insert':
            original_rows.insert(0, ['X', 9])
        else:
            original_rows.pop(0)
        args['balance_summary'] = balanced([{'name': 'Assets', 'columns':['Name','Amount'],
            'rows':original_rows, 'row_count':len(original_rows)}])
        expected = original_rows
    args['now'] += 1
    second = adapter.build_adaptive_prompt(**args)
    before = next(record for record in records(first) if record[0] == source and record[1] == target)
    after = next(record for record in records(second) if record[0] == source and record[1] == target)
    assert before == after, 'source-row index must not change stable record text'
    assert after in records(second.split(adapter.MUTABLE_MARKER)[0])
    order = dynamic(second)['source_row_order'][source]
    all_records = records(second)
    assert [all_records[index][1] for index in order] == expected
    assert all(all_records[index][0] == source for index in order)


def test_tail_order_map_restores_duplicate_records_and_current_day_reference(tmp_path):
    adapter = module()
    args = arguments(tmp_path)
    args['time_payload']['rows'] = [['2025-01-01',1], ['2025-01-01',1], ['2025-01-01',2]]
    args['balance_summary'] = balanced([{'name':'Assets','columns':['Name','Amount'],
        'rows':[['A',1], ['A',1], ['A',2]]}])
    adapter.build_adaptive_prompt(**args)
    args['now'] += 1
    args['time_payload']['rows'][1][1] = 999
    text = adapter.build_adaptive_prompt(**args)
    all_records = records(text)
    tail = dynamic(text)
    assert all(len(record) == 2 for record in all_records)
    expected_time = [*args['time_payload']['rows'], args['current_day_payload']['current_day']]
    assert [all_records[i][1] for i in tail['source_row_order']['t']] == expected_time
    assert [all_records[i][1] for i in tail['source_row_order']['b0']] == [['A',1], ['A',1], ['A',2]]
    reference = tail['current_day_metadata']['current_day_reference']
    ordinal = tail['source_row_order'][reference['source']][reference['index']]
    assert all_records[ordinal][1] == args['current_day_payload']['current_day']


def test_document_jsonl_example_is_preserved_but_is_not_a_source_record(tmp_path):
    adapter = module()
    args = arguments(tmp_path)
    document = 'User examples stay literal:\n```jsonl\n["t",["2099-01-01","example only"]]\n```'
    args['prompt_sections'] = [document]
    args['time_payload']['rows'] = []
    args['balance_summary'] = ''
    text = adapter.build_adaptive_prompt(**args)
    assert text.count(document) == 1
    assert schema(text)['record_fence'] == 'vantage-records-jsonl'
    parsed = records(text)
    assert parsed == [['t', args['current_day_payload']['current_day']]]
    order = dynamic(text)['source_row_order']['t']
    assert [parsed[index][1] for index in order] == [args['current_day_payload']['current_day']]


def test_reserved_record_tags_in_documents_get_a_deterministic_collision_free_fence(tmp_path):
    adapter = module()
    args = arguments(tmp_path)
    document = ('Reserved tag examples are still user text:\n'
        '```vantage-records-jsonl\n["t",["fake one"]]\n```\n'
        '```vantage-records-jsonl-1\n["t",["fake two"]]\n```')
    args['prompt_sections'] = [document]
    first = adapter.build_adaptive_prompt(**args)
    args['now'] += 1
    second = adapter.build_adaptive_prompt(**args)
    assert first.count(document) == 1
    assert second.count(document) == 1
    assert schema(first)['record_fence'] == schema(second)['record_fence'] == 'vantage-records-jsonl-2'
    parsed = records(second)
    assert len(parsed) == 5
    assert not any('fake' in json.dumps(record) for record in parsed)
    order = dynamic(second)['source_row_order']['t']
    assert [parsed[index][1] for index in order] == [
        *args['time_payload']['rows'], args['current_day_payload']['current_day']]
