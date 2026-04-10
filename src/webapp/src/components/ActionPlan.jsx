import { useEffect, useRef, useState, useCallback } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { RotateCcw, FileText, CheckSquare, Activity } from 'lucide-react';
import {
  getActionPlanRenderState,
  splitActionPlanContent,
} from '../utils/actionPlanContent';
import {
  ACTION_PLAN_REASONING_OPTIONS,
  loadStoredActionPlanReasoningEffort,
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
  createNdjsonLineBuffer,
  createStreamRenderScheduler,
  parseActionPlanStreamLog,
} from '../utils/actionPlanStream';
import { CHAT_CONTEXT_BASE_UPDATED_EVENT } from '../utils/chatContextState';
import { fetchBackend, fetchBackendJson } from '../utils/backendRequest';

const COPY_FEEDBACK_DURATION_MS = 1500;

const WELCOME_ANALYSIS = [
  '### Welcome to Action Plan',
  '',
  'Today\'s analysis starts automatically on app launch. Click **Regenerate** to run it again.',
].join('\n');

const WELCOME_PLAN = [
  '### Waiting for generation',
  '',
  'Today\'s action items will appear here after the run completes.',
].join('\n');

const LEGACY_ANALYSIS = [
  '### Historical plan loaded',
  '',
  'This record uses the old single-section format, so no standalone analysis is available.',
].join('\n');

const LOAD_ERROR_ANALYSIS = [
  '### Load failed',
  '',
  'The page could not reach the backend service. Refresh and try again.',
].join('\n');

const CONNECTING_ANALYSIS = [
  '### Connecting to backend',
  '',
  'Waiting for the backend service to start...',
].join('\n');

function renderMarkdownOrText(contentState) {
  if (contentState.plainText) {
    return (
      <>
        <div className="action-plan-warning">
          Corrupted historical formatting was detected. Showing a safe plain-text view.
        </div>
        <div className="action-plan-plain-text">
          {contentState.plainTextContent || 'No content available.'}
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

export default function ActionPlan({ isVisible = true }) {
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
  const [stats, setStats] = useState(null);
  const [availableModels, setAvailableModels] = useState([]);
  const [modelReasoningSupport, setModelReasoningSupport] = useState({});
  const [selectedModel, setSelectedModel] = useState('');
  const [isGenerating, setIsGenerating] = useState(false);

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
  const selectedModelRef = useRef(selectedModel);
  const selectedReasoningEffortRef = useRef(selectedReasoningEffort);

  visibilityRef.current = isVisible;
  isGeneratingRef.current = isGenerating;
  selectedModelRef.current = selectedModel;
  selectedReasoningEffortRef.current = selectedReasoningEffort;

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

  const applyLoadedContent = useCallback((rawContent) => {
    const sections = splitActionPlanContent(rawContent);
    const nextAnalysis = sections.analysis || LEGACY_ANALYSIS;
    const nextPlan = sections.plan || WELCOME_PLAN;

    setAnalysisContentWithRef(nextAnalysis);
    setPlanContentWithRef(nextPlan);
    setSystemPrompt('');
    setAnalysisPrompt('');
    setPlanPrompt('');
    setAnalysisReplyReady(Boolean(sections.analysis));
    setPlanReplyReady(Boolean(sections.plan));
    setCopiedKey('');
  }, []);

  const copyActionPlanText = useCallback(async (content, key) => {
    if (
      !content ||
      !globalThis.navigator?.clipboard ||
      typeof globalThis.navigator.clipboard.writeText !== 'function'
    ) {
      return;
    }

    try {
      await globalThis.navigator.clipboard.writeText(content);
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
        return;
      }

      if (data.exists && data.content) {
        applyLoadedContent(data.content);
        setStats({
          speed: 'loaded',
          total_duration: 0,
          total_tokens: 0,
          historical_total_tokens: undefined,
        });
        return;
      }

        setAnalysisContentWithRef(WELCOME_ANALYSIS);
        setPlanContentWithRef(WELCOME_PLAN);
    } catch (err) {
      if (err.name === 'AbortError') {
        return;
      }

      console.error('Failed to load today plan:', err);
      setAnalysisContentWithRef(LOAD_ERROR_ANALYSIS);
      setPlanContentWithRef(WELCOME_PLAN);
    } finally {
      if (loadAbortControllerRef.current?.signal === signal) {
        loadAbortControllerRef.current = null;
      }
    }
  }, [applyLoadedContent]);

  const stopGeneration = useCallback(() => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }

    setIsGenerating(false);
    setPlanContentWithRef((prev) => `${prev}\n\n> Generation stopped by user.`);
  }, []);

  const handleReasoningEffortChange = (event) => {
    const nextValue = saveActionPlanReasoningEffort(event.target.value);
    setSelectedReasoningEffort(nextValue);
  };

  const handleModelChange = (event) => {
    const nextModel = event.target.value;
    setSelectedModel(nextModel);
    localStorage.setItem('preferred_llm_model', nextModel);
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
        },
      }));
    } catch (error) {
      console.error('Failed to refresh chat context base:', error);
    }
  }, []);

  const startGeneration = useCallback(async ({ replaceToday = false, modelOverride = null } = {}) => {
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
    setAnalysisContentWithRef('### Analyzing data\n\nStreaming analysis output...');
    setPlanContentWithRef('### Waiting for analysis\n\nThe action plan will start once the first pass completes.');
    const effectiveReasoningEffort = selectedReasoningEffortRef.current;

    setStats({
      speed: '0 t/s',
      total_duration: 0,
      total_tokens: 0,
      startTime: Date.now(),
      reasoning_effort: effectiveReasoningEffort,
    });

    abortControllerRef.current = new AbortController();
    const signal = abortControllerRef.current.signal;
    let currentSection = 'analysis';
    const effectiveModel = modelOverride || selectedModelRef.current;

    try {
      const response = await fetchBackend('/api/action_plan', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(
          buildActionPlanGenerationPayload(effectiveReasoningEffort, {
            replaceToday,
            model: effectiveModel,
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

          if (log.includes('---ANALYSIS_START---')) {
            setAnalysisContentWithRef('');
            setAnalysisThinking('');
            const parts = log.split('---ANALYSIS_START---');
            if (parts[1]) {
              log = parts[1];
            } else {
              return;
            }
          }

          const sectionedLog = parseActionPlanStreamLog(log);
          if (sectionedLog) {
            currentSection = sectionedLog.section;

            if (sectionedLog.kind === 'thinking') {
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
                setAnalysisContentWithRef((prev) => `${prev}\n\nError: ${sectionedLog.content}`);
              } else {
                setPlanContentWithRef((prev) => `${prev}\n\nError: ${sectionedLog.content}`);
              }
              shouldYieldRender = true;
            }

            if (shouldYieldRender) {
              await waitForRender();
            }
            return;
          }

          if (
            log.includes("Today's Action Plan") ||
            log.includes('---PLAN_START---')
          ) {
            currentSection = 'plan';
            setAnalysisReplyReady(Boolean(analysisContentRef.current.trim()));
            setPlanContentWithRef('');
            setPlanThinking('');
            return;
          }

          if (log.startsWith('STREAM_THINKING:')) {
            const raw = log.replace('STREAM_THINKING:', '');
            try {
              const thought = JSON.parse(raw);
              if (currentSection === 'analysis') {
                setAnalysisThinking((prev) => prev + thought);
              } else {
                setPlanThinking((prev) => prev + thought);
              }
            } catch {
              if (currentSection === 'analysis') {
                setAnalysisThinking((prev) => prev + raw);
              } else {
                setPlanThinking((prev) => prev + raw);
              }
            }
            await waitForRender();
            return;
          }

          if (log.startsWith('STREAM_CONTENT:')) {
            const raw = log.replace('STREAM_CONTENT:', '');
            let content = raw;

            try {
              content = JSON.parse(raw);
            } catch {
              content = raw;
            }

            if (currentSection === 'analysis') {
              setAnalysisContentWithRef((prev) => prev + content);
            } else {
              setPlanContentWithRef((prev) => prev + content);
            }

            const estimatedTokens = Math.max(1, Math.ceil(content.length * 0.7));
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
            await waitForRender();
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
      if (err.name === 'AbortError') {
        console.log('Generation aborted');
      } else {
        setPlanContentWithRef((prev) => `${prev}\n\nError: ${err.message}`);
      }
    } finally {
      if (abortControllerRef.current?.signal === signal) {
        setIsGenerating(false);
        abortControllerRef.current = null;
      }
    }
  }, [refreshChatContextBase, stopGeneration]);

  useEffect(() => {
    const initializeModels = async () => {
      try {
        const data = await fetchBackendJson('/api/llm_models', { retryPolicy: 'load' });
        const modelList = Array.isArray(data?.models) ? data.models : [];
        setAvailableModels(modelList);
        setModelReasoningSupport(parseModelReasoningSupport(data?.providers));

        const storageModel = localStorage.getItem('preferred_llm_model');
        if (modelList.length > 0) {
          const nextModel = modelList.includes(storageModel) ? storageModel : modelList[0];
          setSelectedModel(nextModel);
          return nextModel;
        }
      } catch (error) {
        console.error('Failed to load model list:', error);
      }

      return null;
    };

    const controller = new AbortController();
    loadAbortControllerRef.current = controller;
    setAnalysisContentWithRef(CONNECTING_ANALYSIS);
    setPlanContentWithRef(WELCOME_PLAN);

    const initializeActionPlan = async () => {
      const initialModel = await initializeModels();
      await loadTodaysPlan(controller.signal);

      if (!shouldAutogenerateActionPlan({
        hasTriggered: startupGenerationTriggeredRef.current,
        isGenerating: isGeneratingRef.current,
        isAborted: controller.signal.aborted,
      })) {
        return;
      }

      startupGenerationTriggeredRef.current = true;
      await startGeneration({ replaceToday: true, modelOverride: initialModel });
    };

    void initializeActionPlan();

    return () => {
      controller.abort();
      if (loadAbortControllerRef.current?.signal === controller.signal) {
        loadAbortControllerRef.current = null;
      }
    };
  }, [loadTodaysPlan, setAnalysisContentWithRef, setPlanContentWithRef, startGeneration]);

  const analysisRender = getActionPlanRenderState(analysisContent);
  const planRender = getActionPlanRenderState(planContent);
  const analysisFullInputContent = buildAnalysisFullInput(systemPrompt, analysisPrompt);
  const planFullInputContent = buildPlanFullInput(
    systemPrompt,
    analysisPrompt,
    analysisContent,
    planPrompt,
  );
  const modelReasoningSupportLabel = formatModelReasoningSupportLabel(selectedModel, modelReasoningSupport);

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: '1rem',
        height: '100%',
        overflow: 'hidden',
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
            Action Plan
          </h2>
          <p style={{ margin: 0, color: 'var(--text-secondary)', fontSize: '0.85rem' }}>
            Daily analysis and task generation
          </p>
        </div>

        <div style={{ display: 'flex', gap: '1rem', alignItems: 'center', flexWrap: 'wrap' }}>
          {stats && (
            <div className="action-plan-stats">
              <span>Speed {stats.speed}</span>
              <span>Time {(stats.total_duration || 0).toFixed(1)}s</span>
              <span>Tokens {((stats.total_tokens || 0) / 1000).toFixed(1)}k</span>
              {stats.historical_total_tokens !== undefined && (
                <span>
                  History {stats.historical_total_tokens >= 1000000
                    ? `${(stats.historical_total_tokens / 1000000).toFixed(2)}M`
                    : `${(stats.historical_total_tokens / 1000).toFixed(1)}k`}
                </span>
              )}
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
            <span>Model</span>
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
              {availableModels.map((model) => (
                <option key={model} value={model}>
                  {model}
                </option>
              ))}
            </select>
            {modelReasoningSupportLabel && (
              <span style={{ color: 'rgba(255, 77, 79, 0.95)' }}>
                {modelReasoningSupportLabel}
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
            <span>Reasoning</span>
            <select
              value={selectedReasoningEffort}
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
              {ACTION_PLAN_REASONING_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>

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
            {isGenerating ? 'Stop' : 'Regenerate'}
          </button>
        </div>
      </div>

      <div className="action-plan-grid">
        <div className="glass-panel" style={{ display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
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
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', minWidth: 0 }}>
              <Activity size={16} color="var(--secondary-color)" />
              <h4 style={{ margin: 0, fontSize: '0.95rem' }}>General Analysis</h4>
            </div>
            <ActionPlanCopyControls
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
            style={{ flex: 1, overflowY: 'auto', padding: '1rem' }}
          >
            {analysisThinking && <ThinkingBlock text={analysisThinking} />}
            {renderMarkdownOrText(analysisRender)}
            <div ref={analysisEndRef} />
          </div>
        </div>

        <div className="glass-panel" style={{ display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
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
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', minWidth: 0 }}>
              <FileText size={16} color="var(--primary-color)" />
              <h4 style={{ margin: 0, fontSize: '0.95rem' }}>Today&apos;s Action Plan</h4>
            </div>
            <ActionPlanCopyControls
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
            style={{ flex: 1, overflowY: 'auto', padding: '1rem' }}
          >
            {planThinking && <ThinkingBlock text={planThinking} />}
            {renderMarkdownOrText(planRender)}
            <div ref={planEndRef} />
          </div>
        </div>
      </div>
    </div>
  );
}

function ThinkingBlock({ text }) {
  return (
    <div className="thinking-block">
      <div className="thinking-header">
        <div
          className="thinking-dot"
          style={{
            width: '6px',
            height: '6px',
            borderRadius: '50%',
            background: 'var(--text-muted)',
          }}
        />
        Analysis Process
      </div>
      {text}
    </div>
  );
}

function ActionPlanCopyControls({
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
        {copiedKey === fullInputKey ? 'Copied' : 'Copy Full Input'}
      </button>
      <button
        type="button"
        className={`action-plan-copy-button${copiedKey === promptKey ? ' is-copied' : ''}`}
        onClick={() => onCopy(promptContent, promptKey)}
        disabled={!promptContent}
      >
        {copiedKey === promptKey ? 'Copied' : 'Copy Prompt'}
      </button>
      <button
        type="button"
        className={`action-plan-copy-button${copiedKey === replyKey ? ' is-copied' : ''}`}
        onClick={() => onCopy(replyContent, replyKey)}
        disabled={!replyReady || !replyContent}
      >
        {copiedKey === replyKey ? 'Copied' : 'Copy Reply'}
      </button>
    </div>
  );
}
