// Window resolution and rendering. Timezone bugs here are the kind that lose exactly
// the evening messages where decisions get made, so MSK boundaries are asserted
// explicitly rather than trusted.

import { test } from "node:test";
import assert from "node:assert/strict";

import { resolveWindow, renderDump, dateStr, timeStr, sanitize, describeAge } from "../window.mjs";

const MSK = (s) => Date.parse(s);

test("--yesterday covers the whole previous MSK day", () => {
  const now = MSK("2026-09-04T09:40:00+03:00");
  const w = resolveWindow({ yesterday: true, now });
  assert.equal(w.label, "2026-09-03");
  assert.equal(dateStr(w.fromMs), "2026-09-03");
  assert.equal(dateStr(w.toMs), "2026-09-03");
  // The late-evening edge is the point: a trailing 24h window run at 09:40 would
  // have cut everything before 09:40 yesterday, dropping the evening entirely.
  assert.ok(w.fromMs <= MSK("2026-09-03T00:00:00+03:00"));
  assert.ok(w.toMs >= MSK("2026-09-03T23:59:00+03:00"));
});

test("--yesterday is correct when the machine runs just after MSK midnight", () => {
  const now = MSK("2026-09-04T00:10:00+03:00");
  assert.equal(resolveWindow({ yesterday: true, now }).label, "2026-09-03");
});

test("--yesterday crosses a month boundary", () => {
  const now = MSK("2026-09-01T08:00:00+03:00");
  assert.equal(resolveWindow({ yesterday: true, now }).label, "2026-08-31");
});

test("explicit --from/--to is inclusive on both ends", () => {
  const w = resolveWindow({ from: "2026-08-01", to: "2026-08-03" });
  assert.equal(dateStr(w.fromMs), "2026-08-01");
  assert.equal(dateStr(w.toMs), "2026-08-03");
  assert.equal(w.label, "2026-08-01..2026-08-03");
});

test("--days N produces a trailing window", () => {
  const now = MSK("2026-09-04T12:00:00+03:00");
  const w = resolveWindow({ days: 7, now });
  assert.equal(Math.round((w.toMs - w.fromMs) / 86400000), 7);
});

test("no arguments falls back to the 14-day default", () => {
  const now = MSK("2026-09-04T12:00:00+03:00");
  const w = resolveWindow({ now });
  assert.equal(Math.round((w.toMs - w.fromMs) / 86400000), 14);
});

test("timestamps render in MSK regardless of host timezone", () => {
  const ms = MSK("2026-09-03T21:30:00+03:00");
  assert.equal(dateStr(ms), "2026-09-03");
  assert.equal(timeStr(ms), "21:30");
});

test("chat names are made filesystem-safe without becoming unrecognizable", () => {
  assert.equal(sanitize("LV/GDS: релиз"), "LV-GDS- релиз");
  assert.equal(sanitize(""), "Без названия");
  assert.ok(sanitize("x".repeat(200)).length <= 80);
});

test("dump carries the frontmatter the radar reads, and groups by day", () => {
  const md = renderDump({
    name: "Штаб", chatId: "c1", windowLabel: "2026-09-03",
    purpose: "блокеры", extract: "решения", incremental: true,
    messages: [
      { authorId: "u1", createdAt: MSK("2026-09-03T10:00:00+03:00"), text: "первое" },
      { authorId: "u2", createdAt: MSK("2026-09-03T11:00:00+03:00"), text: "второе" },
    ],
    resolvedAuthors: new Map([["u1", "Романов"], ["u2", "Ананьев"]]),
  });
  assert.match(md, /^---\n/);
  assert.match(md, /chat-id: "c1"/);
  assert.match(md, /purpose: "блокеры"/);
  assert.match(md, /msg-count: 2/);
  assert.match(md, /incremental: true/);
  assert.match(md, /## 2026-09-03/);
  assert.match(md, /Романов 10:00: первое/);
  assert.match(md, /Ананьев 11:00: второе/);
});

test("unresolved author still yields an anchored line", () => {
  const md = renderDump({
    name: "X", chatId: "c", windowLabel: "w", messages: [
      { authorId: "ghost", createdAt: MSK("2026-09-03T10:00:00+03:00"), text: "t" },
    ],
    resolvedAuthors: new Map(),
  });
  assert.match(md, /— 10:00: t/);
});

test("age is reported in units a human reads at a glance", () => {
  const now = MSK("2026-09-04T12:00:00+03:00");
  assert.equal(describeAge(now - 30 * 60000, now), "30 мин назад");
  assert.equal(describeAge(now - 5 * 3600000, now), "5 ч назад");
  assert.equal(describeAge(now - 3 * 86400000, now), "3 дн назад");
});
