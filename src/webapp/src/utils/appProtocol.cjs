const fs = require('node:fs');
const path = require('node:path');
const { Readable } = require('node:stream');
const { resolveBackendConnection, buildConnectionUrl } = require('./backendConnection.cjs');

const APP_SCHEME = 'vantage';
const APP_ORIGIN = 'vantage://app';
const APP_ENTRY_URL = `${APP_ORIGIN}/index.html`;
const APP_SCHEME_PRIVILEGES = Object.freeze({ standard: true, secure: true, supportFetchAPI: true, corsEnabled: true, stream: true });
const CONTENT_SECURITY_POLICY = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; media-src 'self' blob:; connect-src 'self'; font-src 'self' data:; object-src 'none'; base-uri 'none'; frame-src 'none'; frame-ancestors 'none'; form-action 'none'";
const MIME_TYPES = {
    '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8',
    '.svg': 'image/svg+xml', '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp',
    '.gif': 'image/gif', '.ico': 'image/x-icon', '.woff': 'font/woff', '.woff2': 'font/woff2', '.ttf': 'font/ttf',
};
const REQUEST_HEADERS = ['accept', 'content-type', 'range', 'if-range', 'if-none-match', 'if-modified-since', 'x-vantage-intent'];
const RESPONSE_HEADERS = ['content-type', 'content-disposition', 'cache-control', 'etag', 'last-modified', 'accept-ranges', 'content-range'];

function parseAppUrl(value) {
    if (typeof value !== 'string' || /[\\\u0000-\u0020\u007f]/.test(value)) throw new TypeError('Invalid app URL.');
    const url = new URL(value);
    if (url.protocol !== `${APP_SCHEME}:` || url.host !== 'app' || url.username || url.password) throw new TypeError('Invalid app host.');
    const rawPath = value.replace(/^[a-z]+:\/\/[^/]+/i, '').split(/[?#]/)[0] || '/';
    const decoded = decodeURIComponent(rawPath);
    if (decoded.includes('\\') || decoded.includes('\0') || /%[\da-f]{2}/i.test(decoded)
        || decoded.split('/').some(part => part === '..' || part === '.') || decoded.includes('//')) {
        throw new TypeError('Invalid app path.');
    }
    return { url, pathname: decodeURIComponent(url.pathname) };
}

function isTrustedAppUrl(value, { documentOnly = false } = {}) {
    try {
        const { url, pathname } = parseAppUrl(value);
        return !documentOnly || ((pathname === '/' || pathname === '/index.html') && !url.search);
    } catch { return false; }
}

function isTrustedInitiator(request) {
    // Newer Electron provides this unforgeable value. Older supported versions
    // carry the browser-controlled Origin/referrer on same-origin requests.
    if (request.initiatorOrigin !== undefined) return request.initiatorOrigin === APP_ORIGIN;
    const origin = request.headers.get('origin');
    if (origin) return origin === APP_ORIGIN;
    return Boolean(request.referrer && isTrustedAppUrl(request.referrer, { documentOnly: true }));
}

function safeHeaders(extra = {}) {
    return { 'content-security-policy': CONTENT_SECURITY_POLICY, 'x-content-type-options': 'nosniff', ...extra };
}

function errorResponse(status, message) {
    return new Response(message, { status, headers: safeHeaders({ 'content-type': 'text/plain; charset=utf-8', 'cache-control': 'no-store' }) });
}

async function awaitReady(waitUntilReady, signal) {
    if (signal?.aborted) throw signal.reason || new DOMException('Aborted', 'AbortError');
    const ready = Promise.resolve().then(waitUntilReady);
    if (!signal) return ready;
    return new Promise((resolve, reject) => {
        const cleanup = () => signal.removeEventListener('abort', abort);
        const abort = () => { cleanup(); reject(signal.reason || new DOMException('Aborted', 'AbortError')); };
        signal.addEventListener('abort', abort, { once: true });
        ready.then(value => { cleanup(); resolve(value); }, error => { cleanup(); reject(error); });
    });
}

function createAppProtocolHandler({ assetRoot, connection, waitUntilReady = async () => {}, fetchBackend = globalThis.fetch, verifyRequest = isTrustedInitiator } = {}) {
    const root = path.resolve(assetRoot);
    const backend = resolveBackendConnection({ baseUrl: connection.baseUrl });
    return async function handleAppRequest(request) {
        let parsed;
        try { parsed = parseAppUrl(request.url); } catch { return errorResponse(400, 'Invalid app resource.'); }
        const { url, pathname } = parsed;
        if (request.initiatorOrigin !== undefined && request.initiatorOrigin !== APP_ORIGIN) {
            return errorResponse(403, 'Untrusted app request.');
        }
        const method = request.method.toUpperCase();
        if (pathname.startsWith('/api/v1/') || pathname.startsWith('/static/')) {
            if (!verifyRequest(request)) return errorResponse(403, 'Untrusted backend request.');
            if (!['GET', 'HEAD', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS'].includes(method)
                || (pathname.startsWith('/static/') && !['GET', 'HEAD'].includes(method))) {
                return errorResponse(405, 'Unsupported method.');
            }
            try {
                await awaitReady(waitUntilReady, request.signal);
                const headers = new Headers();
                for (const name of REQUEST_HEADERS) {
                    if (request.headers.has(name)) headers.set(name, request.headers.get(name));
                }
                const response = await fetchBackend(buildConnectionUrl(backend, `${url.pathname}${url.search}`), {
                    method, headers, redirect: 'manual', credentials: 'omit', signal: request.signal,
                    ...(!['GET', 'HEAD'].includes(method) && request.body ? { body: request.body, duplex: 'half' } : {}),
                });
                if (response.status >= 300 && response.status < 400 && response.status !== 304) {
                    await response.body?.cancel();
                    return errorResponse(502, 'Backend redirects are not supported.');
                }
                const responseHeaders = new Headers(safeHeaders());
                for (const name of RESPONSE_HEADERS) {
                    if (response.headers.has(name)) responseHeaders.set(name, response.headers.get(name));
                }
                // Preserve the live stream. Cancelling it only closes this HTTP
                // observer; job cancellation requires its explicit POST route.
                return new Response(method === 'HEAD' || [204, 205, 304].includes(response.status) ? null : response.body, {
                    status: response.status, headers: responseHeaders,
                });
            } catch (error) {
                if (request.signal?.aborted) throw error;
                return errorResponse(502, 'Local backend unavailable.');
            }
        }
        if (!['GET', 'HEAD'].includes(method)) return errorResponse(405, 'Unsupported method.');
        const relativeName = pathname === '/' ? 'index.html' : pathname.slice(1);
        const contentType = MIME_TYPES[path.extname(relativeName).toLowerCase()];
        if (!contentType || (path.extname(relativeName).toLowerCase() === '.html' && relativeName !== 'index.html')) {
            return errorResponse(404, 'App resource not found.');
        }
        try {
            const [realRoot, realFile] = await Promise.all([
                fs.promises.realpath(root), fs.promises.realpath(path.resolve(root, relativeName)),
            ]);
            const relative = path.relative(realRoot, realFile);
            if (!relative || relative.startsWith(`..${path.sep}`) || relative === '..' || path.isAbsolute(relative)) {
                return errorResponse(403, 'App resource is outside the bundle.');
            }
            const stat = await fs.promises.stat(realFile);
            if (!stat.isFile()) return errorResponse(404, 'App resource not found.');
            return new Response(method === 'HEAD' ? null : Readable.toWeb(fs.createReadStream(realFile)), {
                headers: safeHeaders({ 'content-type': contentType, 'content-length': String(stat.size) }),
            });
        } catch { return errorResponse(404, 'App resource not found.'); }
    };
}

function isTrustedAppNetworkRequest(details, webContents) {
    if (!webContents || details.webContentsId !== webContents.id || !isTrustedAppUrl(details.url)) return false;
    if (details.resourceType === 'mainFrame') return isTrustedAppUrl(details.url, { documentOnly: true });
    if (details.resourceType === 'subFrame' || details.frame?.parent) return false;
    return isTrustedAppUrl(details.frame?.url || webContents.getURL(), { documentOnly: true });
}

function installAppProtocol({ session, getWebContents, ...options }) {
    // Electron 42 does not expose initiatorOrigin or a referrer on protocol.handle
    // requests. Enforce identity in webRequest BEFORE reaching the handler.
    // The protected session owns both this gate and the protocol registration.
    session.webRequest.onBeforeRequest({ urls: [`${APP_SCHEME}://*/*`] }, (details, callback) => {
        callback({ cancel: !isTrustedAppNetworkRequest(details, getWebContents()) });
    });
    session.protocol.handle(APP_SCHEME, createAppProtocolHandler({
        ...options,
        verifyRequest: request => request.initiatorOrigin === undefined || isTrustedInitiator(request),
    }));
}

module.exports = { APP_SCHEME, APP_ORIGIN, APP_ENTRY_URL, APP_SCHEME_PRIVILEGES, createAppProtocolHandler, installAppProtocol, isTrustedAppNetworkRequest, isTrustedAppUrl };
