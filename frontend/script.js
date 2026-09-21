const API_BASE = "http://localhost:8000";

const chatArea = document.getElementById("chatArea");
const messagesContainer = document.getElementById("messagesContainer");
const welcomeContainer = document.getElementById("welcomeContainer");
const questionInput = document.getElementById("questionInput");
const sendBtn = document.getElementById("sendBtn");
const newChatBtn = document.getElementById("newChatBtn");
const keyBtn = document.getElementById("keyBtn");
const keyModal = document.getElementById("keyModal");
const keyInput = document.getElementById("keyInput");
const keyModalSave = document.getElementById("keyModalSave");
const keyModalCancel = document.getElementById("keyModalCancel");
const uploadBtn = document.getElementById("uploadBtn");
const uploadModal = document.getElementById("uploadModal");
const uploadDrop = document.getElementById("uploadDrop");
const uploadDropText = document.getElementById("uploadDropText");
const uploadFile = document.getElementById("uploadFile");
const uploadNs = document.getElementById("uploadNs");
const uploadSave = document.getElementById("uploadSave");
const uploadCancel = document.getElementById("uploadCancel");

// ---- State ----
let isLoading = false;
let _keyResolve = null; // promise resolver used to wait for the key modal

// ---- Session: stable id for this browser, reused across the conversation ----
let sessionId = localStorage.getItem("faq_session_id") || (crypto.randomUUID && crypto.randomUUID()) || Date.now().toString(36);
localStorage.setItem("faq_session_id", sessionId);

// ---- API key (persisted locally; optional if the backend disables auth) ----
let apiKey = localStorage.getItem("faq_api_key") || "";
let authEnabled = true;

function getHeaders() {
    const headers = { "Content-Type": "application/json" };
    if (apiKey) headers["X-API-Key"] = apiKey;
    return headers;
}

function updateKeyStatus() {
    const has = !!apiKey;
    keyStatusText.textContent = !authEnabled ? "Auth off" : has ? "Key set" : "Key needed";
    keyBtn.classList.toggle("is-set", has);
    keyBtn.classList.toggle("is-needed", !has && authEnabled);
    keyBtn.classList.toggle("is-off", !authEnabled);
    keyBtn.title = !authEnabled
        ? "API key authentication is disabled on the server."
        : has
        ? `API key set (…${apiKey.slice(-4)}). Click to change it.`
        : "No API key set. Click to enter the API key.";
}

function openKeyModal(prefill) {
    keyInput.value = prefill !== undefined ? prefill : apiKey;
    keyModal.classList.remove("hidden");
    // Focus after the overlay is visible so the field is ready to type into.
    requestAnimationFrame(() => {
        keyInput.focus();
        keyInput.select();
    });
}

function closeKeyModal(result) {
    keyModal.classList.add("hidden");
    if (_keyResolve) {
        _keyResolve(result);
        _keyResolve = null;
    }
}

function saveKey() {
    const value = keyInput.value.trim();
    apiKey = value;
    localStorage.setItem("faq_api_key", apiKey);
    updateKeyStatus();
    closeKeyModal(apiKey);
}

// Wait for the user to finish with the key modal; resolves with the new key
// (or ""/null if the modal was dismissed without saving).
function waitForKeyEntry() {
    return new Promise((resolve) => {
        _keyResolve = resolve;
    });
}

keyBtn.addEventListener("click", () => openKeyModal(apiKey));
keyModalSave.addEventListener("click", saveKey);
keyModalCancel.addEventListener("click", () => closeKeyModal(null));
keyInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
        e.preventDefault();
        saveKey();
    }
});
// Close when clicking outside the modal panel.
keyModal.addEventListener("click", (e) => {
    if (e.target === keyModal) closeKeyModal(null);
});

// ---- Document Upload ----
let uploadInProgress = false;

function resetUploadModal() {
    uploadFile.value = "";
    uploadNs.value = "";
    uploadDrop.classList.remove("has-file");
    uploadDropText.textContent = "Click to choose a file";
    uploadSave.disabled = true;
}

function openUploadModal() {
    resetUploadModal();
    uploadModal.classList.remove("hidden");
}

function closeUploadModal() {
    uploadModal.classList.add("hidden");
}

uploadBtn.addEventListener("click", openUploadModal);
uploadCancel.addEventListener("click", closeUploadModal);
uploadModal.addEventListener("click", (e) => {
    if (e.target === uploadModal) closeUploadModal();
});

uploadDrop.addEventListener("click", () => uploadFile.click());
uploadFile.addEventListener("change", () => {
    const file = uploadFile.files[0];
    if (!file) return;
    uploadDrop.classList.add("has-file");
    uploadDropText.textContent = `Selected: ${file.name}`;
    uploadSave.disabled = uploadInProgress;
});

uploadSave.addEventListener("click", () => uploadDocument(false));

async function uploadDocument(retried) {
    const file = uploadFile.files[0];
    if (!file || uploadInProgress) return;

    uploadInProgress = true;
    uploadSave.disabled = true;
    uploadSave.textContent = "Uploading…";

    const formData = new FormData();
    formData.append("file", file);
    formData.append("agent_ns", uploadNs.value.trim() || "course_handouts");

    const headers = {};
    if (apiKey) headers["X-API-Key"] = apiKey;

    try {
        const response = await fetch(`${API_BASE}/api/documents`, {
            method: "POST",
            headers,
            body: formData,
        });

        if (response.status === 401 && !retried) {
            // Ask for a key, then retry the upload once.
            const before = apiKey;
            openKeyModal(apiKey);
            const entered = await waitForKeyEntry();
            if (entered && entered !== before) {
                uploadInProgress = false;
                uploadSave.textContent = "Upload & Store";
                return uploadDocument(true);
            }
            throw new Error("API key required to upload documents.");
        }

        const data = await response.json();
        if (!response.ok) {
            throw new Error(data.detail || `Upload failed (${response.status})`);
        }

        closeUploadModal();
        appendMessage(
            "bot",
            `Stored **${file.name}** as **${data.chunks}** chunk(s) in namespace ` +
            `\`${data.agent_ns}\`. You can now ask questions about it.`
        );
    } catch (err) {
        closeUploadModal();
        appendMessage(
            "bot",
            `Upload failed: ${err.message}. Check the file type and try again.`
        );
        console.error("Upload error:", err);
    } finally {
        uploadInProgress = false;
        uploadSave.textContent = "Upload & Store";
    }
}

// ---- Detect whether the server requires an API key ----
async function checkAuth() {
    try {
        const res = await fetch(`${API_BASE}/api/auth/status`);
        if (!res.ok) return;
        const data = await res.json();
        authEnabled = !!data.auth_enabled;
        updateKeyStatus();
        // If a key is required and we don't have one, ask straight away.
        if (authEnabled && !apiKey) {
            requestAnimationFrame(() => openKeyModal(apiKey));
        }
    } catch {
        // Server unreachable; the ask flow will surface the error.
    }
}

updateKeyStatus();
checkAuth();

newChatBtn.addEventListener("click", async () => {
    // Clear backend memory for this session, then reset the UI.
    try {
        await fetch(`${API_BASE}/api/clear`, {
            method: "POST",
            headers: getHeaders(),
            body: JSON.stringify({ question: "", session_id: sessionId }),
        });
    } catch (err) {
        // Non-fatal: the new local session still isolates the conversation.
        console.warn("Could not clear server session:", err);
    }
    sessionId = (crypto.randomUUID && crypto.randomUUID()) || Date.now().toString(36);
    localStorage.setItem("faq_session_id", sessionId);
    messagesContainer.innerHTML = "";
    welcomeContainer.classList.remove("hidden");
    questionInput.focus();
});

// ---- Auto-resize textarea ----
questionInput.addEventListener("input", () => {
    questionInput.style.height = "auto";
    questionInput.style.height = Math.min(questionInput.scrollHeight, 120) + "px";
    sendBtn.disabled = !questionInput.value.trim();
});

// ---- Send on Enter (Shift+Enter for newline) ----
questionInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        if (!isLoading && questionInput.value.trim()) {
            sendQuestion();
        }
    }
});

sendBtn.addEventListener("click", () => {
    if (!isLoading && questionInput.value.trim()) {
        sendQuestion();
    }
});

// ---- Suggestion Chips ----
document.querySelectorAll(".chip").forEach((chip) => {
    chip.addEventListener("click", () => {
        const question = chip.dataset.question;
        questionInput.value = question;
        sendBtn.disabled = false;
        sendQuestion();
    });
});

// ---- Send Question ----
async function postAsk(question, retried = false) {
    const response = await fetch(`${API_BASE}/api/ask`, {
        method: "POST",
        headers: getHeaders(),
        body: JSON.stringify({ question, session_id: sessionId }),
    });

    // Server requires a key. Show the modal, wait for input, then retry.
    if (response.status === 401 && !retried) {
        const before = apiKey;
        openKeyModal(apiKey);
        const entered = await waitForKeyEntry();
        if (entered && entered !== before) {
            return postAsk(question, true);
        }
    }

    return response;
}

async function sendQuestion() {
    const question = questionInput.value.trim();
    if (!question || isLoading) return;

    isLoading = true;
    sendBtn.disabled = true;

    // Hide welcome screen
    welcomeContainer.classList.add("hidden");

    // Add user message
    appendMessage("user", question);

    // Clear input
    questionInput.value = "";
    questionInput.style.height = "auto";

    // Show typing indicator
    const typingEl = appendTypingIndicator();

    try {
        const response = await postAsk(question);

        if (response.status === 401) {
            throw new Error(
                apiKey
                    ? "The API key was rejected. Click the key button to update it."
                    : "An API key is required to use this chat. Click the key button to add one."
            );
        }
        if (response.status === 429) {
            throw new Error("Rate limit reached. Please wait a minute and try again.");
        }
        if (!response.ok) {
            throw new Error(`Server error: ${response.status}`);
        }

        const data = await response.json();

        // Remove typing indicator
        typingEl.remove();

        // Add bot response
        appendMessage("bot", data.answer, data.sources);
    } catch (err) {
        typingEl.remove();
        appendMessage(
            "bot",
            err.message && err.message.includes("key")
                ? err.message
                : "Sorry, I couldn't process your question right now. Please try again later."
        );
        console.error("Error:", err);
    } finally {
        isLoading = false;
        sendBtn.disabled = !questionInput.value.trim();
    }
}

// ---- Append Message ----
function appendMessage(role, text, sources = []) {
    const messageEl = document.createElement("div");
    messageEl.className = `message message-${role}`;

    const avatarEl = document.createElement("div");
    avatarEl.className = "message-avatar";

    if (role === "user") {
        avatarEl.innerHTML = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>`;
    } else {
        avatarEl.innerHTML = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 10v6M2 10l10-5 10 5-10 5z"/><path d="M6 12v5c3 3 9 3 12 0v-5"/></svg>`;
    }

    const contentEl = document.createElement("div");
    contentEl.className = "message-content";

    if (role === "bot") {
        contentEl.innerHTML = formatMarkdown(text);

        // Add sources if available
        if (sources && sources.length > 0) {
            const sourcesEl = document.createElement("div");
            sourcesEl.className = "sources-section";

            const labelEl = document.createElement("div");
            labelEl.className = "sources-label";
            labelEl.textContent = "Sources";
            sourcesEl.appendChild(labelEl);

            const uniqueNs = [
                ...new Set(
                    sources.map((s) => s.metadata?.agent_ns).filter(Boolean)
                ),
            ];
            uniqueNs.forEach((ns) => {
                const tag = document.createElement("span");
                tag.className = "source-tag";
                tag.textContent = ns;
                sourcesEl.appendChild(tag);
            });

            contentEl.appendChild(sourcesEl);
        }
    } else {
        contentEl.textContent = text;
    }

    messageEl.appendChild(avatarEl);
    messageEl.appendChild(contentEl);
    messagesContainer.appendChild(messageEl);

    scrollToBottom();
}

// ---- Typing Indicator ----
function appendTypingIndicator() {
    const messageEl = document.createElement("div");
    messageEl.className = "message message-bot";

    const avatarEl = document.createElement("div");
    avatarEl.className = "message-avatar";
    avatarEl.innerHTML = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 10v6M2 10l10-5 10 5-10 5z"/><path d="M6 12v5c3 3 9 3 12 0v-5"/></svg>`;

    const contentEl = document.createElement("div");
    contentEl.className = "message-content";

    const typingEl = document.createElement("div");
    typingEl.className = "typing-indicator";
    typingEl.innerHTML = `
        <div class="typing-dot"></div>
        <div class="typing-dot"></div>
        <div class="typing-dot"></div>
    `;

    contentEl.appendChild(typingEl);
    messageEl.appendChild(avatarEl);
    messageEl.appendChild(contentEl);
    messagesContainer.appendChild(messageEl);

    scrollToBottom();
    return messageEl;
}

// ---- Simple Markdown Formatter ----
function formatMarkdown(text) {
    // Escape HTML
    let html = text
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;");

    // Bold
    html = html.replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>");

    // Bullet lists
    html = html.replace(/^[-•]\s+(.+)$/gm, "<li>$1</li>");
    html = html.replace(/((?:<li>.*<\/li>\n?)+)/g, "<ul>$1</ul>");

    // Numbered lists
    html = html.replace(/^\d+\.\s+(.+)$/gm, "<li>$1</li>");

    // Paragraphs
    html = html
        .split(/\n\n+/)
        .map((block) => {
            block = block.trim();
            if (!block) return "";
            if (
                block.startsWith("<ul>") ||
                block.startsWith("<ol>") ||
                block.startsWith("<li>")
            )
                return block;
            return `<p>${block.replace(/\n/g, "<br>")}</p>`;
        })
        .join("");

    return html;
}

// ---- Scroll to bottom ----
function scrollToBottom() {
    requestAnimationFrame(() => {
        chatArea.scrollTop = chatArea.scrollHeight;
    });
}
