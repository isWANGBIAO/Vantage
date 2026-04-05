import { normalizeActionPlanContent } from './actionPlanContent.js';

export const CHAT_HISTORY_STORAGE_KEY = 'chat_history';
export const CHAT_CONTEXT_VERSION_STORAGE_KEY = 'chat_context_version';
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

  if (safeStorage && (didReset || messages.length === 0)) {
    saveStoredChatMessages(nextMessages, safeStorage);
    safeStorage.setItem(CHAT_CONTEXT_VERSION_STORAGE_KEY, normalizedBaseVersion);
  }

  return {
    messages: nextMessages,
    didReset,
    baseVersion: normalizedBaseVersion,
  };
}
