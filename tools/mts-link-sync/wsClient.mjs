// Minimal read-only JSON-RPC client for the MTS Link chat WebSocket.
//
// Protocol (reverse-engineered): server sends control "open" → we send control
// "token" with the harvested JWT → server "setTokenResp" ok → then request/response
// "messages" frames keyed by a per-message uuid. Keepalive is control "ping"/"pong".
//
// READ-ONLY: this client only ever sends `token`, `ping`, and `Get*` queries.
// It must NEVER send mutating methods (e.g. Chat.MarkMessagesAsRead), which would
// change the PO's account state (clear unread counters).

import { randomUUID } from "node:crypto";

const PING_MS = 10000;
const CALL_TIMEOUT_MS = 20000;

export async function connect({ wsUrl, token }) {
  const ws = new WebSocket(wsUrl);
  let seq = 0;             // our outbound frame counter
  let ack = 0;             // highest server seq we've seen
  const pending = new Map(); // message id -> {resolve, reject, timer}
  let pinger = null;

  const send = (obj) => ws.send(JSON.stringify(obj));

  function rejectAll(err) {
    for (const p of pending.values()) { clearTimeout(p.timer); p.reject(err); }
    pending.clear();
  }

  await new Promise((resolve, reject) => {
    const authTimer = setTimeout(() => reject(new Error("WS auth timeout")), CALL_TIMEOUT_MS);

    ws.addEventListener("message", (ev) => {
      let msg;
      try { msg = JSON.parse(ev.data); } catch { return; }
      if (typeof msg.seq === "number") ack = Math.max(ack, msg.seq);

      const ctl = msg.control?.name;
      if (ctl === "open") { send({ control: { name: "token", param: { token } }, seq: ++seq, ack }); return; }
      if (ctl === "setTokenResp") {
        clearTimeout(authTimer);
        if (msg.control.param?.status !== "ok") return reject(new Error("WS token rejected"));
        pinger = setInterval(() => { try { send({ control: { name: "ping" }, seq: ++seq, ack }); } catch {} }, PING_MS);
        resolve();
        return;
      }
      if (ctl === "ping") { send({ control: { name: "pong", param: { success: true } }, seq: ++seq, ack }); return; }

      for (const m of msg.messages || []) {
        if (m.type === "response" && pending.has(m.id)) {
          const p = pending.get(m.id); pending.delete(m.id); clearTimeout(p.timer);
          p.resolve(m);
        }
      }
    });

    ws.addEventListener("error", (e) => { const err = new Error("WS error: " + (e.message || e.type || "unknown")); clearTimeout(authTimer); rejectAll(err); reject(err); });
    ws.addEventListener("close", () => { if (pinger) clearInterval(pinger); rejectAll(new Error("WS closed")); });
  });

  // Send a query and resolve with its `result` (throws on RPC error / timeout).
  function call(dst, method, param = {}) {
    const id = randomUUID();
    seq += 1;
    send({ messages: [{ id, dst, method, param, kind: "command", seq }], seq, ack });
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => { pending.delete(id); reject(new Error(`RPC timeout: ${method}`)); }, CALL_TIMEOUT_MS);
      pending.set(id, {
        resolve: (m) => (m.error ? reject(new Error(`RPC error ${method}: ${JSON.stringify(m.error)}`)) : resolve(m.result)),
        reject, timer,
      });
    });
  }

  function close() { if (pinger) clearInterval(pinger); try { ws.close(); } catch {} }

  return { call, close };
}
