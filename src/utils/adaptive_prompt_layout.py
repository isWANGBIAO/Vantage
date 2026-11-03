"""Lossless, compact prompt serialization around a fingerprint-only layout.

The state engine chooses an order, never old values. This adapter always renders
the caller's current complete records. Statistics and changing runtime context
are deliberately outside the reusable schema/data prefix.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json
import re

from src.utils.adaptive_prompt_cache import arrange_prompt_units

PROTOCOL_HEADER = '# Vantage Adaptive Context v1'
STABLE_MARKER = '## Stable Context'
MUTABLE_MARKER = '## Mutable Context'
DIAGNOSTICS_MARKER = '## Cache Layout Diagnostics'
BALANCE_MARKER = '## Balance Sheet Data (JSON)\n\n```json\n'
DIAGNOSTIC_COUNTS = frozenset({'schema_version', 'stable_unit_count', 'volatile_unit_count',
    'new_unit_count', 'deleted_unit_count', 'demoted_unit_count', 'promoted_unit_count'})
DIAGNOSTIC_STATES = frozenset({'initialized', 'ready', 'reset', 'unavailable'})


def _json(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def _identity(*parts):
    return hashlib.sha256(_json(parts).encode('utf-8')).hexdigest()


def _json_block(title, value):
    return f'## {title}\n\n```json\n{_json(value)}\n```'


def _balance_payload(text):
    """Only consume the exact existing protocol; unknown text is kept intact."""
    if not isinstance(text, str) or not text.startswith(BALANCE_MARKER):
        return None
    body = text[len(BALANCE_MARKER):]
    if not body.endswith('\n```'):
        return None
    try:
        payload = json.loads(body[:-len('\n```')])
    except (ValueError, TypeError):
        return None
    if not isinstance(payload, dict) or not isinstance(payload.get('sheets'), list):
        return None
    for sheet in payload['sheets']:
        if not isinstance(sheet, dict) or not isinstance(sheet.get('columns'), list) or not isinstance(sheet.get('rows'), list):
            return None
        if not all(isinstance(row, list) for row in sheet['rows']):
            return None
    return payload


def _finance_anchor(columns, row, index):
    id_names = {'id', 'uuid', '编号', '记录编号', '记录id', '流水号'}
    for i, column in enumerate(columns):
        name = re.sub(r'\s+', '', str(column)).casefold()
        if name in id_names and i < len(row) and row[i] not in (None, ''):
            return ('id', i, row[i])
    for i, value in enumerate(row):
        # A descriptive name/date is an anchor, not the complete mutable row.
        if isinstance(value, str) and value.strip() and not re.fullmatch(r'[-+]?\d+(?:\.\d+)?', value.strip()):
            return ('text', i, value)
    return ('index', index)


def _render(entries, by_id):
    chunks, rows = [], []

    def flush():
        if rows:
            chunks.append('```jsonl\n' + '\n'.join(rows) + '\n```')
            rows.clear()

    for identity in entries:
        unit = by_id[identity]
        if unit['kind'] == 'record':
            rows.append(unit['text'])
        else:
            flush()
            chunks.append(unit['text'])
    flush()
    return '\n\n'.join(chunks)


def build_adaptive_prompt(*, prompt_sections, time_payload, balance_summary,
    future_planned_rows, current_day_payload, runtime_context_summary,
    state_path, now=None):
    """Return current full input in persistent stable/mutable order.

    JSONL records are ``[source_code, row_values, original_source_row_index]``.
    The source schema carries columns once. The original index preserves source
    ordering/duplicates even when cache-oriented presentation changes order.
    """
    if not isinstance(time_payload, dict) or not isinstance(current_day_payload, dict):
        raise ValueError('invalid-adaptive-prompt-input')
    if not isinstance(time_payload.get('columns'), list) or not isinstance(time_payload.get('rows'), list):
        raise ValueError('invalid-adaptive-time-data')
    if not all(isinstance(row, list) for row in time_payload['rows']):
        raise ValueError('invalid-adaptive-time-row')
    if not isinstance(prompt_sections, (list, tuple)) or not all(isinstance(s, str) for s in prompt_sections):
        raise ValueError('invalid-adaptive-documents')
    if not all(isinstance(s, str) for s in (balance_summary, future_planned_rows, runtime_context_summary)):
        raise ValueError('invalid-adaptive-context-text')

    units = []
    def add(key, text, *, kind='text', stable=True, always=False):
        identity = _identity(*key)
        units.append(dict(id=identity, text=text, kind=kind,
            initial_stable=stable, always_volatile=always, weight=len(text)))
        return identity

    document_occurrences = Counter()
    for index, document in enumerate(prompt_sections):
        if not document:
            continue
        heading = document.split('\n', 1)[0] if document.startswith('#') else f'document-{index}'
        anchor = 'personal' if index == 0 else heading
        occurrence = document_occurrences[anchor]
        document_occurrences[anchor] += 1
        add(('document', anchor, occurrence), document)

    sources = {'t': {'kind': 'time', 'columns': time_payload['columns']}}
    if 'column_meta' in time_payload:
        sources['t']['column_meta'] = time_payload['column_meta']
    time_rows = list(time_payload['rows'])
    current = current_day_payload.get('current_day')
    if current is not None and not isinstance(current, list):
        raise ValueError('invalid-adaptive-current-day')
    current_index = len(time_rows) if current is not None else None
    if current is not None:
        time_rows.append(current)
    time_occurrences = Counter()
    for index, row in enumerate(time_rows):
        anchor = _json(row[0] if row else None)
        occurrence = time_occurrences[anchor]
        time_occurrences[anchor] += 1
        add(('time', anchor, occurrence), _json(['t', row, index]), kind='record', stable=index != current_index)

    payload = _balance_payload(balance_summary)
    balance_metadata = None
    if payload is not None:
        balance_metadata = {key: value for key,value in payload.items() if key != 'sheets'}
        balance_metadata['sheets'] = []
        sheet_occurrences = Counter()
        for sheet_index, sheet in enumerate(payload['sheets']):
            name = sheet.get('name')
            anchor = _json(name) if name is not None else f'unnamed-{sheet_index}'
            occurrence = sheet_occurrences[anchor]
            sheet_occurrences[anchor] += 1
            sheet_identity = _identity('sheet', anchor, occurrence)
            # The schema establishes these short source aliases once. Persistent
            # unit IDs still use the opaque sheet identity, not a mutable index.
            source = f'b{sheet_index}'
            if source in sources:
                raise ValueError('adaptive-source-identity-collision')
            sources[source] = {'kind': 'balance', 'columns': sheet['columns']}
            if 'name' in sheet:
                sources[source]['name'] = sheet['name']
            metadata = {key: value for key,value in sheet.items() if key not in ('name','columns','rows')}
            balance_metadata['sheets'].append({'source': source, 'metadata': metadata})
            row_occurrences = Counter()
            for index, row in enumerate(sheet['rows']):
                row_anchor = _json(_finance_anchor(sheet['columns'], row, index))
                row_occurrence = row_occurrences[row_anchor]
                row_occurrences[row_anchor] += 1
                add(('balance', sheet_identity, row_anchor, row_occurrence),
                    _json([source, row, index]), kind='record')

    # No statistics, source row counts or clock values are inside this schema.
    schema = {'version': 1, 'record_format': ['source', 'values', 'source_row_index'],
        'sources': dict(sorted(sources.items()))}
    time_metadata = {key: value for key,value in time_payload.items() if key not in ('columns','rows','column_meta')}
    current_metadata = {key: value for key,value in current_day_payload.items() if key != 'current_day'}
    current_metadata['current_day_reference'] = {'source': 't', 'index': current_index} if current_index is not None else None
    dynamic = {'time_metadata': time_metadata, 'current_day_metadata': current_metadata,
        'balance_metadata': balance_metadata}
    add(('tail','dynamic'), _json_block('Dynamic Context (JSON)', dynamic), stable=False, always=True)
    if balance_summary and payload is None:
        add(('tail','unparsed-balance'), balance_summary, stable=False, always=True)
    if future_planned_rows:
        add(('tail','future'), future_planned_rows, stable=False, always=True)
    if runtime_context_summary:
        add(('tail','runtime'), runtime_context_summary, stable=False, always=True)

    by_id = {unit['id']: unit for unit in units}
    if len(by_id) != len(units):
        raise ValueError('duplicate-adaptive-unit-identity')
    arranged = arrange_prompt_units(units, state_path=state_path, now=now)
    stable, mutable = arranged.get('stable', []), arranged.get('volatile', [])
    ordered = stable + mutable
    if len(ordered) != len(units) or len(set(ordered)) != len(units) or set(ordered) != set(by_id):
        raise ValueError('incomplete-adaptive-layout')
    if any(by_id[identity]['always_volatile'] for identity in stable):
        raise ValueError('unsafe-adaptive-layout')
    # Footer units are forced to remain after every editable document/record,
    # regardless of when a stable record was demoted by the state engine.
    mutable_records = [key for key in mutable if not by_id[key]['always_volatile']]
    footer = [unit['id'] for unit in units if unit['always_volatile']]
    preamble = (PROTOCOL_HEADER + '\n\n'
        'Records are complete current values, not patches. JSONL entries use the '
        'schema below. Their source_row_index preserves original table order; '
        'use record dates rather than presentation order for chronology. '
        'The current-day reference points to the corresponding Time source row.\n\n'
        + _json_block('Context Schema (JSON)', schema))
    prefix = preamble + '\n\n' + STABLE_MARKER + '\n\n' + _render(stable, by_id) + '\n\n'
    mutable_text = _render(mutable_records + footer, by_id)
    metadata = arranged.get('metadata') or {}
    diagnostics = {key: value for key,value in metadata.items()
        if key in DIAGNOSTIC_COUNTS and type(value) is int and value >= 0}
    if metadata.get('state') in DIAGNOSTIC_STATES:
        diagnostics['state'] = metadata['state']
    diagnostics.update(stable_prefix_hash=hashlib.sha256(prefix.encode('utf-8')).hexdigest(),
        stable_prefix_char_count=len(prefix))
    return (prefix + MUTABLE_MARKER + '\n\n' + mutable_text + '\n\n'
        + DIAGNOSTICS_MARKER + '\n\n```json\n' + _json(diagnostics) + '\n```')
