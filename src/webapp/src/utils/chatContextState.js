import { normalizeActionPlanContent } from './actionPlanContent.js';

export const CHAT_HISTORY_STORAGE_KEY = 'chat_history';
export const CHAT_CONTEXT_VERSION_STORAGE_KEY = 'chat_context_version';
export const CHAT_CONTEXT_BASE_MESSAGE_COUNT_STORAGE_KEY = 'chat_context_base_message_count';
export const CHAT_CONTEXT_BASE_UPDATED_EVENT = 'chat-context-base-updated';

function getStorage(storage = globalThis.localStorage) {
  if (!storage || typeof storage.getItem !== 'function') {
    return null;
  }

  return storage;
}

export function normalizeChatContextBaseVersion(value) {
  if (typeof value !== 'string') {
    return 'empty';
  }

  const normalized = value.trim();
  return normalized || 'empty';
}

export function inferLeadingAssistantMessageCount(messages) {
  if (!Array.isArray(messages) || messages.length === 0) {
    return 0;
  }

  let count = 0;

  while (count < messages.length) {
    const message = messages[count];
    if (message?.role !== 'assistant') {
      break;
    }
    count += 1;
  }

  return count;
}

export function normalizeChatContextBaseMessageCount(value, fallbackMessages = []) {
  if (value === null || value === undefined || value === '') {
    return inferLeadingAssistantMessageCount(fallbackMessages);
  }

  const parsed = Number.parseInt(value, 10);
  if (!Number.isFinite(parsed) || parsed < 0) {
    return inferLeadingAssistantMessageCount(fallbackMessages);
  }

  return parsed;
}

export function loadStoredChatMessages(storage = globalThis.localStorage) {
  const safeStorage = getStorage(storage);
  if (!safeStorage) {
    return [];
  }

  const raw = safeStorage.getItem(CHAT_HISTORY_STORAGE_KEY);
  if (!raw) {
    return [];
  }

  try {
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    safeStorage.removeItem(CHAT_HISTORY_STORAGE_KEY);
    return [];
  }
}

export function loadStoredChatContextBaseMessageCount(
  storage = globalThis.localStorage,
  fallbackMessages = null,
) {
  const safeStorage = getStorage(storage);
  const messages = Array.isArray(fallbackMessages)
    ? fallbackMessages
    : loadStoredChatMessages(safeStorage);

  if (!safeStorage) {
    return inferLeadingAssistantMessageCount(messages);
  }

  const raw = safeStorage.getItem(CHAT_CONTEXT_BASE_MESSAGE_COUNT_STORAGE_KEY);
  return normalizeChatContextBaseMessageCount(raw, messages);
}

export function saveStoredChatMessages(messages, storage = globalThis.localStorage) {
  const safeStorage = getStorage(storage);
  if (!safeStorage) {
    return;
  }

  if (!Array.isArray(messages) || messages.length === 0) {
    safeStorage.removeItem(CHAT_HISTORY_STORAGE_KEY);
    return;
  }

  safeStorage.setItem(CHAT_HISTORY_STORAGE_KEY, JSON.stringify(messages));
}

export function storeChatContextBaseVersion(baseVersion, storage = globalThis.localStorage) {
  const safeStorage = getStorage(storage);
  const normalized = normalizeChatContextBaseVersion(baseVersion);

  if (safeStorage) {
    safeStorage.setItem(CHAT_CONTEXT_VERSION_STORAGE_KEY, normalized);
  }

  return normalized;
}

export function storeChatContextBaseMessageCount(
  baseMessageCount,
  storage = globalThis.localStorage,
) {
  const safeStorage = getStorage(storage);
  const normalized = normalizeChatContextBaseMessageCount(baseMessageCount);

  if (safeStorage) {
    safeStorage.setItem(CHAT_CONTEXT_BASE_MESSAGE_COUNT_STORAGE_KEY, String(normalized));
  }

  return normalized;
}

function normalizeBaseChatMessages(baseMessages) {
  if (!Array.isArray(baseMessages)) {
    return [];
  }

  return baseMessages.map((message) => {
    if (!message || typeof message !== 'object') {
      return message;
    }

    if (message.role !== 'assistant' || typeof message.content !== 'string') {
      return message;
    }

    return {
      ...message,
      content: normalizeActionPlanContent(message.content),
    };
  });
}

export function reconcileChatHistoryWithBaseVersion({
  storage = globalThis.localStorage,
  nextBaseVersion,
  baseMessages = [],
} = {}) {
  const safeStorage = getStorage(storage);
  const messages = loadStoredChatMessages(safeStorage);
  const normalizedBaseMessages = normalizeBaseChatMessages(baseMessages);
  const normalizedBaseVersion = normalizeChatContextBaseVersion(nextBaseVersion);
  const storedBaseVersion = safeStorage?.getItem(CHAT_CONTEXT_VERSION_STORAGE_KEY);
  const startsWithBaseMessages = normalizedBaseMessages.every((baseMessage, index) => {
    const currentMessage = messages[index];
    return JSON.stringify(currentMessage) === JSON.stringify(baseMessage);
  });
  const shouldHydrateBaseMessages = messages.length === 0 || !startsWithBaseMessages;
  const didReset = storedBaseVersion !== normalizedBaseVersion || shouldHydrateBaseMessages;
  const nextMessages = didReset ? normalizedBaseMessages : messages;

  if (safeStorage) {
    safeStorage.setItem(CHAT_CONTEXT_VERSION_STORAGE_KEY, normalizedBaseVersion);
    safeStorage.setItem(
      CHAT_CONTEXT_BASE_MESSAGE_COUNT_STORAGE_KEY,
      String(normalizedBaseMessages.length),
    );
  }

  if (safeStorage && (didReset || messages.length === 0)) {
    saveStoredChatMessages(nextMessages, safeStorage);
  }

  return {
    messages: nextMessages,
    didReset,
    baseVersion: normalizedBaseVersion,
    baseMessageCount: normalizedBaseMessages.length,
  };
}

export function buildInitialEmbeddedChatState(storage = globalThis.localStorage) {
  const messages = loadStoredChatMessages(storage);
  const baseMessageCount = loadStoredChatContextBaseMessageCount(storage, messages);

  return {
    messages,
    baseMessages: Array.from({ length: baseMessageCount }, () => null),
  };
}
