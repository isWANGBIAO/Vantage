// Isolated process: global-agent patches Node's global HTTP(S) methods.
const assert = require('node:assert/strict')
const fs = require('node:fs/promises')
const os = require('node:os')
const path = require('node:path')
const { createRequire } = require('node:module')

async function main() {
  const options = JSON.parse(process.argv[2])
  const builderRequire = createRequire(require.resolve('app-builder-lib/package.json'))
  const getRequire = createRequire(builderRequire.resolve('@electron/get/package.json'))
  assert.equal(getRequire('./package.json').version, '3.1.0', 'exercise builder get, not root get 5')
  const { initializeProxy } = builderRequire('@electron/get')
  initializeProxy()
  assert.ok(global.GLOBAL_AGENT, 'initializeProxy must not silently swallow bootstrap failure')
  if (options.inspectLogging) {
    const agentRequire = createRequire(getRequire.resolve('global-agent/package.json'))
    const logger = agentRequire('roarr').default
    assert.equal(typeof logger.child, 'function', 'global-agent needs the default.child API')
    logger.child({ fixture: 'dependency-compatibility', untrusted: options.payload })
      .info('message=%s count=%d', options.payload, 7)
    global.GLOBAL_AGENT.NO_PROXY = options.payload
  }
  if (options.repeatBootstrap) {
    const controller = global.GLOBAL_AGENT
    controller.NO_PROXY = 'preserved.invalid'
    initializeProxy()
    assert.equal(global.GLOBAL_AGENT, controller)
    assert.equal(global.GLOBAL_AGENT.NO_PROXY, 'preserved.invalid')
  }
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), 'vantage-proxy-compat-'))
  try {
    const { GotDownloader } = getRequire('./dist/cjs/GotDownloader.js')
    const downloaderOptions = {
      quiet: true,
      retry: { limit: 0 },
      timeout: { request: 4000 },
    }
    if (options.ca) downloaderOptions.https = { certificateAuthority: await fs.readFile(options.ca) }
    const destination = path.join(directory, 'synthetic-download.txt')
    try {
      await new GotDownloader().download(options.url, destination, downloaderOptions)
      console.log(JSON.stringify({ ok: true, body: await fs.readFile(destination, 'utf8') }))
    } catch (error) {
      console.log(JSON.stringify({ ok: false, code: error.code, message: error.message }))
    }
  } finally {
    await fs.rm(directory, { recursive: true, force: true })
  }
}

main().catch(error => {
  console.error(error)
  process.exitCode = 1
})
