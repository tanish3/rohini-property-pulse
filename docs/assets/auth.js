// Rohini Property Pulse — login gate (client-side)
// Uses Web Crypto SHA-256 to compare credentials against a stored hash.
// The plaintext password is never stored in source.
//
// SECURITY NOTE:
// Client-side auth on a static site is "defense in depth", not real auth.
// The repo is private so the hash is not publicly visible, but a determined
// attacker with the code can extract the hash. For real security, put
// Cloudflare Access (free) in front of the GitHub Pages URL.
//
// To change the password, see scripts/generate_password_hash.py.

const AUTH_CONFIG = {
  // Default credentials (change these!):
  username: "admin",
  // SHA-256 hex of the password. Default password: rohini2026
  passwordHash: "5479dabd460644b52d11151c796827307add8c95f248f98183acb31ca51cd98f",
  // Session timeout in minutes (0 = no timeout, only cleared on tab close)
  sessionMinutes: 60 * 12,
  // Set to true to show a "Remember me" checkbox (uses localStorage)
  rememberOption: true,
};

const SESSION_KEY = "rpp_session";

async function sha256Hex(text) {
  const buf = new TextEncoder().encode(text);
  const hash = await crypto.subtle.digest("SHA-256", buf);
  return [...new Uint8Array(hash)]
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

function setSession(remember) {
  const exp = AUTH_CONFIG.sessionMinutes
    ? Date.now() + AUTH_CONFIG.sessionMinutes * 60_000
    : 0;
  const payload = { exp, v: 1 };
  const json = JSON.stringify(payload);
  if (remember) localStorage.setItem(SESSION_KEY, json);
  else sessionStorage.setItem(SESSION_KEY, json);
}

function clearSession() {
  sessionStorage.removeItem(SESSION_KEY);
  localStorage.removeItem(SESSION_KEY);
}

function hasValidSession() {
  for (const store of [sessionStorage, localStorage]) {
    const raw = store.getItem(SESSION_KEY);
    if (!raw) continue;
    try {
      const { exp } = JSON.parse(raw);
      if (!exp || exp > Date.now()) return true;
      store.removeItem(SESSION_KEY);
    } catch {
      store.removeItem(SESSION_KEY);
    }
  }
  return false;
}

function showApp() {
  document.documentElement.classList.remove("locked");
  document.getElementById("login-gate")?.remove();
  document.getElementById("app-root")?.removeAttribute("hidden");
  window.rppAuthReady = true;
  window.dispatchEvent(new Event("rpp:ready"));
}

function showError(msg) {
  const el = document.getElementById("login-error");
  if (el) {
    el.textContent = msg;
    el.classList.add("show");
  }
}

function renderLogin() {
  document.documentElement.classList.add("locked");
  const gate = document.createElement("div");
  gate.id = "login-gate";
  gate.setAttribute("role", "dialog");
  gate.setAttribute("aria-modal", "true");
  gate.setAttribute("aria-labelledby", "login-title");
  gate.innerHTML = `
    <div class="login-card">
      <div class="login-brand">
        <span class="login-icon" aria-hidden="true">
          <svg viewBox="0 0 24 24" width="32" height="32"><path d="M3 11 L12 3 L21 11 L21 21 L14 21 L14 14 L10 14 L10 21 L3 21 Z" fill="currentColor"/></svg>
        </span>
        <h1 id="login-title">Rohini Property Pulse</h1>
        <p class="login-sub">Sign in to continue</p>
      </div>
      <form id="login-form" autocomplete="on" novalidate>
        <label class="login-field">
          <span>Username</span>
          <input id="login-username" name="username" type="text" autocomplete="username" required autocapitalize="none" autocorrect="off" spellcheck="false" />
        </label>
        <label class="login-field">
          <span>Password</span>
          <input id="login-password" name="password" type="password" autocomplete="current-password" required />
        </label>
        <label class="login-remember" id="login-remember-wrap">
          <input id="login-remember" type="checkbox" />
          <span>Remember me on this device</span>
        </label>
        <button type="submit" class="login-submit">Sign in</button>
        <div id="login-error" class="login-error" role="alert"></div>
      </form>
      <p class="login-foot">Private dataset · authorized access only</p>
    </div>
  `;
  document.body.appendChild(gate);

  document.getElementById("login-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const u = document.getElementById("login-username").value.trim();
    const p = document.getElementById("login-password").value;
    const remember = document.getElementById("login-remember")?.checked || false;
    if (!u || !p) return showError("Enter username and password.");
    const [hashU, hashP] = await Promise.all([sha256Hex(u), sha256Hex(p)]);
    if (u !== AUTH_CONFIG.username || hashP !== AUTH_CONFIG.passwordHash) {
      showError("Incorrect username or password.");
      document.getElementById("login-password").value = "";
      document.getElementById("login-password").focus();
      return;
    }
    setSession(remember);
    showApp();
  });

  // Focus first field
  setTimeout(() => document.getElementById("login-username")?.focus(), 50);
}

function lock() {
  clearSession();
  document.documentElement.classList.add("locked");
  const root = document.getElementById("app-root");
  if (root) root.setAttribute("hidden", "");
  renderLogin();
}

function initAuth() {
  if (hasValidSession()) {
    showApp();
    return;
  }
  // Hide app until authenticated
  const root = document.getElementById("app-root");
  if (root) root.setAttribute("hidden", "");
  // No app init when not authed; app.js waits for rpp:ready
  renderLogin();
}

// Global lock helper for the sign-out button
window.rppLock = lock;

// Boot as early as possible (this script is loaded with `defer` after the
// <div id="app-root"> in index.html, so DOM is parsed).
initAuth();
