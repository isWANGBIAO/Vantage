// No Node/Electron dependency: the connection contract is shared with Vite and UI.
const DEFAULT_BACKEND_BASE_URL = 'http://127.0.0.1:8000';

function isLoopbackHost(value) {
    const host = String(value || '').toLowerCase().replace(/^\[|\]$/g, '');
    if (host === 'localhost' || host === '::1') return true;
    const octets = host.split('.');
    return octets.length === 4 && octets[0] === '127'
        && octets.every((part) => /^(0|[1-9]\d{0,2})$/.test(part) && Number(part) <= 255);
}

function normalizeBackendBaseUrl(value) {
    const input = typeof value === 'string' ? value.trim() : '';
    let parsed;
    try {
        parsed = new URL(input);
    } catch {
        throw new TypeError('Vantage backend URL must be a valid loopback HTTP(S) URL.');
    }
    if (!['http:', 'https:'].includes(parsed.protocol) || !isLoopbackHost(parsed.hostname)
        || parsed.username || parsed.password || parsed.search || parsed.hash
        || input.includes('\\') || /[\u0000-\u001f\u007f]/.test(input)
        || parsed.port === '0') {
        throw new TypeError('Vantage backend URL must use HTTP(S) and a loopback host without credentials, query, or fragment.');
    }
    // URL() normalizes non-standard IPv4 notation, which other clients reject.
    const authority = input.match(/^https?:\/\/([^/]+)/i)?.[1];
    const rawHost = authority?.startsWith('[') ? authority.slice(0, authority.indexOf(']') + 1) : authority?.split(':')[0];
    if (!isLoopbackHost(rawHost)) throw new TypeError('Vantage backend URL must use a loopback host.');
    return parsed.href.replace(/\/+$/, '');
}

function resolveBackendConnection({ baseUrl, env = {} } = {}) {
    const configured = baseUrl || env.VANTAGE_BACKEND_URL;
    const host = String(env.VANTAGE_BACKEND_HOST || '127.0.0.1').trim();
    const port = String(env.VANTAGE_BACKEND_PORT || '8000').trim();
    if (!configured && (!isLoopbackHost(host) || !/^\d+$/.test(port) || Number(port) < 1 || Number(port) > 65535)) {
        throw new TypeError('Vantage backend host and port must identify a loopback HTTP endpoint.');
    }
    const formattedHost = host.includes(':') && !host.startsWith('[') ? `[${host}]` : host;
    const normalized = normalizeBackendBaseUrl(configured || `http://${formattedHost}:${port}`);
    const parsed = new URL(normalized);
    return Object.freeze({
        baseUrl: normalized,
        protocol: parsed.protocol,
        hostname: parsed.hostname.replace(/^\[|\]$/g, ''),
        port: Number(parsed.port || (parsed.protocol === 'https:' ? 443 : 80)),
        pathPrefix: parsed.pathname.replace(/\/+$/, ''),
    });
}

function buildConnectionUrl(connection, apiPath) {
    const pathOnly = typeof apiPath === 'string' ? apiPath.split('?')[0] : '';
    if (typeof apiPath !== 'string' || !apiPath.startsWith('/') || apiPath.startsWith('//')
        || apiPath.includes('\\') || /(?:^|\/)\.{1,2}(?:\/|$|\?)/.test(pathOnly)
        || /%(?:2e|2f|5c)/i.test(pathOnly)) {
        throw new TypeError('Backend requests require an absolute local API path.');
    }
    return `${connection.baseUrl}${apiPath}`;
}

module.exports = { DEFAULT_BACKEND_BASE_URL, isLoopbackHost, normalizeBackendBaseUrl, resolveBackendConnection, buildConnectionUrl };
