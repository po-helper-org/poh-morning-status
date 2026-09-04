// One-time interactive login for MTS Link.
//
// MTS Link uses corporate SSO, which can't be automated. So we open a real visible
// browser, you log in by hand, and we persist the session to AUTH_FILE. harvest.mjs
// then reuses that session headlessly.
//
// Run:  npm run login
// Re-run whenever the saved session expires (the tool tells you when).

import { chromium } from "playwright";
import { createInterface } from "node:readline/promises";
import { stdin, stdout } from "node:process";
import { mkdirSync } from "node:fs";
import { dirname } from "node:path";
import { AUTH_FILE } from "./config.mjs";

const BASE_URL = process.env.MTS_LINK_LOGIN_URL || "https://my.mts-link.ru/";

const browser = await chromium.launch({ headless: false });
const context = await browser.newContext();
const page = await context.newPage();
await page.goto(BASE_URL, { waitUntil: "domcontentloaded" });

console.log("\n========================================================");
console.log("  Log in via corporate SSO in the opened window.");
console.log("  Get to the point where you see your account / chats.");
console.log("  Then come back here and press Enter.");
console.log("========================================================\n");

const rl = createInterface({ input: stdin, output: stdout });
await rl.question("Press Enter once you are logged in... ");
rl.close();

mkdirSync(dirname(AUTH_FILE), { recursive: true });
await context.storageState({ path: AUTH_FILE });
console.log(`\nSession saved to ${AUTH_FILE}`);
await browser.close();
