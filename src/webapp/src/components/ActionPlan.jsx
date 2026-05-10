import { useEffect, useRef, useState, useCallback } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { RotateCcw, FileText, CheckSquare, Activity } from 'lucide-react';
import { getActionPlanRenderState } from '../utils/actionPlanContent';
import {
  getReasoningOptionsForModel,
  loadStoredActionPlanReasoningEffort,
  normalizeReasoningEffortForModel,
  saveActionPlanReasoningEffort,
} from '../utils/actionPlanReasoning';
import {
  buildActionPlanGenerationPayload,
  shouldAutogenerateActionPlan,
} from '../utils/actionPlanGeneration';
import {
  formatModelReasoningSupportLabel,
  parseModelReasoningSupport,
} from '../utils/modelReasoningSupport';
import {
  computeDisplayedDurationSeconds,
  formatActionPlanCacheBreakdown,
  formatActionPlanTokenBreakdown,
  formatSecondsValue,
  formatThinkingTitleWithDuration,
  formatPoweredByLabel,
  getActionPlanRoundStats,
  isActionPlanRoundPossiblyIncomplete,
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
  resolveFastServiceTier,
  saveFastModeEnabled,
} from '../utils/modelServiceTier';
import {
  createNdjsonLineBuffer,
  createStreamRenderScheduler,
  parseActionPlanStreamLog,
} from '../utils/actionPlanStream';
import { CHAT_CONTEXT_BASE_UPDATED_EVENT } from '../utils/chatContextState';
import { fetchBackend, fetchBackendJson } from '../utils/backendRequest';
import { loadSettingsState } from '../utils/settingsState';
import { useDisplayLanguage } from '../context/DisplayLanguageContext.jsx';

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
  const [liveDurationNowMs, setLiveDurationNowMs] = useState(() => Date.now());

  const abortControllerRef = useRef(null);
  const loadAbortControllerRef = useRef(null);
  const startupGenerationTriggeredRef = useRef(false);
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
  selectedReasoningEffortRef.current = normalizeReasoningEffortForModel(
    selectedReasoningEffort,
    selectedModelOption?.model,
  );
  fastModeEnabledRef.current = fastModeEnabled;

  const setAnalysisContentWithRef = useCallback((value) => {
    if (typeof value === 'function') {
      setAnalysisContent((prev) => {
        const nextContent = value(prev);
        analysisContentRef.current = nextContent;
        return nextContent;
      });
      return;
    }

    analysisContentRef.current = value;
    setAnalysisContent(value);
  }, []);

  const setPlanContentWithRef = useCallback((value) => {
    if (typeof value === 'function') {
      setPlanContent((prev) => {
        const nextContent = value(prev);
        planContentRef.current = nextContent;
        return nextContent;
      });
      return;
    }

    planContentRef.current = value;
    setPlanContent(value);
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

  const applyLoadedActionPlan = useCallback((data) => {
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
    setAnalysisThinking('');
    setPlanContentWithRef(
      planBody || buildMarkdownPlaceholder(
        t('action_plan.placeholder.plan_unavailable.title'),
        t('action_plan.placeholder.plan_unavailable.body'),
      ),
    );
    setPlanThinking('');
    setSystemPrompt(savedInput.system_prompt || '');
    setAnalysisPrompt(savedInput.analysis_prompt || '');
    setPlanPrompt(savedInput.plan_prompt || '');
    setAnalysisReplyReady(Boolean(analysisBody));
    setPlanReplyReady(Boolean(planBody));
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
      const data = await fetchBackendJson('/api/action_plan/today', {
        retryPolicy: 'load',
        signal,
      });

      if (loadAbortControllerRef.current?.signal !== signal) {
        return { aborted: true };
      }

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

  const stopGeneration = useCallback(() => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }

    setIsGenerating(false);
    setPlanContentWithRef((prev) => `${prev}\n\n> ${t('action_plan.placeholder.stopped')}`);
  }, [setPlanContentWithRef, t]);

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
      const data = await fetchBackendJson('/api/chat/context', {
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

  const startGeneration = useCallback(async ({
    replaceToday = false,
    modelOverride = null,
    waitForProviderReady = false,
  } = {}) => {
    if (isGeneratingRef.current) {
      stopGeneration();
    }

    if (loadAbortControllerRef.current) {
      loadAbortControllerRef.current.abort();
      loadAbortControllerRef.current = null;
    }

    setIsGenerating(true);
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
    const effectiveModelOption = modelOverride || selectedModelRef.current;
    const effectiveReasoningEffort = normalizeReasoningEffortForModel(
      selectedReasoningEffortRef.current,
      effectiveModelOption?.model,
    );
    const effectiveFastModeEnabled = fastModeEnabledRef.current
      && isFastModeSupportedForModel(effectiveModelOption?.model);
    const effectiveServiceTier = resolveFastServiceTier({
      fastModeEnabled: effectiveFastModeEnabled,
      model: effectiveModelOption?.model,
    });

    setStats({
      speed: '0 t/s',
      total_duration: 0,
      total_tokens: 0,
      startTime: Date.now(),
      reasoning_effort: effectiveReasoningEffort,
      service_tier: effectiveServiceTier,
    });

    abortControllerRef.current = new AbortController();
    const signal = abortControllerRef.current.signal;
    let currentSection = 'analysis';

    try {
      const response = await fetchBackend('/api/action_plan', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(
          buildActionPlanGenerationPayload(effectiveReasoningEffort, {
            replaceToday,
            model: effectiveModelOption?.model,
            providerRoute: effectiveModelOption?.provider_route,
            fastModeEnabled: effectiveFastModeEnabled,
            startupAutoGenerate: waitForProviderReady,
          }),
        ),
        signal,
        retryPolicy: 'stream',
      });

      if (!response.body) {
        throw new Error('No response body');
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      const lineBuffer = createNdjsonLineBuffer();
      const waitForRender = createStreamRenderScheduler({
        shouldYield: () => {
          if (!visibilityRef.current) {
            return false;
          }

          return !(typeof document !== 'undefined' && document.hidden);
        },
      });

      const processStreamLine = async (line) => {
        let shouldYieldRender = false;

        if (!line.trim()) {
          return;
        }

        try {
          const data = JSON.parse(line);
          let { log } = data;

          if (!log) {
            return;
          }

          if (log.startsWith('STATS_JSON:')) {
            try {
              const jsonStr = log.replace('STATS_JSON:', '').trim();
              const newStats = JSON.parse(jsonStr);
              setStats((prev) => ({ ...prev, ...newStats }));
            } catch (err) {
              console.error('Stats parse error', err);
            }
            return;
          }

          const sectionedLog = parseActionPlanStreamLog(log);
          if (sectionedLog) {
            if (
              sectionedLog.kind === 'start' ||
              sectionedLog.kind === 'metadata' ||
              sectionedLog.kind === 'thinking' ||
              sectionedLog.kind === 'content' ||
              sectionedLog.kind === 'error'
            ) {
              currentSection = sectionedLog.section;
            }

            if (sectionedLog.kind === 'start') {
              if (sectionedLog.section === 'analysis') {
                setAnalysisContentWithRef('');
                setAnalysisThinking('');
                setAnalysisReplyReady(false);
              } else {
                setAnalysisReplyReady(Boolean(analysisContentRef.current.trim()));
                setPlanContentWithRef('');
                setPlanThinking('');
                setPlanReplyReady(false);
              }
              shouldYieldRender = true;
            } else if (sectionedLog.kind === 'thinking') {
              if (sectionedLog.section === 'analysis') {
                setAnalysisThinking((prev) => prev + sectionedLog.content);
              } else {
                setPlanThinking((prev) => prev + sectionedLog.content);
              }
              shouldYieldRender = true;
            } else if (sectionedLog.kind === 'system') {
              setSystemPrompt((prev) => prev + sectionedLog.content);
              shouldYieldRender = true;
            } else if (sectionedLog.kind === 'prompt') {
              if (sectionedLog.section === 'analysis') {
                setAnalysisPrompt((prev) => prev + sectionedLog.content);
              } else {
                setPlanPrompt((prev) => prev + sectionedLog.content);
              }
              shouldYieldRender = true;
            } else if (sectionedLog.kind === 'metadata') {
              if (sectionedLog.content && typeof sectionedLog.content === 'object') {
                setStats((prev) => ({ ...prev, ...sectionedLog.content }));
              }
              shouldYieldRender = true;
            } else if (sectionedLog.kind === 'content') {
              if (sectionedLog.section === 'analysis') {
                setAnalysisContentWithRef((prev) => prev + sectionedLog.content);
              } else {
                setPlanContentWithRef((prev) => prev + sectionedLog.content);
              }

              const estimatedTokens = Math.max(1, Math.ceil(sectionedLog.content.length * 0.7));
              setStats((prev) => {
                const startTime = prev?.startTime || Date.now();
                const duration = (Date.now() - startTime) / 1000;
                const totalTokens = (prev?.total_tokens || 0) + estimatedTokens;
                const speed = duration > 0 ? `${(totalTokens / duration).toFixed(2)} t/s` : '0.00 t/s';

                return {
                  ...prev,
                  startTime,
                  total_tokens: totalTokens,
                  total_duration: duration,
                  speed,
                };
              });
              shouldYieldRender = true;
            } else if (sectionedLog.kind === 'error') {
              if (sectionedLog.section === 'analysis') {
                setAnalysisContentWithRef((prev) => `${prev}\n\n${t('common.error_prefix', { error: sectionedLog.content })}`);
              } else {
                setPlanContentWithRef((prev) => `${prev}\n\n${t('common.error_prefix', { error: sectionedLog.content })}`);
              }
              shouldYieldRender = true;
            }

            if (shouldYieldRender) {
              await waitForRender();
            }
            return;
          }

          if (log.startsWith('STREAM_DONE:') || log.startsWith('STREAM_ERROR:')) {
            return;
          }

          if (currentSection === 'analysis') {
            setAnalysisContentWithRef((prev) => prev + `${log}\n`);
          } else {
            setPlanContentWithRef((prev) => prev + `${log}\n`);
          }
          shouldYieldRender = true;
        } catch {
          if (currentSection === 'analysis') {
            setAnalysisContentWithRef((prev) => prev + `${line}\n`);
          } else {
            setPlanContentWithRef((prev) => prev + `${line}\n`);
          }
          shouldYieldRender = true;
        }

        if (shouldYieldRender) {
          await waitForRender();
        }
      };

      while (true) {
        const { value, done } = await reader.read();
        if (done) {
          break;
        }

        const chunk = decoder.decode(value, { stream: true });
        const lines = lineBuffer.push(chunk);

        for (const line of lines) {
          await processStreamLine(line);
        }
      }

      const trailingChunk = decoder.decode();
      if (trailingChunk) {
        const trailingLines = lineBuffer.push(trailingChunk);
        for (const line of trailingLines) {
          await processStreamLine(line);
        }
      }

      const finalLines = lineBuffer.flush();
      for (const line of finalLines) {
        await processStreamLine(line);
      }

      setAnalysisReplyReady(Boolean(analysisContentRef.current.trim()));
      setPlanReplyReady(Boolean(planContentRef.current.trim()));
      await refreshChatContextBase();
    } catch (err) {
      if (err.name !== 'AbortError') {
        setPlanContentWithRef((prev) => `${prev}\n\n${t('common.error_prefix', { error: err.message })}`);
      }
    } finally {
      if (abortControllerRef.current?.signal === signal) {
        setIsGenerating(false);
        abortControllerRef.current = null;
      }
    }
  }, [
    refreshChatContextBase,
    setAnalysisContentWithRef,
    setPlanContentWithRef,
    stopGeneration,
    t,
  ]);

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
        const data = await fetchBackendJson('/api/llm_models', { retryPolicy: 'load' });
        return applyModelCatalog(data);
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

    const loadStartupAutoGenerateEnabled = async () => {
      try {
        const settingsState = await loadSettingsState();
        return settingsState.settings?.actionPlanAutoGenerate !== false;
      } catch (error) {
        console.warn('Failed to load Action Plan startup setting:', error);
        return true;
      }
    };

    const initializeActionPlan = async () => {
      const [initialModel, autoGenerateEnabled] = await Promise.all([
        initializeModels(),
        loadStartupAutoGenerateEnabled(),
      ]);
      const loadResult = await loadTodaysPlan(controller.signal);

      if (!shouldAutogenerateActionPlan({
        autoGenerateEnabled,
        hasTriggered: startupGenerationTriggeredRef.current,
        isGenerating: isGeneratingRef.current,
        isAborted: controller.signal.aborted,
        hasExistingPlan: loadResult?.exists === true,
        loadFailed: Boolean(loadResult?.error),
      })) {
        return;
      }

      startupGenerationTriggeredRef.current = true;
      await startGeneration({
        replaceToday: true,
        modelOverride: initialModel,
        waitForProviderReady: true,
      });
    };

    void initializeActionPlan();

    const handleModelCatalogUpdated = (event) => {
      applyModelCatalog(event.detail);
    };
    window.addEventListener('vantage:llm-models-updated', handleModelCatalogUpdated);

    return () => {
      window.removeEventListener('vantage:llm-models-updated', handleModelCatalogUpdated);
      controller.abort();
      if (loadAbortControllerRef.current?.signal === controller.signal) {
        loadAbortControllerRef.current = null;
      }
    };
  }, [loadTodaysPlan, setAnalysisContentWithRef, setPlanContentWithRef, startGeneration, t]);

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
  const analysisPossiblyIncomplete = isActionPlanRoundPossiblyIncomplete(
    stats,
    'analysis',
    analysisContent,
  );
  const planPossiblyIncomplete = isActionPlanRoundPossiblyIncomplete(
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
  const reasoningOptions = getReasoningOptionsForModel(selectedModelOption?.model);
  const fastModeSupported = isFastModeSupportedForModel(selectedModelOption?.model);
  const displayedReasoningEffort = normalizeReasoningEffortForModel(
    selectedReasoningEffort,
    selectedModelOption?.model,
  );

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
        </div>

        <div style={{ display: 'flex', gap: '1rem', alignItems: 'center', flexWrap: 'wrap' }}>
          {stats && (
            <div className="action-plan-stats">
              <span>{t('common.first_token', { value: formatDurationChipValue(stats.first_token_latency) })}</span>
              <span>{t('common.speed', { value: stats.speed })}</span>
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
            {analysisPossiblyIncomplete && (
              <div className="action-plan-warning">
                {t('action_plan.render.incomplete')}
              </div>
            )}
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
            {planPossiblyIncomplete && (
              <div className="action-plan-warning">
                {t('action_plan.render.incomplete')}
              </div>
            )}
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
