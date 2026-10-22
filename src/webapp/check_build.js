import path from 'node:path';
import { fileURLToPath } from 'node:url';
import buildCache from './src/utils/frontendBuildCache.cjs';

const webappRoot = path.dirname(fileURLToPath(import.meta.url));
globalThis.process.exit(buildCache.isBuildCurrent(webappRoot) ? 0 : 1);
