// Cursor behaviour. These guard the failure modes that are invisible in production:
// a brief that silently repeats yesterday, or one that silently skips a day.

import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { readCursor, writeCursor, advance, watermark, windowStart, CURSOR_VERSION } from "../cursor.mjs";

const tmp = () => mkdtempSync(join(tmpdir(), "mls-cursor-"));

test("missing cursor file is a first run, not an error", () => {
  const dir = tmp();
  try {
    const c = readCursor(join(dir, "nope.json"));
    assert.equal(c.version, CURSOR_VERSION);
    assert.deepEqual(c.chats, {});
  } finally { rmSync(dir, { recursive: true, force: true }); }
});

test("corrupt cursor degrades to empty instead of throwing", () => {
  const dir = tmp();
  const f = join(dir, "c.json");
  try {
    writeFileSync(f, "{not json");
    assert.deepEqual(readCursor(f).chats, {});
  } finally { rmSync(dir, { recursive: true, force: true }); }
});

test("foreign cursor version is ignored rather than misread", () => {
  const dir = tmp();
  const f = join(dir, "c.json");
  try {
    writeFileSync(f, JSON.stringify({ version: 99, chats: { a: { lastMessageMs: 5 } } }));
    assert.deepEqual(readCursor(f).chats, {});
  } finally { rmSync(dir, { recursive: true, force: true }); }
});

test("round-trips through disk", () => {
  const dir = tmp();
  const f = join(dir, "c.json");
  try {
    const c = advance(readCursor(f), "chat-1", 1000, { name: "Штаб" });
    writeCursor(f, c);
    const back = readCursor(f);
    assert.equal(watermark(back, "chat-1"), 1000);
    assert.equal(back.chats["chat-1"].name, "Штаб");
  } finally { rmSync(dir, { recursive: true, force: true }); }
});

test("advance is monotonic — a stale run cannot rewind the watermark", () => {
  let c = advance(readCursor("/nonexistent"), "chat-1", 5000);
  c = advance(c, "chat-1", 1000);
  assert.equal(watermark(c, "chat-1"), 5000);
});

test("first pull of a chat uses the requested window verbatim", () => {
  const c = readCursor("/nonexistent");
  assert.equal(windowStart(c, "new-chat", 12345), 12345);
});

test("subsequent pull starts just past the watermark, not at it", () => {
  // Starting *at* the mark would re-export the last message every single run,
  // so each dump would open with a line the PO already read.
  const c = advance(readCursor("/nonexistent"), "chat-1", 9000);
  assert.equal(windowStart(c, "chat-1", 1000), 9001);
});

test("an explicitly wider request never narrows below the watermark", () => {
  const c = advance(readCursor("/nonexistent"), "chat-1", 9000);
  assert.equal(windowStart(c, "chat-1", 50000), 50000);
});

test("floor bounds the backfill after a long absence", () => {
  // Two weeks away must still produce a readable brief, not a 3000-message re-read.
  const c = advance(readCursor("/nonexistent"), "chat-1", 1000);
  const floorMs = 100000;
  assert.equal(windowStart(c, "chat-1", 0, { floorMs }), floorMs);
});

test("floor does not pull the window forward past a fresh watermark", () => {
  const c = advance(readCursor("/nonexistent"), "chat-1", 500000);
  assert.equal(windowStart(c, "chat-1", 0, { floorMs: 100000 }), 500001);
});

test("chats are tracked independently", () => {
  let c = advance(readCursor("/nonexistent"), "a", 1000);
  c = advance(c, "b", 7000);
  assert.equal(watermark(c, "a"), 1000);
  assert.equal(watermark(c, "b"), 7000);
  assert.equal(watermark(c, "c"), undefined);
});
