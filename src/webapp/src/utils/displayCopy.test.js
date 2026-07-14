import test from 'node:test';
import assert from 'node:assert/strict';
import { readdirSync, readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { DISPLAY_COPY } from './displayCopy.js';

const UI_SOURCE_ROOT = fileURLToPath(new URL('../', import.meta.url));
const MANUAL_KEYS = [
  'app.language.follow_system',
  'app.language.zh_cn',
  'app.language.en_us',
  'app.theme.switch_to_light',
  'app.theme.switch_to_dark',
  'plots.chart.support',
  'face_history.trend.day',
  'face_history.trend.week',
  'face_history.trend.month',
  'face_history.trend.all',
];

function collectUiFiles(dirPath, results = []) {
  for (const entry of readdirSync(dirPath, { withFileTypes: true })) {
    const entryPath = path.join(dirPath, entry.name);
    if (entry.isDirectory()) {
      collectUiFiles(entryPath, results);
      continue;
    }

    if (!/\.(jsx|js|cjs)$/.test(entry.name) || /\.test\./.test(entry.name)) {
      continue;
    }

    results.push(entryPath);
  }

  return results;
}

function collectReferencedKeys() {
  const referenced = new Set(MANUAL_KEYS);
  const patterns = [
    /\bt\('([^']+)'/g,
    /labelKey:\s*'([^']+)'/g,
  ];

  for (const filePath of collectUiFiles(UI_SOURCE_ROOT)) {
    const source = readFileSync(filePath, 'utf8');
    for (const pattern of patterns) {
      let match;
      while ((match = pattern.exec(source))) {
        referenced.add(match[1]);
      }
    }
  }

  return [...referenced].sort();
}

test('displayCopy defines translations for every referenced UI key', () => {
  const referencedKeys = collectReferencedKeys();

  for (const language of ['en-US', 'zh-CN']) {
    const missing = referencedKeys.filter((key) => !(key in DISPLAY_COPY[language]));
    assert.deepEqual(missing, [], `${language} is missing keys: ${missing.join(', ')}`);
  }
});

test('displayCopy keeps en-US and zh-CN key sets aligned', () => {
  const enKeys = Object.keys(DISPLAY_COPY['en-US']).sort();
  const zhKeys = Object.keys(DISPLAY_COPY['zh-CN']).sort();

  assert.deepEqual(zhKeys, enKeys);
});

test('camera detection copy describes camera-facing face detection', () => {
  assert.equal(DISPLAY_COPY['en-US']['camera_feed.enable_detection'], 'Enable camera-facing face detection');
  assert.equal(DISPLAY_COPY['zh-CN']['camera_feed.enable_detection'], '开启面向摄像头的人脸检测');
  assert.equal(DISPLAY_COPY['en-US']['camera_feed.disable_detection'], 'Disable camera-facing face detection');
  assert.equal(DISPLAY_COPY['zh-CN']['camera_feed.disable_detection'], '关闭面向摄像头的人脸检测');
});

test('displayCopy includes Expense Sheet JSON copy labels in both languages', () => {
  for (const key of [
    'expense.copy_json',
    'expense.copy_json_copied',
    'expense.copy_json_failed',
    'expense.copy_json_unavailable',
    'expense.purchase.title',
    'expense.purchase.regenerate',
    'expense.purchase.copy_json',
    'expense.purchase.dismiss',
    'expense.purchase.dismissed_count',
    'expense.purchase.show_dismissed',
    'expense.purchase.hide_dismissed',
    'expense.purchase.restore_dismissed',
    'expense.purchase.recommendation_count',
    'expense.purchase.clear_dismissed',
    'expense.purchase.clear_dismissed_title',
    'expense.purchase.mix_summary',
    'expense.purchase.mode_contextual',
    'expense.purchase.mode_random',
  ]) {
    assert.ok(DISPLAY_COPY['en-US'][key], `en-US missing ${key}`);
    assert.ok(DISPLAY_COPY['zh-CN'][key], `zh-CN missing ${key}`);
  }
});

test('displayCopy includes provider mode and build info labels in both languages', () => {
  for (const key of [
    'settings.provider.mode.inherit_ai',
    'settings.provider.mode.custom',
    'settings.provider.inherited_from_ai',
    'settings.provider.inherited_key_available',
    'settings.about.build_date',
    'settings.about.build_commit',
  ]) {
    assert.ok(DISPLAY_COPY['en-US'][key], `${key} should exist in English copy`);
    assert.ok(DISPLAY_COPY['zh-CN'][key], `${key} should exist in Chinese copy`);
  }
});

test('displayCopy includes partial storage scan labels in both languages', () => {
  assert.ok(DISPLAY_COPY['en-US']['dashboard.stat.storage_partial']);
  assert.ok(DISPLAY_COPY['zh-CN']['dashboard.stat.storage_partial']);
});

test('displayCopy distinguishes focus detection states in both languages', () => {
  const expected = {
    'dashboard.stat.focus_duration': ['{value} min', '{value} 分钟'],
    'dashboard.stat.focus_present': ['Focus detected · limit: {value} min', '持续专注中 · 阈值：{value} 分钟'],
    'dashboard.stat.focus_absent': ['No person detected · grace period active', '暂未检测到人 · 宽限中'],
    'dashboard.stat.focus_absent_confirmed': ['Away confirmed · timer reset', '已确认离座 · 计时已重置'],
    'dashboard.stat.focus_unavailable': ['Measurement unavailable · timer preserved', '测量暂不可用 · 计时保留'],
  };

  for (const [key, [english, chinese]] of Object.entries(expected)) {
    assert.equal(DISPLAY_COPY['en-US'][key], english);
    assert.equal(DISPLAY_COPY['zh-CN'][key], chinese);
  }
});

test('displayCopy includes Action Plan context limit warning labels in both languages', () => {
  for (const key of [
    'action_plan.context_limit.title',
    'action_plan.context_limit.message',
    'action_plan.context_limit.estimated_message',
  ]) {
    assert.ok(DISPLAY_COPY['en-US'][key], `${key} should exist in English copy`);
    assert.ok(DISPLAY_COPY['zh-CN'][key], `${key} should exist in Chinese copy`);
  }
});
