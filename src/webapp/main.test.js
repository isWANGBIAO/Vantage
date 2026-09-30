import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createServer } from 'node:http';
import { once } from 'node:events';
import protocol from './src/utils/configurationProtocol.cjs';
import transport from './src/utils/backendTransport.cjs';
import connection from './src/utils/backendConnection.cjs';

const protocolSource = readFileSync(new URL('./src/utils/configurationProtocol.cjs', import.meta.url), 'utf8');
const mainSource = readFileSync(new URL('./main.cjs', import.meta.url), 'utf8');
const appSource = readFileSync(new URL('./src/App.jsx', import.meta.url), 'utf8');
const settingsSource = readFileSync(new URL('./src/components/Settings.jsx', import.meta.url), 'utf8');
const packageJson = JSON.parse(
  readFileSync(new URL('./package.json', import.meta.url), 'utf8'),
);

test('startup transport waits for backend readiness before sending onboarding and settings requests', async () => {
  let release;
  const backendReadyPromise = new Promise(resolve => { release = resolve; });
  const sent = [];
  const server = createServer((request, response) => {
    sent.push(request.url);
    response.setHeader('Content-Type', 'application/json');
    response.end(JSON.stringify({ ready: true }));
  });
  server.listen(0, '127.0.0.1');
  await once(server, 'listening');
  try {
    const requestBackendJson = transport.createBackendJsonRequester({
      connection: connection.resolveBackendConnection({ baseUrl: `http://127.0.0.1:${server.address().port}` }),
      waitUntilReady: () => backendReadyPromise,
    });
    const requests = ['/api/v1/onboarding', '/api/v1/settings'].map(p => requestBackendJson('GET', p));
    assert.equal(sent.length, 0, 'No connection attempt while packaged backend is starting');
    release();
    const responses = await Promise.all(requests);
    assert.equal(sent.length, 2);
    assert.ok(responses.every(response => response.ready));
    await assert.rejects(requestBackendJson('POST', '/api/not-allowlisted'), /Unsupported/);
    assert.equal(sent.length, 2);
  } finally {
    server.closeAllConnections();
    await new Promise(resolve => server.close(resolve));
  }
});

test('Electron main process loads the bounded logger factory but starts with a no-op logger', () => {
  assert.match(
    mainSource,
    /const\s*\{\s*createBoundedLogger\s*\}\s*=\s*require\(['"]\.\/src\/utils\/boundedLogger\.cjs['"]\);/,
  );
  assert.match(
    mainSource,
    /let\s+log\s*=\s*\{\s*info:\s*\(\)\s*=>\s*\{\},\s*warn:\s*\(\)\s*=>\s*\{\},\s*error:\s*\(\)\s*=>\s*\{\},\s*\};/,
  );
});

test('Electron main process has no recursive inline file and console logger', () => {
  assert.doesNotMatch(mainSource, /function\s+writeLog\s*\(/);
  assert.doesNotMatch(mainSource, /fs\.appendFileSync\(logFile,/);
  assert.doesNotMatch(mainSource, /console\.(?:log|error)\(logEntry\)/);
});

test('Electron main process activates and cleans file logging only for the primary instance', () => {
  const lockCall = 'const gotTheLock = app.requestSingleInstanceLock();';
  const lockIndex = mainSource.indexOf(lockCall);
  assert.notEqual(lockIndex, -1);
  assert.doesNotMatch(
    mainSource.slice(0, lockIndex),
    /createBoundedLogger\(\{/,
    'the file logger must not be constructed before the instance lock',
  );
  assert.doesNotMatch(
    mainSource.slice(0, lockIndex),
    /app\.getPath\(['"](?:home|userData)['"]\)/,
    'sensitive logger roots must not query app paths before the instance lock',
  );

  const singleInstanceBranch = mainSource
    .slice(lockIndex + lockCall.length)
    .match(
      /^\s*if\s*\(!gotTheLock\)\s*\{(?<secondary>[\s\S]*?)\}\s*else\s*\{(?<primaryPrefix>[\s\S]*?)app\.on\('second-instance'/,
    );

  assert.ok(singleInstanceBranch, 'expected cleanup to be scoped by the single-instance branch');

  const { secondary, primaryPrefix } = singleInstanceBranch.groups;
  assert.doesNotMatch(secondary, /createBoundedLogger\(\{/);
  assert.doesNotMatch(secondary, /log\.(?:info|warn|error|cleanup)\(/);
  assert.doesNotMatch(secondary, /app\.getPath\(/);
  assert.match(secondary, /app\.quit\(\)/);

  assert.match(primaryPrefix, /log\s*=\s*createBoundedLogger\(\{/);
  const expectedPathMappings = [
    [/prefix:\s*app\.getPath\('home'\),\s*label:\s*'<user-home>'/],
    [/prefix:\s*app\.getPath\('userData'\),\s*label:\s*'<user-data>'/],
    [/prefix:\s*runtimePaths\.dataDir,\s*label:\s*'<runtime-data>'/],
    [/prefix:\s*runtimePaths\.logDir,\s*label:\s*'<runtime-logs>'/],
    [/prefix:\s*__dirname,\s*label:\s*'<app-root>'/],
    [/prefix:\s*projectRoot,\s*label:\s*'<project-root>'/],
    [/prefix:\s*path\.dirname\(process\.execPath\),\s*label:\s*'<app-executable>'/],
  ];
  for (const [mappingPattern] of expectedPathMappings) {
    assert.match(primaryPrefix, mappingPattern);
  }
  const constructionIndex = primaryPrefix.indexOf('log = createBoundedLogger({');
  const cleanupIndex = primaryPrefix.indexOf('log.cleanup();');
  const startupIndex = primaryPrefix.indexOf("log.info('Vantage Electron starting...');");
  assert.notEqual(constructionIndex, -1);
  assert.notEqual(cleanupIndex, -1);
  assert.notEqual(startupIndex, -1);
  assert.ok(constructionIndex < cleanupIndex, 'construction must precede cleanup');
  assert.ok(cleanupIndex < startupIndex, 'cleanup must precede primary-instance startup logs');
  assert.equal(mainSource.match(/createBoundedLogger\(\{/g)?.length, 1);
  assert.equal(mainSource.match(/log\.cleanup\(\)/g)?.length, 1);
});

test('npm test explicitly runs the Electron main-process contract', () => {
  assert.match(packageJson.scripts.test, /(?:^|\s)main\.test\.js(?:\s|$)/);
  assert.match(packageJson.scripts.test, /vite\.config\.test\.js/);
  assert.match(packageJson.scripts.test, /package\.test\.js/);
  assert.match(packageJson.scripts.test, /src\/\*\*\/\*\.test\.js/);
});

test('Electron main window hides native chrome while keeping native window controls', () => {
  assert.ok(mainSource.includes('Menu.setApplicationMenu(null)'));
  assert.match(mainSource, /titleBarStyle\s*=\s*'hidden'/);
  assert.match(mainSource, /titleBarOverlay\s*=/);
  assert.ok(mainSource.includes('autoHideMenuBar: true'));
});

test('Electron exposes one canonical configuration transport and only narrow native IPC', () => {
  assert.ok(mainSource.includes("ipcMain.handle('backend:configuration-request'"));
  assert.ok(mainSource.includes("ipcMain.handle('platform:open-settings-path'"));
  assert.doesNotMatch(mainSource, /ipcMain\.handle\('(?:settings:|onboarding:)/);
  assert.doesNotMatch(mainSource, /buildElectronSettingsState|toBackendSettingsPayload|configurationProtocol/);
  assert.doesNotMatch(mainSource, /saveSettingsPayload|saveOnboardingCompletion|persistSettings/);
  assert.ok(mainSource.includes('resolveAllowedSettingsPath'));
  assert.ok(mainSource.includes('settingsPathAllowlist'));
});

test('native preferences reread canonical settings before applying OS side effects', () => {
  const readPreferences = mainSource.match(/async function readSavedPreferences\([\s\S]*?\n\}/)?.[0];
  const applyPreferences = mainSource.match(/function applySavedNativePreferences\([\s\S]*?\n\}/)?.[0];
  assert.match(readPreferences, /requestBackendJson\('GET', '\/api\/v1\/settings'\)/);
  assert.match(applyPreferences, /await readSavedPreferences\(\)/);
  assert.match(applyPreferences, /applyLaunchAtLoginSetting/);
  assert.match(applyPreferences, /settings\.launch_at_login/);
  assert.match(applyPreferences, /syncTrayMenu\(\)/);
  assert.match(applyPreferences, /setTitleBarOverlay/);
});

test('Electron settings mapping forwards provider context and output capability fields', () => {
  const providerFields = protocolSource.match(/const providerFields = \[([\s\S]*?)\n\s*\];/)?.[1];
  assert.ok(providerFields);
  assert.match(providerFields, /'context_window_tokens'/);
  assert.match(providerFields, /'max_output_tokens'/);
});

test('Electron settings mapper preserves omitted provider maps and explicit replacements', () => {
  const sandbox = { mapSettings: protocol.toBackendSettingsPayload };

  const partial = sandbox.mapSettings({
    providerConfig: { sampling_defaults: { temperature: 0.7 }, model_profiles: { local: { top_p: 0.9 } } },
  });
  assert.equal(Object.hasOwn(partial.provider_config, 'providers'), false);
  assert.deepEqual(partial.provider_config.sampling_defaults, { temperature: 0.7 });

  const replacement = sandbox.mapSettings({
    providerConfig: { providers: { local: { route: 'local', model: 'example-model' } } },
  });
  assert.equal(Object.hasOwn(replacement.provider_config, 'providers'), true);
  assert.equal(replacement.provider_config.providers.local.model, 'example-model');
});

test('Electron settings mapper preserves invalid null and array provider values for backend rejection', () => {
  const sandbox = { mapSettings: protocol.toBackendSettingsPayload };

  for (const providers of [null, [{ route: 'local', model: 'example-model' }]]) {
    const mapped = sandbox.mapSettings({ providerConfig: { providers } });
    assert.strictEqual(mapped.provider_config.providers, providers);
  }
});

test('Electron settings mapper rejects non-record provider entries before sending a request', () => {
  const sandbox = { mapSettings: protocol.toBackendSettingsPayload };

  for (const entry of [null, false, 42, 'placeholder', []]) {
    assert.throws(
      () => sandbox.mapSettings({ providerConfig: { providers: { placeholder: entry } } }),
      /plain JSON object/,
    );
  }
});

test('Electron settings mapper rejects non-JSON provider entries before they can become empty replacements', () => {
  const sandbox = { mapSettings: protocol.toBackendSettingsPayload };

  for (const entry of [new Date(), new Map(), undefined]) {
    assert.throws(
      () => sandbox.mapSettings({ providerConfig: { providers: { local: entry } } }),
      /plain JSON object/,
    );
  }
  for (const providers of [new Date(), new Map()]) {
    assert.throws(
      () => sandbox.mapSettings({ providerConfig: { providers } }),
      /plain JSON object/,
    );
  }
  assert.throws(
    () => sandbox.mapSettings({ providerConfig: { providers: { local: { model: undefined } } } }),
    /plain JSON object/,
  );

  const ordinaryRecord = sandbox.mapSettings({
    providerConfig: { providers: { local: { route: 'local', model: 'example-model' } } },
  });
  assert.equal(ordinaryRecord.provider_config.providers.local.model, 'example-model');

  const nullPrototypeRecord = Object.create(null);
  nullPrototypeRecord.model = 'example-model';
  const nullPrototypeMapped = sandbox.mapSettings({
    providerConfig: { providers: { local: nullPrototypeRecord } },
  });
  assert.equal(nullPrototypeMapped.provider_config.providers.local.model, 'example-model');

  const omittedProviders = sandbox.mapSettings({ providerConfig: { sampling_defaults: { temperature: 1 } } });
  assert.equal(Object.hasOwn(omittedProviders.provider_config, 'providers'), false);
  const explicitEmptyProviders = sandbox.mapSettings({ providerConfig: { providers: {} } });
  assert.deepEqual(explicitEmptyProviders.provider_config.providers, {});
});

test('desktop backend read failures are visible and cannot save fallback settings or onboarding defaults', () => {
  assert.match(settingsSource, /loadSettingsState\(\)[\s\S]*?catch\s*\(error\)[\s\S]*?settings\.load\.failed/);
  assert.match(settingsSource, /disabled=\{saving\s*\|\|\s*!state\}/);
  assert.match(appSource, /initializeOnboardingState[\s\S]*?catch\s*\(error\)[\s\S]*?backendError/);
  assert.match(appSource, /if\s*\(onboardingState\.backendError\s*\|\|\s*settingsError\)/);
  assert.match(appSource, /app\.loading\.failed/);
});

test('Electron keeps native directory, picker, login, tray, and title-bar effects allowlisted', () => {
  const settingsPathAllowlist = mainSource.match(/const settingsPathAllowlist = \{([\s\S]*?)\n\};/)?.[1];
  const openPath = mainSource.match(
    /ipcMain\.handle\('platform:open-settings-path',[\s\S]*?\n\}\);\n\nipcMain\.handle\('platform:pick-legacy-root'/,
  )?.[0];
  const picker = mainSource.match(
    /ipcMain\.handle\('platform:pick-legacy-root',[\s\S]*?\n\}\);\n\nipcMain\.handle\('platform:get-system-locale'/,
  )?.[0];
  const titleBarTheme = mainSource.match(
    /ipcMain\.handle\('platform:set-title-bar-theme',[\s\S]*?\n\}\);/,
  )?.[0];

  assert.ok(settingsPathAllowlist);
  for (const directory of ['config', 'history', 'logs', 'plots', 'cache', 'runtime', 'data']) {
    assert.match(settingsPathAllowlist, new RegExp(`${directory}: \\(\\) => runtimePaths\\.`));
  }
  assert.match(openPath, /resolveAllowedSettingsPath\(pathKey\)/);
  assert.match(openPath, /shell\.openPath\(targetPath\)/);
  assert.match(openPath, /if \(!targetPath\)/);
  assert.match(picker, /dialog\.showOpenDialog/);
  assert.match(picker, /properties: \['openDirectory'\]/);
  assert.match(titleBarTheme, /setTitleBarOverlay/);
});

test('Electron main process requests macOS camera access before bundled backend startup', () => {
  assert.ok(mainSource.includes('systemPreferences'));
  assert.ok(mainSource.includes('session.defaultSession.setPermissionRequestHandler'));
  assert.ok(mainSource.includes("permission === 'media'"));
  assert.ok(mainSource.includes("requestedMediaTypes.includes('video')"));
  assert.ok(mainSource.includes('Approved renderer media permission request for camera priming'));
  assert.ok(mainSource.includes("CAMERA_PERMISSION_PRIME_CHANNEL = 'camera:prime-renderer-access'"));
  assert.ok(mainSource.includes("CAMERA_PERMISSION_RESULT_CHANNEL = 'camera:renderer-access-result'"));
  assert.ok(mainSource.includes('requestRendererCameraAccess'));
  assert.ok(mainSource.includes('mainWindow.webContents.send(CAMERA_PERMISSION_PRIME_CHANNEL)'));
  assert.ok(mainSource.includes("systemPreferences.getMediaAccessStatus('camera')"));
  assert.ok(mainSource.includes("systemPreferences.askForMediaAccess('camera')"));
  assert.ok(mainSource.includes('openMacosCameraPrivacySettings'));
  assert.ok(mainSource.includes('Privacy_Camera'));
  assert.ok(mainSource.includes('continuing backend startup'));
  assert.ok(mainSource.includes("CAMERA_FRAME_BRIDGE_START_CHANNEL = 'camera:start-frame-bridge'"));
  assert.ok(mainSource.includes("CAMERA_FRAME_CHANNEL = 'camera:renderer-frame'"));
  assert.ok(mainSource.includes("CAMERA_FRAME_BRIDGE_ERROR_CHANNEL = 'camera:frame-bridge-error'"));
  assert.ok(mainSource.includes("buildConnectionUrl(backendConnection, '/api/v1/camera/frame')"));
  assert.ok(mainSource.includes("'x-vantage-intent': RENDERER_CAMERA_FRAME_INTENT"));
  assert.ok(mainSource.includes('Renderer camera access granted; confirming macOS camera media access'));
  assert.ok(mainSource.includes('Renderer camera frame capture failed'));
  assert.ok(mainSource.includes('startRendererCameraFrameBridge'));
  assert.ok(
    mainSource.indexOf('configureMediaPermissionHandler();')
      < mainSource.indexOf('        createWindow();'),
  );
  assert.ok(
    mainSource.indexOf('        createWindow();')
      < mainSource.indexOf('await requestMacosCameraAccess()'),
  );
  assert.ok(
    mainSource.indexOf('await requestMacosCameraAccess()')
      < mainSource.indexOf('ensureBundledBackendReady({'),
  );
  assert.ok(
    mainSource.indexOf('ensureBundledBackendReady({')
      < mainSource.indexOf('await startRendererCameraFrameBridge()'),
  );
});

test('new platform IPC forwards only canonical configuration operations and independently applies native effects', () => {
  assert.match(mainSource, /ipcMain\.handle\('backend:configuration-request'[\s\S]*?event\.sender !== mainWindow\?\.webContents[\s\S]*?requestBackendJson\(method, apiPath, payload\)/);
  assert.match(mainSource, /ipcMain\.handle\('platform:apply-saved-preferences'/);
  assert.match(mainSource, /mainWindow\.on\('focus',[\s\S]*?applySavedNativePreferences/);
  assert.match(mainSource, /Object\.hasOwn\(settingsPathAllowlist, pathKey\)/);
});

test('production uses a secure same-origin protocol and blocks document escapes', () => {
  assert.match(mainSource, /registerSchemesAsPrivileged/);
  assert.match(mainSource, /installAppProtocol\(\{[\s\S]*?session: session\.defaultSession/);
  assert.match(mainSource, /loadURL\(APP_ENTRY_URL\)/);
  assert.doesNotMatch(mainSource, /loadFile\(/);
  assert.doesNotMatch(mainSource, /webSecurity:\s*false/);
  assert.match(mainSource, /setWindowOpenHandler\(\(\) => \(\{ action: 'deny' \}\)\)/);
  assert.match(mainSource, /'will-navigate', preventUntrustedNavigation/);
  assert.match(mainSource, /'will-redirect', preventUntrustedNavigation/);
});
