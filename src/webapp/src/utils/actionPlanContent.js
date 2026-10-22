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
  let sanitized = line;
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

  if (DROP_LINE_PATTERNS.some((pattern) => pattern.test(sanitized.trim()))) {
    return '';
  }

  return sanitized;
}

function collapseBlankLines(lines) {
  const collapsed = [];
  let blankCount = 0;

  for (const { line, literal } of lines) {
    if (!literal && !line.trim()) {
      blankCount += 1;
      if (blankCount > 2) {
        continue;
      }
    } else {
      blankCount = 0;
    }
    collapsed.push(line);
  }

  return collapsed.join('\n').replace(/^\n+|\n+$/g, '');
}

function sanitizeDocument(content) {
  let fence = null;
  let indented = false;
  return content.split('\n').map(line => {
    const marker = line.match(/^ {0,3}(`{3,}|~{3,})(.*)$/);
    if (fence) {
      if (marker && marker[1][0] === fence.character && marker[1].length >= fence.length && !marker[2].trim()) fence = null;
      return { line, literal: true };
    }
    if (marker && !(marker[1][0] === '`' && marker[2].includes('`'))) {
      fence = { character: marker[1][0], length: marker[1].length };
      return { line, literal: true };
    }
    if (line.trim()) indented = line.startsWith('    ') || line.startsWith('\t');
    return { line: indented ? line : sanitizeLine(line), literal: indented };
  });
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
  return collapseBlankLines(sanitizeDocument(normalized));
}

export function shouldRenderActionPlanAsPlainText(content) {
  if (!content) {
    return false;
  }

  const normalized = normalizeActionPlanContent(content);
  const prose = sanitizeDocument(normalized).filter(({ literal }) => !literal).map(({ line }) => line).join('\n');
  return CORRUPTION_PATTERNS.some((pattern) => pattern.test(prose));
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
