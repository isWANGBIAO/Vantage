import { useState, useRef, useEffect } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { RotateCcw, FileText, CheckSquare, Activity } from 'lucide-react';

export default function ActionPlan() {
    const [analysisContent, setAnalysisContent] = useState('');
    const [planContent, setPlanContent] = useState('');

    // Stats
    const [stats, setStats] = useState(null);
    const [isGenerating, setIsGenerating] = useState(false);

    // Auto-scroll refs
    const analysisEndRef = useRef(null);
    const planEndRef = useRef(null);

    // Initial load
    useEffect(() => {
        // Auto-start or load history? 
        // For webapp, maybe we wait for user, or check if we have data.
        // Let's just default to empty valid state.
        // Check for existing plan via chat API fallback?
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
        // Try to fetch today's plan if available
        // We can reuse the chat endpoint to "read" the file if we trust the backend to find it
        // Or just leave it empty until user generates.
        // Let's try the fetch hack from previous version but cleaner
        try {
            // We won't implement this yet as we don't have a dedicated endpoint for "get_todays_plan"
            // and sending a chat message to "read file" is flaky for a UI component.
            // We can rely on user clicking start.
        } catch (e) { }
    };

    const startGeneration = async () => {
        setIsGenerating(true);
        setAnalysisContent('### ⏳ Analyzing Data...\n\n');
        setPlanContent('### ⏳ Waiting for Analysis...\n\n');
        setStats(null);

        let currentSection = 'analysis'; // 'analysis' or 'plan'
        let buffer = ''; // To handle split lines if necessary, though line-by-line usually works

        try {
            const response = await fetch('/api/action_plan', { method: 'POST' });
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
                                    setStats(JSON.parse(jsonStr));
                                } catch (e) { console.error("Stats parse error", e); }
                                return;
                            }

                            // 2. Check for Section Separators
                            if (log.includes("---ANALYSIS_START---")) {
                                setAnalysisContent(""); // Clear buffer text
                                const parts = log.split("---ANALYSIS_START---");
                                if (parts[1]) log = parts[1];
                                else return; // Just a marker
                            }

                            if (log.includes("初始分析已完成。正在生成今日行动建议...") || log.includes("Today's Action Plan")) {
                                currentSection = 'plan';
                                setPlanContent(""); // Clear waiting text
                                if (log.includes("rocket") || log.includes("🚀")) {
                                    setPlanContent("🚀 Generating Plan...\n\n");
                                }
                                return;
                            }

                            // 3. Append Content
                            if (currentSection === 'analysis') {
                                setAnalysisContent(prev => prev + log + "\n");
                            } else {
                                setPlanContent(prev => prev + log + "\n");
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
            setPlanContent(prev => prev + `\n❌ Error: ${err.message}`);
        } finally {
            setIsGenerating(false);
        }
    };

    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem', height: '85vh' }}>
            {/* Header */}
            <div className="glass-panel" style={{ padding: '1.5rem', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div>
                    <h2 style={{ margin: 0, display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                        <CheckSquare size={24} color="var(--primary-color)" />
                        Action Plan
                    </h2>
                    <p style={{ margin: 0, color: 'var(--text-secondary)' }}>Daily Analysis & Task Generation</p>
                </div>

                <div style={{ display: 'flex', gap: '1rem', alignItems: 'center' }}>
                    {stats && (
                        <div style={{
                            fontSize: '0.85rem', color: 'var(--text-secondary)',
                            display: 'flex', gap: '1rem',
                            background: 'rgba(0,0,0,0.2)', padding: '0.5rem 1rem', borderRadius: '8px'
                        }}>
                            <span>⚡ {stats.speed}</span>
                            <span>⏱️ {stats.total_duration.toFixed(1)}s</span>
                            <span>🪙 {stats.total_tokens} toks</span>
                        </div>
                    )}

                    <button
                        onClick={startGeneration}
                        disabled={isGenerating}
                        style={{
                            padding: '0.8rem 1.5rem', fontSize: '1rem',
                            display: 'flex', alignItems: 'center', gap: '0.5rem',
                            background: isGenerating ? 'var(--bg-surface-hover)' : 'var(--primary-color)',
                            color: isGenerating ? 'var(--text-muted)' : '#fff',
                            border: 'none', borderRadius: '8px', cursor: isGenerating ? 'default' : 'pointer'
                        }}
                    >
                        {isGenerating ? <Activity className="spin-animation" size={18} /> : <RotateCcw size={18} />}
                        {isGenerating ? 'Generating...' : 'Regenerate'}
                    </button>
                </div>
            </div>

            {/* Split View Content */}
            <div style={{
                display: 'grid',
                gridTemplateColumns: '1fr 1fr',
                gap: '1.5rem',
                flex: 1,
                minHeight: 0 // Crucial for nested scroll
            }}>
                {/* Left: Analysis */}
                <div className="glass-panel" style={{ display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
                    <div style={{
                        padding: '1rem', borderBottom: '1px solid var(--border-color)',
                        background: 'rgba(255,255,255,0.02)',
                        display: 'flex', alignItems: 'center', gap: '0.5rem'
                    }}>
                        <Activity size={18} color="var(--secondary-color)" />
                        <h4 style={{ margin: 0 }}>General Analysis</h4>
                    </div>
                    <div className="markdown-body custom-scrollbar" style={{ flex: 1, overflowY: 'auto', padding: '1.5rem' }}>
                        <ReactMarkdown remarkPlugins={[remarkGfm]}>
                            {analysisContent}
                        </ReactMarkdown>
                        <div ref={analysisEndRef} />
                    </div>
                </div>

                {/* Right: Plan */}
                <div className="glass-panel" style={{ display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
                    <div style={{
                        padding: '1rem', borderBottom: '1px solid var(--border-color)',
                        background: 'rgba(255,255,255,0.02)',
                        display: 'flex', alignItems: 'center', gap: '0.5rem'
                    }}>
                        <FileText size={18} color="var(--primary-color)" />
                        <h4 style={{ margin: 0 }}>Today's Plan</h4>
                    </div>
                    <div className="markdown-body custom-scrollbar" style={{ flex: 1, overflowY: 'auto', padding: '1.5rem' }}>
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
