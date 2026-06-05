const { contextBridge, ipcRenderer } = require('electron');

const CAMERA_FRAME_BRIDGE_START_CHANNEL = 'camera:start-frame-bridge';
const CAMERA_FRAME_BRIDGE_RESULT_CHANNEL = 'camera:frame-bridge-result';
const CAMERA_FRAME_BRIDGE_ERROR_CHANNEL = 'camera:frame-bridge-error';
const CAMERA_FRAME_CHANNEL = 'camera:renderer-frame';
let rendererCameraBridge = null;
let rendererCameraPrimeStream = null;
let rendererCameraBridgeLastErrorSentAt = 0;

function stopRendererCameraStream(stream) {
    if (!stream) {
        return;
    }
    for (const track of stream.getTracks()) {
        track.stop();
    }
}

function hasLiveVideoTrack(stream) {
    return Boolean(stream?.getVideoTracks?.().some((track) => track.readyState === 'live'));
}

function consumeRendererCameraPrimeStream() {
    if (!hasLiveVideoTrack(rendererCameraPrimeStream)) {
        stopRendererCameraStream(rendererCameraPrimeStream);
        rendererCameraPrimeStream = null;
        return null;
    }

    const stream = rendererCameraPrimeStream;
    rendererCameraPrimeStream = null;
    return stream;
}

async function primeRendererCameraAccess() {
    if (!navigator.mediaDevices?.getUserMedia) {
        return {
            granted: false,
            error: 'renderer mediaDevices.getUserMedia is unavailable',
        };
    }

    if (rendererCameraBridge?.started || hasLiveVideoTrack(rendererCameraPrimeStream)) {
        return { granted: true, reused: true };
    }

    try {
        rendererCameraPrimeStream = await navigator.mediaDevices.getUserMedia({ video: true, audio: false });
        return { granted: true };
    } catch (error) {
        return {
            granted: false,
            error: error?.message || String(error),
        };
    }
}

function blobToBuffer(blob) {
    return blob.arrayBuffer().then((arrayBuffer) => Buffer.from(arrayBuffer));
}

function withTimeout(promise, timeoutMs, message) {
    return Promise.race([
        promise,
        new Promise((resolve, reject) => {
            setTimeout(() => reject(new Error(message)), timeoutMs);
        }),
    ]);
}

function describeRendererCameraError(error) {
    if (error?.message) {
        return error.message;
    }
    const text = String(error);
    return text && text !== 'undefined' ? text : 'unknown renderer camera capture error';
}

function reportRendererCameraBridgeError(error) {
    const now = Date.now();
    if (now - rendererCameraBridgeLastErrorSentAt < 5000) {
        return;
    }
    rendererCameraBridgeLastErrorSentAt = now;
    ipcRenderer.send(CAMERA_FRAME_BRIDGE_ERROR_CHANNEL, {
        error: describeRendererCameraError(error),
    });
}

async function waitForVideoMetadata(video) {
    if (video.videoWidth && video.videoHeight) {
        return;
    }

    await new Promise((resolve, reject) => {
        const timeout = setTimeout(() => {
            cleanup();
            reject(new Error('renderer camera metadata timed out'));
        }, 5000);
        const cleanup = () => {
            clearTimeout(timeout);
            video.removeEventListener('loadedmetadata', onLoadedMetadata);
            video.removeEventListener('error', onError);
        };
        const onLoadedMetadata = () => {
            cleanup();
            resolve();
        };
        const onError = () => {
            cleanup();
            reject(new Error('renderer camera video element failed'));
        };

        video.addEventListener('loadedmetadata', onLoadedMetadata, { once: true });
        video.addEventListener('error', onError, { once: true });
    });
}

async function playVideoWithTimeout(video) {
    await withTimeout(video.play(), 5000, 'renderer camera video play timed out');
}

async function createRendererCameraVideo(stream) {
    const video = document.createElement('video');
    video.muted = true;
    video.autoplay = true;
    video.playsInline = true;
    video.style.display = 'none';
    video.setAttribute('muted', '');
    video.setAttribute('playsinline', '');
    video.srcObject = stream;
    (document.body || document.documentElement)?.appendChild(video);
    try {
        await waitForVideoMetadata(video);
        await playVideoWithTimeout(video);
        return video;
    } catch (error) {
        video.remove();
        throw error;
    }
}

async function startRendererCameraFrameBridge({
    intervalMs = 500,
    width = 1280,
    height = 720,
    quality = 0.82,
} = {}) {
    if (!navigator.mediaDevices?.getUserMedia) {
        return {
            started: false,
            error: 'renderer mediaDevices.getUserMedia is unavailable',
        };
    }

    if (rendererCameraBridge?.started) {
        return { started: true, reused: true };
    }

    let stream = null;
    let video = null;
    try {
        stream = consumeRendererCameraPrimeStream();
        if (!stream) {
            stream = await navigator.mediaDevices.getUserMedia({
                video: {
                    width: { ideal: width },
                    height: { ideal: height },
                },
                audio: false,
            });
        }

        const [videoTrack] = stream.getVideoTracks();
        let imageCapture = typeof ImageCapture === 'function' && videoTrack
            ? new ImageCapture(videoTrack)
            : null;
        let mode = imageCapture ? 'imageCapture' : 'video';

        if (!imageCapture) {
            video = await createRendererCameraVideo(stream);
        }

        const canvas = document.createElement('canvas');
        const context = canvas.getContext('2d', { alpha: false });
        if (!context) {
            throw new Error('renderer camera canvas context is unavailable');
        }
        const captureFrame = async () => {
            if (!rendererCameraBridge?.started) {
                return;
            }

            let source = video;
            let shouldCloseSource = false;
            if (imageCapture) {
                try {
                    source = await withTimeout(
                        imageCapture.grabFrame(),
                        5000,
                        'renderer camera grabFrame timed out',
                    );
                    shouldCloseSource = true;
                } catch (error) {
                    reportRendererCameraBridgeError(error);
                    const fallbackVideo = await createRendererCameraVideo(stream);
                    imageCapture = null;
                    mode = 'video';
                    video = fallbackVideo;
                    rendererCameraBridge.video = video;
                    rendererCameraBridge.mode = mode;
                    source = video;
                }
            }

            if (!imageCapture && (!video || video.readyState < HTMLMediaElement.HAVE_CURRENT_DATA)) {
                return;
            }

            const frameWidth = source.width || source.videoWidth || width;
            const frameHeight = source.height || source.videoHeight || height;
            if (!frameWidth || !frameHeight) {
                if (shouldCloseSource) {
                    source.close?.();
                }
                return;
            }

            if (canvas.width !== frameWidth) {
                canvas.width = frameWidth;
            }
            if (canvas.height !== frameHeight) {
                canvas.height = frameHeight;
            }

            context.drawImage(source, 0, 0, frameWidth, frameHeight);
            if (shouldCloseSource) {
                source.close?.();
            }
            const blob = await new Promise((resolve) => canvas.toBlob(resolve, 'image/jpeg', quality));
            if (!blob) {
                return;
            }

            const buffer = await blobToBuffer(blob);
            ipcRenderer.send(CAMERA_FRAME_CHANNEL, buffer);
        };

        rendererCameraBridge = {
            started: true,
            stream,
            video,
            mode,
            timer: null,
        };
        const runCaptureFrame = () => {
            void captureFrame().catch(reportRendererCameraBridgeError);
        };
        rendererCameraBridge.timer = setInterval(runCaptureFrame, Math.max(250, intervalMs));
        runCaptureFrame();
        return { started: true, mode };
    } catch (error) {
        stopRendererCameraStream(stream);
        video?.remove();
        rendererCameraBridge = null;
        return {
            started: false,
            error: error?.message || String(error),
        };
    }
}

ipcRenderer.on('camera:prime-renderer-access', async () => {
    const result = await primeRendererCameraAccess();
    ipcRenderer.send('camera:renderer-access-result', result);
});

ipcRenderer.on(CAMERA_FRAME_BRIDGE_START_CHANNEL, async (event, options = {}) => {
    const result = await startRendererCameraFrameBridge(options);
    ipcRenderer.send(CAMERA_FRAME_BRIDGE_RESULT_CHANNEL, result);
});

contextBridge.exposeInMainWorld('electronAPI', {
    platform: process.platform,
    showNotification: (title, body) => {
        ipcRenderer.send('show-notification', { title, body });
    },
    minimizeToTray: () => {
        ipcRenderer.send('minimize-to-tray');
    },
    getOnboardingState: () => ipcRenderer.invoke('onboarding:get-state'),
    completeOnboarding: (payload) => ipcRenderer.invoke('onboarding:complete', payload),
    pickLegacyRoot: () => ipcRenderer.invoke('onboarding:pick-legacy-root'),
    getSettingsState: () => ipcRenderer.invoke('settings:get-state'),
    saveSettings: (payload) => ipcRenderer.invoke('settings:save', payload),
    openSettingsPath: (pathKey) => ipcRenderer.invoke('settings:open-path', pathKey),
    getDisplayLanguageState: () => ipcRenderer.invoke('settings:get-display-language-state'),
    setDisplayLanguage: (displayLanguage) => ipcRenderer.invoke('settings:set-display-language', displayLanguage),
    getSystemLocale: () => ipcRenderer.invoke('settings:get-system-locale'),
    setTitleBarTheme: (theme) => ipcRenderer.invoke('window:set-title-bar-theme', theme),
    onMessage: (channel, callback) => {
        const validChannels = ['update-available', 'backend-status'];
        if (validChannels.includes(channel)) {
            ipcRenderer.on(channel, (event, ...args) => callback(...args));
        }
    },
});
