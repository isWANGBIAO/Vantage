const CORRUPTION_PATTERNS = [
  /(?:<strong>-<\/strong>){2,}/i,
  /<b<br>>/i,
  /<b<(?:b<)+/i,
  /<stron<br>/i,
  /<stron[gG]/i,
  /<br\s*\/?>/i,
  /<\/?(p|strong|ul|ol|li|em)\b[^>]*>/i,
];

const DROP_LINE_PATTERNS = [
  /^\|\s*$/,
  /^(?:\|\s*){2,}$/,
  /^#{2,}\s*\|\s*$/,
  /^(?:\*\s*){3,}$/,
  /^#{3,}\s*$/,
  /^(?:#{1,6}\s*){2,}$/,
  /^(?:\*\*\s*){2,}$/,
  /^(?:[-*+]\s*)+$/,
];

function sanitizeLine(line) {
  let sanitized = line.trimEnd();
  sanitized = sanitized.replace(/(?:<strong>-<\/strong>){2,}/gi, ' ');
  sanitized = sanitized.replace(/<b<br>>/gi, ' ');
  sanitized = sanitized.replace(/<b(?:<b)+<?b*/gi, ' ');
  sanitized = sanitized.replace(/<\/?stron<br>?/gi, ' ');
  sanitized = sanitized.replace(/<br\s*\/?>/gi, ' ');
  sanitized = sanitized.replace(/<\/p>/gi, ' ');
  sanitized = sanitized.replace(/<p>/gi, '');
  sanitized = sanitized.replace(/<li>/gi, '- ');
  sanitized = sanitized.replace(/<\/li>/gi, ' ');
  sanitized = sanitized.replace(/<\/?(ul|ol|strong|em)\b[^>]*>/gi, '');
  sanitized = sanitized.replace(/&nbsp;/gi, ' ');
  sanitized = sanitized.replace(/\s{2,}/g, ' ');

  if (DROP_LINE_PATTERNS.some((pattern) => pattern.test(sanitized.trim()))) {
    return '';
  }

  return sanitized.trimEnd();
}

function collapseBlankLines(lines) {
  const collapsed = [];
  let blankCount = 0;

  for (const line of lines) {
    if (!line.trim()) {
      blankCount += 1;
      if (blankCount > 2) {
        continue;
      }
    } else {
      blankCount = 0;
    }
    collapsed.push(line);
  }

  return collapsed.join('\n').trim();
}

function unwrapMarkdownDocumentFence(content) {
  let unwrapped = content.replace(/^\s*```(?:markdown|md)?\s*\n/i, '');

  if (unwrapped !== content) {
    unwrapped = unwrapped.replace(/\n```[\t ]*$/i, '');
  }

  return unwrapped;
}

export function normalizeActionPlanContent(content) {
  if (!content) {
    return '';
  }

  const normalized = unwrapMarkdownDocumentFence(content.replace(/\r\n/g, '\n'));
  return collapseBlankLines(normalized.split('\n').map(sanitizeLine));
}

export function shouldRenderActionPlanAsPlainText(content) {
  if (!content) {
    return false;
  }

  const normalized = normalizeActionPlanContent(content);
  return CORRUPTION_PATTERNS.some((pattern) => pattern.test(normalized));
}

export function toPlainTextActionPlanContent(content) {
  return normalizeActionPlanContent(content)
    .replace(/<br\s*\/?>/gi, '\n')
    .replace(/<\/p>/gi, '\n\n')
    .replace(/<p>/gi, '')
    .replace(/<li>/gi, '- ')
    .replace(/<\/li>/gi, '\n')
    .replace(/<\/?(ul|ol|strong|em|h[1-6])>/gi, '')
    .replace(/&nbsp;/gi, ' ')
    .replace(/\n{3,}/g, '\n\n')
    .trim();
}

export function getActionPlanRenderState(content) {
  const plainText = shouldRenderActionPlanAsPlainText(content);
  return {
    plainText,
    markdownContent: normalizeActionPlanContent(content),
    plainTextContent: toPlainTextActionPlanContent(content),
  };
}
