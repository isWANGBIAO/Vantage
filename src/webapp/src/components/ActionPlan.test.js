import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const actionPlanSource = readFileSync(new URL('./ActionPlan.jsx', import.meta.url), 'utf8');

test('ActionPlan refreshes chat context base after a new plan is generated', () => {
  assert.ok(actionPlanSource.includes("fetchBackendJson('/api/chat/context'"));
  assert.ok(actionPlanSource.includes('CHAT_CONTEXT_BASE_UPDATED_EVENT'));
});

test('ActionPlan exposes copy controls for both round prompts and replies', () => {
  assert.ok(actionPlanSource.includes('Copy Prompt'));
  assert.ok(actionPlanSource.includes('Copy Reply'));
  assert.ok(actionPlanSource.includes('Copy Full Input'));
  assert.ok(actionPlanSource.includes('navigator.clipboard.writeText'));
  assert.ok(actionPlanSource.includes('systemPrompt'));
  assert.ok(actionPlanSource.includes('analysisReplyReady'));
  assert.ok(actionPlanSource.includes('planReplyReady'));
});

test('ActionPlan keeps streamed reply refs in sync for copy readiness', () => {
  assert.ok(actionPlanSource.includes('analysisContentRef.current = nextContent'));
  assert.ok(actionPlanSource.includes('planContentRef.current = nextContent'));
});

test('ActionPlan appends streamed system and prompt chunks instead of overwriting them', () => {
  assert.ok(actionPlanSource.includes('setSystemPrompt((prev) => prev + sectionedLog.content)'));
  assert.ok(actionPlanSource.includes('setAnalysisPrompt((prev) => prev + sectionedLog.content)'));
  assert.ok(actionPlanSource.includes('setPlanPrompt((prev) => prev + sectionedLog.content)'));
});

test('ActionPlan loads structured analysis and plan bodies from the backend response', () => {
  assert.ok(actionPlanSource.includes('data.analysis?.body'));
  assert.ok(actionPlanSource.includes('data.plan?.body'));
});

test('ActionPlan no longer depends on delimiter parsing or thinking-as-reply fallback', () => {
  assert.equal(actionPlanSource.includes('splitActionPlanContent'), false);
  assert.equal(actionPlanSource.includes('coalesceActionPlanReplyContent'), false);
});

test('ActionPlan keeps thinking blocks collapsed until the user expands them', () => {
  assert.ok(actionPlanSource.includes('<details className="thinking-block">'));
  assert.ok(actionPlanSource.includes('<summary className="thinking-header">'));
  assert.equal(actionPlanSource.includes('<details className="thinking-block" open>'), false);
});

test('ActionPlan shows actual execution metadata and flags fallback runs', () => {
  assert.ok(actionPlanSource.includes('formatPoweredByLabel(stats)'));
  assert.ok(actionPlanSource.includes("stats.provider_route !== 'cliproxyapi_primary'"));
  assert.ok(actionPlanSource.includes('stats.model !== selectedModel'));
  assert.ok(actionPlanSource.includes('action-plan-fallback-warning'));
  assert.ok(actionPlanSource.includes('Fallback'));
});

test('ActionPlan shows live elapsed time while generation is active', () => {
  assert.ok(actionPlanSource.includes('computeDisplayedDurationSeconds'));
  assert.ok(actionPlanSource.includes('const [liveDurationNowMs, setLiveDurationNowMs] = useState(() => Date.now())'));
  assert.equal(actionPlanSource.includes('Time {(stats.total_duration || 0).toFixed(1)}s'), false);
});

test('ActionPlan supports stacked reading mode without card-level scrolling', () => {
  assert.ok(actionPlanSource.includes("layoutMode = 'split'"));
  assert.ok(actionPlanSource.includes("'action-plan-stack'"));
  assert.ok(actionPlanSource.includes("overflowY: layoutMode === 'stacked' ? 'visible' : 'auto'"));
});
