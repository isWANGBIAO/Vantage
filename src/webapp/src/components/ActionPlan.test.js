import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const actionPlanSource = readFileSync(new URL('./ActionPlan.jsx', import.meta.url), 'utf8');

test('ActionPlan refreshes chat context base after a new plan is generated', () => {
  assert.ok(actionPlanSource.includes("fetchBackendJson('/api/chat/context'"));
  assert.ok(actionPlanSource.includes('CHAT_CONTEXT_BASE_UPDATED_EVENT'));
});

test('ActionPlan exposes copy controls for both round prompts and replies', () => {
  assert.ok(actionPlanSource.includes("t('action_plan.copy.prompt')"));
  assert.ok(actionPlanSource.includes("t('action_plan.copy.reply')"));
  assert.ok(actionPlanSource.includes("t('action_plan.copy.full_input')"));
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
  assert.ok(actionPlanSource.includes('data.meta?.input'));
  assert.ok(actionPlanSource.includes('setSystemPrompt(savedInput.system_prompt'));
  assert.ok(actionPlanSource.includes('setAnalysisPrompt(savedInput.analysis_prompt'));
  assert.ok(actionPlanSource.includes('setPlanPrompt(savedInput.plan_prompt'));
});

test('ActionPlan renders per-round first token, duration, token, and speed stats', () => {
  assert.ok(actionPlanSource.includes("getActionPlanRoundStats(stats, 'analysis')"));
  assert.ok(actionPlanSource.includes("getActionPlanRoundStats(stats, 'plan')"));
  assert.ok(actionPlanSource.includes("t('common.first_token'"));
  assert.ok(actionPlanSource.includes("t('common.tokens_detail'"));
  assert.ok(actionPlanSource.includes('formatActionPlanTokenBreakdown'));
  assert.equal(actionPlanSource.includes("t('common.history'"), false);
  assert.equal(actionPlanSource.includes('historical_total_tokens'), false);
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

test('ActionPlan annotates each reasoning block title with that round duration', () => {
  assert.ok(actionPlanSource.includes('formatThinkingTitleWithDuration'));
  assert.ok(actionPlanSource.includes('analysisRoundStats?.duration'));
  assert.ok(actionPlanSource.includes('analysisRoundStats?.completion_reasoning_tokens'));
  assert.ok(actionPlanSource.includes('planRoundStats?.duration'));
  assert.ok(actionPlanSource.includes('planRoundStats?.completion_reasoning_tokens'));
});

test('ActionPlan shows actual execution metadata and flags fallback runs', () => {
  assert.ok(actionPlanSource.includes('formatPoweredByLabel(stats)'));
  assert.ok(actionPlanSource.includes('isFallbackExecution(stats, selectedModelRef)'));
  assert.ok(actionPlanSource.includes('action-plan-fallback-warning'));
  assert.ok(actionPlanSource.includes("t('action_plan.execution.fallback_label'"));
});

test('ActionPlan uses provider-aware model options before falling back to legacy models', () => {
  assert.ok(actionPlanSource.includes('const defaultModel = data?.default_model'));
  assert.ok(actionPlanSource.includes('buildModelOptionsFromCatalog(data)'));
  assert.ok(actionPlanSource.includes('preferred_llm_model_ref'));
  assert.ok(actionPlanSource.includes('provider_route'));
  assert.ok(actionPlanSource.includes("vantage:llm-models-updated"));
});

test('ActionPlan uses model-aware reasoning options and payload mapping', () => {
  assert.ok(actionPlanSource.includes('getReasoningOptionsForModel(selectedModelOption?.model)'));
  assert.ok(actionPlanSource.includes('normalizeReasoningEffortForModel('));
  assert.ok(actionPlanSource.includes('reasoningOptions.map((option)'));
  assert.equal(actionPlanSource.includes('ACTION_PLAN_REASONING_OPTIONS.map((option)'), false);
});

test('ActionPlan exposes fast mode only through service tier payload for supported proxy models', () => {
  assert.ok(actionPlanSource.includes('loadStoredFastModeEnabled'));
  assert.ok(actionPlanSource.includes('saveFastModeEnabled'));
  assert.ok(actionPlanSource.includes('isFastModeSupportedForModel'));
  assert.ok(actionPlanSource.includes('fastModeEnabled'));
  assert.ok(actionPlanSource.includes("t('common.fast_mode')"));
  assert.ok(actionPlanSource.includes('service_tier'));
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
