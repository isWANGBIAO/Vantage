const http = require('http');
const https = require('https');
const { buildConnectionUrl } = require('./backendConnection.cjs');

const CONFIGURATION_OPERATIONS = new Set([
    'GET /api/automation/settings',
    'PUT /api/automation/settings',
    'GET /api/automation/settings/display-language',
    'PUT /api/automation/settings/display-language',
    'GET /api/automation/onboarding',
    'POST /api/automation/onboarding/complete',
]);

function createBackendJsonRequester({ connection, waitUntilReady = async () => {}, timeoutMs = 10000 } = {}) {
    return async function requestBackendJson(method, apiPath, payload) {
        if (!CONFIGURATION_OPERATIONS.has(`${method} ${apiPath}`)) {
            throw new Error('Unsupported local backend operation.');
        }
        await waitUntilReady();
        const body = payload === undefined ? null : Buffer.from(JSON.stringify(payload), 'utf8');
        return new Promise((resolve, reject) => {
            const transport = connection.protocol === 'https:' ? https : http;
            const request = transport.request(buildConnectionUrl(connection, apiPath), {
                method,
                headers: body ? { 'content-type': 'application/json', 'content-length': body.length } : {},
            }, (response) => {
                const chunks = [];
                let size = 0;
                response.on('error', reject);
                response.on('data', (chunk) => {
                    size += chunk.length;
                    if (size > 2 * 1024 * 1024) {
                        request.destroy(new Error('Vantage backend response was too large.'));
                        return;
                    }
                    chunks.push(chunk);
                });
                response.on('end', () => {
                    // Native HTTP never follows redirects, including credential-bearing mutations.
                    if (response.statusCode < 200 || response.statusCode >= 300) {
                        reject(new Error(`Vantage backend request failed with status ${response.statusCode}.`));
                        return;
                    }
                    try {
                        resolve(JSON.parse(Buffer.concat(chunks).toString('utf8')));
                    } catch {
                        reject(new Error('Vantage backend returned an invalid JSON response.'));
                    }
                });
            });
            request.setTimeout(timeoutMs, () => request.destroy(new Error('Vantage backend request timed out.')));
            request.on('error', () => reject(new Error('Vantage backend request failed.')));
            if (body) request.write(body);
            request.end();
        });
    };
}

module.exports = { createBackendJsonRequester };
