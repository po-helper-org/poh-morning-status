// Delta cursor: per-chat watermark of the newest message already exported.
//
// WHY: the morning brief must answer "what changed since I last looked", not "what
// exists". Without a watermark every run re-exports the same window, the radar
// re-classifies the same blockers, and the PO learns to skim past them — the exact
// failure mode that makes a daily brief worthless by week two.
//
// The watermark is the newest message timestamp actually written for a chat, not the
// time the run happened. Wall-clock would silently skip messages that arrived while a
// pull was in flight; a message-derived mark cannot.
//
// Shape (JSON, alongside the dumps):
//   {
//     "version": 1,
//     "chats": { "<chat-id>": { "lastMessageMs": 1755440000000, "lastPullAt": "2026-09-04T09:12:00.000Z", "name": "..." } }
//   }

import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname } from "node:path";

export const CURSOR_VERSION = 1;

const empty = () => ({ version: CURSOR_VERSION, chats: {} });

/**
 * Read the cursor. A missing file is a first run, not an error.
 * A corrupt or foreign-version file is treated as absent — a bad cursor must degrade
 * into "export the requested window" (harmless duplicate work), never into a crash or
 * into skipped messages.
 */
export function readCursor(path) {
  if (!existsSync(path)) return empty();
  let parsed;
  try {
    parsed = JSON.parse(readFileSync(path, "utf8"));
  } catch {
    return empty();
  }
  if (!parsed || typeof parsed !== "object") return empty();
  if (parsed.version !== CURSOR_VERSION) return empty();
  if (!parsed.chats || typeof parsed.chats !== "object") return empty();
  return { version: CURSOR_VERSION, chats: parsed.chats };
}

export function writeCursor(path, cursor) {
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, JSON.stringify(cursor, null, 2) + "\n", "utf8");
}

/** Watermark for one chat, or undefined when the chat was never pulled. */
export function watermark(cursor, chatId) {
  const e = cursor.chats?.[String(chatId)];
  return e && Number.isFinite(e.lastMessageMs) ? e.lastMessageMs : undefined;
}

/**
 * Advance a chat's watermark. Monotonic by construction: a later run that happens to
 * read an older window must not rewind the mark and cause re-exports.
 */
export function advance(cursor, chatId, lastMessageMs, { name, at = new Date() } = {}) {
  const key = String(chatId);
  const prev = cursor.chats[key]?.lastMessageMs;
  const next = Number.isFinite(prev) ? Math.max(prev, lastMessageMs) : lastMessageMs;
  cursor.chats[key] = {
    lastMessageMs: next,
    lastPullAt: at.toISOString(),
    ...(name ? { name } : {}),
  };
  return cursor;
}

/**
 * Effective lower bound for a chat's pull window.
 *
 * `+1` past the watermark: the mark is a message we already exported, and the API
 * range is inclusive, so without it every run re-emits that one message and each
 * dump opens with a line the PO has already read.
 *
 * The floor keeps an unattended gap from turning into an unbounded backfill: coming
 * back from two weeks of vacation should produce yesterday's brief, not a 3000-message
 * re-read that buries the signal it exists to surface.
 */
export function windowStart(cursor, chatId, requestedFromMs, { floorMs } = {}) {
  const mark = watermark(cursor, chatId);
  if (mark === undefined) return requestedFromMs;
  const afterMark = mark + 1;
  const start = Math.max(requestedFromMs, afterMark);
  if (Number.isFinite(floorMs)) return Math.max(start, floorMs);
  return start;
}
