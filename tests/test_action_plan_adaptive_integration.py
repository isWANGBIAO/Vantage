"""Action Plan alone opts into adaptive layout; complete inputs remain intact."""
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

import pandas as pd
import pytest

from src.scripts import run_prompt
from src.utils.data_loader import DataLoader


def construct(tmp_path, *, budget=None, adaptive=True):
    prompt = tmp_path / 'Prompt_Personal_Info.md'
    prompt.write_text('Synthetic personal instructions', encoding='utf-8')
    excel = tmp_path / 'Time.xlsx'
    excel.write_bytes(b'placeholder')
    today = datetime.now().date()
    frame = pd.DataFrame({'日期': [pd.Timestamp(today-timedelta(days=90)), pd.Timestamp(today)],
                          'note': ['COMPLETE_OLD_ROW', 'COMPLETE_CURRENT_ROW']})
    extra = {'cache_layout_state_path': tmp_path / 'layout/state.json'} if adaptive else {}
    with patch.object(DataLoader, 'load_excel_data', return_value=frame), patch.object(
        DataLoader, 'resolve_data_path', side_effect=lambda name, **_: tmp_path / name
    ), patch.object(DataLoader, 'get_balance_sheet_data_summary', return_value=''), patch.object(
        DataLoader, 'get_future_planned_rows', return_value='Future: synthetic record'
    ), patch.object(DataLoader, '_build_calendar_info', return_value='Synthetic calendar'):
        return DataLoader.construct_prompt(prompt, excel, start_date='earliest',
            prompt_token_budget=budget, **extra)


def test_structured_action_plan_can_enable_complete_adaptive_layout(tmp_path):
    text = construct(tmp_path)
    assert text.startswith('# Vantage Adaptive Context v1')
    assert 'COMPLETE_OLD_ROW' in text and 'COMPLETE_CURRENT_ROW' in text
    assert 'Synthetic personal instructions' in text and 'Future: synthetic record' in text
    assert (tmp_path / 'layout/state.json').is_file()
    metadata = DataLoader.build_prompt_cache_metadata(text)
    assert metadata['cache_layout'] == 'adaptive_stable_prefix_v1'
    assert len(metadata['adaptive_stable_prefix_hash']) == 64
    assert metadata['adaptive_stable_prefix_char_count'] > 0


def test_other_prompt_consumers_keep_explicit_legacy_format(tmp_path):
    text = construct(tmp_path, adaptive=False)
    assert text.startswith('## Time Series Data (JSON)')
    assert not (tmp_path / 'layout/state.json').exists()


def test_adaptive_output_still_rejects_an_incomplete_budget_instead_of_truncating(tmp_path):
    with pytest.raises(ValueError, match='budget'):
        construct(tmp_path, budget=30)


def test_adaptive_budget_cannot_hide_an_old_long_row_that_latest_values_do_not_repeat(tmp_path):
    prompt = tmp_path / 'Prompt_Personal_Info.md'
    prompt.write_text('Synthetic instructions', encoding='utf-8')
    source = tmp_path / 'Time.xlsx'
    source.write_bytes(b'placeholder')
    today = datetime.now().date()
    frame = pd.DataFrame({'日期': [pd.Timestamp(today-timedelta(days=2)),
        pd.Timestamp(today-timedelta(days=1)), pd.Timestamp(today)],
        'note': ['OLD_REQUIRED_ROW_' + 'X'*20000, 'short yesterday', 'short today']})
    with patch.object(DataLoader, 'load_excel_data', return_value=frame), patch.object(
        DataLoader, 'resolve_data_path', side_effect=lambda name, **_: tmp_path / name
    ), patch.object(DataLoader, 'get_balance_sheet_data_summary', return_value=''), patch.object(
        DataLoader, 'get_future_planned_rows', return_value='Future: none'
    ), patch.object(DataLoader, '_build_calendar_info', return_value='Synthetic'):
        with pytest.raises(ValueError, match='budget'):
            DataLoader.construct_prompt(prompt, source, start_date='earliest', prompt_token_budget=1500,
                cache_layout_state_path=tmp_path/'layout/state.json')


def test_normal_plan_uses_private_state_and_reuses_first_round_verbatim(tmp_path):
    history = tmp_path / 'history'
    history.mkdir()
    (tmp_path / '2_今日行动计划.md').write_text('Daily requirements {current_time}', encoding='utf-8')
    client = Mock()
    client.get_prompt_budget.return_value = {'input_budget_tokens': 5000, 'output_reserve_tokens': 50}
    sent = []
    def reply(messages, **kwargs):
        sent.append([dict(m) for m in messages])
        return {'content': 'Long-term complete answer' if len(sent)==1 else 'Daily complete answer',
                'usage': {}, 'duration': 0}
    client.chat.side_effect = reply
    with patch.object(run_prompt.Config, 'load_env'), patch.object(
        run_prompt.Config, 'get_history_dir', return_value=history
    ), patch.object(run_prompt, 'LLMClient', return_value=client), patch.object(
        DataLoader, 'resolve_data_path', side_effect=lambda name, **_: tmp_path / name
    ), patch.object(DataLoader, 'construct_prompt', return_value='Complete initial input') as build, patch.object(
        DataLoader, 'get_system_prompt_content', return_value='System'
    ), patch.object(DataLoader, 'get_past_seven_days_rows', return_value='Recent'), patch.object(
        DataLoader, 'get_today_data_row', return_value='Today'
    ), patch.object(DataLoader, 'get_yesterday_data_row', return_value='Yesterday'), patch.object(
        DataLoader, 'get_future_planned_rows', return_value='Future'
    ), patch.object(sys, 'argv', ['run_prompt.py']):
        run_prompt.main()
    state = Path(build.call_args.kwargs['cache_layout_state_path'])
    assert state.is_relative_to(history)
    assert len(sent)==2 and sent[1][:len(sent[0])] == sent[0]
    assert sent[1][2] == {'role': 'assistant', 'content': 'Long-term complete answer'}
    assert len(list(history.glob('action_plan_*.json'))) == 1


def test_adaptive_metadata_ignores_untrusted_footer_fields():
    text = '# Vantage Adaptive Context v1\n\n## Cache Layout Diagnostics\n\n```json\n' + json.dumps({
        'stable_prefix_hash': 'a'*64, 'stable_prefix_char_count': 123,
        'stable_unit_count': 2, 'volatile_unit_count': 1, 'secret': 'PRIVATE_SECRET'}) + '\n```'
    result = DataLoader.build_prompt_cache_metadata(text)
    assert result['cache_layout'] == 'adaptive_stable_prefix_v1'
    assert result['adaptive_stable_unit_count'] == 2
    assert 'PRIVATE_SECRET' not in json.dumps(result)
