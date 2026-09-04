// Configuration for mts-link-sync.
//
// Nothing personal is baked in. Override anything via a local `.env` file in the
// tool directory (copy `.env.example` → `.env`) or via real environment variables.
// The `.env` file is gitignored — your paths and session location never get committed.
//
// WHY THE VAULT PATH IS REQUIRED (and not defaulted):
// The predecessor tool defaulted OUTPUT_DIR to `./chats-out` inside the tool. When the
// `.env` that pointed at the real vault went missing, the tool kept exiting 0 while
// silently reading an empty registry from the wrong place and creating a stray output
// dir — "registry is empty" is indistinguishable from "you are looking in the wrong
// directory". A morning brief that silently reads nothing reports a calm day when the
// day was on fire, so this config fails loudly instead of guessing.

import { homedir } from "node:os";
import { join, isAbsolute, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { existsSync } from "node:fs";

const TOOL_DIR = dirname(fileURLToPath(import.meta.url));

// --- load .env from the tool directory, if present (built-in, no dependency) ---
try { process.loadEnvFile(join(TOOL_DIR, ".env")); } catch { /* no .env — use real env */ }

// Resolve a path setting: absolute stays, `~` expands, relative is anchored to the tool dir.
function resolvePath(value, fallback) {
  const v = value || fallback;
  if (v.startsWith("~/")) return join(homedir(), v.slice(2));
  return isAbsolute(v) ? v : join(TOOL_DIR, v);
}

// Entry point of the chats web app. Override for a different MTS Link instance.
export const CHATS_URL = process.env.MTS_LINK_CHATS_URL || "https://my.mts-link.ru/chats/";

// Saved browser session (cookies + localStorage), produced by `npm run login`.
// Lives in the home dir, OUTSIDE any repo — it is a personal SSO secret.
export const AUTH_FILE = resolvePath(process.env.MTS_LINK_AUTH_FILE, "~/.mts-link-chat-sync/auth.json");

// Where exported chat markdown and the cursor land. NO DEFAULT — see the note above.
const rawOutput = process.env.MTS_LINK_OUTPUT_DIR;

/**
 * Resolve the output dir, or throw with an actionable message.
 * Callers that need the path use this; `--status` uses `describeConfig` instead so
 * it can report a misconfiguration rather than die on it.
 */
export function outputDir() {
  if (!rawOutput) {
    throw new Error(
      "MTS_LINK_OUTPUT_DIR не задан — не знаю, куда писать выгрузки.\n" +
      `  Создай ${join(TOOL_DIR, ".env")} (см. .env.example) со строкой:\n` +
      "    MTS_LINK_OUTPUT_DIR=/абсолютный/путь/до/GROUND/_intake/chats\n" +
      "  Без него инструмент молча читал бы пустой реестр не из того места."
    );
  }
  return resolvePath(rawOutput);
}

// Registry of watched chats. Defaults to sitting alongside the output.
export function registryFile() {
  return process.env.MTS_LINK_REGISTRY
    ? resolvePath(process.env.MTS_LINK_REGISTRY)
    : join(outputDir(), "watched-chats.yaml");
}

// Delta cursor: per-chat watermark of the last exported message time.
export function cursorFile() {
  return process.env.MTS_LINK_CURSOR
    ? resolvePath(process.env.MTS_LINK_CURSOR)
    : join(outputDir(), ".sync-cursor.json");
}

/**
 * Non-throwing view of the configuration, for `--status` and for diagnostics.
 * Reports what is set, what is missing, and whether the paths actually exist —
 * so a wrong path is visible before a pull, not after a silent empty result.
 */
export function describeConfig() {
  const out = { ok: true, problems: [], authFile: AUTH_FILE, chatsUrl: CHATS_URL };

  out.authExists = existsSync(AUTH_FILE);
  if (!out.authExists) {
    out.ok = false;
    out.problems.push(`Нет SSO-сессии (${AUTH_FILE}). Разовый вход: npm run login`);
  }

  if (!rawOutput) {
    out.ok = false;
    out.problems.push(
      "MTS_LINK_OUTPUT_DIR не задан. Скопируй .env.example → .env и укажи путь до GROUND/_intake/chats."
    );
    return out;
  }

  out.outputDir = resolvePath(rawOutput);
  out.outputExists = existsSync(out.outputDir);
  if (!out.outputExists) {
    out.ok = false;
    out.problems.push(`Папка выгрузок не существует: ${out.outputDir}`);
  }

  out.registryFile = registryFile();
  out.registryExists = existsSync(out.registryFile);
  if (!out.registryExists) {
    out.ok = false;
    out.problems.push(`Реестр не найден: ${out.registryFile}. Настрой через /tg-watch-аналог: --list-chats → --add`);
  }

  out.cursorFile = cursorFile();
  out.cursorExists = existsSync(out.cursorFile);

  return out;
}
