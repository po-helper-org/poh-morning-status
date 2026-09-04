// Read/write the watched-chats registry (YAML in the vault).
//
// Schema is unchanged from the predecessor tool, so an existing
// `watched-chats.yaml` keeps working as-is:
//
//   - chat-id: "abc123"
//     name: "Продуктовый штаб Ticketland"
//     purpose: "Слежу за продуктовыми решениями и блокерами"
//     extract: "Решения, блокеры, дедлайны, спорные вопросы"
//     added: 2026-07-09
//
// `purpose`/`extract` are free text the PO curates. They ride into each exported
// file's frontmatter and steer the later LLM analysis: the registry is where the PO
// says *why* a chat is watched, so the brief can extract what he actually cares about
// instead of summarizing everything equally.

import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname } from "node:path";
import YAML from "yaml";
import { registryFile } from "./config.mjs";

const HEADER = `# Отслеживаемые чаты MTS Link — их выгружает \`mts-link-sync --pull\`.
# Правь через скилл /mts-watch или руками. Одна запись — один чат.
# purpose = зачем следишь; extract = что вытаскивать (направляет анализ агента).
`;

export function readRegistry() {
  const file = registryFile();
  if (!existsSync(file)) return [];
  const parsed = YAML.parse(readFileSync(file, "utf8"));
  if (!parsed) return [];
  if (!Array.isArray(parsed)) throw new Error(`Реестр ${file} должен быть YAML-списком.`);
  return parsed;
}

export function writeRegistry(entries) {
  const file = registryFile();
  mkdirSync(dirname(file), { recursive: true });
  writeFileSync(file, HEADER + "\n" + YAML.stringify(entries), "utf8");
}

// Add entries, skipping chat-ids already present. Returns count actually added.
export function addEntries(newOnes) {
  const entries = readRegistry();
  const have = new Set(entries.map((e) => String(e["chat-id"])));
  let added = 0;
  for (const e of newOnes) {
    if (have.has(String(e["chat-id"]))) continue;
    entries.push(e);
    have.add(String(e["chat-id"]));
    added += 1;
  }
  writeRegistry(entries);
  return added;
}

export function removeEntry(chatId) {
  const entries = readRegistry();
  const kept = entries.filter((e) => String(e["chat-id"]) !== String(chatId));
  writeRegistry(kept);
  return entries.length - kept.length;
}
