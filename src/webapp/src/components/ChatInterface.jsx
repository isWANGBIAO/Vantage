import { useState, useRef, useEffect } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Mic, Send, StopCircle, Bot, User, Trash2 } from 'lucide-react';
import { fetchBackend, fetchBackendJson } from '../utils/backendRequest';
import {
  formatModelReasoningSupportLabel,
  parseModelReasoningSupport,
} from '../utils/modelReasoningSupport';

export default function ChatInterface() {
    const [messages, setMessages] = useState([]);
    const [input, setInput] = useState('');
    const [availableModels, setAvailableModels] = useState([]);
    const [modelReasoningSupport, setModelReasoningSupport] = useState({});
    const [selectedModel, setSelectedModel] = useState('');
    const [isLoading, setIsLoading] = useState(false);
    const [isRecording, setIsRecording] = useState(false);
    const [recordingTime, setRecordingTime] = useState(0);

    const endRef = useRef(null);
    const mediaRecorderRef = useRef(null);
    const audioChunksRef = useRef([]);
    const timerRef = useRef(null);
    const streamRef = useRef(null); // 存储 audio stream 避免作用域问题

    const scrollToBottom = () => {
        endRef.current?.scrollIntoView({ behavior: 'smooth' });
    };

    // Load chat history from localStorage on mount
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
                }
            } catch (error) {
                console.error('Failed to load model list:', error);
            }
        };

        initializeModels();

        try {
            const saved = localStorage.getItem('chat_history');
            if (saved) {
                setMessages(JSON.parse(saved));
            }
        } catch (e) {
            console.error('Failed to load chat history:', e);
        }
    }, []);

    // Save chat history to localStorage on change
    useEffect(() => {
        if (messages.length > 0) {
            localStorage.setItem('chat_history', JSON.stringify(messages));
        }
        scrollToBottom();
    }, [messages]);

    const clearChat = () => {
        setMessages([]);
        localStorage.removeItem('chat_history');
    };

    const handleModelChange = (event) => {
        const nextModel = event.target.value;
        setSelectedModel(nextModel);
        localStorage.setItem('preferred_llm_model', nextModel);
    };

    // Shared stream processing function to avoid code duplication
    const processStreamResponse = async (response) => {
        const reader = response.body.getReader();
        const decoder = new TextDecoder();

        setMessages(prev => [...prev, { role: 'assistant', content: '', thinking: '' }]);

        let assistantContent = "";
        let assistantThinking = "";

        while (true) {
            const { value, done } = await reader.read();
            if (done) break;

            const chunk = decoder.decode(value, { stream: true });
            const lines = chunk.split('\n');

            for (const line of lines) {
                if (!line.trim()) continue;

                try {
                    const data = JSON.parse(line);

                    if (data.error) {
                        throw new Error(data.error);
                    }

                    if (data.log) {
                        const text = data.log;

                        if (text.startsWith("STREAM_THINKING:")) {
                            const raw = text.replace("STREAM_THINKING:", "");
                            try {
                                assistantThinking += JSON.parse(raw);
                            } catch { assistantThinking += raw; }
                        } else if (text.startsWith("STREAM_CONTENT:")) {
                            const raw = text.replace("STREAM_CONTENT:", "");
                            try {
                                assistantContent += JSON.parse(raw);
                            } catch { assistantContent += raw; }
                        } else if (
                            text.startsWith("STREAM_DONE:") ||
                            text.startsWith("STREAM_ERROR:") ||
                            text.startsWith("STATS_JSON:") ||
                            text.includes("---CHAT_START---") ||
                            text.includes("---ANALYSIS_END---") ||
                            text.includes("---PLAN_START---") ||
                            text.startsWith("Response saved to:") ||
                            text.trim() === ""
                        ) {
                            // Ignore control signals and markers
                        } else {
                            const cleanText = text
                                .replace(/---CHAT_START---/g, '')
                                .replace(/---ANALYSIS_END---/g, '')
                                .replace(/STATS_JSON:\{.*\}/g, '')
                                .trim();
                            if (cleanText) {
                                assistantContent += cleanText;
                            }
                        }

                        setMessages(prev => {
                            const newMessages = [...prev];
                            const lastMsg = newMessages[newMessages.length - 1];
                            if (lastMsg.role === 'assistant') {
                                lastMsg.content = assistantContent;
                                lastMsg.thinking = assistantThinking;
                            }
                            return newMessages;
                        });
                    }
                } catch (e) {
                    console.debug("JSON parse error for chunk", line, e);
                }
            }
        }
    };

    const sendMessage = async () => {
        if (!input.trim() || isLoading) return;

        const userMsg = input.trim();
        setMessages(prev => [...prev, { role: 'user', content: userMsg }]);
        setInput('');
        setIsLoading(true);

        try {
            const payload = { message: userMsg };
            if (selectedModel) {
                payload.model = selectedModel;
            }

            const res = await fetchBackend('/api/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
                retryPolicy: 'stream',
            });

            await processStreamResponse(res);

        } catch (err) {
            setMessages(prev => [...prev, { role: 'assistant', content: `Network Error: ${err.message}` }]);
        } finally {
            setIsLoading(false);
        }
    };

    const handleKeyDown = (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    };

    // --- Audio Recording Logic ---
    const startRecording = async () => {
        console.log("[Voice] Starting recording...");
        try {
            const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
            streamRef.current = stream; // 存储 stream 引用

            mediaRecorderRef.current = new MediaRecorder(stream);
            audioChunksRef.current = [];

            mediaRecorderRef.current.ondataavailable = (event) => {
                console.log("[Voice] Data available:", event.data.size, "bytes");
                if (event.data.size > 0) {
                    audioChunksRef.current.push(event.data);
                }
            };

            mediaRecorderRef.current.onstop = async () => {
                console.log("[Voice] Recording stopped, chunks:", audioChunksRef.current.length);

                // 停止媒体轨道
                if (streamRef.current) {
                    streamRef.current.getTracks().forEach(track => track.stop());
                    streamRef.current = null;
                }

                if (audioChunksRef.current.length === 0) {
                    console.warn("[Voice] No audio data captured");
                    setInput("");
                    setIsLoading(false);
                    return;
                }

                const audioBlob = new Blob(audioChunksRef.current, { type: 'audio/webm' });
                console.log("[Voice] Audio blob size:", audioBlob.size, "bytes");

                const formData = new FormData();
                formData.append('file', audioBlob, 'recording.webm');

                setIsLoading(true);
                setInput("正在转写语音...");

                try {
                    console.log("[Voice] Sending to /api/transcribe...");
                    const data = await fetchBackendJson('/api/transcribe', {
                        method: 'POST',
                        body: formData,
                        retryPolicy: 'mutation',
                    });
                    console.log("[Voice] Transcribe result:", data);

                    if (data.transcription && data.transcription.trim()) {
                        // 自动发送转写后的消息
                        const transcribedText = data.transcription.trim();
                        console.log("[Voice] Transcribed text:", transcribedText);
                        setInput(""); // 清空输入框

                        // 直接发送消息
                        setMessages(prev => [...prev, { role: 'user', content: transcribedText }]);

                        // 调用聊天 API (reuse shared stream processor)
                        try {
                            const chatPayload = { message: transcribedText };
                            if (selectedModel) {
                                chatPayload.model = selectedModel;
                            }

                            const chatRes = await fetchBackend('/api/chat', {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify(chatPayload),
                                retryPolicy: 'stream',
                            });

                            await processStreamResponse(chatRes);
                        } catch (chatErr) {
                            console.error("[Voice] Chat error:", chatErr);
                            setMessages(prev => [...prev, { role: 'assistant', content: `Network Error: ${chatErr.message}` }]);
                        }
                    } else {
                        // 转写失败或返回空结果
                        console.warn("[Voice] Transcription empty or failed");
                        setInput("语音转写失败，请重试或手动输入");
                    }
                } catch (err) {
                    console.error("[Voice] Transcription error:", err);
                    setInput("语音转写出错: " + err.message);
                } finally {
                    setIsLoading(false);
                }
            };

            mediaRecorderRef.current.start();
            console.log("[Voice] MediaRecorder started");
            setIsRecording(true);
            setRecordingTime(0);
            timerRef.current = setInterval(() => {
                setRecordingTime(prev => prev + 1);
            }, 1000);

        } catch (err) {
            console.error("[Voice] Error accessing microphone:", err);
            alert("无法访问麦克风，请检查权限设置。\n错误: " + err.message);
        }
    };

    const stopRecording = () => {
        if (mediaRecorderRef.current && isRecording) {
            mediaRecorderRef.current.stop();
            setIsRecording(false);
            if (timerRef.current) {
                clearInterval(timerRef.current);
                timerRef.current = null;
            }
        }
    };

    const formatTime = (seconds) => {
        const mins = Math.floor(seconds / 60);
        const secs = seconds % 60;
        return `${mins}:${secs.toString().padStart(2, '0')}`;
    };

    return (
        <div className="glass-panel" style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
            <div style={{ padding: '1rem', borderBottom: '1px solid var(--border-color)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <h3 style={{ margin: 0, display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                    <Bot size={20} color="var(--primary-color)" />
                    AI Assistant
                </h3>
                <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
                    <label
                        style={{
                            display: 'flex',
                            alignItems: 'center',
                            gap: '0.5rem',
                            color: 'var(--text-secondary)',
                            fontSize: '0.8rem',
                        }}
                    >
                        <span>模型</span>
                        <select
                            value={selectedModel}
                            onChange={handleModelChange}
                            disabled={isLoading || availableModels.length === 0}
                            style={{
                                padding: '0.3rem 0.6rem',
                                borderRadius: '6px',
                                border: '1px solid var(--border-color)',
                                background: 'var(--bg-surface)',
                                color: 'var(--text-primary)',
                                cursor: isLoading || availableModels.length === 0 ? 'not-allowed' : 'pointer',
                            }}
                        >
                            {availableModels.length === 0 && <option value="">默认模型</option>}
                            {availableModels.map((model) => (
                                <option key={model} value={model}>
                                    {`${model}${formatModelReasoningSupportLabel(model, modelReasoningSupport)}`}
                                </option>
                            ))}
                        </select>
                    </label>
                    <span style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>Powered by Gemini</span>
                    {messages.length > 0 && (
                        <button
                            onClick={clearChat}
                            title="Clear chat history"
                            style={{
                                background: 'transparent',
                                border: '1px solid var(--border-color)',
                                borderRadius: '6px',
                                padding: '0.4rem 0.6rem',
                                cursor: 'pointer',
                                display: 'flex',
                                alignItems: 'center',
                                gap: '0.3rem',
                                color: 'var(--text-secondary)',
                                fontSize: '0.75rem',
                                transition: 'all 0.2s'
                            }}
                        >
                            <Trash2 size={14} />
                            Clear
                        </button>
                    )}
                </div>
            </div>

            <div style={{
                flex: 1,
                overflowY: 'auto',
                padding: '1.5rem',
                display: 'flex',
                flexDirection: 'column',
                gap: '1.5rem'
            }}>
                {messages.length === 0 && (
                    <div style={{ textAlign: 'center', color: 'var(--text-muted)', marginTop: '2rem' }}>
                        <p>Start a conversation with your AI Assistant.</p>
                        <p style={{ fontSize: '0.9rem' }}>Try sending a message or recording voice input.</p>
                    </div>
                )}

                {messages.map((msg, i) => (
                    <div key={i} style={{
                        alignSelf: msg.role === 'user' ? 'flex-end' : 'flex-start',
                        maxWidth: '85%',
                        display: 'flex',
                        gap: '0.8rem',
                        flexDirection: msg.role === 'user' ? 'row-reverse' : 'row'
                    }}>
                        <div style={{
                            width: '32px', height: '32px',
                            background: msg.role === 'user' ? 'var(--primary-color)' : 'var(--bg-surface-hover)',
                            borderRadius: '50%',
                            display: 'flex', alignItems: 'center', justifyContent: 'center',
                            flexShrink: 0
                        }}>
                            {msg.role === 'user' ? <User size={16} /> : <Bot size={16} />}
                        </div>

                        <div style={{
                            background: msg.role === 'user' ? 'linear-gradient(135deg, var(--primary-color), var(--primary-hover))' : 'var(--bg-surface)',
                            color: msg.role === 'user' ? '#fff' : 'var(--text-primary)',
                            padding: '1rem 1.2rem',
                            borderRadius: '16px',
                            borderTopRightRadius: msg.role === 'user' ? '4px' : '16px',
                            borderTopLeftRadius: msg.role === 'user' ? '16px' : '4px',
                            lineHeight: '1.6',
                            boxShadow: '0 2px 8px rgba(0,0,0,0.1)',
                            border: msg.role === 'user' ? 'none' : '1px solid var(--border-color)',
                            minWidth: '200px'
                        }}>
                            {/* Thinking Process Display */}
                            {msg.thinking && (
                                <div style={{
                                    fontSize: '0.85rem',
                                    color: 'var(--text-muted)',
                                    background: 'rgba(0,0,0,0.1)',
                                    padding: '0.8rem',
                                    borderRadius: '8px',
                                    marginBottom: '1rem',
                                    borderLeft: '3px solid var(--border-color)',
                                    whiteSpace: 'pre-wrap'
                                }}>
                                    <div style={{ fontWeight: 600, marginBottom: '0.4rem', display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                                        <div className="thinking-dot" style={{ width: '6px', height: '6px', borderRadius: '50%', background: 'var(--text-muted)' }}></div>
                                        Reasoning Process
                                    </div>
                                    {msg.thinking}
                                </div>
                            )}

                            <div className="markdown-body" style={{ fontSize: '0.95rem' }}>
                                <ReactMarkdown remarkPlugins={[remarkGfm]}>
                                    {msg.content}
                                </ReactMarkdown>
                            </div>
                        </div>
                    </div>
                ))}

                {isLoading && (
                    <div style={{ alignSelf: 'flex-start', display: 'flex', alignItems: 'center', gap: '0.5rem', paddingLeft: '3.5rem' }}>
                        <div className="typing-indicator">
                            <span></span><span></span><span></span>
                        </div>
                        <span style={{ fontSize: '0.85rem', color: 'var(--text-muted)' }}>Thinking...</span>
                    </div>
                )}
                <div ref={endRef} />
            </div>

            <div style={{ padding: '1.2rem', borderTop: '1px solid var(--border-color)', background: 'rgba(0,0,0,0.2)' }}>
                <div style={{
                    display: 'flex',
                    gap: '0.8rem',
                    background: 'var(--bg-surface)',
                    padding: '0.5rem',
                    borderRadius: '12px',
                    border: '1px solid var(--border-color)',
                    alignItems: 'flex-end'
                }}>
                    <button
                        onClick={isRecording ? stopRecording : startRecording}
                        className={isRecording ? 'pulse-animation' : ''}
                        disabled={isLoading && !isRecording} // Disable start if loading, but allow stop if recording
                        style={{
                            background: isRecording ? '#ff4d4d' : 'transparent',
                            color: isRecording ? '#fff' : 'var(--text-secondary)',
                            border: 'none',
                            borderRadius: '8px',
                            width: '40px', height: '40px',
                            display: 'flex', alignItems: 'center', justifyContent: 'center',
                            cursor: 'pointer',
                            transition: 'all 0.2s ease'
                        }}
                        title={isRecording ? "Stop Recording" : "Start Recording"}
                    >
                        {isRecording ? <StopCircle size={20} /> : <Mic size={20} />}
                    </button>

                    {isRecording && (
                        <div style={{
                            flex: 1, display: 'flex', alignItems: 'center',
                            color: '#ff4d4d', fontWeight: 'bold', fontSize: '0.9rem'
                        }}>
                            Recording... {formatTime(recordingTime)}
                        </div>
                    )}

                    {!isRecording && (
                        <textarea
                            value={input}
                            onChange={(e) => setInput(e.target.value)}
                            onKeyDown={handleKeyDown}
                            placeholder="Type a message..."
                            disabled={isLoading}
                            rows={1}
                            style={{
                                flex: 1,
                                background: 'transparent',
                                border: 'none',
                                color: 'var(--text-primary)',
                                padding: '0.6rem 0.5rem',
                                outline: 'none',
                                fontSize: '0.95rem',
                                resize: 'none',
                                minHeight: '24px',
                                maxHeight: '100px'
                            }}
                            onInput={(e) => {
                                e.target.style.height = 'auto'; // Reset height
                                e.target.style.height = e.target.scrollHeight + 'px'; // Set new height
                            }}
                        />
                    )}

                    <button
                        onClick={sendMessage}
                        disabled={!input.trim() || isLoading}
                        style={{
                            background: (!input.trim() || isLoading) ? 'var(--bg-surface-hover)' : 'var(--primary-color)',
                            color: (!input.trim() || isLoading) ? 'var(--text-muted)' : '#fff',
                            border: 'none',
                            borderRadius: '8px',
                            width: '40px', height: '40px',
                            display: 'flex', alignItems: 'center', justifyContent: 'center',
                            cursor: 'pointer',
                            transition: 'all 0.2s ease'
                        }}
                    >
                        <Send size={18} />
                    </button>
                </div>
            </div>
        </div>
    );
}
