// mts-link-sync — export MTS Link chat messages into markdown for the morning brief.
//
// Modes:
//   --status                              offline: config, session, registry, cursor age
//   --list-chats [--search "text"]        list chats (numbered from 0)
//   --watch 0,3,7                         resolve picked indices -> chat-id + name
//   --add --chat-id X --name "" --purpose "" --extract ""    append one registry entry
//   --list-watched                        print the current registry
//   --unwatch <chat-id>                   remove a registry entry
//   --pull [--since-last | --yesterday | --days N | --from D --to D] [--dry] [--all]
//
// READ-ONLY against the MTS Link chat API (see wsClient.mjs). It sends only `token`,
// `ping` and `Get*` queries — never Chat.MarkMessagesAsRead, which would clear the
// PO's unread counters. The tool must be invisible to the account it reads.

import { existsSync, mkdirSync, readFileSync, writeFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { harvest } from "./harvest.mjs";
import { connect } from "./wsClient.mjs";
import { readRegistry, addEntries, removeEntry } from "./registry.mjs";
import { outputDir, registryFile, cursorFile, describeConfig } from "./config.mjs";
import { readCursor, writeCursor, advance, watermark, windowStart } from "./cursor.mjs";
import {
  resolveWindow, renderDump, dateStr, sanitize, describeAge, SINCE_LAST_FLOOR_DAYS,
} from "./window.mjs";

// ---------- args ----------
const argv = process.argv.slice(2);
const has = (f) => argv.includes(`--${f}`);
const arg = (f) => { const i = argv.indexOf(`--${f}`); return i >= 0 ? argv[i + 1] : undefined; };

// ---------- chat list normalization ----------
// dialogs/group chats come wrapped: {type, value:{...}}; channels come flat.
function normDialogItem(it) {
  const v = it.value || {};
  if (it.type === "FavoritesListItem") return { chatId: v.chatId, name: "Избранное", kind: "favorites" };
  if (it.type === "DialogListItem") return { chatId: v.chatId, name: null, kind: "dialog", interlocutorId: v.interlocutorId };
  return { chatId: v.chatId, name: v.name, kind: "group" };
}

async function fetchAllChats(rpc, resolveName) {
  const dialogs = (await rpc.call("chat", "Chat.GetMyDialogsAndGroupChatsV2", {})).value.items || [];
  const channels = (await rpc.call("chat", "Chat.GetMyChannelsV2", {})).value.items || [];
  const out = [];
  for (const it of dialogs) {
    const n = normDialogItem(it);
    if (!n.chatId) continue;
    if (!n.name && n.interlocutorId) n.name = await resolveName(n.interlocutorId);
    out.push(n);
  }
  for (const c of channels) out.push({ chatId: c.chatId, name: c.name, kind: "channel" });
  return out;
}

// ---------- member name resolution (cached per run) ----------
function makeResolver(rpc, orgId) {
  const cache = new Map();
  const fn = async (userId) => {
    if (!userId) return "—";
    if (cache.has(userId)) return cache.get(userId);
    let name = userId.slice(0, 8);
    try {
      const p = (await rpc.call("organization", "Organization.GetMemberV2", { organizationId: orgId, userId })).value?.profile || {};
      name = [p.firstName, p.lastName].filter(Boolean).join(" ").trim() || p.displayName || name;
    } catch { /* keep short-id fallback: an unresolved author is still an anchor */ }
    cache.set(userId, name);
    return name;
  };
  fn.cache = cache;
  return fn;
}

// ---------- message pagination for a window ----------
async function fetchWindow(rpc, chatId, fromMs, toMs) {
  const collected = [];
  let cursor = undefined; // message id to page from; first page = newest (no cursor)
  for (let guard = 0; guard < 200; guard++) {
    const param = cursor ? { chatId, limit: 50, from: cursor, direction: "Before" } : { chatId, limit: 50 };
    const res = await rpc.call("chat", "Chat.GetMessagesV2", param);
    const msgs = res.value?.messages || [];
    if (msgs.length === 0) break;
    for (const m of msgs) collected.push(m);
    const oldest = msgs.reduce((a, b) => (a.createdAt <= b.createdAt ? a : b));
    if (oldest.createdAt < fromMs) break;   // paged past the window's left edge
    if (cursor === oldest.id) break;         // no progress — stop
    cursor = oldest.id;
  }
  const seen = new Set();
  return collected
    .filter((m) => { if (seen.has(m.id)) return false; seen.add(m.id); return true; })
    .filter((m) => !m.isDeleted && m.createdAt >= fromMs && m.createdAt <= toMs)
    .sort((a, b) => a.createdAt - b.createdAt);
}

// ---------- offline status ----------
function printStatus() {
  const cfg = describeConfig();
  console.log("Конфигурация mts-link-sync\n");
  console.log(`  SSO-сессия:  ${cfg.authFile}`);
  console.log(`               ${cfg.authExists ? `есть, обновлена ${cfg.authAgeDays} дн назад` : "НЕТ → npm run login"}`);
  if (cfg.outputDir) {
    console.log(`  Выгрузки:    ${cfg.outputDir} ${cfg.outputExists ? "" : "(НЕ СУЩЕСТВУЕТ)"}`);
    console.log(`  Реестр:      ${cfg.registryFile} ${cfg.registryExists ? "" : "(НЕ НАЙДЕН)"}`);
  } else {
    console.log("  Выгрузки:    [MTS_LINK_OUTPUT_DIR не задан]");
  }

  if (cfg.registryExists) {
    const reg = readRegistry();
    console.log(`  Чатов в реестре: ${reg.length}`);
  }

  if (cfg.cursorFile) {
    if (cfg.cursorExists) {
      const cur = readCursor(cfg.cursorFile);
      const marks = Object.values(cur.chats)
        .map((c) => c.lastMessageMs)
        .filter(Number.isFinite);
      const newest = marks.length ? Math.max(...marks) : undefined;
      console.log(`  Курсор:      ${Object.keys(cur.chats).length} чатов`);
      if (newest) console.log(`               свежайшее сообщение: ${dateStr(newest)} (${describeAge(newest)})`);
    } else {
      console.log("  Курсор:      нет (первый прогон выгрузит всё окно)");
    }
  }

  if (cfg.problems.length) {
    console.log("\nПроблемы:");
    for (const p of cfg.problems) console.log(`  · ${p}`);
  }
  if (cfg.warnings.length) {
    console.log("\nПредупреждения:");
    for (const w of cfg.warnings) console.log(`  · ${w}`);
  }
  if (!cfg.problems.length && !cfg.warnings.length) console.log("\nВсё на месте.");
  else if (!cfg.problems.length) console.log("\nКонфигурация цела, но см. предупреждения выше.");
  return cfg.ok ? 0 : 1;
}

// ====================================================================
async function main() {
  // --- offline modes: no network, no session needed ---
  if (has("status")) return printStatus();

  if (has("list-watched")) {
    const reg = readRegistry();
    if (!reg.length) {
      console.log(`Реестр пуст: ${registryFile()}`);
      console.log("Добавь чаты: --list-chats → --add (см. README).");
      return 0;
    }
    reg.forEach((e, i) => console.log(
      `  ${i}. ${e.name}  [${e["chat-id"]}]\n       purpose: ${e.purpose || "—"}\n       extract: ${e.extract || "—"}`
    ));
    return 0;
  }
  if (has("add")) {
    const entry = {
      "chat-id": arg("chat-id"), name: arg("name") || "",
      purpose: arg("purpose") || "", extract: arg("extract") || "",
      added: dateStr(Date.now()),
    };
    if (!entry["chat-id"]) throw new Error("--add требует --chat-id");
    const n = addEntries([entry]);
    console.log(n ? `Добавлено: ${entry.name} [${entry["chat-id"]}]` : `Уже в реестре: ${entry["chat-id"]}`);
    return 0;
  }
  if (has("unwatch")) {
    const n = removeEntry(arg("unwatch"));
    console.log(n ? `Удалено из реестра: ${arg("unwatch")}` : `Не найдено: ${arg("unwatch")}`);
    return 0;
  }

  if (!has("list-chats") && !has("watch") && !has("pull")) {
    console.log("Режимы: --status | --list-chats | --watch | --add | --list-watched | --unwatch | --pull");
    console.log("Окно для --pull: --since-last | --yesterday | --days N | --from D --to D");
    return 0;
  }

  // --- network modes ---
  const OUT = outputDir();
  mkdirSync(OUT, { recursive: true });
  const LIST_FILE = join(OUT, ".last-chats.json");

  const h = await harvest();
  const rpc = await connect(h);
  try {
    if (has("list-chats")) {
      const resolveName = makeResolver(rpc, h.orgId);
      let chats = await fetchAllChats(rpc, resolveName);
      const search = arg("search");
      if (search) chats = chats.filter((c) => (c.name || "").toLowerCase().includes(search.toLowerCase()));
      chats.sort((a, b) => (a.name || "").localeCompare(b.name || "", "ru"));
      const watched = new Set(readRegistry().map((e) => String(e["chat-id"])));
      chats.forEach((c, i) => (c.index = i));
      writeFileSync(LIST_FILE, JSON.stringify(chats, null, 2));
      console.log(`Чатов${search ? ` по «${search}»` : ""}: ${chats.length}\n`);
      for (const c of chats) console.log(`  ${c.index}. ${c.name}  [${c.chatId}]${watched.has(String(c.chatId)) ? "   [слежу]" : ""}`);
      console.log(`\nДальше: node sync.mjs --watch <номера>, затем --add по каждому.`);
      return 0;
    }

    if (has("watch")) {
      if (!existsSync(LIST_FILE)) throw new Error("Нет .last-chats.json — сначала --list-chats");
      const list = JSON.parse(readFileSync(LIST_FILE, "utf8"));
      const picks = String(arg("watch")).split(",").map((s) => Number(s.trim())).filter(Number.isInteger);
      console.log(JSON.stringify(
        picks.map((i) => list[i]).filter(Boolean).map((c) => ({ "chat-id": c.chatId, name: c.name })),
        null, 2
      ));
      return 0;
    }

    if (has("pull")) {
      let reg;
      if (has("all")) {
        const rn = makeResolver(rpc, h.orgId);
        reg = (await fetchAllChats(rpc, rn)).map((c) => ({ "chat-id": c.chatId, name: c.name, purpose: "", extract: "" }));
      } else {
        reg = readRegistry();
        if (!reg.length) {
          throw new Error(`Реестр пуст (${registryFile()}). Сначала --list-chats → --add, либо --pull --all.`);
        }
      }

      const incremental = has("since-last");
      const requested = resolveWindow({
        from: arg("from"), to: arg("to"), days: arg("days"), yesterday: has("yesterday"),
      });
      const dry = has("dry");
      const CURSOR = cursorFile();
      const cursor = readCursor(CURSOR);
      const floorMs = Date.now() - SINCE_LAST_FLOOR_DAYS * 86400000;
      const resolveName = makeResolver(rpc, h.orgId);

      console.log(`Окно: ${requested.label}${incremental ? " (инкрементально от курсора)" : ""}${dry ? "  (dry-run)" : ""}\n`);

      const saved = [];
      for (const e of reg) {
        const chatId = e["chat-id"];
        const fromMs = incremental
          ? windowStart(cursor, chatId, requested.fromMs, { floorMs })
          : requested.fromMs;

        const msgs = await fetchWindow(rpc, chatId, fromMs, requested.toMs);
        if (msgs.length === 0) {
          const mark = watermark(cursor, chatId);
          console.log(`  · ${e.name}: нового нет${mark ? ` (последнее: ${dateStr(mark)})` : ""}`);
          continue;
        }
        if (dry) { console.log(`  [dry] ${e.name}: ${msgs.length} сообщений`); continue; }

        // Resolve authors before rendering — rendering itself stays pure.
        const resolvedAuthors = new Map();
        for (const m of msgs) {
          if (!resolvedAuthors.has(m.authorId)) resolvedAuthors.set(m.authorId, await resolveName(m.authorId));
        }

        const windowLabel = `${dateStr(fromMs)}..${dateStr(requested.toMs)}`;
        const fileBase = `${windowLabel} ${sanitize(e.name)}`;
        writeFileSync(
          join(OUT, `${fileBase}.md`),
          renderDump({
            name: e.name, chatId, windowLabel, purpose: e.purpose, extract: e.extract,
            messages: msgs, resolvedAuthors, incremental,
          }),
          "utf8"
        );

        const newest = msgs[msgs.length - 1].createdAt;
        advance(cursor, chatId, newest, { name: e.name });
        console.log(`  ✓ ${fileBase}.md  (${msgs.length} сообщений)`);
        saved.push({ file: `${fileBase}.md`, chatId, msgCount: msgs.length });
      }

      if (!dry) {
        // Cursor is written only after the dumps exist: a crash mid-pull must leave the
        // watermark behind, causing a harmless re-export, never a silent gap.
        writeCursor(CURSOR, cursor);
        writeFileSync(join(OUT, ".last-pull.json"), JSON.stringify(
          { at: new Date().toISOString(), window: requested.label, incremental, files: saved }, null, 2
        ));
      }
      console.log(`\nГотово. Файлов: ${dry ? 0 : saved.length}. Папка: ${OUT}`);
      return 0;
    }
  } finally {
    rpc.close();
  }
  return 0;
}

main()
  .then((code) => process.exit(code || 0))
  .catch((e) => { console.error("\n" + e.message); process.exit(1); });
