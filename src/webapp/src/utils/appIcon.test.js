import test from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { createRequire } from 'node:module';
import { readFileSync } from 'node:fs';
const require = createRequire(import.meta.url);
const { loadAppIcon } = require('./appIcon.cjs');

test('Windows loads the bundled multi-resolution ICO from inside app.asar', () => {
    const appRoot = path.resolve('resources', 'app.asar');
    const seen = [];
    const image = { isEmpty: () => false };
    const result = loadAppIcon({ appRoot, platform: 'win32', nativeImage: {
        createFromPath(file) { seen.push(file); return image; },
    } });
    assert.deepEqual(seen, [path.join(appRoot, 'assets', 'icon.ico')]);
    assert.equal(result.image, image);
});

test('an invalid ICO falls back to PNG and never returns an empty tray image', () => {
    const nativeImage = { createFromPath: file => ({ isEmpty: () => file.endsWith('.ico') }) };
    assert.match(loadAppIcon({ appRoot: '.', platform: 'win32', nativeImage }).iconPath, /icon\.png$/);
    assert.throws(() => loadAppIcon({ appRoot: '.', nativeImage: {
        createFromPath: () => ({ isEmpty: () => true }),
    } }), /missing or invalid/);
});

test('packaging includes real PNG and ICO assets at the runtime path', () => {
    const pkg = JSON.parse(readFileSync(new URL('../../package.json', import.meta.url)));
    assert.ok(pkg.build.files.includes('assets/**/*'));
    assert.equal(pkg.build.win.icon, 'assets/icon.ico');
    const png = readFileSync(new URL('../../assets/icon.png', import.meta.url));
    assert.equal(png.subarray(1, 4).toString(), 'PNG');
    const ico = readFileSync(new URL('../../assets/icon.ico', import.meta.url));
    assert.equal(ico.readUInt16LE(2), 1);
    const count = ico.readUInt16LE(4);
    const sizes = Array.from({ length: count }, (_, i) => ico[6 + i * 16] || 256);
    for (const size of [16, 20, 24, 32, 40, 48, 64, 256]) assert.ok(sizes.includes(size));
});
