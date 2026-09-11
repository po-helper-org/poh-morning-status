// E2E кликов по слайду ретро: настоящий Chromium, файл открыт как file://.
// Запуск: node test/e2e.mjs   (после `python3 render.py test/sample.md -o test/out/demo.html`)
// Playwright и браузер берутся из ../mts-link-sync (там уже установлены).
import { createRequire } from 'node:module'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { dirname, resolve } from 'node:path'
import { existsSync } from 'node:fs'
import { execFileSync } from 'node:child_process'
import assert from 'node:assert/strict'

const here = dirname(fileURLToPath(import.meta.url))
const linkSync = resolve(here, '..', '..', 'mts-link-sync')
process.env.PLAYWRIGHT_BROWSERS_PATH ??= resolve(linkSync, '.browsers')
const { chromium } = createRequire(resolve(linkSync, 'package.json'))('playwright')

const out = resolve(here, 'out', 'demo.html')
execFileSync('python3', [resolve(here, '..', 'render.py'), resolve(here, 'sample.md'), '-o', out], { stdio: 'inherit' })
assert.ok(existsSync(out))
const url = pathToFileURL(out).href

const visible = (page, sel) => page.locator(sel).evaluate(el => getComputedStyle(el).display !== 'none')

async function scenario(browser, { javaScriptEnabled, viewport = { width: 1200, height: 800 } }) {
  const label = `${javaScriptEnabled ? 'JS включён' : 'JS выключен'}, ${viewport.width}×${viewport.height}`
  const ctx = await browser.newContext({ javaScriptEnabled, viewport })
  const page = await ctx.newPage()
  const errors = []
  page.on('pageerror', e => errors.push(String(e)))
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text()) })
  await page.goto(url)

  // 1. На титуле вкладки нет; на слайде ретро — есть.
  const edge = page.locator('label.edge')
  assert.equal(await edge.count(), 1, `${label}: одна вкладка`)
  assert.ok(await edge.evaluate(el => el.closest('.slide').id === 'retro'), `${label}: вкладка внутри слайда ретро`)
  await page.locator('#retro').scrollIntoViewIfNeeded()
  await edge.waitFor({ state: 'visible' })

  // 2. Клик по «Описать ретро» → заметка слева с черновиком; ✕ закрывает.
  assert.equal(await visible(page, '#retro-note-sheet'), false, `${label}: заметка скрыта до клика`)
  await edge.click()
  assert.equal(await visible(page, '#retro-note-sheet'), true, `${label}: заметка открылась`)
  const draft = await page.locator('#retro-note-sheet textarea').inputValue()
  assert.match(draft, /Хронология/, `${label}: черновик подставлен`)
  await page.locator('#retro-note-sheet label[for="retro-note"]').click()
  assert.equal(await visible(page, '#retro-note-sheet'), false, `${label}: заметка закрылась`)

  // 3. Клик по задаче → панель справа с заголовком, описанием и источником.
  const rowTask0 = page.locator('label.row[for="task-0"]')
  await rowTask0.click()
  const sheet0 = page.locator('#task-0 ~ aside.sheet')
  await sheet0.waitFor({ state: 'visible' })
  assert.match(await sheet0.locator('.title').innerText(), /смету за август/, `${label}: заголовок задачи`)
  assert.match(await sheet0.locator('.src').innerText(), /Источник: Backlog\.md: backlog\/tasks\/po-105/, `${label}: источник задачи`)
  assert.match(await sheet0.locator('.foot .id').innerText(), /PO-105/)

  // 4. Клик по другой задаче закрывает первую панель (radio — одна открытая).
  await page.locator('label.row[for="task-1"]').click()
  const sheet1 = page.locator('#task-1 ~ aside.sheet')
  await sheet1.waitFor({ state: 'visible' })
  assert.equal(await visible(page, '#task-0 ~ aside.sheet'), false, `${label}: первая панель закрыта`)
  assert.match(await sheet1.locator('.foot .id').innerText(), /без id/, `${label}: задача без id`)
  assert.match(await sheet1.locator('.src').innerText(), /createdAt 2026-09-10/)

  // 5. ✕ закрывает; клик по событию открывает панель события с источником.
  await sheet1.locator('.foot label[for="sheet-none"]').click()
  assert.equal(await visible(page, '#task-1 ~ aside.sheet'), false, `${label}: панель закрыта крестиком`)
  await page.locator('label.row[for="event-0"]').click()
  const ev = page.locator('#event-0 ~ aside.sheet')
  await ev.waitFor({ state: 'visible' })
  assert.match(await ev.locator('.title').innerText(), /VK: переезд виджета/)
  assert.match(await ev.locator('.src').innerText(), /календарь MTS Exchange/)
  await ev.locator('.head label[for="sheet-none"]').click()
  assert.equal(await visible(page, '#event-0 ~ aside.sheet'), false)

  // 6. Заметка правится; при JS — сохраняется в localStorage и переживает перезагрузку.
  await edge.click()
  const ta = page.locator('#retro-note-sheet textarea')
  await ta.fill('моя заметка')
  if (javaScriptEnabled) {
    await page.reload()
    await page.locator('#retro').scrollIntoViewIfNeeded()
    await page.locator('label.edge').click()
    assert.equal(await page.locator('#retro-note-sheet textarea').inputValue(), 'моя заметка', 'заметка пережила перезагрузку')
  }

  assert.deepEqual(errors, [], `${label}: ошибок в консоли нет`)
  await ctx.close()
  console.log(`ok — ${label}`)
}

async function emptyData(browser) {
  // 7. Пустые данные: «Данных не найдено» в обоих виджетах и в заметке, ничего лишнего.
  const empty = resolve(here, 'out', 'empty.html')
  const emptyJson = resolve(here, 'out', 'empty.retro.json')
  const emptyMd = resolve(here, 'out', 'empty.md')
  const { writeFileSync, readFileSync } = await import('node:fs')
  writeFileSync(emptyMd, readFileSync(resolve(here, 'sample.md')))
  writeFileSync(emptyJson, JSON.stringify({ date: '2026-09-10', tasks: [], activity: [] }))
  execFileSync('python3', [resolve(here, '..', 'render.py'), emptyMd, '-o', empty], { stdio: 'inherit' })
  const ctx = await browser.newContext({ javaScriptEnabled: false })
  const page = await ctx.newPage()
  await page.goto(pathToFileURL(empty).href)
  assert.equal(await page.locator('.widget .empty').count(), 2)
  assert.equal(await page.locator('label.row').count(), 0)
  await page.locator('label.edge').click()
  assert.equal(await page.locator('#retro-note-sheet textarea').inputValue(), '')
  assert.equal(await page.locator('#retro-note-sheet textarea').getAttribute('placeholder'), 'Данных не найдено')
  await ctx.close()
  console.log('ok — пустые данные')
}

const browser = await chromium.launch()
try {
  await scenario(browser, { javaScriptEnabled: true })
  await scenario(browser, { javaScriptEnabled: false })
  await scenario(browser, { javaScriptEnabled: false, viewport: { width: 700, height: 900 } })
  await emptyData(browser)
} finally {
  await browser.close()
}
