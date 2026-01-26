
// Globals
let bridge = null;

// Initialize QWebChannel
document.addEventListener("DOMContentLoaded", () => {

    // Function to initialize Bridge
    const initBridge = () => {
        if (typeof qt !== "undefined" && typeof qt.webChannelTransport !== "undefined") {
            new QWebChannel(qt.webChannelTransport, function (channel) {
                bridge = channel.objects.chatBridge;
                console.log("Bridge connected!");
            });
        } else {
            console.log("Waiting for qt.webChannelTransport...");
            setTimeout(initBridge, 100);
        }
    }

    // Start trying to connect
    initBridge();

    // Auto-resize textarea
    const textarea = document.getElementById('chat-input');
    textarea.addEventListener('input', function () {
        this.style.height = 'auto';
        this.style.height = (this.scrollHeight) + 'px';
        if (this.value === '') {
            this.style.height = 'auto';
        }
    });

    // Handle Enter to send
    textarea.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
        // Ctrl+Enter also accepted (standard)
        if (e.key === 'Enter' && e.ctrlKey) {
            e.preventDefault();
            sendMessage();
        }
    });

    document.getElementById('send-btn').addEventListener('click', sendMessage);
});

// Markdown Renderer (Wrapper around marked)
function renderMarkdown(text) {
    if (typeof marked !== 'undefined') {
        try {
            return marked.parse(text);
        } catch (e) {
            console.error("Marked parse error", e);
            return text;
        }
    }
    // Fallback: Simple replacements
    return text.replace(/\n/g, '<br>')
        .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
}

// Add Message to Chat
function addMessage(role, text) {
    const history = document.getElementById('chat-history');

    const bubble = document.createElement('div');
    bubble.className = `message ${role}`;

    // Render Markdown
    bubble.innerHTML = renderMarkdown(text);

    history.appendChild(bubble);

    // Scroll to bottom
    setTimeout(() => {
        history.scrollTop = history.scrollHeight;
    }, 50);
}

// Send Message
function sendMessage() {
    const textarea = document.getElementById('chat-input');
    let text = textarea.value.trim();

    if (text && bridge) {
        // Append Timestamp
        const now = new Date();
        const timeStr = now.getFullYear() + '-' +
            String(now.getMonth() + 1).padStart(2, '0') + '-' +
            String(now.getDate()).padStart(2, '0') + ' ' +
            String(now.getHours()).padStart(2, '0') + ':' +
            String(now.getMinutes()).padStart(2, '0') + ':' +
            String(now.getSeconds()).padStart(2, '0');

        const textWithTime = text + `\n\n*(发送时间: ${timeStr})*`;

        // Show user message immediately
        addMessage('user', textWithTime);

        textarea.value = '';
        textarea.style.height = 'auto'; // Reset height

        bridge.sendMessageToPython(textWithTime);
    }
}

// Stream logic
let currentStreamBubble = null;

// Start a new AI response stream
function startStreamResponse() {
    const history = document.getElementById('chat-history');

    currentStreamBubble = document.createElement('div');
    currentStreamBubble.className = 'message assistant';
    currentStreamBubble.innerHTML = '<strong>Assistant:</strong><br><span class="thinking">Thinking...</span>';

    history.appendChild(currentStreamBubble);

    setTimeout(() => {
        history.scrollTop = history.scrollHeight;
    }, 50);
}

// Update the current AI stream
function updateStreamResponse(text) {
    if (!currentStreamBubble) {
        startStreamResponse();
    }
    // Render Markdown on the fly
    // Note: Rendering full markdown on every chunk might be heavy for very long texts, 
    // but ensures format correctness (e.g. closing tags).
    // For better performance, we could append raw text and only markdown finalize, 
    // but "Cherry Studio" feel needs live markdown.
    currentStreamBubble.innerHTML = '<strong>Assistant:</strong><br>' + renderMarkdown(text);

    const history = document.getElementById('chat-history');
    if (history.scrollHeight - history.scrollTop < 600) { // Only auto-scroll if near bottom
        history.scrollTop = history.scrollHeight;
    }
}

// Finalize stream
function endStreamResponse() {
    currentStreamBubble = null;
}

// Theme Switching
function setTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme);
}
