import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const read = (path) => readFileSync(new URL(path, import.meta.url), 'utf8');

const appSource = read('./App.jsx');
const appCss = read('./App.css');
const indexCss = read('./index.css');
const chatSource = read('./components/ChatInterface.jsx');
const dashboardSource = read('./components/Dashboard.jsx');
const cameraFeedSource = read('./components/CameraFeed.jsx');
const systemLogsSource = read('./components/SystemLogs.jsx');
const usagePanelSource = read('./components/UsagePanel.jsx');
const usagePanelCss = read('./components/UsagePanel.css');
const settingsSource = read('./components/Settings.jsx');
const projectProgressCss = read('./components/ProjectProgress.css');
const plotsSource = read('./components/Plots.jsx');
const plotChartCardSource = read('./components/PlotChartCard.jsx');
const expenseSource = read('./components/ExpenseSheet.jsx');
const faceHistorySource = read('./components/FaceHistory.jsx');
const displayCopySource = read('./utils/displayCopy.js');

test('global shell keeps navigation discoverable and reduces accidental motion', () => {
  assert.match(appCss, /\.app-nav\s*\{[\s\S]*scrollbar-width:\s*thin/s);
  assert.match(appCss, /\.app-nav::-webkit-scrollbar\s*\{[\s\S]*height:\s*6px/s);
  assert.ok(appCss.includes('aria-current'));
  assert.ok(appSource.includes('href={`#${item.key.replaceAll'));
  assert.ok(indexCss.includes('@media (prefers-reduced-motion: reduce)'));
  assert.equal(indexCss.includes('button:hover:not(:disabled) {\n  transform: translateY(-2px);'), false);
  assert.equal(indexCss.includes('.glass-panel:hover {'), false);
  assert.equal(indexCss.includes('overflow-x: hidden;'), false);
});

test('markdown and long text remain readable instead of breaking every character', () => {
  assert.match(indexCss, /\.markdown-body table\s*\{[\s\S]*display:\s*block[\s\S]*overflow-x:\s*auto/s);
  assert.match(indexCss, /\.markdown-body strong\s*\{[\s\S]*color:\s*inherit/s);
  assert.equal(indexCss.includes('word-break: break-all;'), false);
  assert.equal(appCss.includes('word-break: break-all;'), false);
});

test('chat avoids hardcoded English controls and never renders undefined stats', () => {
  assert.ok(chatSource.includes("t('chat.role.user')"));
  assert.ok(chatSource.includes("t('chat.role.assistant')"));
  assert.ok(chatSource.includes("t('chat.record.short_start')"));
  assert.ok(chatSource.includes("t('chat.record.short_stop')"));
  assert.ok(chatSource.includes("t('chat.send_short')"));
  assert.ok(chatSource.includes('formatChatSpeed'));
  assert.equal(chatSource.includes('stats.speed })'), false);
  assert.equal(chatSource.includes("alert(t('chat.microphone_error'"), false);
  assert.ok(chatSource.includes('setVoiceError'));
  assert.ok(chatSource.includes('isTextChatModelOption'));
  assert.equal(chatSource.includes("'gpt-image-2'"), false);
});

test('dashboard and camera default to privacy-safe media display', () => {
  assert.ok(dashboardSource.includes('mediaPrivacyRevealed'));
  assert.ok(dashboardSource.includes("t('dashboard.media.show')"));
  assert.ok(dashboardSource.includes("t('dashboard.media.hide')"));
  assert.ok(dashboardSource.includes("alt={t('dashboard.latest_photo_alt')}"));
  assert.ok(dashboardSource.includes("alt={t('dashboard.latest_screenshot_alt')}"));
  assert.equal(dashboardSource.includes('latestImages.photo_name &&'), false);
  assert.equal(dashboardSource.includes('latestImages.screenshot_name &&'), false);
  assert.equal(dashboardSource.includes('alert('), false);
  assert.ok(cameraFeedSource.includes('privacyRevealed'));
  assert.ok(cameraFeedSource.includes("t('camera_feed.show_stream')"));
  assert.ok(cameraFeedSource.includes('if (!isVisible)'));
  assert.equal(cameraFeedSource.includes("fontSize: '8px'"), false);
});

test('system logs expose usable controls and mask sensitive raw lines', () => {
  assert.ok(systemLogsSource.includes('paused'));
  assert.ok(systemLogsSource.includes('searchTerm'));
  assert.ok(systemLogsSource.includes('severityFilter'));
  assert.ok(systemLogsSource.includes('copyVisibleLogs'));
  assert.ok(systemLogsSource.includes('maskSensitiveLogLine'));
  assert.ok(systemLogsSource.includes("t('system_logs.empty')"));
  assert.ok(systemLogsSource.includes("t('system_logs.pause')"));
  assert.ok(systemLogsSource.includes("t('system_logs.resume')"));
  assert.ok(systemLogsSource.includes("t('system_logs.search_placeholder')"));
  assert.ok(systemLogsSource.includes("t('system_logs.copy_visible')"));
  assert.equal(systemLogsSource.includes("scrollIntoView({ behavior: 'smooth' })"), false);
});

test('usage view keeps overview compact and explains throughput scope', () => {
  assert.ok(usagePanelSource.includes("t('usage.window.all_time')"));
  assert.ok(usagePanelSource.includes("t('usage.speed_trend.axis_note')"));
  assert.ok(usagePanelSource.includes("t('usage.label.total_rate_hint')"));
  assert.match(usagePanelCss, /\.usage-speed-card\s*\{[\s\S]*order:\s*2/s);
  assert.match(usagePanelCss, /\.usage-summary-grid\s*\{[\s\S]*grid-template-columns:\s*repeat\(auto-fit,\s*minmax\(180px,\s*1fr\)\)/s);
  assert.match(usagePanelCss, /\.usage-table-wrap\s*\{[\s\S]*max-width:\s*100%/s);
});

test('settings destructive and clipboard actions provide explicit feedback', () => {
  assert.ok(settingsSource.includes('confirmProviderDelete'));
  assert.ok(settingsSource.includes('settings.provider.delete_confirm'));
  assert.ok(settingsSource.includes("disabled={form.providerConfig.selected_provider === currentProviderRoute}"));
  assert.ok(settingsSource.includes('copyDiagnosticsFallback'));
  assert.ok(settingsSource.includes("t('settings.about.copy_failed')"));
  assert.ok(settingsSource.includes("t('settings.voice_provider.test_hint')"));
  assert.equal(displayCopySource.includes("'settings.section.voice_provider': '语音 Provider'"), false);
});

test('project, plots, expense, and face pages remove visible audit regressions', () => {
  assert.equal(projectProgressCss.includes('--text-accent'), false);
  assert.equal(projectProgressCss.includes('--bg-hover'), false);
  assert.equal(projectProgressCss.includes('--bg-body'), false);
  assert.equal(plotsSource.includes('letterSpacing: \'-0.03em\''), false);
  assert.equal(plotChartCardSource.includes("letterSpacing: '-0.03em'"), false);
  assert.ok(plotsSource.includes('warningExpanded'));
  assert.ok(expenseSource.includes('compactWorkbookPath'));
  assert.ok(expenseSource.includes('role="tab"'));
  assert.ok(expenseSource.includes('aria-selected'));
  assert.ok(faceHistorySource.includes('face_history.error_prefix'));
  assert.ok(faceHistorySource.includes('privacyRevealed'));
  assert.equal(faceHistorySource.includes('alert('), false);
});

test('display copy contains the new UI audit labels in both languages', () => {
  [
    'chat.role.user',
    'chat.role.assistant',
    'chat.send_short',
    'dashboard.media.show',
    'dashboard.media.hide',
    'dashboard.latest_photo_alt',
    'dashboard.latest_screenshot_alt',
    'system_logs.empty',
    'system_logs.pause',
    'system_logs.resume',
    'system_logs.copy_visible',
    'usage.window.all_time',
    'usage.speed_trend.axis_note',
    'usage.label.total_rate_hint',
    'settings.provider.delete_confirm',
    'settings.about.copy_failed',
    'settings.voice_provider.test_hint',
    'face_history.error_prefix',
  ].forEach((key) => {
    const occurrences = displayCopySource.match(new RegExp(`'${key}'`, 'g')) || [];
    assert.equal(occurrences.length, 2, `expected English and Chinese copy for ${key}`);
  });
});
