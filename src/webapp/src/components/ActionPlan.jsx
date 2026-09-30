import { useEffect, useRef, useState, useCallback } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { RotateCcw, FileText, CheckSquare, Activity, AlertTriangle } from 'lucide-react';
import { getActionPlanRenderState } from '../utils/actionPlanContent';
import automationLimits from '../utils/automationLimits.cjs';
import {
  getReasoningOptionsForModelContract,
  loadStoredActionPlanReasoningEffort,
  normalizeReasoningEffortForModelContract,
  saveActionPlanReasoningEffort,
} from '../utils/actionPlanReasoning';
import { buildActionPlanGenerationPayload } from '../utils/actionPlanGeneration';
import {
  formatModelReasoningSupportLabel,
  parseModelReasoningSupport,
} from '../utils/modelReasoningSupport';
import {
  computeDisplayedDurationSeconds,
  formatActionPlanCacheBreakdown,
  formatActionPlanSpeed,
  formatActionPlanTokenBreakdown,
  formatCompactTokenValue,
  formatSecondsValue,
  formatThinkingTitleWithDuration,
  formatPoweredByLabel,
  getActionPlanPromptContextWarning,
  getActionPlanRoundNotice,
  getActionPlanRoundStats,
  isFallbackExecution,
} from '../utils/actionPlanStats';
import {
  buildModelOptionsFromCatalog,
  findModelOption,
  persistPreferredModelOption,
  resolvePreferredModelOption,
} from '../utils/llmModelCatalog';
import {
  isFastModeSupportedForModel,
  loadStoredFastModeEnabled,
  saveFastModeEnabled,
} from '../utils/modelServiceTier';
import {
  createStreamRenderScheduler,
  parseActionPlanStreamLog,
} from '../utils/actionPlanStream';
import { redactSensitiveText } from '../utils/sensitiveText';
import { CHAT_CONTEXT_BASE_UPDATED_EVENT } from '../utils/chatContextState';
import { fetchBackendJson } from '../utils/backendRequest';
import { loadSettingsState, saveSettingsState } from '../utils/settingsState';
import {
  createActionPlanJobMonitor,
  getActionPlanJobError,
  getCompletedActionPlanJobResult,
  isActiveActionPlanJob,
  isBackgroundActionPlanJob,
  isActionPlanJobResultCurrent,
} from '../utils/actionPlanJobs';
import { useDisplayLanguage } from '../context/DisplayLanguageContext.jsx';

const { MAX_ACTION_PLAN_CHECK_INTERVAL_MINUTES } = automationLimits;
const COPY_FEEDBACK_DURATION_MS = 1500;

async function writeTextWithFallback(content) {
  if (!content) {
    return false;
  }

  if (
    globalThis.navigator?.clipboard
    && typeof globalThis.navigator.clipboard.writeText === 'function'
  ) {
    await globalThis.navigator.clipboard.writeText(content);
    return true;
  }

  const documentRef = globalThis.document;
  if (!documentRef?.createElement || !documentRef.body || typeof documentRef.execCommand !== 'function') {
    return false;
  }

  const textarea = documentRef.createElement('textarea');
  textarea.value = content;
  textarea.setAttribute('readonly', '');
  textarea.style.position = 'fixed';
  textarea.style.opacity = '0';
  documentRef.body.appendChild(textarea);
  textarea.select();

  try {
    return documentRef.execCommand('copy');
  } finally {
    documentRef.body.removeChild(textarea);
  }
}

function buildMarkdownPlaceholder(title, body) {
  return [title, '', body].join('\n');
}

function renderMarkdownOrText(contentState, t) {
  if (contentState.plainText) {
    return (
      <>
        <div className="action-plan-warning">
          {t('action_plan.render.corrupted')}
        </div>
        <div className="action-plan-plain-text">
          {contentState.plainTextContent || t('action_plan.render.empty')}
        </div>
      </>
    );
  }

  return (
    <ReactMarkdown remarkPlugins={[remarkGfm]}>
      {contentState.markdownContent}
    </ReactMarkdown>
  );
}

function renderActionPlanRoundNotice(notice, t) {
  if (notice === 'incomplete') {
    return (
      <div className="action-plan-warning">
        {t('action_plan.render.incomplete')}
      </div>
    );
  }
  if (notice === 'usage_unavailable') {
    return (
      <div className="action-plan-info">
        {t('action_plan.render.usage_unavailable')}
      </div>
    );
  }
  return null;
}

function buildAnalysisFullInput(systemPrompt, analysisPrompt) {
  if (!systemPrompt || !analysisPrompt) {
    return '';
  }

  return [
    '[System]',
    systemPrompt,
    '',
    '[User]',
    analysisPrompt,
  ].join('\n');
}

function buildPlanFullInput(systemPrompt, analysisPrompt, analysisReply, planPrompt) {
  if (!systemPrompt || !analysisPrompt || !analysisReply || !planPrompt) {
    return '';
  }

  return [
    '[System]',
    systemPrompt,
    '',
    '[User - Round 1]',
    analysisPrompt,
    '',
    '[Assistant - Round 1]',
    analysisReply,
    '',
    '[User - Round 2]',
    planPrompt,
  ].join('\n');
}

export default function ActionPlan({ isVisible = true, layoutMode = 'split' }) {
  const { effectiveLanguage, t } = useDisplayLanguage();
  const [analysisContent, setAnalysisContent] = useState('');
  const [analysisThinking, setAnalysisThinking] = useState('');
  const [planContent, setPlanContent] = useState('');
  const [planThinking, setPlanThinking] = useState('');
  const [systemPrompt, setSystemPrompt] = useState('');
  const [analysisPrompt, setAnalysisPrompt] = useState('');
  const [planPrompt, setPlanPrompt] = useState('');
  const [analysisReplyReady, setAnalysisReplyReady] = useState(false);
  const [planReplyReady, setPlanReplyReady] = useState(false);
  const [copiedKey, setCopiedKey] = useState('');
  const [selectedReasoningEffort, setSelectedReasoningEffort] = useState(() => loadStoredActionPlanReasoningEffort());
  const [fastModeEnabled, setFastModeEnabled] = useState(() => loadStoredFastModeEnabled());
  const [stats, setStats] = useState(null);
  const [availableModels, setAvailableModels] = useState([]);
  const [modelReasoningSupport, setModelReasoningSupport] = useState({});
  const [selectedModel, setSelectedModel] = useState('');
  const selectedModelOption = findModelOption(availableModels, selectedModel);
  const [isGenerating, setIsGenerating] = useState(false);
  const [checkIntervalMinutes, setCheckIntervalMinutes] = useState(null);
  const [intervalDraft, setIntervalDraft] = useState('60');
  const [autoRefreshStatus, setAutoRefreshStatus] = useState('');
  const [savingInterval, setSavingInterval] = useState(false);
  const [jobsReady, setJobsReady] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isCancelling, setIsCancelling] = useState(false);
  const jobMonitorRef = useRef(null);
  const displayedJobIdRef = useRef(null);
  const completedJobIdRef = useRef(null);
  const truncatedJobIdRef = useRef(null);
  const planDateRef = useRef(null);
  const currentSectionRef = useRef('analysis');
  const [liveDurationNowMs, setLiveDurationNowMs] = useState(() => Date.now());

  const loadAbortControllerRef = useRef(null);
  const analysisEndRef = useRef(null);
  const planEndRef = useRef(null);
  const analysisContentRef = useRef('');
  const planContentRef = useRef('');
  const copyResetTimeoutRef = useRef(null);
  const visibilityRef = useRef(isVisible);
  const isGeneratingRef = useRef(isGenerating);
  const selectedModelRef = useRef(selectedModelOption);
  const selectedReasoningEffortRef = useRef(selectedReasoningEffort);
  const fastModeEnabledRef = useRef(fastModeEnabled);

  visibilityRef.current = isVisible;
  isGeneratingRef.current = isGenerating;
  selectedModelRef.current = selectedModelOption;
  selectedReasoningEffortRef.current = normalizeReasoningEffortForModelContract(
    selectedReasoningEffort,
    selectedModelOption?.model,
    selectedModelOption?.reasoning_tiers,
    selectedModelOption?.reasoning_aliases,
  );
  fastModeEnabledRef.current = fastModeEnabled;

  const setAnalysisContentWithRef = useCallback((value) => {
    if (typeof value === 'function') {
      setAnalysisContent((prev) => {
        const nextContent = redactSensitiveText(value(prev));
        analysisContentRef.current = nextContent;
        return nextContent;
      });
      return;
    }

    const redactedValue = redactSensitiveText(value);
    analysisContentRef.current = redactedValue;
    setAnalysisContent(redactedValue);
  }, []);

  const setPlanContentWithRef = useCallback((value) => {
    if (typeof value === 'function') {
      setPlanContent((prev) => {
        const nextContent = redactSensitiveText(value(prev));
        planContentRef.current = nextContent;
        return nextContent;
      });
      return;
    }

    const redactedValue = redactSensitiveText(value);
    planContentRef.current = redactedValue;
    setPlanContent(redactedValue);
  }, []);

  useEffect(() => () => {
    if (copyResetTimeoutRef.current) {
      clearTimeout(copyResetTimeoutRef.current);
    }
  }, []);

  useEffect(() => {
    if (isGenerating && isVisible && analysisContent) {
      analysisEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
  }, [analysisContent, isGenerating, isVisible]);

  useEffect(() => {
    if (isGenerating && isVisible && planContent) {
      planEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
  }, [planContent, isGenerating, isVisible]);

  useEffect(() => {
    if (!isGenerating || !stats?.startTime) {
      return undefined;
    }

    setLiveDurationNowMs(Date.now());
    const intervalId = window.setInterval(() => {
      setLiveDurationNowMs(Date.now());
    }, 200);

    return () => {
      window.clearInterval(intervalId);
    };
  }, [isGenerating, stats?.startTime]);

  const applyLoadedActionPlan = useCallback((data, { keepThinking = false } = {}) => {
    const analysisBody = data.analysis?.body || '';
    const planBody = data.plan?.body || '';
    const savedStats = data.meta?.stats;
    const savedInput = data.meta?.input || {};

    setAnalysisContentWithRef(
      analysisBody || buildMarkdownPlaceholder(
        t('action_plan.placeholder.analysis_unavailable.title'),
        t('action_plan.placeholder.analysis_unavailable.body'),
      ),
    );
    if (!keepThinking) setAnalysisThinking('');
    setPlanContentWithRef(
      planBody || buildMarkdownPlaceholder(
        t('action_plan.placeholder.plan_unavailable.title'),
        t('action_plan.placeholder.plan_unavailable.body'),
      ),
    );
    if (!keepThinking) setPlanThinking('');
    setSystemPrompt(savedInput.system_prompt || '');
    setAnalysisPrompt(savedInput.analysis_prompt || '');
    setPlanPrompt(savedInput.plan_prompt || '');
    const complete = Boolean(analysisBody.trim() && planBody.trim());
    setAnalysisReplyReady(complete);
    setPlanReplyReady(complete);
    setCopiedKey('');
    setStats(
      savedStats && typeof savedStats === 'object'
        ? savedStats
        : {
            speed: 'loaded',
            total_duration: 0,
            total_tokens: 0,
          },
    );
  }, [setAnalysisContentWithRef, setPlanContentWithRef, t]);

  const copyActionPlanText = useCallback(async (content, key) => {
    if (!content) {
      return;
    }

    try {
      const copied = await writeTextWithFallback(content);
      if (!copied) {
        console.warn('Action plan copy skipped because clipboard access is unavailable.');
        return;
      }
      setCopiedKey(key);
      if (copyResetTimeoutRef.current) {
        clearTimeout(copyResetTimeoutRef.current);
      }
      copyResetTimeoutRef.current = setTimeout(() => {
        setCopiedKey((currentKey) => (currentKey === key ? '' : currentKey));
      }, COPY_FEEDBACK_DURATION_MS);
    } catch (error) {
      console.error('Failed to copy action plan text:', error);
    }
  }, []);

  const loadTodaysPlan = useCallback(async (signal) => {
    try {
      const data = await fetchBackendJson('/api/v1/action-plan/today', {
        retryPolicy: 'load',
        signal,
      });

      if (loadAbortControllerRef.current?.signal !== signal) {
        return { aborted: true };
      }

      planDateRef.current = data.date || null;
      if (data.exists) {
        applyLoadedActionPlan(data);
        return data;
      }

      setAnalysisContentWithRef(buildMarkdownPlaceholder(
        t('action_plan.placeholder.welcome.title'),
        t('action_plan.placeholder.welcome.body'),
      ));
      setAnalysisThinking('');
      setPlanContentWithRef(buildMarkdownPlaceholder(
        t('action_plan.placeholder.waiting.title'),
        t('action_plan.placeholder.waiting.body'),
      ));
      setPlanThinking('');
      setSystemPrompt('');
      setAnalysisPrompt('');
      setPlanPrompt('');
      setAnalysisReplyReady(false);
      setPlanReplyReady(false);
      setCopiedKey('');
      setStats(null);
      return data;
    } catch (err) {
      if (err.name === 'AbortError') {
        return { aborted: true };
      }

      console.error('Failed to load today plan:', err);
      setAnalysisContentWithRef(buildMarkdownPlaceholder(
        t('action_plan.placeholder.load_failed.title'),
        t('action_plan.placeholder.load_failed.body'),
      ));
      setAnalysisThinking('');
      setPlanContentWithRef(buildMarkdownPlaceholder(
        t('action_plan.placeholder.waiting.title'),
        t('action_plan.placeholder.waiting.body'),
      ));
      setPlanThinking('');
      setSystemPrompt('');
      setAnalysisPrompt('');
      setPlanPrompt('');
      setAnalysisReplyReady(false);
      setPlanReplyReady(false);
      setCopiedKey('');
      setStats(null);
      return { exists: false, error: err };
    } finally {
      if (loadAbortControllerRef.current?.signal === signal) {
        loadAbortControllerRef.current = null;
      }
    }
  }, [applyLoadedActionPlan, setAnalysisContentWithRef, setPlanContentWithRef, t]);

  const stopGeneration = useCallback(async () => {
    if (!jobMonitorRef.current || isCancelling) return;
    setIsCancelling(true);
    try {
      await jobMonitorRef.current.cancelActive();
    } catch (error) {
      if (error.name !== 'AbortError') {
        setAutoRefreshStatus(t('common.error_prefix', { error: redactSensitiveText(getActionPlanJobError(error)) }));
      }
    } finally {
      setIsCancelling(false);
    }
  }, [isCancelling, t]);

  const handleReasoningEffortChange = (event) => {
    const nextValue = saveActionPlanReasoningEffort(
      event.target.value,
      globalThis.localStorage,
      selectedModelOption?.model,
    );
    setSelectedReasoningEffort(nextValue);
  };

  const handleModelChange = (event) => {
    const nextModel = event.target.value;
    setSelectedModel(nextModel);
    persistPreferredModelOption(findModelOption(availableModels, nextModel));
  };

  const handleFastModeChange = (event) => {
    setFastModeEnabled(saveFastModeEnabled(event.target.checked));
  };

  const refreshChatContextBase = useCallback(async () => {
    try {
      const data = await fetchBackendJson('/api/v1/chat/context', {
        retryPolicy: 'load',
      });

      window.dispatchEvent(new CustomEvent(CHAT_CONTEXT_BASE_UPDATED_EVENT, {
        detail: {
          baseContextVersion: data?.base_context_version || 'empty',
          displayMessages: Array.isArray(data?.display_messages) ? data.display_messages : [],
          preferredModel: data?.preferred_model || null,
          preferredProviderRoute: data?.preferred_provider_route || null,
          preferredModelOptionId: data?.preferred_model_option_id || null,
        },
      }));
    } catch (error) {
      console.error('Failed to refresh chat context base:', error);
    }
  }, []);

  const handleJobSnapshot = useCallback((job) => {
    const active = isActiveActionPlanJob(job);
    const background = isBackgroundActionPlanJob(job);
    const newJob = displayedJobIdRef.current !== job.id;
    displayedJobIdRef.current = job.id;
    isGeneratingRef.current = active;
    setIsGenerating(active);

    if (newJob && active && !background) {
      currentSectionRef.current = 'analysis';
      setAnalysisThinking('');
      setPlanThinking('');
      setSystemPrompt('');
      setAnalysisPrompt('');
      setPlanPrompt('');
      setAnalysisReplyReady(false);
      setPlanReplyReady(false);
      setCopiedKey('');
      setAnalysisContentWithRef(buildMarkdownPlaceholder(
        t('action_plan.placeholder.analyzing.title'),
        t('action_plan.placeholder.analyzing.body'),
      ));
      setPlanContentWithRef(buildMarkdownPlaceholder(
        t('action_plan.placeholder.waiting_analysis.title'),
        t('action_plan.placeholder.waiting_analysis.body'),
      ));
      setStats({
        speed: '0 t/s',
        total_duration: 0,
        total_tokens: 0,
        startTime: Date.parse(job.started_at || job.created_at) || Date.now(),
        reasoning_effort: job.request?.reasoning_effort,
        service_tier: job.request?.service_tier,
      });
    }

    if (active) {
      setAutoRefreshStatus(t(truncatedJobIdRef.current === job.id
        ? 'action_plan.job.truncated' : `action_plan.job.${job.status}`));
      return;
    }
    if (completedJobIdRef.current === job.id) return;
    const result = getCompletedActionPlanJobResult(job);
    if (result) {
      completedJobIdRef.current = job.id;
      applyLoadedActionPlan(result, { keepThinking: !background && !newJob });
      setAutoRefreshStatus(t(background ? 'action_plan.auto.updated' : 'action_plan.job.succeeded'));
      void refreshChatContextBase();
    } else {
      if (job.status !== 'succeeded') completedJobIdRef.current = job.id;
      if (!background) {
        setAnalysisReplyReady(false);
        setPlanReplyReady(false);
      }
      if (job.status === 'cancelled') {
        setAutoRefreshStatus(t(background ? 'action_plan.auto.stopped' : 'action_plan.job.cancelled'));
      } else {
        const error = job.status === 'succeeded'
          ? t('action_plan.job.incomplete')
          : getActionPlanJobError(job.error);
        setAutoRefreshStatus(t(background ? 'action_plan.auto.failed' : 'action_plan.job.failed', { error: redactSensitiveText(error) }));
      }
    }
  }, [applyLoadedActionPlan, refreshChatContextBase, setAnalysisContentWithRef, setPlanContentWithRef, t]);

  const handleJobEvent = useCallback(async (data, job) => {
    if (isBackgroundActionPlanJob(job)) return;
    if (data.truncated === true || data.event_truncated === true) {
      truncatedJobIdRef.current = job.id;
      setAutoRefreshStatus(t('action_plan.job.truncated'));
      return;
    }
    let { log } = data;
    const appendError = (error) => {
      const text = t('common.error_prefix', { error: redactSensitiveText(getActionPlanJobError(error)) });
      if (currentSectionRef.current === 'analysis') setAnalysisContentWithRef((prev) => `${prev}\n\n${text}`);
      else setPlanContentWithRef((prev) => `${prev}\n\n${text}`);
    };
    if (data.error) appendError(data.error);
    if (!log) return;
    log = redactSensitiveText(log);
    if (log.startsWith('STATS_JSON:')) {
      try {
        const newStats = JSON.parse(log.slice('STATS_JSON:'.length).trim());
        setStats((prev) => ({ ...prev, ...newStats }));
      } catch (error) {
        console.error('Stats parse error', error);
      }
      return;
    }

    const sectionedLog = parseActionPlanStreamLog(log);
    if (sectionedLog) {
      currentSectionRef.current = sectionedLog.section;
      if (sectionedLog.kind === 'start') {
        if (sectionedLog.section === 'analysis') {
          setAnalysisContentWithRef('');
          setAnalysisThinking('');
        } else {
          setPlanContentWithRef('');
          setPlanThinking('');
        }
      } else if (sectionedLog.kind === 'thinking') {
        if (sectionedLog.section === 'analysis') setAnalysisThinking((prev) => prev + sectionedLog.content);
        else setPlanThinking((prev) => prev + sectionedLog.content);
      } else if (sectionedLog.kind === 'system') {
        setSystemPrompt((prev) => prev + sectionedLog.content);
      } else if (sectionedLog.kind === 'prompt') {
        if (sectionedLog.section === 'analysis') setAnalysisPrompt((prev) => prev + sectionedLog.content);
        else setPlanPrompt((prev) => prev + sectionedLog.content);
      } else if (sectionedLog.kind === 'metadata') {
        if (sectionedLog.content && typeof sectionedLog.content === 'object') {
          setStats((prev) => ({ ...prev, ...sectionedLog.content }));
        }
      } else if (sectionedLog.kind === 'content') {
        if (sectionedLog.section === 'analysis') setAnalysisContentWithRef((prev) => prev + sectionedLog.content);
        else setPlanContentWithRef((prev) => prev + sectionedLog.content);
        const estimatedTokens = Math.max(1, Math.ceil(sectionedLog.content.length * 0.7));
        setStats((prev) => {
          const startTime = prev?.startTime || Date.now();
          const duration = (Date.now() - startTime) / 1000;
          const totalTokens = (prev?.total_tokens || 0) + estimatedTokens;
          return {
            ...prev,
            startTime,
            total_tokens: totalTokens,
            total_duration: duration,
            speed: duration > 0 ? `${(totalTokens / duration).toFixed(2)} t/s` : '0.00 t/s',
          };
        });
      } else if (sectionedLog.kind === 'error') {
        appendError(sectionedLog.content);
      }
    } else if (log.startsWith('STREAM_ERROR:')) {
      appendError(log.slice('STREAM_ERROR:'.length));
    } else if (!log.startsWith('STREAM_DONE:')) {
      if (currentSectionRef.current === 'analysis') setAnalysisContentWithRef((prev) => prev + `${log}\n`);
      else setPlanContentWithRef((prev) => prev + `${log}\n`);
    }
    const waitForRender = createStreamRenderScheduler({
      shouldYield: () => visibilityRef.current && !(typeof document !== 'undefined' && document.hidden),
    });
    await waitForRender();
  }, [setAnalysisContentWithRef, setPlanContentWithRef, t]);

  const startGeneration = useCallback(async () => {
    if (!jobMonitorRef.current || isGeneratingRef.current || isSubmitting) return;
    setIsSubmitting(true);
    const model = selectedModelRef.current;
    const reasoningEffort = normalizeReasoningEffortForModelContract(
      selectedReasoningEffortRef.current, model?.model, model?.reasoning_tiers, model?.reasoning_aliases,
    );
    try {
      await jobMonitorRef.current.submit(buildActionPlanGenerationPayload(reasoningEffort, {
        model: model?.model,
        providerRoute: model?.provider_route,
        fastModeEnabled: fastModeEnabledRef.current && isFastModeSupportedForModel(model?.model),
      }));
    } catch (error) {
      if (error.name !== 'AbortError') {
        setAutoRefreshStatus(t('common.error_prefix', { error: redactSensitiveText(getActionPlanJobError(error)) }));
      }
    } finally {
      setIsSubmitting(false);
    }
  }, [isSubmitting, t]);

  useEffect(() => {
    const applyModelCatalog = (data) => {
      const modelList = buildModelOptionsFromCatalog(data);
      setAvailableModels(modelList);
      setModelReasoningSupport(parseModelReasoningSupport(data?.providers));

      const storageModelRef = localStorage.getItem('preferred_llm_model_ref');
      const storageModel = localStorage.getItem('preferred_llm_model');
      if (modelList.length > 0) {
        const defaultModel = data?.default_model;
        const nextModel = (
          findModelOption(modelList, storageModelRef)
          || findModelOption(modelList, storageModel)
          || resolvePreferredModelOption(modelList)
          || findModelOption(modelList, defaultModel)
          || modelList[0]
        );
        setSelectedModel(nextModel.id);
        return nextModel;
      }

      return null;
    };

    const initializeModels = async () => {
      try {
        const data = await fetchBackendJson('/api/v1/models', { retryPolicy: 'load', signal: controller.signal });
        if (!controller.signal.aborted) return applyModelCatalog(data);
      } catch (error) {
        console.error('Failed to load model list:', error);
      }

      return null;
    };

    const controller = new AbortController();
    loadAbortControllerRef.current = controller;
    setAnalysisContentWithRef(buildMarkdownPlaceholder(
      t('action_plan.placeholder.connecting.title'),
      t('action_plan.placeholder.connecting.body'),
    ));
    setAnalysisThinking('');
    setPlanContentWithRef(buildMarkdownPlaceholder(
      t('action_plan.placeholder.waiting.title'),
      t('action_plan.placeholder.waiting.body'),
    ));
    setPlanThinking('');

    const loadCheckInterval = async () => {
      try {
        const settingsState = await loadSettingsState();
        if (controller.signal.aborted) return;
        const interval = settingsState.settings?.actionPlanCheckIntervalMinutes ?? 60;
        setCheckIntervalMinutes(interval);
        setIntervalDraft(String(interval));
      } catch (error) {
        if (controller.signal.aborted) return;
        setCheckIntervalMinutes(60);
        console.warn('Failed to load Action Plan check interval:', error);
      }
    };

    setJobsReady(false);
    displayedJobIdRef.current = null;
    completedJobIdRef.current = null;
    truncatedJobIdRef.current = null;
    const monitor = createActionPlanJobMonitor({
      onSnapshot: handleJobSnapshot,
      onEvent: handleJobEvent,
      shouldDisplayResult: (job) => isActionPlanJobResultCurrent(job, planDateRef.current),
      onMissingJob: async (job) => {
        isGeneratingRef.current = false;
        setIsGenerating(false);
        if (!isBackgroundActionPlanJob(job)) {
          setAnalysisReplyReady(false);
          setPlanReplyReady(false);
        }
        setAutoRefreshStatus(t('action_plan.job.unavailable'));
        // Job history is process-local, but committed plans survive a backend
        // restart. Recover that saved view without inventing a job outcome.
        const saved = await fetchBackendJson('/api/v1/action-plan/today', {
          signal: controller.signal, retryPolicy: 'none',
        });
        if (controller.signal.aborted || displayedJobIdRef.current !== job.id || isGeneratingRef.current) return;
        if (saved.exists && saved.analysis?.body?.trim() && saved.plan?.body?.trim()) {
          planDateRef.current = saved.date || planDateRef.current;
          applyLoadedActionPlan(saved);
        }
      },
      onObservationError: (error) => {
        setAutoRefreshStatus(t('action_plan.job.reconnecting', {
          error: redactSensitiveText(getActionPlanJobError(error)),
        }));
      },
    });
    jobMonitorRef.current = monitor;
    const initializeActionPlan = async () => {
      await Promise.all([initializeModels(), loadCheckInterval(), loadTodaysPlan(controller.signal)]);
      if (controller.signal.aborted) return;
      await monitor.start();
      if (!controller.signal.aborted) setJobsReady(true);
    };

    void initializeActionPlan();

    const handleModelCatalogUpdated = (event) => {
      applyModelCatalog(event.detail);
    };
    window.addEventListener('vantage:llm-models-updated', handleModelCatalogUpdated);

    return () => {
      window.removeEventListener('vantage:llm-models-updated', handleModelCatalogUpdated);
      controller.abort();
      monitor.stop();
      if (jobMonitorRef.current === monitor) jobMonitorRef.current = null;
      if (loadAbortControllerRef.current?.signal === controller.signal) {
        loadAbortControllerRef.current = null;
      }
    };
  }, [applyLoadedActionPlan, handleJobEvent, handleJobSnapshot, loadTodaysPlan, setAnalysisContentWithRef, setPlanContentWithRef, t]);

  const saveCheckInterval = async () => {
    const value = Number(intervalDraft);
    if (!intervalDraft.trim() || !Number.isInteger(value) || value < 0 || value > MAX_ACTION_PLAN_CHECK_INTERVAL_MINUTES) {
      setAutoRefreshStatus(t('action_plan.auto.invalid', {
        max: MAX_ACTION_PLAN_CHECK_INTERVAL_MINUTES.toLocaleString('en-US'),
      }));
      return;
    }
    setSavingInterval(true);
    try {
      const result = await saveSettingsState({ actionPlanCheckIntervalMinutes: value });
      const saved = result.settings?.actionPlanCheckIntervalMinutes ?? value;
      setCheckIntervalMinutes(saved);
      setIntervalDraft(String(saved));
      setAutoRefreshStatus(t(saved === 0 ? 'action_plan.auto.disabled' : 'action_plan.auto.saved'));
    } catch (error) {
      setAutoRefreshStatus(t('action_plan.auto.save_failed', { error: redactSensitiveText(error.message) }));
    } finally { setSavingInterval(false); }
  };

  const analysisRender = getActionPlanRenderState(analysisContent);
  const planRender = getActionPlanRenderState(planContent);
  const analysisFullInputContent = buildAnalysisFullInput(systemPrompt, analysisPrompt);
  const planFullInputContent = buildPlanFullInput(
    systemPrompt,
    analysisPrompt,
    analysisContent,
    planPrompt,
  );
  const modelReasoningSupportLabel = formatModelReasoningSupportLabel(selectedModelOption?.model, modelReasoningSupport, t);
  const actualExecutionLabel = formatPoweredByLabel(stats);
  const fallbackExecutionActive = isFallbackExecution(stats, selectedModelRef);
  const displayedDurationSeconds = computeDisplayedDurationSeconds(stats, {
    isActive: isGenerating,
    nowMs: liveDurationNowMs,
  });
  const cacheBreakdown = formatActionPlanCacheBreakdown(stats);
  const analysisRoundStats = getActionPlanRoundStats(stats, 'analysis');
  const planRoundStats = getActionPlanRoundStats(stats, 'plan');
  const analysisRoundNotice = getActionPlanRoundNotice(
    stats,
    'analysis',
    analysisContent,
  );
  const planRoundNotice = getActionPlanRoundNotice(
    stats,
    'plan',
    planContent,
  );
  const analysisThinkingTitle = formatThinkingTitleWithDuration(
    t('action_plan.thinking_title'),
    analysisRoundStats?.duration,
    analysisRoundStats?.completion_reasoning_tokens,
  );
  const planThinkingTitle = formatThinkingTitleWithDuration(
    t('action_plan.thinking_title'),
    planRoundStats?.duration,
    planRoundStats?.completion_reasoning_tokens,
  );
  const reasoningOptions = getReasoningOptionsForModelContract(
    selectedModelOption?.model,
    selectedModelOption?.reasoning_tiers,
  );
  const fastModeSupported = isFastModeSupportedForModel(selectedModelOption?.model);
  const displayedReasoningEffort = normalizeReasoningEffortForModelContract(
    selectedReasoningEffort,
    selectedModelOption?.model,
    selectedModelOption?.reasoning_tiers,
  );
  const promptContextWarning = getActionPlanPromptContextWarning(stats);

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: '1rem',
        height: layoutMode === 'stacked' ? 'auto' : '100%',
        overflow: layoutMode === 'stacked' ? 'visible' : 'hidden',
        boxSizing: 'border-box',
      }}
    >
      <div
        className="glass-panel"
        style={{
          padding: '1rem 1.5rem',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          gap: '1rem',
          flexWrap: 'wrap',
          flexShrink: 0,
        }}
      >
        <div>
          <h2
            style={{
              margin: 0,
              display: 'flex',
              alignItems: 'center',
              gap: '0.5rem',
              fontSize: '1.25rem',
            }}
          >
            <CheckSquare size={20} color="var(--primary-color)" />
            {t('action_plan.title')}
          </h2>
          <p style={{ margin: 0, color: 'var(--text-secondary)', fontSize: '0.85rem' }}>
            {t('action_plan.subtitle')}
          </p>
          <label style={{ display: 'flex', gap: '0.4rem', alignItems: 'center', fontSize: '0.85rem', marginTop: '0.5rem' }}>
            {t('action_plan.auto.interval')}
            <input type="number" min="0" max={MAX_ACTION_PLAN_CHECK_INTERVAL_MINUTES} step="1" value={intervalDraft}
              disabled={savingInterval || checkIntervalMinutes === null}
              onChange={(event) => setIntervalDraft(event.target.value)}
              onBlur={saveCheckInterval}
              onKeyDown={(event) => { if (event.key === 'Enter') event.currentTarget.blur(); }}
              style={{ width: '5rem' }} />
          </label>
          {autoRefreshStatus && <p role="status" style={{ fontSize: '0.8rem', margin: '0.25rem 0' }}>{autoRefreshStatus}</p>}
        </div>

        <div style={{ display: 'flex', gap: '1rem', alignItems: 'center', flexWrap: 'wrap' }}>
          {stats && (
            <div className="action-plan-stats">
              <span>{t('common.first_token', { value: formatDurationChipValue(stats.first_token_latency) })}</span>
              <span>{t('common.speed', { value: formatActionPlanSpeed(stats) })}</span>
              <span>{t('common.time', { value: displayedDurationSeconds.toFixed(1) })}</span>
              <span>{t('common.tokens_detail', { value: formatActionPlanTokenBreakdown(stats) })}</span>
              {cacheBreakdown ? <span>{t('common.cache_session', { value: cacheBreakdown })}</span> : null}
            </div>
          )}

          <label
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '0.5rem',
              color: 'var(--text-secondary)',
              fontSize: '0.9rem',
            }}
          >
            <span>{t('common.model')}</span>
            <select
              value={selectedModel}
              onChange={handleModelChange}
              disabled={isGenerating || availableModels.length === 0}
              style={{
                padding: '0.65rem 0.85rem',
                borderRadius: '8px',
                border: '1px solid var(--border-color)',
                background: 'var(--bg-surface)',
                color: 'var(--text-primary)',
                minWidth: '180px',
                cursor: isGenerating || availableModels.length === 0 ? 'not-allowed' : 'pointer',
                opacity: isGenerating || availableModels.length === 0 ? 0.65 : 1,
              }}
            >
              {availableModels.map((modelOption) => (
                <option key={modelOption.id} value={modelOption.id}>
                  {modelOption.label}
                </option>
              ))}
            </select>
            {modelReasoningSupportLabel && (
              <span style={{ color: 'rgba(255, 77, 79, 0.95)' }}>
                {modelReasoningSupportLabel}
              </span>
            )}
            {actualExecutionLabel && (
              <span
                className={fallbackExecutionActive ? 'action-plan-fallback-warning' : 'action-plan-actual-model'}
                style={{
                  color: fallbackExecutionActive ? 'rgba(255, 77, 79, 0.95)' : 'var(--text-secondary)',
                  fontWeight: fallbackExecutionActive ? 700 : 500,
                }}
                title={fallbackExecutionActive
                  ? t('action_plan.execution.fallback_tooltip')
                  : t('action_plan.execution.actual_tooltip')}
              >
                {fallbackExecutionActive
                  ? t('action_plan.execution.fallback_label', { value: actualExecutionLabel })
                  : t('action_plan.execution.actual_label', { value: actualExecutionLabel })}
              </span>
            )}
          </label>

          <label
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '0.5rem',
              color: 'var(--text-secondary)',
              fontSize: '0.9rem',
            }}
          >
            <span>{t('common.reasoning')}</span>
            <select
              value={displayedReasoningEffort}
              onChange={handleReasoningEffortChange}
              disabled={isGenerating}
              style={{
                padding: '0.65rem 0.85rem',
                borderRadius: '8px',
                border: '1px solid var(--border-color)',
                background: 'var(--bg-surface)',
                color: 'var(--text-primary)',
                minWidth: '140px',
                cursor: isGenerating ? 'not-allowed' : 'pointer',
                opacity: isGenerating ? 0.65 : 1,
              }}
            >
              {reasoningOptions.map((option) => (
                <option key={option.value} value={option.value}>
                  {t(option.labelKey) || option.fallbackLabel}
                </option>
              ))}
            </select>
          </label>

          {fastModeSupported && (
            <label
              title={t('common.fast_mode_tooltip')}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '0.45rem',
                color: 'var(--text-secondary)',
                fontSize: '0.9rem',
                cursor: isGenerating ? 'not-allowed' : 'pointer',
                opacity: isGenerating ? 0.65 : 1,
              }}
            >
              <input
                type="checkbox"
                checked={fastModeEnabled}
                onChange={handleFastModeChange}
                disabled={isGenerating}
              />
              <span>{t('common.fast_mode')}</span>
            </label>
          )}

          <button
            onClick={isGenerating ? stopGeneration : startGeneration}
            disabled={!jobsReady || isSubmitting || isCancelling}
            style={{
              padding: '0.8rem 1.5rem',
              fontSize: '1rem',
              display: 'flex',
              alignItems: 'center',
              gap: '0.5rem',
              background: isGenerating ? '#ff4d4f' : 'var(--primary-color)',
              color: '#fff',
              border: 'none',
              borderRadius: '8px',
              cursor: 'pointer',
              transition: 'background 0.3s',
            }}
          >
            {isGenerating ? (
              <div style={{ width: 18, height: 18, background: 'white', borderRadius: 2 }} />
            ) : (
              <RotateCcw size={18} />
            )}
            {isGenerating ? t('action_plan.button.stop') : t('action_plan.button.regenerate')}
          </button>
        </div>
      </div>

      {promptContextWarning && (
        <div className="action-plan-context-warning" role="alert">
          <AlertTriangle size={18} />
          <div>
            <strong>{t('action_plan.context_limit.title')}</strong>
            <span>
              {t(promptContextWarning.estimated
                ? 'action_plan.context_limit.estimated_message'
                : 'action_plan.context_limit.message', {
                tokens: formatCompactTokenValue(promptContextWarning.observedPromptTokens),
                limit: formatCompactTokenValue(promptContextWarning.limit),
              })}
            </span>
          </div>
        </div>
      )}

      <div className={layoutMode === 'stacked' ? 'action-plan-stack' : 'action-plan-grid'}>
        <div
          className="glass-panel"
          style={{
            display: 'flex',
            flexDirection: 'column',
            overflow: layoutMode === 'stacked' ? 'visible' : 'hidden',
          }}
        >
          <div
            style={{
              padding: '0.8rem 1rem',
              borderBottom: '1px solid var(--border-color)',
              background: 'rgba(255,255,255,0.02)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              gap: '0.75rem',
            }}
          >
            <div className="action-plan-panel-header-main">
              <div className="action-plan-panel-title">
                <Activity size={16} color="var(--secondary-color)" />
                <h4 style={{ margin: 0, fontSize: '0.95rem' }}>{t('action_plan.panel.analysis')}</h4>
              </div>
              <ActionPlanRoundStats stats={analysisRoundStats} t={t} effectiveLanguage={effectiveLanguage} />
            </div>
            <ActionPlanCopyControls
              t={t}
              copiedKey={copiedKey}
              onCopy={copyActionPlanText}
              fullInputContent={analysisFullInputContent}
              fullInputKey="analysis-full-input"
              fullInputReady={Boolean(analysisFullInputContent)}
              promptContent={analysisPrompt}
              promptKey="analysis-prompt"
              replyContent={analysisContent}
              replyKey="analysis-reply"
              replyReady={analysisReplyReady}
            />
          </div>
          <div
            className="markdown-body compact-markdown custom-scrollbar"
            style={{
              flex: layoutMode === 'stacked' ? '0 0 auto' : 1,
              overflowY: layoutMode === 'stacked' ? 'visible' : 'auto',
              padding: '1rem',
            }}
          >
            {analysisThinking && <ThinkingBlock text={analysisThinking} title={analysisThinkingTitle} />}
            {renderActionPlanRoundNotice(analysisRoundNotice, t)}
            {renderMarkdownOrText(analysisRender, t)}
            <div ref={analysisEndRef} />
          </div>
        </div>

        <div
          className="glass-panel"
          style={{
            display: 'flex',
            flexDirection: 'column',
            overflow: layoutMode === 'stacked' ? 'visible' : 'hidden',
          }}
        >
          <div
            style={{
              padding: '0.8rem 1rem',
              borderBottom: '1px solid var(--border-color)',
              background: 'rgba(255,255,255,0.02)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              gap: '0.75rem',
            }}
          >
            <div className="action-plan-panel-header-main">
              <div className="action-plan-panel-title">
                <FileText size={16} color="var(--primary-color)" />
                <h4 style={{ margin: 0, fontSize: '0.95rem' }}>{t('action_plan.panel.today_plan')}</h4>
              </div>
              <ActionPlanRoundStats stats={planRoundStats} t={t} effectiveLanguage={effectiveLanguage} />
            </div>
            <ActionPlanCopyControls
              t={t}
              copiedKey={copiedKey}
              onCopy={copyActionPlanText}
              fullInputContent={planFullInputContent}
              fullInputKey="plan-full-input"
              fullInputReady={Boolean(planFullInputContent)}
              promptContent={planPrompt}
              promptKey="plan-prompt"
              replyContent={planContent}
              replyKey="plan-reply"
              replyReady={planReplyReady}
            />
          </div>
          <div
            className="markdown-body compact-markdown custom-scrollbar"
            style={{
              flex: layoutMode === 'stacked' ? '0 0 auto' : 1,
              overflowY: layoutMode === 'stacked' ? 'visible' : 'auto',
              padding: '1rem',
            }}
          >
            {planThinking && <ThinkingBlock text={planThinking} title={planThinkingTitle} />}
            {renderActionPlanRoundNotice(planRoundNotice, t)}
            {renderMarkdownOrText(planRender, t)}
            <div ref={planEndRef} />
          </div>
        </div>
      </div>
    </div>
  );
}

function formatDurationChipValue(value) {
  const formatted = formatSecondsValue(value);
  return formatted === '-' ? '-' : `${formatted}s`;
}

function formatGeneratedAtChipValue(value, language) {
  if (!value) {
    return '-';
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return '-';
  }
  return new Intl.DateTimeFormat(language === 'zh-CN' ? 'zh-CN' : 'en-US', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).format(date);
}

function formatRoundSpeedValue(stats) {
  const rawValue = stats?.completion_tokens_per_second ?? stats?.output_tokens_per_second;
  if (rawValue === null || rawValue === undefined) {
    return '-';
  }
  const value = Number(rawValue);
  if (!Number.isFinite(value)) {
    return '-';
  }
  return `${value.toFixed(2)} tokens/s`;
}

function ActionPlanRoundStats({ stats, t, effectiveLanguage }) {
  if (!stats) {
    return null;
  }

  const cacheBreakdown = formatActionPlanCacheBreakdown(stats);

  return (
    <div className="action-plan-round-stats">
      <span>{t('common.first_token', { value: formatDurationChipValue(stats.first_token_latency) })}</span>
      <span>{t('common.generated_at', { value: formatGeneratedAtChipValue(stats.completed_at, effectiveLanguage) })}</span>
      <span>{t('common.time', { value: formatSecondsValue(stats.duration) })}</span>
      <span>{t('common.tokens_detail', { value: formatActionPlanTokenBreakdown(stats) })}</span>
      {cacheBreakdown ? <span>{t('common.cache_request', { value: cacheBreakdown })}</span> : null}
      <span>{t('common.speed', { value: formatRoundSpeedValue(stats) })}</span>
    </div>
  );
}

function ThinkingBlock({ text, title }) {
  return (
    <details className="thinking-block">
      <summary className="thinking-header">
        <span
          className="thinking-dot"
          style={{
            width: '6px',
            height: '6px',
            borderRadius: '50%',
            background: 'var(--text-muted)',
          }}
        />
        {title}
      </summary>
      <div className="thinking-content">{text}</div>
    </details>
  );
}

function ActionPlanCopyControls({
  t,
  fullInputContent,
  fullInputReady,
  fullInputKey,
  promptContent,
  replyContent,
  replyReady,
  promptKey,
  replyKey,
  copiedKey,
  onCopy,
}) {
  return (
    <div className="action-plan-copy-controls">
      <button
        type="button"
        className={`action-plan-copy-button${copiedKey === fullInputKey ? ' is-copied' : ''}`}
        onClick={() => onCopy(fullInputContent, fullInputKey)}
        disabled={!fullInputReady}
      >
        {copiedKey === fullInputKey ? t('action_plan.copy.copied') : t('action_plan.copy.full_input')}
      </button>
      <button
        type="button"
        className={`action-plan-copy-button${copiedKey === promptKey ? ' is-copied' : ''}`}
        onClick={() => onCopy(promptContent, promptKey)}
        disabled={!promptContent}
      >
        {copiedKey === promptKey ? t('action_plan.copy.copied') : t('action_plan.copy.prompt')}
      </button>
      <button
        type="button"
        className={`action-plan-copy-button${copiedKey === replyKey ? ' is-copied' : ''}`}
        onClick={() => onCopy(replyContent, replyKey)}
        disabled={!replyReady || !replyContent}
      >
        {copiedKey === replyKey ? t('action_plan.copy.copied') : t('action_plan.copy.reply')}
      </button>
    </div>
  );
}
