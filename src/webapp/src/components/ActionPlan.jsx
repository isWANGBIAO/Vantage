import { useEffect, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { RotateCcw, FileText, CheckSquare, Activity } from 'lucide-react';
import {
  getActionPlanRenderState,
  splitActionPlanContent,
} from '../utils/actionPlanContent';
import {
  formatPoweredByLabel,
  formatReasoningEffortLabel,
} from '../utils/actionPlanStats';
import {
  createNdjsonLineBuffer,
  createStreamRenderScheduler,
  parseActionPlanStreamLog,
} from '../utils/actionPlanStream';

const WELCOME_ANALYSIS = [
  '### Welcome to Action Plan',
  '',
  'Click **Regenerate** to create today\'s analysis.',
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

export default function ActionPlan() {
  const [analysisContent, setAnalysisContent] = useState('');
  const [analysisThinking, setAnalysisThinking] = useState('');
  const [planContent, setPlanContent] = useState('');
  const [planThinking, setPlanThinking] = useState('');
  const [stats, setStats] = useState(null);
  const [isGenerating, setIsGenerating] = useState(false);

  const abortControllerRef = useRef(null);
  const analysisEndRef = useRef(null);
  const planEndRef = useRef(null);

  useEffect(() => {
    loadTodaysPlan();
  }, []);

  useEffect(() => {
    if (isGenerating && analysisContent) {
      analysisEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
  }, [analysisContent, isGenerating]);

  useEffect(() => {
    if (isGenerating && planContent) {
      planEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
  }, [planContent, isGenerating]);

  const applyLoadedContent = (rawContent) => {
    const sections = splitActionPlanContent(rawContent);
    const nextAnalysis = sections.analysis || LEGACY_ANALYSIS;
    const nextPlan = sections.plan || WELCOME_PLAN;

    setAnalysisContent(nextAnalysis);
    setPlanContent(nextPlan);
  };

  const loadTodaysPlan = async () => {
    try {
      const res = await fetch('http://localhost:8000/api/action_plan/today');
      const data = await res.json();

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

      setAnalysisContent(WELCOME_ANALYSIS);
      setPlanContent(WELCOME_PLAN);
    } catch (err) {
      console.error('Failed to load today plan:', err);
      setAnalysisContent(LOAD_ERROR_ANALYSIS);
      setPlanContent(WELCOME_PLAN);
    }
  };

  const stopGeneration = () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }

    setIsGenerating(false);
    setPlanContent((prev) => `${prev}\n\n> Generation stopped by user.`);
  };

  const startGeneration = async () => {
    if (isGenerating) {
      stopGeneration();
    }

    setIsGenerating(true);
    setAnalysisThinking('');
    setPlanThinking('');
    setAnalysisContent('### Analyzing data\n\nStreaming analysis output...');
    setPlanContent('### Waiting for analysis\n\nThe action plan will start once the first pass completes.');
    setStats({
      speed: '0 t/s',
      total_duration: 0,
      total_tokens: 0,
      startTime: Date.now(),
    });

    abortControllerRef.current = new AbortController();
    const signal = abortControllerRef.current.signal;
    let currentSection = 'analysis';

    try {
      const response = await fetch('http://localhost:8000/api/action_plan', {
        method: 'POST',
        signal,
      });

      if (!response.body) {
        throw new Error('No response body');
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      const lineBuffer = createNdjsonLineBuffer();
      const waitForRender = createStreamRenderScheduler();

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
            setAnalysisContent('');
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
            } else if (sectionedLog.kind === 'content') {
              if (sectionedLog.section === 'analysis') {
                setAnalysisContent((prev) => prev + sectionedLog.content);
              } else {
                setPlanContent((prev) => prev + sectionedLog.content);
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
                setAnalysisContent((prev) => `${prev}\n\nError: ${sectionedLog.content}`);
              } else {
                setPlanContent((prev) => `${prev}\n\nError: ${sectionedLog.content}`);
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
            setPlanContent('');
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
              setAnalysisContent((prev) => prev + content);
            } else {
              setPlanContent((prev) => prev + content);
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
            setAnalysisContent((prev) => prev + `${log}\n`);
          } else {
            setPlanContent((prev) => prev + `${log}\n`);
          }
          shouldYieldRender = true;
        } catch {
          if (currentSection === 'analysis') {
            setAnalysisContent((prev) => prev + `${line}\n`);
          } else {
            setPlanContent((prev) => prev + `${line}\n`);
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
    } catch (err) {
      if (err.name === 'AbortError') {
        console.log('Generation aborted');
      } else {
        setPlanContent((prev) => `${prev}\n\nError: ${err.message}`);
      }
    } finally {
      if (abortControllerRef.current?.signal === signal) {
        setIsGenerating(false);
        abortControllerRef.current = null;
      }
    }
  };

  const analysisRender = getActionPlanRenderState(analysisContent);
  const planRender = getActionPlanRenderState(planContent);
  const poweredByLabel = formatPoweredByLabel(stats);
  const reasoningEffortLabel = formatReasoningEffortLabel(stats?.reasoning_effort);

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
              {poweredByLabel && <span>Powered by {poweredByLabel}</span>}
              {reasoningEffortLabel && <span>Thinking {reasoningEffortLabel}</span>}
            </div>
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
              gap: '0.5rem',
            }}
          >
            <Activity size={16} color="var(--secondary-color)" />
            <h4 style={{ margin: 0, fontSize: '0.95rem' }}>General Analysis</h4>
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
              gap: '0.5rem',
            }}
          >
            <FileText size={16} color="var(--primary-color)" />
            <h4 style={{ margin: 0, fontSize: '0.95rem' }}>Today&apos;s Action Plan</h4>
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
