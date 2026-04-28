import { useState, useRef, useEffect, useCallback } from 'react';

import ReactMarkdown from 'react-markdown';

import remarkGfm from 'remark-gfm';

import { Bot, Trash2 } from 'lucide-react';

import { fetchBackend, fetchBackendJson } from '../utils/backendRequest';
import { loadSettingsState } from '../utils/settingsState';
import {
  CHAT_CONTEXT_BASE_UPDATED_EVENT,
  buildInitialEmbeddedChatState,
  loadStoredChatMessages,
  reconcileChatHistoryWithBaseVersion,
  saveStoredChatMessages,
  storeChatContextBaseVersion,
} from '../utils/chatContextState';
import {
    loadStoredActionPlanReasoningEffort,
    normalizeReasoningEffortForModel,
} from '../utils/actionPlanReasoning';
import {
    computeDisplayedDurationSeconds,
    formatActionPlanCacheBreakdown,
    formatThinkingTitleWithDuration,
} from '../utils/actionPlanStats';

import {

  formatModelReasoningSupportLabel,

  parseModelReasoningSupport,

} from '../utils/modelReasoningSupport';
import {
  buildModelOptionId,
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
import { useDisplayLanguage } from '../context/DisplayLanguageContext.jsx';

const DEFAULT_VOICE_MODEL = 'FunAudioLLM/SenseVoiceSmall';

function normalizeVoiceConfig(settingsState) {
    const settings = settingsState?.settings || {};
    return {
        baseUrl: typeof settings.voiceBaseUrl === 'string' ? settings.voiceBaseUrl : '',
        model: typeof settings.voiceModel === 'string' && settings.voiceModel.trim()
            ? settings.voiceModel
            : DEFAULT_VOICE_MODEL,
    };
}

function buildClientSentAt() {
    const now = new Date();
    const offsetMinutes = -now.getTimezoneOffset();
    const sign = offsetMinutes >= 0 ? '+' : '-';
    const absoluteOffsetMinutes = Math.abs(offsetMinutes);
    const offsetHours = String(Math.floor(absoluteOffsetMinutes / 60)).padStart(2, '0');
    const offsetRemainderMinutes = String(absoluteOffsetMinutes % 60).padStart(2, '0');
    const year = now.getFullYear();
    const month = String(now.getMonth() + 1).padStart(2, '0');
    const day = String(now.getDate()).padStart(2, '0');
    const hours = String(now.getHours()).padStart(2, '0');
    const minutes = String(now.getMinutes()).padStart(2, '0');
    const seconds = String(now.getSeconds()).padStart(2, '0');

    return `${year}-${month}-${day}T${hours}:${minutes}:${seconds}${sign}${offsetHours}:${offsetRemainderMinutes}`;
}

function renderChatMarkdownComponents(role) {
    const isUser = role === 'user';

    return {
        p: (props) => (
            <p
                {...props}
                style={{
                    color: isUser ? 'inherit' : 'var(--text-secondary)',
                    marginBottom: '1rem',
                }}
            />
        ),
        li: (props) => (
            <li
                {...props}
                style={{
                    color: 'inherit',
                    marginBottom: '0.3rem',
                }}
            />
        ),
        strong: (props) => (
            <strong
                {...props}
                style={{
                    color: isUser ? 'inherit' : 'var(--accent-color)',
                }}
            />
        ),
    };
}

function ThinkingDisclosure({ title, text }) {
    if (!text) {
        return null;
    }

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


function consumeChatStreamChunk(previousState, chunkText) {
    const nextState = {
        buffer: `${previousState.buffer ?? ''}${chunkText}`,
        assistantContent: previousState.assistantContent ?? '',
        assistantThinking: previousState.assistantThinking ?? '',
        stats: previousState.stats ?? null,
        error: previousState.error ?? null,
    };

    const lines = nextState.buffer.split('\n');
    nextState.buffer = lines.pop() ?? '';

    for (const line of lines) {
        if (!line.trim()) {
            continue;
        }

        let data;
        try {
            data = JSON.parse(line);
        } catch {
            continue;
        }

        const errorMessage = data?.error;
        if (errorMessage) {
            nextState.error = typeof errorMessage === 'string'
                ? errorMessage
                : JSON.stringify(errorMessage);
            return nextState;
        }

        const text = typeof data?.log === 'string' ? data.log : '';
        if (!text) {
            continue;
        }

        const readPayload = (prefix) => {
            const raw = text.slice(prefix.length);
            try {
                return JSON.parse(raw);
            } catch {
                return raw;
            }
        };

        if (text.startsWith('STATS_JSON:')) {
            const raw = text.slice('STATS_JSON:'.length);
            try {
                const parsed = JSON.parse(raw);
                nextState.stats = {
                    ...(nextState.stats ?? {}),
                    ...parsed,
                };
            } catch {
                continue;
            }
        } else if (text.startsWith('STREAM_THINKING:')) {
            nextState.assistantThinking += readPayload('STREAM_THINKING:');
        } else if (text.startsWith('STREAM_CONTENT:')) {
            nextState.assistantContent += readPayload('STREAM_CONTENT:');
        } else if (text.startsWith('STREAM_ERROR:')) {
            nextState.error = readPayload('STREAM_ERROR:');
            return nextState;
        }
    }

    return nextState;
}

function getVisibleMessages({ embedded, messages, baseMessages }) {
    return embedded
        ? messages.slice(baseMessages.length)
        : messages;
}

function isTextChatModelOption(modelOption) {
    const modelName = String(modelOption?.model || modelOption?.id || '').toLowerCase();
    if (!modelName) {
        return false;
    }
    return !/(^|[-_/])(image|audio|tts|whisper|embedding|vision)([-_/]|$)/i.test(modelName);
}

function formatChatSpeed(currentStats) {
    if (typeof currentStats?.speed === 'string' && currentStats.speed.trim()) {
        return currentStats.speed;
    }
    const outputRate = Number(currentStats?.output_tokens_per_second);
    if (Number.isFinite(outputRate) && outputRate > 0) {
        return `${outputRate.toFixed(2)} tokens/s`;
    }
    return '-';
}

function formatOptionalSeconds(value) {
    const numberValue = Number(value);
    return Number.isFinite(numberValue) && numberValue > 0 ? `${numberValue.toFixed(1)}s` : '-';
}

function getMessageKey(message, index) {
    const timestamp = message.created_at || message.client_sent_at || message.id || '';
    const snippet = typeof message.content === 'string' ? message.content.slice(0, 48) : '';
    return `${message.role || 'message'}-${timestamp}-${snippet}-${index}`;
}


export default function ChatInterface({ embedded = false } = {}) {
    const { t } = useDisplayLanguage();

    const [initialEmbeddedChatState] = useState(() => buildInitialEmbeddedChatState());
    const [messages, setMessages] = useState(() => (
        embedded
            ? initialEmbeddedChatState.messages
            : loadStoredChatMessages()
    ));
    const [baseMessages, setBaseMessages] = useState(() => (
        embedded
            ? initialEmbeddedChatState.baseMessages
            : []
    ));

    const [chatBaseVersion, setChatBaseVersion] = useState('empty');

    const [stats, setStats] = useState(null);

    const [input, setInput] = useState('');

    const [availableModels, setAvailableModels] = useState([]);

    const [modelReasoningSupport, setModelReasoningSupport] = useState({});

    const [selectedModel, setSelectedModel] = useState('');

    const [fastModeEnabled, setFastModeEnabled] = useState(() => loadStoredFastModeEnabled());

    const [contextPreferredModelId, setContextPreferredModelId] = useState('');

    const [voiceConfig, setVoiceConfig] = useState(() => normalizeVoiceConfig(null));
    const [voiceError, setVoiceError] = useState('');

    const [isLoading, setIsLoading] = useState(false);

    const [isRecording, setIsRecording] = useState(false);

    const [recordingTime, setRecordingTime] = useState(0);
    const [liveDurationNowMs, setLiveDurationNowMs] = useState(() => Date.now());



    const endRef = useRef(null);

    const mediaRecorderRef = useRef(null);

    const audioChunksRef = useRef([]);

    const timerRef = useRef(null);

    const contextPreferredModelRef = useRef('');

    const availableModelsRef = useRef([]);

    const selectedModelRef = useRef('');

    const manualModelSelectionRef = useRef(false);

    const streamRef = useRef(null);


    const cleanupRecordingResources = useCallback(() => {
        if (timerRef.current) {
            clearInterval(timerRef.current);
            timerRef.current = null;
        }

        const recorder = mediaRecorderRef.current;
        if (recorder) {
            recorder.ondataavailable = null;
            mediaRecorderRef.current.onstop = null;
            try {
                if (recorder.state && recorder.state !== 'inactive') {
                    recorder.stop();
                }
            } catch (error) {
                console.warn('[Voice] Failed to stop recorder during cleanup:', error);
            }
            mediaRecorderRef.current = null;
        }

        if (streamRef.current) {
            streamRef.current.getTracks().forEach((track) => track.stop());
            streamRef.current = null;
        }
    }, []);

    useEffect(() => {
        return cleanupRecordingResources;
    }, [cleanupRecordingResources]);

    useEffect(() => {

        let cancelled = false;

        const loadVoiceConfig = async () => {

            const settingsState = await loadSettingsState().catch(() => null);

            if (!cancelled) {

                setVoiceConfig(normalizeVoiceConfig(settingsState));

            }

        };

        const handleSettingsUpdated = (event) => {

            setVoiceConfig(normalizeVoiceConfig({ settings: event?.detail }));

            void loadVoiceConfig();

        };

        void loadVoiceConfig();

        window.addEventListener('vantage:settings-updated', handleSettingsUpdated);

        return () => {

            cancelled = true;

            window.removeEventListener('vantage:settings-updated', handleSettingsUpdated);

        };

    }, []);



    const scrollToBottom = () => {

        endRef.current?.scrollIntoView({ behavior: 'smooth' });

    };



    useEffect(() => {

        selectedModelRef.current = selectedModel;

    }, [selectedModel]);



    useEffect(() => {

        const syncChatContext = async ({ baseVersionOverride = null, baseMessagesOverride = null } = {}) => {

            if (baseVersionOverride) {

                const syncedState = reconcileChatHistoryWithBaseVersion({
                    nextBaseVersion: baseVersionOverride,
                    baseMessages: baseMessagesOverride,
                });

                setMessages(syncedState.messages);
                setBaseMessages(Array.isArray(baseMessagesOverride) ? baseMessagesOverride : []);
                setChatBaseVersion(syncedState.baseVersion);
                return;

            }

            try {

                const data = await fetchBackendJson('/api/chat/context', {
                    retryPolicy: 'load',
                });

                const syncedState = reconcileChatHistoryWithBaseVersion({
                    nextBaseVersion: data?.base_context_version,
                    baseMessages: data?.display_messages,
                });

                setMessages(syncedState.messages);
                setBaseMessages(Array.isArray(data?.display_messages) ? data.display_messages : []);
                setChatBaseVersion(syncedState.baseVersion);
                setStats(data?.stats || null);
                const preferredModelRef = (
                    data?.preferred_model_option_id
                    || buildModelOptionId(data?.preferred_provider_route, data?.preferred_model)
                );
                contextPreferredModelRef.current = preferredModelRef || '';
                setContextPreferredModelId(preferredModelRef || '');
                if (!manualModelSelectionRef.current && preferredModelRef && availableModelsRef.current.length > 0) {
                    const inheritedOption = findModelOption(availableModelsRef.current, preferredModelRef);
                    if (inheritedOption) {
                        setSelectedModel(inheritedOption.id);
                    }
                }

            } catch (error) {

                console.error('Failed to sync chat context:', error);
                setMessages(loadStoredChatMessages());
                setStats(null);

            }

        };

        const applyModelCatalog = (data) => {

            const modelList = buildModelOptionsFromCatalog(data).filter(isTextChatModelOption);

            setAvailableModels(modelList);
            availableModelsRef.current = modelList;

            setModelReasoningSupport(parseModelReasoningSupport(data?.providers));
            const defaultModel = data?.default_model;
            const storedModelRef = localStorage.getItem('preferred_llm_model_ref');
            const storedModel = localStorage.getItem('preferred_llm_model');

            if (modelList.length > 0) {
                const nextOption = (
                    (!manualModelSelectionRef.current && findModelOption(modelList, contextPreferredModelRef.current))
                    || findModelOption(modelList, selectedModelRef.current)
                    || findModelOption(modelList, storedModelRef)
                    || findModelOption(modelList, storedModel)
                    || resolvePreferredModelOption(modelList)
                    || findModelOption(modelList, defaultModel)
                    || modelList[0]
                );

                setSelectedModel(nextOption.id);

            }

        };

        const initializeModels = async () => {

            try {

                const data = await fetchBackendJson('/api/llm_models', { retryPolicy: 'load' });
                applyModelCatalog(data);

            } catch (error) {

                console.error('Failed to load model list:', error);

            }

        };



        initializeModels();
        void syncChatContext();

        const handleModelCatalogUpdated = (event) => {
            applyModelCatalog(event.detail);
        };
        window.addEventListener('vantage:llm-models-updated', handleModelCatalogUpdated);

        const handleChatContextBaseUpdated = (event) => {
            const preferredModelRef = (
                event?.detail?.preferredModelOptionId
                || buildModelOptionId(event?.detail?.preferredProviderRoute, event?.detail?.preferredModel)
            );
            if (preferredModelRef) {
                manualModelSelectionRef.current = false;
            }
            contextPreferredModelRef.current = preferredModelRef || '';
            setContextPreferredModelId(preferredModelRef || '');
            if (!manualModelSelectionRef.current && preferredModelRef && availableModelsRef.current.length > 0) {
                const inheritedOption = findModelOption(availableModelsRef.current, preferredModelRef);
                if (inheritedOption) {
                    setSelectedModel(inheritedOption.id);
                }
            }
            void syncChatContext({
                baseVersionOverride: event?.detail?.baseContextVersion ?? null,
                baseMessagesOverride: event?.detail?.displayMessages ?? [],
            });
        };

        window.addEventListener(CHAT_CONTEXT_BASE_UPDATED_EVENT, handleChatContextBaseUpdated);

        return () => {
            window.removeEventListener('vantage:llm-models-updated', handleModelCatalogUpdated);
            window.removeEventListener(CHAT_CONTEXT_BASE_UPDATED_EVENT, handleChatContextBaseUpdated);
        };

    }, []);



    useEffect(() => {

        saveStoredChatMessages(messages);

        if (!embedded || isLoading) {
            scrollToBottom();
        }

    }, [embedded, isLoading, messages]);

    useEffect(() => {

        storeChatContextBaseVersion(chatBaseVersion);

    }, [chatBaseVersion]);

    useEffect(() => {
        if (!isLoading || !stats?.startTime) {
            return undefined;
        }

        setLiveDurationNowMs(Date.now());
        const intervalId = window.setInterval(() => {
            setLiveDurationNowMs(Date.now());
        }, 200);

        return () => {
            window.clearInterval(intervalId);
        };
    }, [isLoading, stats?.startTime]);



    const clearChat = async () => {

        if (isLoading) return;

        if (typeof window.confirm === 'function' && !window.confirm(t('chat.clear_confirm'))) {
            return;
        }

        try {

            const data = await fetchBackendJson('/api/chat/context', {
                method: 'DELETE',
                retryPolicy: 'mutation',
            });

            const syncedState = reconcileChatHistoryWithBaseVersion({
                nextBaseVersion: data?.base_context_version,
                baseMessages: data?.display_messages,
            });
            setChatBaseVersion(syncedState.baseVersion);
            setMessages(syncedState.messages);
            setBaseMessages(Array.isArray(data?.display_messages) ? data.display_messages : []);
            setStats(data?.stats || null);

        } catch (error) {

            console.error('Failed to clear chat context:', error);
            setMessages(prev => [...prev, {
                role: 'assistant',
                content: t('chat.clear_failed', { error: error.message }),
            }]);

        }

    };



    const handleModelChange = (event) => {

        const nextModel = event.target.value;

        manualModelSelectionRef.current = true;

        setSelectedModel(nextModel);

        persistPreferredModelOption(findModelOption(availableModels, nextModel));

    };

    const handleFastModeChange = (event) => {

        setFastModeEnabled(saveFastModeEnabled(event.target.checked));

    };



    // Shared stream processing function to avoid code duplication

    const processStreamResponse = async (response, initialStats = null) => {

        const reader = response.body.getReader();

        const decoder = new TextDecoder();



        setMessages(prev => [...prev, { role: 'assistant', content: '', thinking: '' }]);



        let streamState = {
            buffer: '',
            assistantContent: '',
            assistantThinking: '',
            stats: initialStats ?? stats,
            error: null,
        };

        const syncAssistantMessage = (contentOverride, thinkingOverride) => {
            const nextContent = contentOverride ?? streamState.assistantContent;
            const nextThinking = thinkingOverride ?? streamState.assistantThinking;

            setMessages(prev => {
                const newMessages = [...prev];
                const lastMsg = newMessages[newMessages.length - 1];
                if (lastMsg?.role === 'assistant') {
                    lastMsg.content = nextContent;
                    lastMsg.thinking = nextThinking;
                    if (streamState.stats) {
                        lastMsg.stats = streamState.stats;
                    }
                }
                return newMessages;
            });
        };



        while (true) {

            const { value, done } = await reader.read();

            if (done) break;



            const chunk = decoder.decode(value, { stream: true });
            streamState = consumeChatStreamChunk(streamState, chunk);

            if (streamState.error) {
                syncAssistantMessage(t('common.error_prefix', { error: streamState.error }), streamState.assistantThinking);
                return false;
            }

            if (streamState.stats) {
                setStats(streamState.stats);
            }

            syncAssistantMessage();

        }

        const tail = decoder.decode();
        if (tail) {
            streamState = consumeChatStreamChunk(streamState, tail);
        }

        if (streamState.buffer) {
            streamState = consumeChatStreamChunk(streamState, '\n');
        }

        if (streamState.error) {
            syncAssistantMessage(t('common.error_prefix', { error: streamState.error }), streamState.assistantThinking);
            return false;
        }

        if (streamState.stats) {
            setStats(streamState.stats);
        }

        syncAssistantMessage();
        return true;

    };



    const sendMessage = async () => {

        if (!input.trim() || isLoading) return;



        const userMsg = input.trim();

        setMessages(prev => [...prev, { role: 'user', content: userMsg }]);

        setInput('');

        setIsLoading(true);



        try {
            const nextStats = {
                ...(stats ?? {}),
                speed: '0.00 tokens/s',
                total_duration: 0,
                total_tokens: 0,
                startTime: Date.now(),
            };
            setStats(nextStats);

            const payload = {
                message: userMsg,
                client_sent_at: buildClientSentAt(),
            };

            const selectedModelOption = findModelOption(availableModels, selectedModel);
            payload.reasoning_effort = normalizeReasoningEffortForModel(
                loadStoredActionPlanReasoningEffort(),
                selectedModelOption?.model,
            );

            if (selectedModelOption?.model) {

                payload.model = selectedModelOption.model;

            }
            if (selectedModelOption?.provider_route) {
                payload.provider_route = selectedModelOption.provider_route;
            }
            const serviceTier = resolveFastServiceTier({
                fastModeEnabled,
                model: selectedModelOption?.model,
            });
            if (serviceTier) {
                payload.service_tier = serviceTier;
            }



            const res = await fetchBackend('/api/chat', {

                method: 'POST',

                headers: { 'Content-Type': 'application/json' },

                body: JSON.stringify(payload),

                retryPolicy: 'stream',

            });



            await processStreamResponse(res, nextStats);



        } catch (err) {

            setMessages(prev => [...prev, {
                role: 'assistant',
                content: t('common.network_error', { error: err.message }),
            }]);

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
            setVoiceError('');

            const stream = await navigator.mediaDevices.getUserMedia({ audio: true });

            streamRef.current = stream;



            mediaRecorderRef.current = new MediaRecorder(stream);

            audioChunksRef.current = [];



            mediaRecorderRef.current.ondataavailable = (event) => {

                if (event.data.size > 0) {

                    audioChunksRef.current.push(event.data);

                }

            };



            mediaRecorderRef.current.onstop = async () => {

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

                const formData = new FormData();

                formData.append('file', audioBlob, 'recording.webm');



                setIsLoading(true);
                setInput(t('chat.transcribing'));



                try {

                    const transcribeResponse = await fetchBackend('/api/transcribe', {

                        method: 'POST',

                        body: formData,

                        retryPolicy: 'mutation',

                        allowHttpError: true,

                    });

                    const data = await transcribeResponse.json().catch(() => ({}));

                    if (!transcribeResponse.ok) {

                        const failedModel = data.voice_model || voiceConfig.model || DEFAULT_VOICE_MODEL;

                        const failedBaseUrl = data.voice_base_url || voiceConfig.baseUrl || '';

                        const details = data.details || data.error || `HTTP ${transcribeResponse.status}`;

                        const failedContext = failedBaseUrl ? `${failedModel} @ ${failedBaseUrl}` : failedModel;

                        if (data.configuration_error) {

                            const message = t('chat.voice_config_error', { model: failedModel });
                            setInput(message);
                            setVoiceError(message);

                        } else {

                            const message = t('chat.transcription_error', {
                                error: `${failedContext}: ${details}`,
                            });
                            setInput(message);
                            setVoiceError(message);

                        }

                        return;

                    }

                    if (data.transcription && data.transcription.trim()) {
                        const transcribedText = data.transcription.trim();
                        setInput("");
                        setMessages(prev => [...prev, { role: "user", content: transcribedText }]);

                        try {
                            const nextStats = {
                                ...(stats ?? {}),
                                speed: '0.00 tokens/s',
                                total_duration: 0,
                                total_tokens: 0,
                                startTime: Date.now(),
                            };
                            setStats(nextStats);

                            const chatPayload = { message: transcribedText };
                            chatPayload.client_sent_at = buildClientSentAt();
                            const selectedModelOption = findModelOption(availableModels, selectedModel);
                            chatPayload.reasoning_effort = normalizeReasoningEffortForModel(
                                loadStoredActionPlanReasoningEffort(),
                                selectedModelOption?.model,
                            );
                            if (selectedModelOption?.model) {
                                chatPayload.model = selectedModelOption.model;
                            }
                            if (selectedModelOption?.provider_route) {
                                chatPayload.provider_route = selectedModelOption.provider_route;
                            }
                            const serviceTier = resolveFastServiceTier({
                                fastModeEnabled,
                                model: selectedModelOption?.model,
                            });
                            if (serviceTier) {
                                chatPayload.service_tier = serviceTier;
                            }

                            const chatRes = await fetchBackend("/api/chat", {
                                method: "POST",
                                headers: { "Content-Type": "application/json" },
                                body: JSON.stringify(chatPayload),
                                retryPolicy: "stream",
                            });

                            await processStreamResponse(chatRes, nextStats);
                        } catch (chatErr) {
                            console.error("[Voice] Chat error:", chatErr);
                            setMessages(prev => [...prev, {
                                role: 'assistant',
                                content: t('common.network_error', { error: chatErr.message }),
                            }]);
                        }
                    } else {
                        console.warn("[Voice] Transcription empty or failed");
                        setInput(t('chat.transcription_failed'));
                        setVoiceError(t('chat.transcription_failed'));
                    }
                } catch (err) {

                    console.error("[Voice] Transcription error:", err);

                    const message = t('chat.transcription_error', {
                        error: `${voiceConfig.model || DEFAULT_VOICE_MODEL}: ${err.message}`,
                    });
                    setInput(message);
                    setVoiceError(message);

                } finally {

                    setIsLoading(false);

                }

            };



            mediaRecorderRef.current.start();
            setIsRecording(true);
            setRecordingTime(0);
            timerRef.current = setInterval(() => {
                setRecordingTime(prev => prev + 1);
            }, 1000);

        } catch (err) {
            console.error("[Voice] Error accessing microphone:", err);
            setVoiceError(t('chat.microphone_error', { error: err.message }));
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

    const roleBadgeLabel = (role) => (role === 'user' ? t('chat.role.user') : t('chat.role.assistant'));

    const recordButtonLabel = isRecording ? t('chat.record.short_stop') : t('chat.record.short_start');

    const sendButtonLabel = t('chat.send_short');

    const selectedModelOption = findModelOption(availableModels, selectedModel);
    const fastModeSupported = isFastModeSupportedForModel(selectedModelOption?.model);
    const providerLabel = selectedModelOption?.provider_label || null;
    const chatCacheBreakdown = formatActionPlanCacheBreakdown(stats);
    const hasCacheRouteWarning = Boolean(
        contextPreferredModelId
        && selectedModel
        && selectedModel !== contextPreferredModelId
        && findModelOption(availableModels, contextPreferredModelId)
    );
    const modelRouteNotice = hasCacheRouteWarning ? (
        <span style={{ fontSize: '0.78rem', color: 'var(--warning-color, #f59e0b)' }}>
            {t('chat.cache_route_warning')}
        </span>
    ) : null;
    const displayedDurationSeconds = computeDisplayedDurationSeconds(stats, {
        isActive: isLoading,
        nowMs: liveDurationNowMs,
    });
    const chatStatsBar = stats ? (
        <div className="action-plan-stats">
            <span>{t('common.first_token', { value: formatOptionalSeconds(stats.first_token_latency) })}</span>
            <span>{t('common.time', { value: displayedDurationSeconds.toFixed(1) })}</span>
            <span>{t('common.tokens', { value: ((stats.total_tokens || 0) / 1000).toFixed(1) })}</span>
            <span>{t('common.speed', { value: formatChatSpeed(stats) })}</span>
            {chatCacheBreakdown ? (
                <span>{t(stats.cache_scope === 'request' ? 'common.cache_request' : 'common.cache_session', { value: chatCacheBreakdown })}</span>
            ) : null}
        </div>
    ) : null;
    const visibleMessages = getVisibleMessages({
        embedded,
        messages,
        baseMessages,
    });
    const chatShellStyle = {
        height: embedded ? 'auto' : '100%',
        display: 'flex',
        flexDirection: 'column',
        overflow: embedded ? 'visible' : 'hidden',
    };
    const fastModeControl = fastModeSupported ? (
        <label
            title={t('common.fast_mode_tooltip')}
            style={{
                display: 'flex',
                alignItems: 'center',
                gap: '0.35rem',
                color: 'var(--text-secondary)',
                fontSize: '0.8rem',
                cursor: isLoading ? 'not-allowed' : 'pointer',
                opacity: isLoading ? 0.65 : 1,
            }}
        >
            <input
                type="checkbox"
                checked={fastModeEnabled}
                onChange={handleFastModeChange}
                disabled={isLoading}
            />
            <span>{t('common.fast_mode')}</span>
        </label>
    ) : null;
    const composerControls = (
        <div style={{

            display: 'flex',

            gap: '0.8rem',

            background: 'var(--bg-surface)',

            padding: '0.5rem',

            borderRadius: '12px',

            border: '1px solid var(--border-color)',

            alignItems: 'flex-end'

        }}>

            <span
                title={voiceConfig.baseUrl || t('settings.voice_provider.base_url')}
                style={{
                    alignSelf: 'center',
                    color: 'var(--text-muted)',
                    fontSize: '0.72rem',
                    maxWidth: '180px',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                }}
            >
                {t('chat.voice_model', { model: voiceConfig.model || DEFAULT_VOICE_MODEL })}
            </span>

            <button

                onClick={isRecording ? stopRecording : startRecording}

                className={isRecording ? 'pulse-animation' : ''}

                disabled={isLoading && !isRecording} // Disable start if loading, but allow stop if recording

                style={{

                    background: isRecording ? '#ff4d4d' : 'transparent',

                    color: isRecording ? '#fff' : 'var(--text-secondary)',

                    border: 'none',

                    borderRadius: '8px',

                    width: '48px', height: '40px',

                    display: 'flex', alignItems: 'center', justifyContent: 'center',

                    cursor: 'pointer',

                    transition: 'all 0.2s ease',

                    fontSize: '0.62rem',

                    fontWeight: 700,

                    letterSpacing: '0.04em'

                }}

                title={isRecording ? t('chat.record.stop') : t('chat.record.start')}

            >

                {recordButtonLabel}

            </button>



            {isRecording && (

                <div style={{

                    flex: 1, display: 'flex', alignItems: 'center',

                    color: '#ff4d4d', fontWeight: 'bold', fontSize: '0.9rem'

                }}>

                    {t('chat.record.active', { value: formatTime(recordingTime) })}

                </div>

            )}



            {!isRecording && (

                <textarea

                    value={input}

                    onChange={(e) => setInput(e.target.value)}

                    onKeyDown={handleKeyDown}

                    placeholder={t('chat.input_placeholder')}

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

                        maxHeight: '180px'

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

                    width: '56px', height: '40px',

                    display: 'flex', alignItems: 'center', justifyContent: 'center',

                    cursor: 'pointer',

                    transition: 'all 0.2s ease',

                    fontSize: '0.62rem',

                    fontWeight: 700,

                    letterSpacing: '0.04em'

                }}

            >

                {sendButtonLabel}

            </button>

            {voiceError ? (
                <span style={{ alignSelf: 'center', color: 'var(--warning-color, #f59e0b)', fontSize: '0.78rem' }}>
                    {voiceError}
                </span>
            ) : null}

        </div>
    );
    const composerPanel = (
        embedded ? (
            <div
                style={{
                    position: 'sticky',
                    bottom: '1rem',
                    zIndex: 3,
                }}
            >
                <div
                    className="glass-panel"
                    style={{
                        padding: '1rem 1.2rem',
                        backdropFilter: 'blur(12px)',
                    }}
                >
                    {composerControls}
                </div>
            </div>
        ) : (
            <div
                style={{
                    padding: '1.2rem',
                    borderTop: '1px solid var(--border-color)',
                    background: 'rgba(0,0,0,0.2)',
                }}
            >
                {composerControls}
            </div>
        )
    );



    return embedded ? (

        <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
            <div
                className="glass-panel"
                style={chatShellStyle}
            >

                <div style={{ padding: '1rem', borderBottom: '1px solid var(--border-color)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>

                    <h3 style={{ margin: 0, display: 'flex', alignItems: 'center', gap: '0.5rem' }}>

                        <Bot size={20} color="var(--primary-color)" />

                        {t('chat.header.title')}

                    </h3>

                    <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
                        {chatStatsBar}
                        <label
                            style={{
                                display: 'flex',
                                alignItems: 'center',
                                gap: '0.5rem',
                                color: 'var(--text-secondary)',
                                fontSize: '0.8rem',
                            }}
                        >
                            <span>{t('common.model')}</span>
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
                                {availableModels.length === 0 && <option value="">{t('chat.default_model')}</option>}
                                {availableModels.map((modelOption) => (
                                    <option key={modelOption.id} value={modelOption.id}>
                                        {`${modelOption.label}${formatModelReasoningSupportLabel(modelOption.model, modelReasoningSupport, t)}`}
                                    </option>
                                ))}
                            </select>
                        </label>
                        {fastModeControl}
                        <span style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                            {providerLabel ? t('chat.powered_by', { provider: providerLabel }) : t('chat.provider_unavailable')}
                        </span>
                        {modelRouteNotice}

                        {messages.length > 0 && (

                            <button

                                onClick={clearChat}

                                title={t('chat.clear_title')}

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

                                {t('chat.clear')}

                            </button>

                        )}

                    </div>

                </div>



                <div style={{

                    flex: embedded ? '0 0 auto' : 1,

                    overflowY: embedded ? 'visible' : 'auto',

                    padding: '1.5rem',

                    display: 'flex',

                    flexDirection: 'column',

                    gap: '1.5rem'

                }}>

                    {visibleMessages.length === 0 && (

                        <div style={{ textAlign: 'center', color: 'var(--text-muted)', marginTop: '2rem' }}>

                            <p>{embedded ? t('chat.empty.with_context') : t('chat.empty.without_context')}</p>

                            <p style={{ fontSize: '0.9rem' }}>
                                {embedded ? t('chat.empty.followup') : t('chat.empty.try_input')}
                            </p>

                        </div>

                    )}



                    {visibleMessages.map((msg, i) => (

                        <div key={getMessageKey(msg, i)} style={{

                            alignSelf: msg.role === 'user' ? 'flex-end' : 'flex-start',

                            maxWidth: '85%',

                            display: 'flex',

                            gap: '0.8rem',

                            flexDirection: msg.role === 'user' ? 'row-reverse' : 'row'

                        }}>

                            <div style={{

                                width: '32px', height: '32px',

                                background: msg.role === 'user' ? 'var(--primary-color)' : 'var(--bg-surface-hover)',

                                color: msg.role === 'user' ? '#fff' : 'var(--primary-color)',

                                borderRadius: '10px',

                                display: 'flex', alignItems: 'center', justifyContent: 'center',

                                flexShrink: 0,

                                fontSize: '0.68rem',

                                fontWeight: 700,

                                letterSpacing: '0.04em',

                                border: msg.role === 'user' ? 'none' : '1px solid var(--border-color)'

                            }}>

                                {roleBadgeLabel(msg.role)}

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

                                minWidth: 0

                            }}>

                                {/* Thinking Process Display */}

                                <ThinkingDisclosure
                                    title={formatThinkingTitleWithDuration(
                                        t('chat.reasoning_title'),
                                        msg.stats?.total_duration ?? msg.stats?.duration,
                                        msg.stats?.completion_reasoning_tokens,
                                    )}
                                    text={msg.thinking}
                                />



                                <div className="markdown-body" style={{ fontSize: '0.95rem' }}>

                                    <ReactMarkdown
                                        remarkPlugins={[remarkGfm]}
                                        components={renderChatMarkdownComponents(msg.role)}
                                    >

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

                            <span style={{ fontSize: '0.85rem', color: 'var(--text-muted)' }}>{t('chat.thinking')}</span>

                        </div>

                    )}

                    <div ref={endRef} />

                </div>
            </div>
            {composerPanel}
        </div>
    ) : (

        <div
            className="glass-panel"
            style={chatShellStyle}
        >

            <div style={{ padding: '1rem', borderBottom: '1px solid var(--border-color)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>

                <h3 style={{ margin: 0, display: 'flex', alignItems: 'center', gap: '0.5rem' }}>

                    <Bot size={20} color="var(--primary-color)" />

                    {t('chat.header.title')}

                </h3>

                <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
                    {chatStatsBar}
                    <label
                        style={{
                            display: 'flex',
                            alignItems: 'center',
                            gap: '0.5rem',
                            color: 'var(--text-secondary)',
                            fontSize: '0.8rem',
                        }}
                    >
                        <span>{t('common.model')}</span>
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
                            {availableModels.length === 0 && <option value="">{t('chat.default_model')}</option>}
                            {availableModels.map((modelOption) => (
                                <option key={modelOption.id} value={modelOption.id}>
                                    {`${modelOption.label}${formatModelReasoningSupportLabel(modelOption.model, modelReasoningSupport, t)}`}
                                </option>
                            ))}
                        </select>
                    </label>
                    {fastModeControl}
                    <span style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                        {providerLabel ? t('chat.powered_by', { provider: providerLabel }) : t('chat.provider_unavailable')}
                    </span>
                    {modelRouteNotice}

                    {messages.length > 0 && (

                        <button

                            onClick={clearChat}

                            title={t('chat.clear_title')}

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

                            {t('chat.clear')}

                        </button>

                    )}

                </div>

            </div>



            <div style={{

                flex: embedded ? '0 0 auto' : 1,

                overflowY: embedded ? 'visible' : 'auto',

                padding: '1.5rem',

                display: 'flex',

                flexDirection: 'column',

                gap: '1.5rem'

            }}>

                {visibleMessages.length === 0 && (

                    <div style={{ textAlign: 'center', color: 'var(--text-muted)', marginTop: '2rem' }}>

                        <p>{embedded ? t('chat.empty.with_context') : t('chat.empty.without_context')}</p>

                        <p style={{ fontSize: '0.9rem' }}>
                            {embedded ? t('chat.empty.followup') : t('chat.empty.try_input')}
                        </p>

                    </div>

                )}



                {visibleMessages.map((msg, i) => (

                    <div key={getMessageKey(msg, i)} style={{

                        alignSelf: msg.role === 'user' ? 'flex-end' : 'flex-start',

                        maxWidth: '85%',

                        display: 'flex',

                        gap: '0.8rem',

                        flexDirection: msg.role === 'user' ? 'row-reverse' : 'row'

                    }}>

                        <div style={{

                            width: '32px', height: '32px',

                            background: msg.role === 'user' ? 'var(--primary-color)' : 'var(--bg-surface-hover)',

                            color: msg.role === 'user' ? '#fff' : 'var(--primary-color)',

                            borderRadius: '10px',

                            display: 'flex', alignItems: 'center', justifyContent: 'center',

                            flexShrink: 0,

                            fontSize: '0.68rem',

                            fontWeight: 700,

                            letterSpacing: '0.04em',

                            border: msg.role === 'user' ? 'none' : '1px solid var(--border-color)'

                        }}>

                            {roleBadgeLabel(msg.role)}

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

                            minWidth: 0

                        }}>

                            {/* Thinking Process Display */}

                            <ThinkingDisclosure
                                title={formatThinkingTitleWithDuration(
                                    t('chat.reasoning_title'),
                                    msg.stats?.total_duration ?? msg.stats?.duration,
                                    msg.stats?.completion_reasoning_tokens,
                                )}
                                text={msg.thinking}
                            />



                            <div className="markdown-body" style={{ fontSize: '0.95rem' }}>

                                <ReactMarkdown
                                    remarkPlugins={[remarkGfm]}
                                    components={renderChatMarkdownComponents(msg.role)}
                                >

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

                        <span style={{ fontSize: '0.85rem', color: 'var(--text-muted)' }}>{t('chat.thinking')}</span>

                    </div>

                )}

                <div ref={endRef} />

            </div>

            {composerPanel}

        </div>
    );

}
