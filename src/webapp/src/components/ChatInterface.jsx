import { useState, useRef, useEffect } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Mic, Send, StopCircle, Bot, User } from 'lucide-react';

export default function ChatInterface() {
    const [messages, setMessages] = useState([]);
    const [input, setInput] = useState('');
    const [isLoading, setIsLoading] = useState(false);
    const [isRecording, setIsRecording] = useState(false);
    const [recordingTime, setRecordingTime] = useState(0);

    const endRef = useRef(null);
    const mediaRecorderRef = useRef(null);
    const audioChunksRef = useRef([]);
    const timerRef = useRef(null);

    const scrollToBottom = () => {
        endRef.current?.scrollIntoView({ behavior: 'smooth' });
    };

    useEffect(() => {
        scrollToBottom();
    }, [messages]);

    const sendMessage = async () => {
        if (!input.trim() || isLoading) return;

        const userMsg = input.trim();
        setMessages(prev => [...prev, { role: 'user', content: userMsg }]);
        setInput('');
        setIsLoading(true);

        try {
            const res = await fetch('/api/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ message: userMsg }),
            });

            const data = await res.json();

            if (data.success) {
                setMessages(prev => [...prev, { role: 'assistant', content: data.response }]);
            } else {
                setMessages(prev => [...prev, { role: 'assistant', content: 'Error: Failed to process request.' }]);
            }
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
        try {
            const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
            mediaRecorderRef.current = new MediaRecorder(stream);
            audioChunksRef.current = [];

            mediaRecorderRef.current.ondataavailable = (event) => {
                if (event.data.size > 0) {
                    audioChunksRef.current.push(event.data);
                }
            };

            mediaRecorderRef.current.onstop = async () => {
                const audioBlob = new Blob(audioChunksRef.current, { type: 'audio/wav' });
                const formData = new FormData();
                formData.append('file', audioBlob, 'recording.wav');

                setIsLoading(true); // Show loading state while transcribing
                setInput("Transcribing audio...");

                try {
                    const res = await fetch('/api/transcribe', {
                        method: 'POST',
                        body: formData
                    });
                    const data = await res.json();
                    if (data.transcription) {
                        setInput(data.transcription);
                    } else {
                        // setInput("Transcription failed.");
                        // Don't overwrite if failed, just clear placeholder
                        setInput("");
                    }
                } catch (err) {
                    console.error("Transcription error", err);
                    setInput("");
                } finally {
                    setIsLoading(false);
                    // Stop tracks
                    stream.getTracks().forEach(track => track.stop());
                }
            };

            mediaRecorderRef.current.start();
            setIsRecording(true);
            setRecordingTime(0);
            timerRef.current = setInterval(() => {
                setRecordingTime(prev => prev + 1);
            }, 1000);

        } catch (err) {
            console.error("Error accessing microphone:", err);
            alert("Could not access microphone. Please check permissions.");
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
        <div className="glass-panel" style={{ height: '70vh', display: 'flex', flexDirection: 'column' }}>
            <div style={{ padding: '1rem', borderBottom: '1px solid var(--border-color)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <h3 style={{ margin: 0, display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                    <Bot size={20} color="var(--primary-color)" />
                    AI Assistant
                </h3>
                <span style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>Powered by Gemini</span>
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
                            border: msg.role === 'user' ? 'none' : '1px solid var(--border-color)'
                        }}>
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
