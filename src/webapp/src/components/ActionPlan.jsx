import { useState, useRef, useEffect } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { RotateCcw, FileText, CheckSquare, Activity } from 'lucide-react';

export default function ActionPlan() {
    const [analysisContent, setAnalysisContent] = useState('');
    const [analysisThinking, setAnalysisThinking] = useState('');
    const [planContent, setPlanContent] = useState('');
    const [planThinking, setPlanThinking] = useState('');

    // Stats
    const [stats, setStats] = useState(null);
    const [isGenerating, setIsGenerating] = useState(false);

    const abortControllerRef = useRef(null);
    const analysisEndRef = useRef(null);
    const planEndRef = useRef(null);

    // Initial load - Check history first, then generate if needed
    useEffect(() => {
        loadTodaysPlan();
    }, []);

    // Auto-scroll effect
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

    const loadTodaysPlan = async () => {
        try {
            const res = await fetch('http://localhost:8000/api/action_plan/today');
            const data = await res.json();

            if (data.exists && data.content) {
                // Parse the content - it contains both analysis and plan sections
                const content = data.content;

                // Check for our new separator format: ---ANALYSIS_END---
                if (content.includes('---ANALYSIS_END---')) {
                    const parts = content.split('---ANALYSIS_END---');
                    setAnalysisContent(parts[0].trim());
                    setPlanContent(parts[1].trim());
                }
                // Legacy format with ---PLAN_START---
                else if (content.includes('---PLAN_START---')) {
                    const parts = content.split('---PLAN_START---');
                    setAnalysisContent(parts[0].replace('---ANALYSIS_START---', '').trim());
                    setPlanContent(parts[1].trim());
                }
                // Single section - assume it's the plan (old files before dual-save)
                else {
                    setPlanContent(content);
                    setAnalysisContent('### 📁 历史计划已加载\n\n此文件为旧版格式，仅包含今日计划。\n\n点击 **Regenerate** 可重新生成完整的分析与计划。');
                }

                setStats({
                    speed: "loaded",
                    total_duration: 0,
                    total_tokens: 0,
                    historical_total_tokens: undefined
                });
            } else {
                // No history - show welcome message
                setAnalysisContent('### 👋 欢迎使用 Action Plan\n\n点击右上角的 **Regenerate** 按钮生成今日计划。');
                setPlanContent('### ⏳ 等待生成...\n\n生成后，今日的行动计划将显示在这里。');
            }
        } catch (err) {
            console.error('Failed to load today plan:', err);
            setAnalysisContent('### ⚠️ 加载失败\n\n无法连接到后端服务，请刷新页面重试。');
        }
    };

    const stopGeneration = () => {
        if (abortControllerRef.current) {
            abortControllerRef.current.abort();
            abortControllerRef.current = null;
        }
        setIsGenerating(false);
        setPlanContent(prev => prev + '\n\n> [!CAUTION]\n> Generation stopped by user.');
    };

    const startGeneration = async () => {
        // Stop any previous run
        if (isGenerating) {
            stopGeneration();
        }

        setIsGenerating(true);
        setAnalysisContent('### ⏳ Analyzing Data...\n\n');
        setPlanContent('### ⏳ Waiting for Analysis...\n\n');
        setStats({ speed: "0 t/s", total_duration: 0, total_tokens: 0, startTime: Date.now() });

        // Create new controller
        abortControllerRef.current = new AbortController();
        const signal = abortControllerRef.current.signal;

        let currentSection = 'analysis';

        try {
            const response = await fetch('http://localhost:8000/api/action_plan', {
                method: 'POST',
                signal: signal
            });

            if (!response.body) throw new Error('No response body');

            const reader = response.body.getReader();
            const decoder = new TextDecoder();

            while (true) {
                const { value, done } = await reader.read();
                if (done) break;

                const chunk = decoder.decode(value, { stream: true });
                const lines = chunk.split('\n');

                lines.forEach(line => {
                    if (!line.trim()) return;

                    try {
                        const data = JSON.parse(line);
                        let log = data.log;

                        if (log) {
                            // 1. Check for Stats
                            if (log.startsWith("STATS_JSON:")) {
                                try {
                                    const jsonStr = log.replace("STATS_JSON:", "").trim();
                                    const newStats = JSON.parse(jsonStr);
                                    setStats(prev => ({ ...prev, ...newStats }));
                                } catch (e) { console.error("Stats parse error", e); }
                                return;
                            }

                            // 2. Check for Section Separators
                            if (log.includes("---ANALYSIS_START---")) {
                                setAnalysisContent("");
                                setAnalysisThinking("");
                                const parts = log.split("---ANALYSIS_START---");
                                if (parts[1]) log = parts[1];
                                else return;
                            }

                            if (log.includes("初始分析已完成。正在生成今日行动建议...") || log.includes("Today's Action Plan") || log.includes("---PLAN_START---")) {
                                currentSection = 'plan';
                                setPlanContent("");
                                setPlanThinking("");
                                if (log.includes("rocket") || log.includes("🚀")) {
                                    setPlanContent("🚀 Generating Plan...\n\n");
                                }
                                return;
                            }

                            // 3. Parse Content & Thinking
                            if (log.startsWith("STREAM_THINKING:")) {
                                const raw = log.replace("STREAM_THINKING:", "");
                                try {
                                    const thought = JSON.parse(raw);
                                    if (currentSection === 'analysis') {
                                        setAnalysisThinking(prev => prev + thought);
                                    } else {
                                        setPlanThinking(prev => prev + thought);
                                    }
                                } catch (e) {
                                    if (currentSection === 'analysis') setAnalysisThinking(prev => prev + raw);
                                    else setPlanThinking(prev => prev + raw);
                                }
                            } else if (log.startsWith("STREAM_CONTENT:")) {
                                const raw = log.replace("STREAM_CONTENT:", "");
                                let content = raw;
                                try {
                                    content = JSON.parse(raw);
                                } catch (e) { }

                                // Update Content
                                if (currentSection === 'analysis') {
                                    setAnalysisContent(prev => prev + content);
                                } else {
                                    setPlanContent(prev => prev + content);
                                }

                                // --- REAL-TIME STATS UPDATES ---
                                const estimatedTokens = Math.max(1, Math.ceil(content.length * 0.7));

                                setStats(prev => {
                                    const startTime = prev?.startTime || Date.now();
                                    const duration = (Date.now() - startTime) / 1000;
                                    const newTotalTokens = (prev?.total_tokens || 0) + estimatedTokens;
                                    const speed = duration > 0 ? (newTotalTokens / duration).toFixed(2) + " t/s" : "0.00 t/s";

                                    return {
                                        ...prev,
                                        startTime: startTime,
                                        total_tokens: newTotalTokens,
                                        total_duration: duration,
                                        speed: speed
                                    };
                                });
                            } else if (log.startsWith("STREAM_DONE:") || log.startsWith("STREAM_ERROR:")) {
                                // ignore
                            } else {
                                // Fallback (Legacy)
                                if (currentSection === 'analysis') {
                                    setAnalysisContent(prev => prev + log + "\n");
                                } else {
                                    setPlanContent(prev => prev + log + "\n");
                                }
                            }
                        }
                    } catch (e) {
                        // raw text fallback
                        if (currentSection === 'analysis') {
                            setAnalysisContent(prev => prev + line + "\n");
                        } else {
                            setPlanContent(prev => prev + line + "\n");
                        }
                    }
                });
            }
        } catch (err) {
            if (err.name === 'AbortError') {
                console.log('Generation aborted');
            } else {
                setPlanContent(prev => prev + `\n❌ Error: ${err.message}`);
            }
        } finally {
            if (abortControllerRef.current?.signal === signal) {
                setIsGenerating(false);
                abortControllerRef.current = null;
            }
        }
    };

    return (
        <div style={{
            display: 'flex',
            flexDirection: 'column',
            gap: '1rem',
            height: '100%', // Fill parent container
            overflow: 'hidden',
            boxSizing: 'border-box'
        }}>
            {/* Header */}
            <div className="glass-panel" style={{ padding: '1rem 1.5rem', display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexShrink: 0 }}>
                <div>
                    <h2 style={{ margin: 0, display: 'flex', alignItems: 'center', gap: '0.5rem', fontSize: '1.25rem' }}>
                        <CheckSquare size={20} color="var(--primary-color)" />
                        Action Plan
                    </h2>
                    <p style={{ margin: 0, color: 'var(--text-secondary)', fontSize: '0.85rem' }}>Daily Analysis & Task Generation</p>
                </div>

                <div style={{ display: 'flex', gap: '1rem', alignItems: 'center' }}>
                    {stats && (
                        <div style={{
                            fontSize: '0.85rem', color: 'var(--text-secondary)',
                            display: 'flex', gap: '1rem',
                            background: 'rgba(0,0,0,0.2)', padding: '0.5rem 1rem', borderRadius: '8px'
                        }}>
                            <span>⚡ {stats.speed}</span>
                            <span>⏱️ {(stats.total_duration || 0).toFixed(1)}s</span>
                            <span>🪙 {stats.total_tokens || 0} toks</span>
                            {stats.historical_total_tokens !== undefined && (
                                <span style={{ borderLeft: '1px solid rgba(255,255,255,0.2)', paddingLeft: '1rem' }}>
                                    📜 {(stats.historical_total_tokens / 1000000).toFixed(2)}M History
                                </span>
                            )}
                        </div>
                    )}

                    <button
                        onClick={isGenerating ? stopGeneration : startGeneration}
                        style={{
                            padding: '0.8rem 1.5rem', fontSize: '1rem',
                            display: 'flex', alignItems: 'center', gap: '0.5rem',
                            background: isGenerating ? '#ff4d4f' : 'var(--primary-color)', // Red for Stop
                            color: '#fff',
                            border: 'none', borderRadius: '8px', cursor: 'pointer',
                            transition: 'background 0.3s'
                        }}
                    >
                        {isGenerating ? <div style={{ width: 18, height: 18, background: 'white', borderRadius: 2 }} /> : <RotateCcw size={18} />}
                        {isGenerating ? 'Stop' : 'Regenerate'}
                    </button>
                </div>
            </div>

            <div style={{
                display: 'grid',
                gridTemplateColumns: '1fr 1fr',
                gap: '1rem', // Reduced gap
                flex: 1,
                minHeight: 0
            }}>
                {/* Left: Analysis */}
                <div className="glass-panel" style={{ display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
                    <div style={{
                        padding: '0.8rem 1rem', borderBottom: '1px solid var(--border-color)',
                        background: 'rgba(255,255,255,0.02)',
                        display: 'flex', alignItems: 'center', gap: '0.5rem'
                    }}>
                        <Activity size={16} color="var(--secondary-color)" />
                        <h4 style={{ margin: 0, fontSize: '0.95rem' }}>📊 总体回复 (General Analysis)</h4>
                    </div>
                    <div className="markdown-body compact-markdown custom-scrollbar" style={{ flex: 1, overflowY: 'auto', padding: '1rem' }}>
                        {analysisThinking && <ThinkingBlock text={analysisThinking} />}
                        <ReactMarkdown remarkPlugins={[remarkGfm]}>
                            {analysisContent}
                        </ReactMarkdown>
                        <div ref={analysisEndRef} />
                    </div>
                </div>

                {/* Right: Plan */}
                <div className="glass-panel" style={{ display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
                    <div style={{
                        padding: '0.8rem 1rem', borderBottom: '1px solid var(--border-color)',
                        background: 'rgba(255,255,255,0.02)',
                        display: 'flex', alignItems: 'center', gap: '0.5rem'
                    }}>
                        <FileText size={16} color="var(--primary-color)" />
                        <h4 style={{ margin: 0, fontSize: '0.95rem' }}>📝 今日计划 (Today's Action Plan)</h4>
                    </div>
                    <div className="markdown-body compact-markdown custom-scrollbar" style={{ flex: 1, overflowY: 'auto', padding: '1rem' }}>
                        {planThinking && <ThinkingBlock text={planThinking} />}
                        <ReactMarkdown remarkPlugins={[remarkGfm]}>
                            {planContent}
                        </ReactMarkdown>
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
                <div className="thinking-dot" style={{ width: '6px', height: '6px', borderRadius: '50%', background: 'var(--text-muted)' }}></div>
                Analysis Process
            </div>
            {text}
        </div>
    );
}
