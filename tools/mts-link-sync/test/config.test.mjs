// Configuration diagnostics. These assert that a broken setup is *loud*: the whole
// point of --status is that "everything is fine" must never be printed over a setup
// that cannot produce data.
//
// config.mjs reads env at import time, so each case runs in a child process with its
// own environment rather than mutating this one.

import { test } from "node:test";
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdtempSync, writeFileSync, rmSync, utimesSync, mkdirSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const TOOL_DIR = dirname(dirname(fileURLToPath(import.meta.url)));

/**
 * Run describeConfig() in a child with a controlled environment.
 *
 * MTS_LINK_ENV_FILE is pointed at a nonexistent path so the developer's own `.env`
 * cannot leak in: without it these cases pass locally for the wrong reason and would
 * stop detecting the very misconfiguration they exist to catch.
 */
function describeWith(env) {
  const src = `
    import { describeConfig } from ${JSON.stringify(join(TOOL_DIR, "config.mjs"))};
    process.stdout.write(JSON.stringify(describeConfig()));
  `;
  const out = execFileSync(process.execPath, ["--input-type=module", "-e", src], {
    env: {
      PATH: process.env.PATH,
      HOME: process.env.HOME,
      MTS_LINK_ENV_FILE: join(tmpdir(), "mls-no-such-env-file"),
      ...env,
    },
    encoding: "utf8",
  });
  return JSON.parse(out);
}

function fixture() {
  const dir = mkdtempSync(join(tmpdir(), "mls-cfg-"));
  const auth = join(dir, "auth.json");
  const out = join(dir, "chats");
  mkdirSync(out);
  writeFileSync(auth, "{}");
  writeFileSync(join(out, "watched-chats.yaml"), "- chat-id: x\n  name: X\n");
  return { dir, auth, out };
}

test("a complete setup reports ok with no problems", () => {
  const f = fixture();
  try {
    const c = describeWith({ MTS_LINK_AUTH_FILE: f.auth, MTS_LINK_OUTPUT_DIR: f.out });
    assert.equal(c.ok, true);
    assert.deepEqual(c.problems, []);
  } finally { rmSync(f.dir, { recursive: true, force: true }); }
});

test("a missing output dir setting is a problem, not a silent default", () => {
  // The predecessor defaulted this and reported "registry empty" from the wrong
  // folder while exiting 0 — a morning brief would have reported a calm day.
  const f = fixture();
  try {
    const c = describeWith({ MTS_LINK_AUTH_FILE: f.auth });
    assert.equal(c.ok, false);
    assert.match(c.problems.join("\n"), /MTS_LINK_OUTPUT_DIR/);
  } finally { rmSync(f.dir, { recursive: true, force: true }); }
});

test("a nonexistent output dir is named explicitly", () => {
  const f = fixture();
  try {
    const c = describeWith({ MTS_LINK_AUTH_FILE: f.auth, MTS_LINK_OUTPUT_DIR: join(f.dir, "nope") });
    assert.equal(c.ok, false);
    assert.match(c.problems.join("\n"), /не существует/);
  } finally { rmSync(f.dir, { recursive: true, force: true }); }
});

test("a missing registry is a problem", () => {
  const f = fixture();
  try {
    rmSync(join(f.out, "watched-chats.yaml"));
    const c = describeWith({ MTS_LINK_AUTH_FILE: f.auth, MTS_LINK_OUTPUT_DIR: f.out });
    assert.equal(c.ok, false);
    assert.match(c.problems.join("\n"), /Реестр не найден/);
  } finally { rmSync(f.dir, { recursive: true, force: true }); }
});

test("a missing session is a problem", () => {
  const f = fixture();
  try {
    const c = describeWith({ MTS_LINK_AUTH_FILE: join(f.dir, "gone.json"), MTS_LINK_OUTPUT_DIR: f.out });
    assert.equal(c.ok, false);
    assert.match(c.problems.join("\n"), /Нет SSO-сессии/);
  } finally { rmSync(f.dir, { recursive: true, force: true }); }
});

test("a stale session warns without claiming to know it is dead", () => {
  // Server-side expiry is invisible on disk, so age can only warn. Staying silent
  // is what let --status answer "Всё на месте" about a 17-day-dead session.
  const f = fixture();
  try {
    const old = Date.now() / 1000 - 30 * 86400;
    utimesSync(f.auth, old, old);
    const c = describeWith({ MTS_LINK_AUTH_FILE: f.auth, MTS_LINK_OUTPUT_DIR: f.out });
    assert.equal(c.ok, true, "age alone must not block a run");
    assert.equal(c.authAgeDays >= 29, true);
    assert.match(c.warnings.join("\n"), /протухла/);
  } finally { rmSync(f.dir, { recursive: true, force: true }); }
});

test("a fresh session produces no staleness warning", () => {
  const f = fixture();
  try {
    const c = describeWith({ MTS_LINK_AUTH_FILE: f.auth, MTS_LINK_OUTPUT_DIR: f.out });
    assert.deepEqual(c.warnings, []);
  } finally { rmSync(f.dir, { recursive: true, force: true }); }
});
