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

test('displayCopy includes Expense Sheet JSON copy labels in both languages', () => {
  for (const key of [
    'expense.copy_json',
    'expense.copy_json_copied',
    'expense.copy_json_failed',
    'expense.copy_json_unavailable',
  ]) {
    assert.ok(DISPLAY_COPY['en-US'][key], `en-US missing ${key}`);
    assert.ok(DISPLAY_COPY['zh-CN'][key], `zh-CN missing ${key}`);
  }
});
