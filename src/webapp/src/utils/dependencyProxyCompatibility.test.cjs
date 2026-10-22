const assert = require('node:assert/strict')
const { execFile } = require('node:child_process')
const fs = require('node:fs')
const http = require('node:http')
const https = require('node:https')
const net = require('node:net')
const path = require('node:path')
const { createRequire } = require('node:module')
const { promisify } = require('node:util')
const test = require('node:test')

const runFile = promisify(execFile)
// These intentionally public self-signed credentials identify only loopback test
// servers. They are synthetic, grant no real access, and need no OpenSSL in CI.
const fixture = path.resolve(__dirname, '../../test-fixtures')
const certificate = path.join(fixture, 'dependency-proxy-cert.pem')
const builderRequire = createRequire(require.resolve('app-builder-lib/package.json'))
const getRequire = createRequire(builderRequire.resolve('@electron/get/package.json'))
const body = 'Vantage synthetic dependency download: 中文 & < >'
const authorization = `Basic ${Buffer.from('synthetic-user:synthetic-password').toString('base64')}`

test('builder download chain preserves global-agent 3 while the vulnerable logging leaf is replaced', () => {
  assert.equal(getRequire('./package.json').version, '3.1.0')
  assert.equal(getRequire('global-agent/package.json').version, '3.0.0')
})

async function startServer(t, server, sockets) {
  server.on('connection', socket => {
    sockets.add(socket)
    socket.on('close', () => sockets.delete(socket))
    socket.on('error', () => {})
  })
  await new Promise((resolve, reject) => {
    server.once('error', reject)
    server.listen(0, '127.0.0.1', resolve)
  })
  t.after(async () => {
    for (const socket of sockets) socket.destroy()
    await new Promise(resolve => server.close(resolve))
  })
  return server.address().port
}

async function networkFixture(t) {
  const sockets = new Set()
  const counts = { origin: 0, secureOrigin: 0, httpProxy: 0, connect: 0, authenticated: 0 }
  const originPort = await startServer(t, http.createServer((_request, response) => {
    counts.origin++
    response.end(body)
  }), sockets)
  const securePort = await startServer(t, https.createServer({
    key: fs.readFileSync(path.join(fixture, 'dependency-proxy-key.pem')),
    cert: fs.readFileSync(certificate),
  }, (_request, response) => {
    counts.secureOrigin++
    response.end(body)
  }), sockets)
  const proxy = http.createServer((request, response) => {
    counts.httpProxy++
    if (request.headers['proxy-authorization'] !== authorization) {
      response.writeHead(407).end()
      return
    }
    counts.authenticated++
    const target = new URL(request.url)
    // Never become an open proxy: fixture forwards only to its own loopback origin.
    assert.equal(target.hostname, '127.0.0.1')
    assert.equal(Number(target.port), originPort)
    const upstream = http.request(target, { headers: { connection: 'close' } }, incoming => {
      response.writeHead(incoming.statusCode)
      incoming.pipe(response)
    })
    upstream.on('error', () => response.destroy())
    request.pipe(upstream)
  })
  proxy.on('connect', (request, client, head) => {
    counts.connect++
    if (request.headers['proxy-authorization'] !== authorization) {
      client.end('HTTP/1.1 407 Proxy Authentication Required\r\n\r\n')
      return
    }
    counts.authenticated++
    assert.equal(request.url, `127.0.0.1:${securePort}`)
    const upstream = net.connect(securePort, '127.0.0.1', () => {
      client.write('HTTP/1.1 200 Connection Established\r\n\r\n')
      if (head.length) upstream.write(head)
      upstream.pipe(client)
      client.pipe(upstream)
    })
    sockets.add(upstream)
    upstream.on('close', () => sockets.delete(upstream))
    upstream.on('error', () => client.destroy())
    client.on('error', () => upstream.destroy())
    client.on('close', () => upstream.destroy())
  })
  const proxyPort = await startServer(t, proxy, sockets)
  return {
    counts,
    url: `http://127.0.0.1:${originPort}/download`,
    secureUrl: `https://127.0.0.1:${securePort}/download`,
    proxy: `http://synthetic-user:synthetic-password@127.0.0.1:${proxyPort}`,
  }
}

async function download(options, proxyEnvironment = {}) {
  const env = { ...process.env }
  for (const key of Object.keys(env)) {
    if (/proxy/i.test(key) || /^NODE_(TLS_REJECT_UNAUTHORIZED|EXTRA_CA_CERTS)$/i.test(key)) delete env[key]
  }
  Object.assign(env, proxyEnvironment, { ELECTRON_GET_NO_PROGRESS: '1' })
  const result = await runFile(process.execPath, ['--max-old-space-size=64', path.join(fixture, 'dependency-proxy-child.cjs'), JSON.stringify(options)], {
    env,
    timeout: 10000,
    maxBuffer: 128 * 1024,
    windowsHide: true,
  })
  const lines = result.stdout.trim().split(/\r?\n/).map(line => JSON.parse(line))
  return { ...lines.at(-1), logs: lines.slice(0, -1) }
}

function successful(result) {
  assert.equal(result.ok, true, JSON.stringify(result))
  assert.equal(result.body, body)
}

test('builder downloader routes HTTP through a real authenticated proxy', { timeout: 15000 }, async t => {
  const network = await networkFixture(t)
  successful(await download({ url: network.url }, { GLOBAL_AGENT_HTTP_PROXY: network.proxy }))
  assert.deepEqual(network.counts, { origin: 1, secureOrigin: 0, httpProxy: 1, connect: 0, authenticated: 1 })
})

test('builder downloader uses authenticated HTTPS CONNECT and an explicit trusted test CA', { timeout: 15000 }, async t => {
  const network = await networkFixture(t)
  successful(await download({ url: network.secureUrl, ca: certificate }, { GLOBAL_AGENT_HTTPS_PROXY: network.proxy }))
  assert.deepEqual(network.counts, { origin: 0, secureOrigin: 1, httpProxy: 0, connect: 1, authenticated: 1 })
})

test('builder downloader rejects an untrusted TLS certificate through CONNECT by default', { timeout: 15000 }, async t => {
  const network = await networkFixture(t)
  const result = await download({ url: network.secureUrl }, { GLOBAL_AGENT_HTTPS_PROXY: network.proxy })
  assert.equal(result.ok, false)
  assert.match(result.code, /SELF_SIGNED_CERT|UNABLE_TO_VERIFY/)
  assert.deepEqual(network.counts, { origin: 0, secureOrigin: 0, httpProxy: 0, connect: 1, authenticated: 1 })
})

test('builder downloader honors NO_PROXY for both HTTP and HTTPS', { timeout: 25000 }, async t => {
  const network = await networkFixture(t)
  const env = { GLOBAL_AGENT_HTTP_PROXY: network.proxy, GLOBAL_AGENT_HTTPS_PROXY: network.proxy, GLOBAL_AGENT_NO_PROXY: '127.0.0.1' }
  successful(await download({ url: network.url }, env))
  successful(await download({ url: network.secureUrl, ca: certificate }, env))
  assert.deepEqual(network.counts, { origin: 1, secureOrigin: 1, httpProxy: 0, connect: 0, authenticated: 0 })
})

test('builder downloader supports ordinary direct HTTP and HTTPS without proxy settings', { timeout: 25000 }, async t => {
  const network = await networkFixture(t)
  successful(await download({ url: network.url }))
  successful(await download({ url: network.secureUrl, ca: certificate }))
  assert.deepEqual(network.counts, { origin: 1, secureOrigin: 1, httpProxy: 0, connect: 0, authenticated: 0 })
})

test('unset HTTPS proxy falls back to the configured HTTP proxy', { timeout: 15000 }, async t => {
  const network = await networkFixture(t)
  successful(await download({ url: network.secureUrl, ca: certificate }, { GLOBAL_AGENT_HTTP_PROXY: network.proxy }))
  assert.equal(network.counts.connect, 1)
  assert.equal(network.counts.authenticated, 1)
  assert.equal(network.counts.secureOrigin, 1)
})

test('explicit empty HTTPS proxy preserves the existing HTTP proxy fallback', { timeout: 15000 }, async t => {
  const network = await networkFixture(t)
  // global-agent 4 changes this build-download proxy behavior from || to ??.
  // Keep the version 3 fallback contract rather than silently changing routing.
  successful(await download({ url: network.secureUrl, ca: certificate }, { GLOBAL_AGENT_HTTP_PROXY: network.proxy, GLOBAL_AGENT_HTTPS_PROXY: '' }))
  assert.equal(network.counts.connect, 1)
  assert.equal(network.counts.authenticated, 1)
  assert.equal(network.counts.secureOrigin, 1)
})

test('repeated get initializeProxy preserves the installed global controller and its state', { timeout: 15000 }, async t => {
  const network = await networkFixture(t)
  successful(await download({ url: network.url, repeatBootstrap: true }, { GLOBAL_AGENT_HTTP_PROXY: network.proxy }))
  assert.equal(network.counts.httpProxy, 1)
  assert.equal(network.counts.authenticated, 1)
})

test('enabled real proxy logging keeps hostile precision strings in URL/context/format arguments as data', { timeout: 15000 }, async t => {
  const network = await networkFixture(t)
  const payload = '%.2147483648f'
  // URLs must be valid URI encoded input; raw percent in context is tested below.
  const url = `${network.url}/${encodeURIComponent(payload)}`
  // This is not a claim that fast-printf accepts arbitrary untrusted formats.
  // global-agent's reviewed messages are literals; external values are context.
  const result = await download({ url, inspectLogging: true, payload }, {
    GLOBAL_AGENT_HTTP_PROXY: network.proxy,
    ROARR_LOG: 'true',
  })
  successful(result)
  assert.equal(network.counts.httpProxy, 1)
  const proxyLog = result.logs.find(log => log.context?.package === 'global-agent' && log.message === 'proxying request')
  assert.ok(proxyLog, 'exercise the actual global-agent logger, not a disabled logger')
  assert.equal(proxyLog.context.destination, url)
  const configurationLog = result.logs.find(log => log.context?.package === 'global-agent' && log.context?.change?.name === 'NO_PROXY' && log.context?.change?.value === payload)
  assert.ok(configurationLog, 'raw hostile precision must remain context data in actual global-agent logs')
  const formatLog = result.logs.find(log => log.context?.fixture === 'dependency-compatibility')
  assert.ok(formatLog, 'default.child logger must emit with ROARR_LOG=true')
  assert.equal(formatLog.context.untrusted, payload)
  assert.equal(formatLog.message, `message=${payload} count=7`)
})

test('builder-resolved plist builds and parses XML special characters without changing values', () => {
  const plist = builderRequire('plist')
  const input = { CFBundleDisplayName: 'Vantage & <Body> "Analysis" 中文', nested: { text: 'x > y & y < z', enabled: true }, values: ['a&b', '<tag>', 42] }
  const xml = plist.build(input)
  assert.match(xml, /&amp;/)
  assert.match(xml, /&lt;/)
  assert.deepEqual(plist.parse(xml), input)
})
