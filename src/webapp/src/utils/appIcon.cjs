const path = require('node:path');

function loadAppIcon({ appRoot, nativeImage, platform = process.platform }) {
    const names = platform === 'win32' ? ['icon.ico', 'icon.png'] : ['icon.png'];
    for (const name of names) {
        const iconPath = path.join(appRoot, 'assets', name);
        const image = nativeImage.createFromPath(iconPath);
        if (!image.isEmpty()) return { iconPath, image };
    }
    throw new Error('Vantage application icon is missing or invalid in bundled assets');
}

module.exports = { loadAppIcon };
