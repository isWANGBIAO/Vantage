import { normalizeActionPlanContent } from './actionPlanContent.js';

export const CHAT_CONTEXT_BASE_UPDATED_EVENT = 'chat-context-base-updated';

function visibleMessages(value) {
  if (!Array.isArray(value)) throw new TypeError('Invalid backend conversation messages');
  return value.map((message) => {
    if (!['user', 'assistant'].includes(message?.role) || typeof message.content !== 'string') {
      throw new TypeError('Invalid backend conversation message');
    }
    return { role: message.role, content: message.content };
  });
}

/** Backend snapshots replace the view, including same-base explicit resets. */
export function normalizeBackendChatContext(payload) {
  if (typeof payload?.context_version !== 'string' || typeof payload?.base_context_version !== 'string') {
    throw new TypeError('Invalid backend conversation revision');
  }
  const baseMessages = visibleMessages(payload.display_messages).map((message) => ({
    ...message,
    content: normalizeActionPlanContent(message.content),
  }));
  const messages = visibleMessages(payload.messages).map((message, index) => (
    index < baseMessages.length ? baseMessages[index] : message
  ));
  return {
    messages,
    baseMessages,
    baseVersion: payload.base_context_version,
    contextVersion: payload.context_version,
  };
}

/** Retain transient rendering details only for messages confirmed by the server. */
export function retainChatPresentation(messages, previous = []) {
  return messages.map((message, index) => {
    const old = previous[index];
    if (old?.role !== message.role || old?.content !== message.content) return message;
    return {
      ...message,
      ...(typeof old.thinking === 'string' ? { thinking: old.thinking } : {}),
      ...(old.stats && typeof old.stats === 'object' ? { stats: old.stats } : {}),
    };
  });
}
