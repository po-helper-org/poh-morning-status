// Harvest the chat WebSocket credentials from a live /chats/ handshake.
//
// MTS Link chats talk JSON-RPC over a WebSocket that the SPA authenticates with
// a short-lived JWT. Rather than mint that JWT ourselves, we let the real app do
// its handshake in a headless Playwright browser (using the saved SSO session)
// and snag {wsUrl, token, orgId} off the frames it sends. wsClient.mjs then opens
// its own socket with these — no browser needed during the actual pull.

import { chromium } from "playwright";
import { existsSync } from "node:fs";
import { AUTH_FILE, CHATS_URL } from "./config.mjs";

const TOKEN_RE = /"name":"token","param":\{"token":"([^"]+)"/;
const ORG_RE = /"organizationId":"([0-9a-f-]{36})"/;

export async function harvest({ timeoutMs = 60000 } = {}) {
  if (!existsSync(AUTH_FILE)) {
    throw new Error(`No saved session (${AUTH_FILE}). Run once: npm run login`);
  }
  const browser = await chromium.launch({ headless: true });
  try {
    const context = await browser.newContext({ storageState: AUTH_FILE });
    const page = await context.newPage();

    let wsUrl = null, token = null, orgId = null;
    page.on("websocket", (sock) => {
      if (!/prod-ws-chat/.test(sock.url())) return;
      wsUrl = sock.url();
      sock.on("framesent", (f) => {
        const d = String(f.payload);
        if (!token) { const m = d.match(TOKEN_RE); if (m) token = m[1]; }
        if (!orgId) { const o = d.match(ORG_RE); if (o) orgId = o[1]; }
      });
    });

    await page.goto(CHATS_URL, { waitUntil: "networkidle", timeout: timeoutMs });
    if (/login|auth|sso|signin/i.test(page.url())) {
      throw new Error("Session expired — redirected to login. Re-run: npm run login");
    }
    // Give the SPA time to open + authenticate the socket.
    for (let i = 0; i < 20 && !(wsUrl && token); i++) await page.waitForTimeout(500);

    if (!wsUrl || !token) {
      throw new Error("Could not capture the chat WS token from the handshake (socket didn't open / protocol changed).");
    }
    return { wsUrl, token, orgId };
  } finally {
    await browser.close();
  }
}
