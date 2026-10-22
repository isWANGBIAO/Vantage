const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const test = require('node:test')

const webapp = path.resolve(__dirname, '../..')
const manifest = JSON.parse(fs.readFileSync(path.join(webapp, 'package.json'), 'utf8'))
const lock = JSON.parse(fs.readFileSync(path.join(webapp, 'package-lock.json'), 'utf8'))

function instances(name) {
  return Object.entries(lock.packages).filter(([location]) => (
    location === `node_modules/${name}` || location.endsWith(`/node_modules/${name}`)
  ))
}

// Audit security floors, including each separately installed nested major.
// Keep these assertions even when npm's live advisory service is unavailable.
const securityFloors = {
  '@humanfs/node': { 0: '0.16.8' },
  '@xmldom/xmldom': { 0: '0.8.15' },
  axios: { 1: '1.20.0' },
  'baseline-browser-mapping': { 2: '2.11.0' },
  'brace-expansion': { 1: '1.1.21', 2: '2.1.7', 5: '5.0.12' },
  browserslist: { 4: '4.28.7' },
  'fast-uri': { 3: '3.1.8' },
  'follow-redirects': { 1: '1.16.1' },
  'http-cache-semantics': { 4: '4.2.1' },
  joi: { 18: '18.2.9' },
  'js-yaml': { 4: '4.3.2' },
  'source-map-js': { 1: '1.2.2' },
  undici: { 6: '6.28.1', 7: '7.29.1' },
}

for (const [name, floors] of Object.entries(securityFloors)) {
  test(`every locked ${name} instance meets its patched security floor`, () => {
    const installed = instances(name)
    assert.ok(installed.length > 0, `${name} must be checked, not silently omitted`)
    for (const [location, entry] of installed) {
      assert.match(entry.version, /^\d+\.\d+\.\d+$/, `${location} needs a stable version`)
      const actual = entry.version.split('.').map(Number)
      const floor = floors[actual[0]]
      assert.ok(floor, `${location}@${entry.version} requires an explicit security review`)
      const required = floor.split('.').map(Number)
      assert.ok(
        actual[1] > required[1] || (actual[1] === required[1] && actual[2] >= required[2]),
        `${location}@${entry.version} must be >= ${floor}`,
      )
    }
  })
}

test('the lockfile replaces vulnerable roarr 2 without changing its default-export API family', () => {
  const loggers = instances('roarr')
  assert.ok(loggers.length > 0, 'the downloader logging dependency remains installed')
  for (const [location, entry] of loggers) {
    assert.equal(entry.version, '3.3.0', `${location} must remove sprintf-js while retaining the logger API`)
    assert.equal(entry.dependencies['sprintf-js'], undefined)
    assert.equal(entry.dependencies['fast-printf'], '^1.3.0')
  }
})

test('the lockfile does not contain unpatched sprintf-js', () => {
  assert.deepEqual(instances('sprintf-js').map(([location]) => location), [])
})

test('security refresh preserves production roots and the current Electron builder toolchain', () => {
  const productionRoots = {
    echarts: '^6.1.0',
    'echarts-for-react': '^3.0.2',
    'lucide-react': '^0.577.0',
    react: '^19.3.1',
    'react-dom': '^19.3.1',
    'react-markdown': '^10.1.0',
    'remark-gfm': '^4.0.1',
    ssh2: '^1.17.0',
  }
  assert.deepEqual(manifest.dependencies, productionRoots)
  assert.deepEqual(lock.packages[''].dependencies, productionRoots)
  assert.equal(manifest.devDependencies.electron, '^42.11.14')
  assert.equal(manifest.devDependencies['electron-builder'], '^26.15.3')
  for (const [name, expected] of Object.entries({
    electron: '42.11.14',
    'electron-builder': '26.15.3',
    'app-builder-lib': '26.15.3',
    'dmg-builder': '26.15.3',
  })) {
    const installed = instances(name)
    assert.ok(installed.length > 0, `${name} must remain installed`)
    for (const [location, entry] of installed) {
      assert.equal(entry.version, expected, `${location} must not be downgraded or upgraded incidentally`)
    }
  }
})

test('the logging override is scoped to the unchanged builder proxy transport', () => {
  assert.deepEqual(manifest.overrides, {
    '@electron/get@3.1.0': { 'global-agent@3.0.0': { roarr: '3.3.0' } },
  })
  const agents = instances('global-agent')
  assert.ok(agents.length > 0, 'the proxy-capable downloader dependency remains installed')
  for (const [location, entry] of agents) {
    assert.equal(entry.version, '3.0.0', `${location} must retain the existing proxy transport`)
  }
  const downloads = instances('@electron/get')
  assert.ok(downloads.some(([, entry]) => entry.version === '3.1.0'))
  for (const [location, entry] of downloads) {
    assert.ok(['3.1.0', '5.0.0'].includes(entry.version), `${location} must not change downloader major`)
  }
})
