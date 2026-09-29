const encoder = new TextEncoder();
const bytes = (value) => encoder.encode(JSON.stringify(value)).length;
export const emptyOutput = () => ({ entries: [], cursor: 0, omitted: false });
export function appendOutput(
  previous,
  batch,
  { maxEntries = 300, maxBytes = 256 * 1024 } = {},
) {
  let omitted = previous.omitted || Boolean(batch.dropped);
  const additions = (batch.entries || [])
    .filter((entry) => entry.seq > previous.cursor)
    .map((entry) => {
      if (bytes([entry]) <= maxBytes) return entry;
      omitted = true;
      const text = String(entry.text);
      let low = 0,
        high = text.length;
      while (low < high) {
        const mid = Math.ceil((low + high) / 2);
        if (
          bytes([{ ...entry, text: text.slice(0, mid), truncated: true }]) <=
          maxBytes
        )
          low = mid;
        else high = mid - 1;
      }
      return { ...entry, text: text.slice(0, low), truncated: true };
    });
  const entries = [...previous.entries, ...additions];
  let size = bytes(entries);
  while (entries.length > maxEntries || size > maxBytes) {
    const removed = entries.shift();
    if (!removed) break;
    size -= bytes(removed) + (entries.length ? 1 : 0);
    omitted = true;
  }
  return {
    entries,
    cursor: Math.max(previous.cursor, batch.cursor || 0),
    omitted,
  };
}
