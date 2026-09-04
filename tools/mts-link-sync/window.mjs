// Pure window/formatting helpers — no network, no filesystem, so they are testable
// directly. Everything here is Moscow-time based: the PO's day boundaries are MSK,
// and "yesterday" in a morning brief must mean his yesterday regardless of the
// machine's timezone.

const MSK_TIME = new Intl.DateTimeFormat("ru-RU", {
  timeZone: "Europe/Moscow", hour: "2-digit", minute: "2-digit",
});
const MSK_DATE = new Intl.DateTimeFormat("sv-SE", {
  timeZone: "Europe/Moscow", year: "numeric", month: "2-digit", day: "2-digit",
});

export const dateStr = (ms) => MSK_DATE.format(new Date(ms)); // YYYY-MM-DD
export const timeStr = (ms) => MSK_TIME.format(new Date(ms)); // HH:MM

export const sanitize = (s) =>
  String(s || "Без названия").replace(/[\/:\\]/g, "-").replace(/\s+/g, " ").trim().slice(0, 80);

export const DEFAULT_DAYS = 14;

/**
 * Hard floor on how far back an incremental pull may reach, in days.
 * See cursor.windowStart: this bounds the backfill after a long absence.
 */
export const SINCE_LAST_FLOOR_DAYS = 7;

/**
 * Resolve the requested window from CLI args.
 *
 * Modes:
 *   --from D --to D   explicit MSK dates, inclusive
 *   --days N          trailing N days from now
 *   --yesterday       exactly the previous MSK calendar day (the brief's default grain)
 *   (nothing)         trailing DEFAULT_DAYS
 *
 * `--yesterday` exists because a morning brief asks about a *day*, not about "the last
 * 24 hours": a trailing window run at 09:40 would cut yesterday's evening messages in
 * half and silently drop the late decisions that most often change the plan.
 */
export function resolveWindow({ from, to, days, yesterday, now = Date.now() } = {}) {
  if (yesterday) {
    const today = dateStr(now);
    const prev = dateStr(Date.parse(`${today}T12:00:00+03:00`) - 86400000);
    return {
      fromMs: Date.parse(`${prev}T00:00:00+03:00`),
      toMs: Date.parse(`${prev}T23:59:59.999+03:00`),
      label: prev,
    };
  }
  const toMs = to ? Date.parse(`${to}T23:59:59.999+03:00`) : now;
  const fromMs = from
    ? Date.parse(`${from}T00:00:00+03:00`)
    : toMs - (Number(days) || DEFAULT_DAYS) * 86400000;
  return { fromMs, toMs, label: `${dateStr(fromMs)}..${dateStr(toMs)}` };
}

/**
 * Render one chat's messages as the markdown dump body.
 * `resolvedAuthors` maps authorId -> display name (resolution is async and network
 * bound, so it happens before this pure step).
 */
export function renderDump({ name, chatId, windowLabel, purpose, extract, messages, resolvedAuthors, incremental }) {
  const lines = [
    "---",
    "type: mts-chat",
    `chat-id: "${chatId}"`,
    `window: ${windowLabel}`,
    `purpose: ${JSON.stringify(purpose || "")}`,
    `extract: ${JSON.stringify(extract || "")}`,
    `msg-count: ${messages.length}`,
    `incremental: ${incremental ? "true" : "false"}`,
    "source: MTS Link",
    "---",
    "",
    `# ${name}`,
    "",
  ];
  let lastDate = "";
  for (const m of messages) {
    const d = dateStr(m.createdAt);
    if (d !== lastDate) {
      lines.push("", `## ${d}`, "");
      lastDate = d;
    }
    const author = resolvedAuthors.get(m.authorId) || "—";
    lines.push(`${author} ${timeStr(m.createdAt)}: ${(m.text || "").trim()}`);
  }
  return lines.join("\n") + "\n";
}

/** Human-readable age, for the freshness check the brief performs before pulling. */
export function describeAge(ms, now = Date.now()) {
  const mins = Math.max(0, Math.round((now - ms) / 60000));
  if (mins < 60) return `${mins} мин назад`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours} ч назад`;
  return `${Math.round(hours / 24)} дн назад`;
}
