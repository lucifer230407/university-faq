// API base: reuse the page's origin when served over http(s) (e.g. the backend
// serves the frontend at "/"), otherwise fall back to the local dev server.
// Override at any time: localStorage.setItem("faq_api_base", "https://...")
const API_BASE =
    localStorage.getItem("faq_api_base") ||
    (location.protocol.startsWith("http")
        ? location.origin
        : "http://localhost:8000");

const chatArea = document.getElementById("chatArea");
const messagesContainer = document.getElementById("messagesContainer");
const welcomeContainer = document.getElementById("welcomeContainer");
const questionInput = document.getElementById("questionInput");
const sendBtn = document.getElementById("sendBtn");
const newChatBtn = document.getElementById("newChatBtn");
const keyBtn = document.getElementById("keyBtn");
const keyModal = document.getElementById("keyModal");
const keyModalTitle = document.getElementById("keyModalTitle");
const keyModalDesc = document.getElementById("keyModalDesc");
const usernameInput = document.getElementById("usernameInput");
const nameInput = document.getElementById("nameInput");
const nameLabel = document.getElementById("nameLabel");
const passwordInput = document.getElementById("passwordInput");
const loginError = document.getElementById("loginError");
const authToggle = document.getElementById("authToggle");
const keyModalSave = document.getElementById("keyModalSave");
const keyModalCancel = document.getElementById("keyModalCancel");
const keyStatusText = document.getElementById("keyStatusText");
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
let _loginResolve = null; // promise resolver used to wait for the login modal
let authEnabled = true;
let loginEnabled = false;
let signupEnabled = false;
let authMode = "login"; // "login" | "signup"

// ---- Session: stable id for this browser, reused across the conversation ----
let sessionId = localStorage.getItem("faq_session_id") || (crypto.randomUUID && crypto.randomUUID()) || Date.now().toString(36);
localStorage.setItem("faq_session_id", sessionId);

// ---- JWT auth (persisted locally) ----
let token = localStorage.getItem("faq_token") || "";
let currentUser = JSON.parse(localStorage.getItem("faq_user") || "null");

function getHeaders() {
    const headers = { "Content-Type": "application/json" };
    if (token) headers["Authorization"] = `Bearer ${token}`;
    return headers;
}

function isAdmin() {
    return !!(currentUser && currentUser.role === "admin");
}

function updateAuthStatus() {
    document.body.classList.toggle("is-admin", isAdmin());
    const locked = document.getElementById("ingestLocked");
    if (locked) locked.classList.toggle("hidden", isAdmin());
    keyStatusText.textContent = currentUser
        ? currentUser.name || currentUser.username
        : !authEnabled
        ? "Auth off"
        : "Sign in";
    keyBtn.classList.toggle("is-set", !!currentUser);
    keyBtn.classList.toggle("is-needed", !currentUser && authEnabled);
    keyBtn.classList.toggle("is-off", !authEnabled);
    keyBtn.title = currentUser
        ? `Signed in as ${currentUser.username}. Click to sign out.`
        : authEnabled
        ? loginEnabled
            ? "Sign in to use the assistant."
            : "No login account configured."
        : "Authentication is disabled on the server.";
}

function storeAuth(user) {
    currentUser = user;
    token = localStorage.getItem("faq_token") || token;
    localStorage.setItem("faq_user", JSON.stringify(user));
    updateAuthStatus();
}

function clearAuth() {
    currentUser = null;
    token = "";
    localStorage.removeItem("faq_token");
    localStorage.removeItem("faq_user");
    updateAuthStatus();
}

function setLoginError(msg) {
    loginError.textContent = msg || "";
}

function openAuthModal(mode) {
    authMode = mode === "signup" && signupEnabled ? "signup" : "login";
    loginError.textContent = "";
    usernameInput.value = "";
    nameInput.value = "";
    passwordInput.value = "";

    const isSignup = authMode === "signup";
    keyModalTitle.textContent = isSignup ? "Create account" : "Sign in";
    keyModalDesc.textContent = isSignup
        ? "Create an account to use the assistant."
        : "Sign in with your account to use the assistant.";
    keyModalSave.textContent = isSignup ? "Sign up" : "Sign in";
    nameInput.hidden = !isSignup;
    nameLabel.hidden = !isSignup;
    passwordInput.autocomplete = isSignup ? "new-password" : "current-password";
    authToggle.textContent = isSignup
        ? "Already have an account? Sign in"
        : "Create account";
    authToggle.hidden = !signupEnabled;

    keyModal.classList.remove("hidden");
    requestAnimationFrame(() => {
        usernameInput.focus();
        usernameInput.select();
    });
}

function openLoginModal() {
    openAuthModal("login");
}

function closeLoginModal() {
    keyModal.classList.add("hidden");
    if (_loginResolve) {
        _loginResolve();
        _loginResolve = null;
    }
}

async function submitAuth() {
    const username = usernameInput.value.trim();
    const password = passwordInput.value;

    if (authMode === "signup") {
        const name = nameInput.value.trim();
        if (!username || !password) {
            setLoginError("Enter a username and password.");
            return;
        }
        if (password.length < 8) {
            setLoginError("Password must be at least 8 characters.");
            return;
        }
        await submitRegister(username, password, name);
    } else {
        if (!username || !password) {
            setLoginError("Enter your username and password.");
            return;
        }
        await submitLogin(username, password);
    }
}

async function submitLogin(username, password) {
    keyModalSave.disabled = true;
    keyModalSave.textContent = "Signing in…";
    setLoginError("");

    try {
        const res = await fetch(`${API_BASE}/api/auth/login`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ username, password }),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
            throw new Error(data.detail || `Sign in failed (${res.status}).`);
        }
        token = data.access_token;
        localStorage.setItem("faq_token", token);
        storeAuth(data.user);
        closeLoginModal();
    } catch (err) {
        setLoginError(err.message);
        console.error("Login error:", err);
    } finally {
        keyModalSave.disabled = false;
        keyModalSave.textContent = "Sign in";
    }
}

async function submitRegister(username, password, name) {
    keyModalSave.disabled = true;
    keyModalSave.textContent = "Signing up…";
    setLoginError("");

    try {
        const res = await fetch(`${API_BASE}/api/auth/register`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ username, password, name }),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
            throw new Error(data.detail || `Sign up failed (${res.status}).`);
        }
        token = data.access_token;
        localStorage.setItem("faq_token", token);
        storeAuth(data.user);
        closeLoginModal();
        appendMessage(
            "bot",
            `Welcome, **${data.user.name || data.user.username}**! Account created — you're all set to ask questions.`
        );
    } catch (err) {
        setLoginError(err.message);
        console.error("Sign-up error:", err);
    } finally {
        keyModalSave.disabled = false;
        keyModalSave.textContent = "Sign up";
    }
}

function logout() {
    if (!currentUser || confirm(`Sign out of ${currentUser.username}?`)) {
        clearAuth();
    }
}

// Wait for the user to finish with the login modal.
function waitForLogin() {
    return new Promise((resolve) => {
        _loginResolve = resolve;
    });
}

keyBtn.addEventListener("click", () => {
    if (currentUser) {
        logout();
    } else if (loginEnabled) {
        openLoginModal();
    }
});
keyModalSave.addEventListener("click", submitAuth);
keyModalCancel.addEventListener("click", closeLoginModal);
authToggle.addEventListener("click", () => {
    openAuthModal(authMode === "signup" ? "login" : "signup");
});
passwordInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
        e.preventDefault();
        submitAuth();
    }
});
usernameInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
        e.preventDefault();
        submitAuth();
    }
});
nameInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
        e.preventDefault();
        submitAuth();
    }
});
// Close when clicking outside the modal panel.
keyModal.addEventListener("click", (e) => {
    if (e.target === keyModal) closeLoginModal();
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
    if (!isAdmin()) {
        appendMessage(
            "bot",
            "Only an administrator can add documents. Student uploads are not used as answers."
        );
        return;
    }
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

// Wait for login to complete before continuing an upload.
async function ensureLoggedIn() {
    if (currentUser || !authEnabled) return true;
    if (loginEnabled) {
        openLoginModal();
        await waitForLogin();
        return !!currentUser;
    }
    return false;
}

uploadSave.addEventListener("click", () => uploadDocument(false));

async function uploadDocument(retried) {
    const file = uploadFile.files[0];
    if (!file || uploadInProgress) return;

    if (!(await ensureLoggedIn())) {
        uploadInProgress = false;
        uploadSave.textContent = "Upload & Store";
        return;
    }

    uploadInProgress = true;
    uploadSave.disabled = true;
    uploadSave.textContent = "Uploading…";
    setIngest("Uploading…", file.name, "35%", "Parsing and embedding the file.");

    const formData = new FormData();
    formData.append("file", file);
    formData.append("agent_ns", uploadNs.value.trim() || "course_handouts");

    const headers = {};
    if (token) headers["Authorization"] = `Bearer ${token}`;

    try {
        const response = await fetch(`${API_BASE}/api/documents`, {
            method: "POST",
            headers,
            body: formData,
        });

        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
            if (response.status === 401 && !retried) {
                clearAuth();
                await ensureLoggedIn();
                uploadInProgress = false;
                uploadSave.textContent = "Upload & Store";
                return uploadDocument(true);
            }
            throw new Error(data.detail || `Upload failed (${response.status})`);
        }

        closeUploadModal();
        setIngest("Stored", file.name, "100%", `${data.chunks} chunk(s) in ${data.agent_ns}. You can ask about this file now.`);
        appendMessage(
            "bot",
            `Stored **${file.name}** as **${data.chunks}** chunk(s) in namespace ` +
            `\`${data.agent_ns}\`. You can now ask questions about it.`
        );
    } catch (err) {
        closeUploadModal();
        setIngest("Failed", file.name, "0%", err.message);
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

// ---- Detect whether the server requires authentication ----
async function checkAuth() {
    try {
        const res = await fetch(`${API_BASE}/api/auth/status`);
        if (!res.ok) return;
        const data = await res.json();
        authEnabled = !!data.auth_enabled;
        loginEnabled = !!data.login_enabled;
        signupEnabled = !!data.signup_enabled;
        // Drop a stored token if the server no longer uses JWT.
        if (!data.methods || !data.methods.jwt) {
            token = "";
            localStorage.removeItem("faq_token");
        }
        updateAuthStatus();
        // If login is required and we have no valid session, ask straight away.
        if (authEnabled && !currentUser && loginEnabled) {
            requestAnimationFrame(() => openLoginModal());
        } else if (currentUser) {
            // Verify the saved token is still valid.
            try {
                const me = await fetch(`${API_BASE}/api/auth/me`, {
                    headers: { Authorization: `Bearer ${token}` },
                });
                if (!me.ok) {
                    clearAuth();
                } else {
                    const meUser = await me.json().catch(() => null);
                    if (meUser && meUser.username) storeAuth(meUser);
                }
            } catch {
                // Network hiccup; leave state alone.
            }
        }
    } catch {
        // Server unreachable; the ask flow will surface the error.
    }
}

updateAuthStatus();
checkAuth();

const chatBox = document.getElementById("chatBox");
const fullscreenBtn = document.getElementById("fullscreenBtn");
const fullscreenIcon = document.getElementById("fullscreenIcon");

function syncFullscreenIcon() {
    const on = document.fullscreenElement === chatBox;
    if (fullscreenIcon) fullscreenIcon.textContent = on ? "fullscreen_exit" : "fullscreen";
    if (fullscreenBtn) fullscreenBtn.title = on ? "Exit full screen" : "Full screen";
}

if (fullscreenBtn && chatBox) {
    fullscreenBtn.addEventListener("click", async () => {
        if (document.fullscreenElement === chatBox) {
            await document.exitFullscreen();
        } else {
            await chatBox.requestFullscreen();
        }
    });
    document.addEventListener("fullscreenchange", syncFullscreenIcon);
}

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
    syncSessionBadge();
    resetInspection();
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

const promptForm = document.getElementById("prompt-form");
if (promptForm) {
    promptForm.addEventListener("submit", (e) => {
        e.preventDefault();
        if (!isLoading && questionInput.value.trim()) sendQuestion();
    });
}

const ingestOpen = document.getElementById("ingestOpen");
if (ingestOpen) ingestOpen.addEventListener("click", openUploadModal);

function syncSessionBadge() {
    const badge = document.getElementById("sessionBadge");
    if (badge) badge.textContent = `session ${sessionId.slice(0, 8)}`;
}
syncSessionBadge();

function setIngest(status, fileName, width, detail) {
    const statusEl = document.getElementById("ingestStatus");
    const nameEl = document.getElementById("ingestFileName");
    const bar = document.getElementById("ingestBar");
    const detailEl = document.getElementById("ingestDetail");
    if (statusEl) statusEl.textContent = status;
    if (nameEl && fileName) nameEl.textContent = fileName;
    if (bar) bar.style.width = width;
    if (detailEl && detail) detailEl.textContent = detail;
}

function updateInspection(sources, elapsedMs) {
    const status = document.getElementById("traceStatus");
    const embed = document.getElementById("embedMeta");
    const gen = document.getElementById("genMeta");
    const count = document.getElementById("matchCount");
    const list = document.getElementById("retrievalMatches");
    const excerpt = document.getElementById("sourceExcerpt");
    const scoreEl = document.getElementById("excerptScore");
    if (status) status.textContent = "Live";
    if (embed) embed.textContent = `${sources.length} hit${sources.length === 1 ? "" : "s"}`;
    if (gen) gen.textContent = elapsedMs != null ? `${elapsedMs}ms` : "gpt";
    if (count) count.textContent = `top ${Math.min(sources.length, 5)}`;
    if (!list) return;
    list.innerHTML = "";
    if (!sources.length) {
        list.innerHTML = `<p class="text-secondary text-body-sm">No local chunks passed the similarity threshold. The answer may use web grounding or say it doesn't know.</p>`;
        if (excerpt) excerpt.textContent = "No excerpt — nothing scored high enough to cite.";
        if (scoreEl) scoreEl.textContent = "—";
        return;
    }
    sources.slice(0, 3).forEach((s, i) => {
        const meta = s.metadata || {};
        const title = meta.title || meta.agent_ns || meta.kind || `Source ${i + 1}`;
        const row = document.createElement("div");
        row.className = "p-2 rounded bg-surface-container-lowest border-l-4 border-primary-container flex items-center justify-between gap-2";
        const left = document.createElement("div");
        left.className = "overflow-hidden";
        const name = document.createElement("div");
        name.className = "font-semibold text-on-surface truncate";
        name.textContent = title;
        const sub = document.createElement("div");
        sub.className = "text-[11px] text-secondary truncate";
        sub.textContent = (s.text || "").replace(/\s+/g, " ").slice(0, 80);
        left.append(name, sub);
        const score = document.createElement("span");
        score.className = "font-mono font-bold text-primary bg-primary-fixed/60 px-2 py-0.5 rounded text-xs shrink-0";
        score.textContent = Number(s.score || 0).toFixed(3);
        row.append(left, score);
        list.appendChild(row);
    });
    const top = sources[0];
    if (excerpt) excerpt.textContent = top.text || "";
    if (scoreEl) scoreEl.textContent = Number(top.score || 0).toFixed(3);
}

function resetInspection() {
    const status = document.getElementById("traceStatus");
    const list = document.getElementById("retrievalMatches");
    const excerpt = document.getElementById("sourceExcerpt");
    const embed = document.getElementById("embedMeta");
    const gen = document.getElementById("genMeta");
    const scoreEl = document.getElementById("excerptScore");
    if (status) status.textContent = "Idle";
    if (embed) embed.textContent = "waiting";
    if (gen) gen.textContent = "gpt · —";
    if (scoreEl) scoreEl.textContent = "—";
    if (excerpt) excerpt.textContent = "The top matching passage will appear here after you ask a question.";
    if (list) list.innerHTML = `<p class="text-secondary text-body-sm">No query yet.</p>`;
}

async function checkHealth() {
    const ribbon = document.getElementById("healthRibbon");
    const pill = document.getElementById("healthPill");
    const latency = document.getElementById("healthLatency");
    const db = document.getElementById("healthDb");
    const dot = document.getElementById("healthDot");
    try {
        const t0 = performance.now();
        const res = await fetch(`${API_BASE}/api/health`);
        const ms = Math.round(performance.now() - t0);
        const data = await res.json().catch(() => ({}));
        const ok = res.ok && data.status === "healthy";
        if (ribbon) {
            ribbon.textContent = ok
                ? "Chitkara AI live · Cosmos DB vector search · Azure OpenAI"
                : "Chitkara AI · API unreachable or database down";
        }
        if (pill) pill.textContent = `GET /api/health: ${res.status}${data.status ? " " + data.status : ""}`;
        if (latency) latency.textContent = `${ms}ms`;
        if (db) db.textContent = data.database === "connected" ? "Database connected" : "Database down";
        if (dot) dot.classList.toggle("opacity-40", !ok);
    } catch {
        if (ribbon) ribbon.textContent = "Chitkara AI · API not reachable";
        if (pill) pill.textContent = "GET /api/health: offline";
        if (db) db.textContent = "Database unknown";
    }
}
checkHealth();

const SNIPPETS = {
    ask: `curl -X POST $API/api/ask \\
  -H "Authorization: Bearer $TOKEN" \\
  -H "Content-Type: application/json" \\
  -d '{"question":"How do I get an exam paper re-evaluated?","session_id":"demo"}'`,
    docs: `curl -X POST $API/api/documents \\
  -H "Authorization: Bearer $TOKEN" \\
  -F "file=@handout.pdf" \\
  -F "agent_ns=course_handouts"`,
    health: `curl $API/api/health`,
};

function switchTab(type) {
    const box = document.getElementById("code-content");
    if (!box) return;
    ["ask", "docs", "health"].forEach((name) => {
        const btn = document.getElementById(`tab-${name}`);
        if (!btn) return;
        btn.className = name === type
            ? "px-2.5 py-1 rounded font-mono text-xs bg-primary-container text-white"
            : "px-2.5 py-1 rounded font-mono text-xs text-secondary-fixed-dim";
    });
    const pre = document.createElement("pre");
    pre.className = "text-white whitespace-pre-wrap";
    pre.textContent = (SNIPPETS[type] || "").replaceAll("$API", API_BASE);
    box.replaceChildren(pre);
}

document.getElementById("tab-ask")?.addEventListener("click", () => switchTab("ask"));
document.getElementById("tab-docs")?.addEventListener("click", () => switchTab("docs"));
document.getElementById("tab-health")?.addEventListener("click", () => switchTab("health"));
switchTab("ask");

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

    // Server requires auth and we got rejected: prompt for sign-in once.
    if (response.status === 401 && !retried) {
        await ensureLoggedIn();
        if (!currentUser) return response;
        return postAsk(question, true);
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

    const started = performance.now();
    try {
        const response = await postAsk(question);

        if (response.status === 401) {
            throw new Error(
                currentUser
                    ? "Your session expired. Click the user icon to sign in again."
                    : authEnabled
                    ? loginEnabled
                        ? "Please sign in to use the assistant."
                        : "No login account is configured on the server."
                    : "Authentication is disabled on the server."
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

        appendMessage("bot", data.answer, data.sources);
        updateInspection(data.sources || [], Math.round(performance.now() - started));
    } catch (err) {
        typingEl.remove();
        appendMessage(
            "bot",
            err.message && err.message.includes("sign")
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

            // Web sources get clickable links to the fetched pages.
            const webSources = sources.filter(
                (s) => s.metadata?.kind === "web" && s.metadata?.source_url
            );
            const seenUrls = new Set();
            webSources.forEach((s) => {
                const href = s.metadata.source_url;
                if (seenUrls.has(href)) return;
                seenUrls.add(href);
                const link = document.createElement("a");
                link.className = "source-link";
                link.href = href;
                link.target = "_blank";
                link.rel = "noopener noreferrer";
                link.title = s.metadata.title || href;
                link.textContent = s.metadata.title || new URL(href).hostname;
                sourcesEl.appendChild(link);
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

// ---- Markdown Rendering (marked + DOMPurify) ----
function formatMarkdown(text) {
    // Sanitize first, then render. Bot output is treated as untrusted.
    const raw = (window.marked && window.marked.parse) ? window.marked.parse(text) : text;
    return window.DOMPurify
        ? DOMPurify.sanitize(raw)
        : text.replace(/[<>&]/g, (c) => ({ "<": "&lt;", ">": "&gt;", "&": "&amp;" }[c]));
}

// ---- Scroll to bottom ----
function scrollToBottom() {
    requestAnimationFrame(() => {
        chatArea.scrollTop = chatArea.scrollHeight;
    });
}