"""Fingerprint-only, persistent ordering for reusable prompt prefixes.

This is layout metadata, never a cache of old prompt values. Callers always
render the returned IDs using their complete current input. Existing stable
order stays fixed; edited/new units move to the tail and can later be archived
in a bounded-frequency batch after repeated, time-separated stable samples.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import time

from src.core.context import atomic_write_json, context_transaction

SCHEMA_VERSION = 1
QUIET_SECONDS = 24 * 3600
MIN_STABLE_OBSERVATIONS = 3
MAX_UNITS = 10000
MAX_STATE_BYTES = 8 * 1024 * 1024
MAX_COUNTER = 10**9
HASH_PATTERN = re.compile(r'^[0-9a-f]{64}$')


def _hash(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def _timestamp(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError('invalid-observation-time')
    if not math.isfinite(value) or not 0 <= value <= 10**12:
        raise ValueError('invalid-observation-time')
    return float(value)


def _counter(value):
    if type(value) is not int or not 0 <= value <= MAX_COUNTER:
        raise ValueError('invalid-state-counter')
    return value


def _inputs(units):
    if not isinstance(units, list) or len(units) > MAX_UNITS:
        raise ValueError('invalid-prompt-units')
    result = {}
    for item in units:
        if not isinstance(item, dict):
            raise ValueError('invalid-prompt-unit')
        identifier, text = item.get('id'), item.get('text')
        if not isinstance(identifier, str) or not identifier or len(identifier) > 512 or '\0' in identifier:
            raise ValueError('invalid-prompt-unit-id')
        if not isinstance(text, str):
            raise ValueError('invalid-prompt-unit-text')
        key = _hash(identifier)
        if key in result:
            raise ValueError('duplicate-prompt-unit-id')
        initial = item.get('initial_stable', True)
        volatile = item.get('always_volatile', False)
        weight = item.get('weight', len(text))
        if type(initial) is not bool or type(volatile) is not bool:
            raise ValueError('invalid-prompt-unit-policy')
        if type(weight) is not int or not 0 <= weight <= 10**9:
            raise ValueError('invalid-prompt-unit-weight')
        result[key] = dict(id=identifier, hash=_hash(text), initial_stable=initial,
                           always_volatile=volatile, weight=weight)
    return result


def _not_link(info):
    return not stat.S_ISLNK(info.st_mode) and not getattr(info, 'st_file_attributes', 0) & 0x400


def _safe_path(path, *, create=False):
    """Check every ancestor before locking/reading and again before publication."""
    for directory in reversed((path.parent, *path.parent.parents)):
        try:
            info = directory.lstat()
        except FileNotFoundError:
            if not create:
                raise OSError('missing-layout-parent') from None
            try:
                directory.mkdir()
            except FileExistsError:
                pass
            info = directory.lstat()
        if not _not_link(info) or not stat.S_ISDIR(info.st_mode):
            raise OSError('unsafe-layout-parent')
    for filename in (path, path.parent / '.context.lock'):
        try:
            info = filename.lstat()
        except FileNotFoundError:
            continue
        if not _not_link(info) or not stat.S_ISREG(info.st_mode) or info.st_nlink > 1:
            raise OSError('unsafe-layout-file')


def _state(value):
    if not isinstance(value, dict) or value.get('schema_version') != SCHEMA_VERSION:
        raise ValueError('invalid-layout-state')
    units = value.get('units')
    stable, volatile = value.get('stable'), value.get('volatile')
    if not isinstance(units, dict) or len(units) > MAX_UNITS:
        raise ValueError('invalid-layout-state')
    if not isinstance(stable, list) or not isinstance(volatile, list):
        raise ValueError('invalid-layout-order')
    order = stable + volatile
    if len(order) > MAX_UNITS or any(not isinstance(key, str) or not HASH_PATTERN.fullmatch(key) for key in order):
        raise ValueError('invalid-layout-order')
    if len(set(order)) != len(order) or set(order) != set(units):
        raise ValueError('inconsistent-layout-order')
    clean = {}
    updated_at = _timestamp(value.get('updated_at'))
    last_archive_at = _timestamp(value.get('last_archive_at'))
    if last_archive_at > updated_at:
        raise ValueError('invalid-layout-clock')
    for key, record in units.items():
        if not isinstance(record, dict) or not isinstance(record.get('hash'), str) or not HASH_PATTERN.fullmatch(record['hash']):
            raise ValueError('invalid-layout-fingerprint')
        last_seen = _timestamp(record.get('last_seen'))
        unchanged_since = _timestamp(record.get('unchanged_since'))
        if unchanged_since > last_seen or last_seen > updated_at:
            raise ValueError('invalid-layout-clock')
        clean[key] = dict(hash=record['hash'], weight=_counter(record.get('weight')),
            observations=_counter(record.get('observations')), changes=_counter(record.get('changes')),
            unchanged_observations=_counter(record.get('unchanged_observations')),
            last_seen=last_seen, unchanged_since=unchanged_since)
    return dict(schema_version=SCHEMA_VERSION, units=clean, stable=list(stable),
        volatile=list(volatile), updated_at=updated_at, last_archive_at=last_archive_at)


def _new_record(item, now):
    return dict(hash=item['hash'], weight=item['weight'], observations=1, changes=0,
        unchanged_observations=1, unchanged_since=now, last_seen=now)


def _advance(current, prior, now):
    if prior is None:
        stable = [key for key, item in current.items() if item['initial_stable'] and not item['always_volatile']]
        volatile = [key for key in current if key not in stable]
        records = {key: _new_record(item, now) for key, item in current.items()}
        return dict(schema_version=SCHEMA_VERSION, stable=stable, volatile=volatile,
            units=records, updated_at=now, last_archive_at=now), dict(
            new_unit_count=len(current), deleted_unit_count=0,
            demoted_unit_count=0, promoted_unit_count=0)

    # Backward wall-clock movement never accumulates false quiet time or samples.
    now = max(now, prior['updated_at'])
    previous = prior['units']
    deleted = len(set(previous) - set(current))
    stable = [key for key in prior['stable'] if key in current]
    stable_keys = set(stable)
    volatile = [key for key in prior['volatile'] if key in current]
    records, demoted, new = {}, [], []
    for key, item in current.items():
        old = previous.get(key)
        if old is None:
            records[key] = _new_record(item, now)
            new.append(key)
            continue
        record = dict(old)
        fresh_sample = now > old['last_seen']
        changed = item['hash'] != old['hash']
        record.update(hash=item['hash'], weight=item['weight'], last_seen=now)
        if fresh_sample:
            record['observations'] = min(MAX_COUNTER, old['observations'] + 1)
        if changed:
            record.update(changes=min(MAX_COUNTER, old['changes'] + 1),
                unchanged_observations=1, unchanged_since=now)
        elif fresh_sample:
            record['unchanged_observations'] = min(MAX_COUNTER, old['unchanged_observations'] + 1)
        if key in stable_keys and (changed or item['always_volatile']):
            demoted.append(key)
        records[key] = record
    # Preserve both existing partitions; edited stable units and new units append.
    demoted_keys = set(demoted)
    demoted = [key for key in stable if key in demoted_keys]
    stable = [key for key in stable if key not in demoted_keys]
    volatile.extend(demoted + new)
    promoted = []
    if now - prior['last_archive_at'] >= QUIET_SECONDS:
        promoted = [key for key in volatile if not current[key]['always_volatile']
            and records[key]['unchanged_observations'] >= MIN_STABLE_OBSERVATIONS
            and now - records[key]['unchanged_since'] >= QUIET_SECONDS]
        # Reorder only this archive batch, never the existing stable prefix.
        promoted.sort(key=lambda key: -(records[key]['weight']
            * records[key]['unchanged_observations'] / (records[key]['changes'] + 1)))
        stable.extend(promoted)
        volatile = [key for key in volatile if key not in promoted]
    return dict(schema_version=SCHEMA_VERSION, stable=stable, volatile=volatile,
        units=records, updated_at=now,
        last_archive_at=now if promoted else prior['last_archive_at']), dict(
        new_unit_count=len(new), deleted_unit_count=deleted,
        demoted_unit_count=len(demoted), promoted_unit_count=len(promoted))


def _result(value, current, status, counts):
    return dict(stable=[current[key]['id'] for key in value['stable']],
        volatile=[current[key]['id'] for key in value['volatile']], metadata=dict(
        schema_version=SCHEMA_VERSION, state=status,
        stable_unit_count=len(value['stable']), volatile_unit_count=len(value['volatile']),
        **counts))


def arrange_prompt_units(units, *, state_path, now=None):
    """Return a complete partition of current IDs, backed by private JSON state.

    Storage failure returns deterministic input-based ordering with an explicit
    ``unavailable`` status. Invalid/duplicate caller units raise ValueError.
    No old value can be returned: prompt text is never persisted here.
    """
    current = _inputs(units)
    stamp = _timestamp(time.time() if now is None else now)
    fallback, fallback_counts = _advance(current, None, stamp)
    try:
        path = Path(os.path.abspath(os.fspath(state_path)))
        _safe_path(path, create=True)
        with context_transaction(path):
            _safe_path(path)
            prior, status = None, 'initialized'
            try:
                if path.stat().st_size > MAX_STATE_BYTES:
                    raise ValueError('oversized-layout-state')
                prior = _state(json.loads(path.read_text(encoding='utf-8')))
                status = 'ready'
            except FileNotFoundError:
                pass
            except (ValueError, TypeError, KeyError):
                status = 'reset'
            value, counts = _advance(current, prior, stamp)
            encoded = json.dumps(value, separators=(',', ':')).encode('utf-8')
            if len(encoded) > MAX_STATE_BYTES:
                raise OSError('layout-state-too-large')
            _safe_path(path)
            atomic_write_json(path, value)
            return _result(value, current, status, counts)
    except (OSError, ValueError, TypeError, RuntimeError):
        return _result(fallback, current, 'unavailable', fallback_counts)
