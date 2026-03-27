import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

function getLatestMtime(dirPath) {
    let latest = 0;
    if (!fs.existsSync(dirPath)) return 0;

    const stat = fs.statSync(dirPath);
    if (!stat.isDirectory()) {
        return stat.mtimeMs;
    }

    const files = fs.readdirSync(dirPath);
    for (const file of files) {
        if (file === 'node_modules' || file === 'dist' || file.startsWith('.')) continue;
        const fullPath = path.join(dirPath, file);
        const fileStat = fs.statSync(fullPath);
        if (fileStat.isDirectory()) {
            latest = Math.max(latest, getLatestMtime(fullPath));
        } else {
            latest = Math.max(latest, fileStat.mtimeMs);
        }
    }
    return latest;
}

try {
    const srcTime = Math.max(
        getLatestMtime(path.join(__dirname, 'src')),
        getLatestMtime(path.join(__dirname, 'public')),
        getLatestMtime(path.join(__dirname, 'index.html')),
        getLatestMtime(path.join(__dirname, 'package.json')),
        getLatestMtime(path.join(__dirname, 'vite.config.js'))
    );

    const distPath = path.join(__dirname, 'dist', 'index.html');
    const distTime = fs.existsSync(distPath) ? fs.statSync(distPath).mtimeMs : 0;

    if (srcTime > distTime) {
        globalThis.process.exit(1); // Needs rebuild
    } else {
        globalThis.process.exit(0); // Up to date
    }
} catch (error) {
    console.error("Error checking build status:", error);
    globalThis.process.exit(1); // Safe fallback: rebuild
}
