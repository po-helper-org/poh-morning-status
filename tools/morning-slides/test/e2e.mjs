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

let localStorageGet
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

  const noteText = sel => page.locator(sel).evaluate(el => el.innerText)

  // 2. «Описать ретро» → заметка слева, сразу редактируемая: название + 4 раздела + чеклист.
  const drawer = page.locator('#retro-note-sheet')
  assert.equal(await visible(page, '#retro-note-sheet'), false, `${label}: заметка скрыта до клика`)
  await edge.click()
  assert.equal(await visible(page, '#retro-note-sheet'), true, `${label}: заметка открылась`)
  const body = '#retro-note-sheet .body'
  assert.match(await noteText(body), /Ретро 2026-09-10/, `${label}: название — первая строка`)
  for (const h of ['Что было сделано', 'Как это влияет на цели спринта', 'Как это влияет на цели квартала', 'Что не получилось сделать']) {
    assert.match(await noteText(body), new RegExp(h), `${label}: раздел «${h}»`)
  }
  if (javaScriptEnabled) {
    assert.equal(await drawer.locator('.editor[contenteditable="true"]').count(), 1, 'редактор смонтирован, режимов нет')
    assert.equal(await drawer.locator('.editor [data-block="title"]').innerText(), 'Ретро 2026-09-10')
    assert.equal(await drawer.locator('.editor [data-block="todo"]').count(), 3)
    assert.equal(await drawer.locator('label.lbl-edit, .btn').count(), 0, 'кнопок режима нет')
  } else {
    assert.equal(await drawer.locator('.note-view li.todo input').count(), 3, `${label}: чеклист отрисован`)
  }
  await drawer.locator('.head label[for="retro-note"]').click()
  assert.equal(await visible(page, '#retro-note-sheet'), false, `${label}: заметка закрылась`)

  // 3. Клик по задаче → заметка «что сделано»; «Источники» — раздел заметки, отдельного блока нет.
  await page.locator('label.row[for="task-0"]').click()
  const sheet0 = page.locator('#task-0 ~ aside.sheet')
  await sheet0.waitFor({ state: 'visible' })
  const t0 = await noteText('#task-0 ~ aside.sheet .body')
  assert.match(t0, /^Ишманов \+ Бордюг: отправить смету за август/, `${label}: название первой строкой`)
  assert.match(t0, /Сделано:.*отправлена Бордюгу/s, `${label}: текст заметки`)
  assert.match(t0, /Источники[\s\S]*backlog\/tasks\/po-105/, `${label}: источники внутри заметки`)
  assert.equal(await sheet0.locator('.chip, .flag, div.src, .lbl-edit').count(), 0, `${label}: лишнего хрома нет`)

  if (javaScriptEnabled) {
    const ed = sheet0.locator('.editor')
    // 4. Чеклист: клик по флажку меняет исходник (- [ ] → - [x]) и сохраняется.
    const todos = ed.locator('[data-block="todo"]')
    assert.equal(await todos.count(), 3)
    assert.equal(await todos.nth(2).getAttribute('data-done'), null)
    await todos.nth(2).locator('.box').click()
    assert.equal(await todos.nth(2).getAttribute('data-done'), '', 'флажок отмечен')
    assert.match(localStorageGet = await page.evaluate(() => localStorage.getItem('morning-note-2026-09-10-task-0')), /- \[x\] получить подтверждение/, 'исходник и localStorage обновлены')

    // 5. Правка названия сразу в заметке: строка виджета обновляется.
    const title = ed.locator('[data-block="title"]')
    await title.click()
    await page.keyboard.press('End')
    await page.keyboard.type(' — ок')
    assert.match(await page.locator('label.row[for="task-0"] .t').innerText(), /смету за август — ок$/, 'название в строке виджета обновилось')

    // 6. «/» в пустом блоке открывает меню блоков с 9 типами; выбор «Пункт с галочкой» делает todo.
    const last = ed.locator('> *').last()
    await last.click()
    await page.keyboard.press('End')
    await page.keyboard.press('Enter')
    await page.keyboard.type('/')
    const menu = sheet0.locator('.menu')
    await menu.waitFor({ state: 'visible' })
    assert.deepEqual(await menu.locator('button').allInnerTexts().then(a => a.map(t => t.replace(/^\S+\s+/, ''))),
      ['Текст', 'Заголовок 1', 'Заголовок 2', 'Заголовок 3', 'Маркированный список', 'Нумерованный список', 'Пункт с галочкой', 'Цитата', 'Разделитель'], 'меню блоков')
    await menu.locator('button', { hasText: 'Пункт с галочкой' }).click()
    await page.keyboard.type('новый пункт')
    assert.equal(await menu.count(), 0, 'меню закрылось')
    assert.match(await page.evaluate(() => localStorage.getItem('morning-note-2026-09-10-task-0')), /- \[ \] новый пункт/, 'todo сохранён в markdown')

    // 7. Набор «# » превращает строку в заголовок, Enter в пустом пункте выходит из списка.
    await page.keyboard.press('Enter')
    await page.keyboard.press('Enter')
    await page.keyboard.type('## Итог')
    assert.match(await page.evaluate(() => localStorage.getItem('morning-note-2026-09-10-task-0')), /\n## Итог$/, 'заголовок через «## »')
  }

  // 8. Другая задача закрывает первую; ✕ закрывает; событие — заметка с итогом и источниками.
  await page.locator('label.row[for="task-1"]').click()
  const sheet1 = page.locator('#task-1 ~ aside.sheet')
  await sheet1.waitFor({ state: 'visible' })
  assert.equal(await visible(page, '#task-0 ~ aside.sheet'), false, `${label}: первая панель закрыта`)
  assert.match(await noteText('#task-1 ~ aside.sheet .body'), /^Заведены 5 инициатив/, `${label}: задача без id`)
  await sheet1.locator('.head label[for="sheet-none"]').click()
  assert.equal(await visible(page, '#task-1 ~ aside.sheet'), false, `${label}: панель закрыта крестиком`)
  await page.locator('label.row[for="event-0"]').click()
  const ev = page.locator('#event-0 ~ aside.sheet')
  await ev.waitFor({ state: 'visible' })
  assert.match(await noteText('#event-0 ~ aside.sheet .body'), /^VK: переезд виджета[\s\S]*Итог[\s\S]*Источники[\s\S]*MTS Exchange/, `${label}: заметка события`)
  await ev.locator('.head label[for="sheet-none"]').click()

  // 9. С JS правки переживают перезагрузку.
  if (javaScriptEnabled) {
    await page.reload()
    await page.locator('#retro').scrollIntoViewIfNeeded()
    assert.match(await page.locator('label.row[for="task-0"] .t').innerText(), /— ок$/, 'название пережило перезагрузку')
    await page.locator('label.row[for="task-0"]').click()
    const t = await noteText('#task-0 ~ aside.sheet .body')
    assert.match(t, /новый пункт/); assert.match(t, /Итог/)
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
  const heads = await page.locator('#retro-note-sheet .note-view h2').allInnerTexts()
  assert.equal(heads.length, 4, 'заготовка ретро есть и без данных')
  assert.equal(await page.locator('#retro-note-sheet .note-view li').count(), 0, 'ничего не придумано')
  assert.equal(await page.locator('#retro-note-sheet .note-view h1.title').innerText(), 'Ретро 2026-09-10')
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
