// One-time interactive login for MTS Link.
//
// MTS Link uses corporate SSO, which cannot be automated. A real visible browser opens,
// the PO logs in by hand, and the resulting session is persisted to AUTH_FILE.
// harvest.mjs then reuses that session headlessly.
//
// Run:  npm run login
// Re-run whenever the saved session expires (the tool says so).
//
// WHY THIS IS MORE THAN "wait for Enter, then save":
// The previous version saved whatever the context held the moment Enter arrived and
// printed "Session saved" unconditionally. A login that had not actually completed, a
// window closed by hand, or an Enter that reached the wrong process all produced the
// same cheerful line over an unusable file — and the failure only surfaced later, as a
// network error during a pull. Saving a session is exactly the step that must not lie
// about itself, so this version verifies before it writes and refuses to write junk.

// config.mjs is imported FIRST on purpose — same reason as in harvest.mjs:
// Playwright reads PLAYWRIGHT_BROWSERS_PATH at module evaluation, and ESM hoists
// imports, so `.env` must be loaded before "playwright" is evaluated.
import { AUTH_FILE } from "./config.mjs";
import { chromium } from "playwright";
import { createInterface } from "node:readline/promises";
import { stdin, stdout } from "node:process";
import { mkdirSync, existsSync, copyFileSync, readFileSync } from "node:fs";
import { dirname } from "node:path";

const BASE_URL = process.env.MTS_LINK_LOGIN_URL || "https://my.mts-link.ru/";
const CHATS_URL = process.env.MTS_LINK_CHATS_URL || "https://my.mts-link.ru/chats/";

/** A saved state with no cookies cannot authenticate anything. */
function countCookies(path) {
  try {
    return (JSON.parse(readFileSync(path, "utf8")).cookies || []).length;
  } catch {
    return 0;
  }
}

const browser = await chromium.launch({ headless: false });
const context = await browser.newContext();
const page = await context.newPage();
await page.goto(BASE_URL, { waitUntil: "domcontentloaded" });

console.log("\n========================================================");
console.log("  Log in via corporate SSO in the opened window.");
console.log("  Get to the point where you see your account / chats.");
console.log("  Then come back here and press Enter.");
console.log("  Keep the browser window OPEN — closing it discards the session.");
console.log("========================================================\n");

const rl = createInterface({ input: stdin, output: stdout });
await rl.question("Press Enter once you are logged in... ");
rl.close();

// The browser must still be alive: storageState reads from the live context, so a
// window closed by hand leaves nothing to save.
if (!browser.isConnected() || page.isClosed()) {
  console.error("\nБраузер закрыт — сохранять нечего. Запусти npm run login заново и не закрывай окно.");
  process.exit(1);
}

// Verify the login actually took, rather than trusting the keypress. Navigating to the
// chats page is the same check harvest.mjs performs, so a session accepted here is one
// that will work during a pull.
console.log("Проверяю сессию…");
let verified = false;
try {
  await page.goto(CHATS_URL, { waitUntil: "domcontentloaded", timeout: 60000 });
  await page.waitForTimeout(2000);
  verified = !/login|auth|sso|signin/i.test(page.url());
} catch (e) {
  console.error(`Не удалось открыть ${CHATS_URL}: ${e.message.split("\n")[0]}`);
}

if (!verified) {
  console.error("\nВход не подтверждён: страница чатов всё ещё редиректит на логин.");
  console.error("Сессия НЕ сохранена — старый файл не тронут. Повтори npm run login и дойди до списка чатов.");
  await browser.close();
  process.exit(1);
}

mkdirSync(dirname(AUTH_FILE), { recursive: true });
// Keep one rollback copy: overwriting a working session with a broken one would cost a
// second SSO round trip, and the previous file is the only spare.
if (existsSync(AUTH_FILE)) copyFileSync(AUTH_FILE, `${AUTH_FILE}.bak`);
await context.storageState({ path: AUTH_FILE });
await browser.close();

const cookies = countCookies(AUTH_FILE);
if (cookies === 0) {
  console.error(`\nСохранённая сессия пуста (0 cookies): ${AUTH_FILE}`);
  console.error("Так она не сработает. Повтори npm run login.");
  process.exit(1);
}

console.log(`\nСессия сохранена: ${AUTH_FILE} (${cookies} cookies)`);
console.log("Проверь: npm run status");
