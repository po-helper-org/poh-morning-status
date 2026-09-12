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
{
  // сайдкары ищутся рядом с markdown по имени, поэтому собираем комплект в out/
  const { copyFileSync, mkdirSync } = await import('node:fs')
  mkdirSync(resolve(here, 'out'), { recursive: true })
  for (const f of ['sample.md', 'sample.retro.json', 'sample.today.json', 'sample.risks.json', 'sample.teams.json']) copyFileSync(resolve(here, f), resolve(here, 'out', f.replace('sample', 'demo')))
}
execFileSync('python3', [resolve(here, '..', 'render.py'), resolve(here, 'out', 'demo.md'), '-o', out], { stdio: 'inherit' })
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
  const edge = page.locator('label.edge[for="retro-note"]')
  assert.equal(await edge.count(), 1, `${label}: одна вкладка ретро`)
  assert.ok(await edge.evaluate(el => el.closest('.slide').id === 'retro'), `${label}: вкладка внутри слайда ретро`)
  assert.equal(await page.locator('h1').filter({ hasText: /^Утро/ }).count(), 0, `${label}: титульного экрана нет`)
  assert.equal(await page.locator('.slide[data-kind]:not(.tail)').count(), 6, `${label}: 6 разделов с цветной полосой`)
  assert.equal(await page.locator('#retro .kicker').innerText(), 'РЕТРО')
  assert.notEqual(await page.locator('#retro').evaluate(el => getComputedStyle(el).borderLeftColor), await page.locator('#today').evaluate(el => getComputedStyle(el).borderLeftColor), `${label}: разделы отличаются цветом`)
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
    assert.equal(await drawer.locator('label.lbl-edit, .btn:not(.close)').count(), 0, 'кнопок режима нет')
  } else {
    assert.equal(await drawer.locator('.note-view li.todo input').count(), 3, `${label}: чеклист отрисован`)
    assert.equal(await drawer.locator('.note-view[contenteditable="true"]').count(), 1, `${label}: без скриптов текст всё равно правится`)
    await drawer.locator('.note-view h1').click()
    await page.keyboard.press('End')
    await page.keyboard.type(' (правка)')
    assert.match(await drawer.locator('.note-view h1').innerText(), /\(правка\)$/, `${label}: набор без JS`)
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
  assert.equal(await sheet0.locator('div.src, .lbl-edit').count(), 0, `${label}: отдельного блока источника и кнопок режима нет`)
  const closeBtn = sheet0.locator('.foot label.btn.close')
  assert.equal(await closeBtn.innerText(), 'Закрыть', `${label}: «Закрыть» внизу панели`)
  const cb = await closeBtn.boundingBox(); const sb0 = await sheet0.boundingBox()
  assert.ok(cb.x + cb.width > sb0.x + sb0.width - 40 && cb.y > sb0.y + sb0.height - 80, `${label}: «Закрыть» в правом нижнем углу`)
  assert.equal(await sheet0.locator('.head .check[data-done]').count(), 1, `${label}: чек в шапке`)
  assert.match(await sheet0.locator('.head .chip').first().innerText(), /Вчера/, `${label}: дата в шапке`)
  assert.equal(await sheet0.locator('.head .flag[data-p="high"]').count(), 1, `${label}: флаг приоритета`)
  if (!javaScriptEnabled) assert.match(await page.locator('noscript').innerText().catch(() => ''), /Скрипты отключены|^$/)

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

  // 8. Панель поверх экрана: слайд не ужат, клик по подложке закрывает; затем другая задача; ✕; событие.
  const padOpen = await page.locator('#retro').evaluate(el => getComputedStyle(el).paddingRight)
  assert.ok(['64px', '20px', '14px'].includes(padOpen), `${label}: слайд под панелью не ужат (${padOpen})`)
  assert.equal(await page.locator('#task-0 ~ .scrim').evaluate(el => getComputedStyle(el).display), 'block', `${label}: подложка показана`)
  await page.mouse.click(30, 760)   // по подложке, мимо панели
  assert.equal(await visible(page, '#task-0 ~ aside.sheet'), false, `${label}: клик по подложке закрыл панель`)
  await page.locator('label.row[for="task-1"]').click()
  const sheet1 = page.locator('#task-1 ~ aside.sheet')
  await sheet1.waitFor({ state: 'visible' })
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

  // ——— «Комментарии для LLM» в конце страницы ———
  await page.locator('#llm').scrollIntoViewIfNeeded()
  const llmBtn = page.locator('label.edge[for="llm-note"]')
  assert.equal(await llmBtn.textContent(), 'Комментарии для LLM')
  await llmBtn.click()
  const llm = page.locator('#llm-sheet')
  await llm.waitFor({ state: 'visible' })
  if (javaScriptEnabled) {
    const prompt = await llm.locator('#llm-prompt').inputValue()
    assert.match(prompt, /Скорректируй утренний отчёт от 2026-09-11/, 'шапка промта')
    assert.match(prompt, /## Ретро 2026-09-10 · Tasks · «Ишманов \+ Бордюг: отправить смету за август — ок»/, 'правка привязана к разделу и заметке')
    assert.match(prompt, /\+ - \[x\] получить подтверждение/, 'отмеченный чеклист попал как правка')
    assert.match(prompt, /\+ - \[ \] новый пункт/, 'добавленный пункт попал')
    assert.match(prompt, /\+ ## Итог/, 'добавленный заголовок попал')
    assert.match(await llm.locator('#llm-status').innerText(), /Правок: 1\./, 'счётчик правок')
    await llm.locator('#llm-copy').click()
    await page.waitForFunction(() => /скопировано|Cmd\+C/.test(document.getElementById('llm-copied').textContent), null, { timeout: 3000 })
  } else {
    assert.match(await llm.locator('#llm-status').innerText(), /Без скриптов правки не отслеживаются/)
  }
  await llm.locator('.foot label.btn.close').click()
  assert.equal(await visible(page, '#llm-sheet'), false, `${label}: «Закрыть» внизу закрывает экран промта`)

  // ——— Слайд «Сегодня» ———
  await page.locator('#today').scrollIntoViewIfNeeded()
  const plan = page.locator('label.edge[for="plan-note"]')
  await plan.waitFor({ state: 'visible' })
  assert.equal(await plan.textContent(), 'План на сегодня', `${label}: зелёная вкладка`)
  assert.equal(await plan.evaluate(el => getComputedStyle(el).backgroundColor), 'rgb(31, 157, 85)', `${label}: вкладка зелёная`)
  assert.equal(await page.locator('#today .widgets h4 span:first-child').allTextContents().then(a => a.join('|')), 'Мои задачи|Договорённости|Ключевые встречи')
  assert.equal(await page.locator('#today').innerText().then(t => /Созвоны/.test(t)), false, `${label}: созвонов на слайде нет`)

  // 10. «План на сегодня» → заметка с заготовкой; сразу редактируется.
  await plan.click()
  assert.equal(await visible(page, '#plan-note-sheet'), true)
  assert.match(await noteText('#plan-note-sheet .body'), /^План на сегодня 2026-09-11[\s\S]*Задачи[\s\S]*Созвоны[\s\S]*Договорённости[\s\S]*Риски/)
  const editable = page.locator('#plan-note-sheet .body [contenteditable="true"]')
  assert.equal(await editable.count(), 1, `${label}: область правки есть сразу`)
  await editable.click()
  await page.keyboard.press('End')
  await page.keyboard.type(' — допечатано')
  assert.match(await noteText('#plan-note-sheet .body'), /допечатано/, `${label}: текст правится сразу после открытия`)
  await page.locator('#plan-note-sheet .head label[for="plan-note"]').click()
  assert.equal(await visible(page, '#plan-note-sheet'), false)

  // 11. «Календарь» → панель с созвонами дня (2), время/тема/участники/повестка.
  await page.locator('label.edge[for="today-calendar"]').click()
  assert.equal(await visible(page, '#today-calendar-sheet'), true)
  assert.equal(await page.locator('#today-calendar-sheet .ev').count(), 2)
  assert.match(await page.locator('#today-calendar-sheet .ev').first().innerText(), /11:00–11:30[\s\S]*VK: бюджет Q4[\s\S]*Юмшанов[\s\S]*переезд виджета/)
  await page.locator('#today-calendar-sheet .head label[for="today-calendar"]').click()
  assert.equal(await visible(page, '#today-calendar-sheet'), false)

  // 12. Задача дня → заметка с шапкой (приоритет, срок), сразу редактируемая.
  await page.locator('label.row[for="todo-0"]').click()
  const td = page.locator('#todo-0 ~ aside.sheet')
  await td.waitFor({ state: 'visible' })
  assert.match(await noteText('#todo-0 ~ aside.sheet .body'), /^Сетевая доступность для GDS[\s\S]*Источники/)
  assert.equal(await td.locator('.head .flag[data-p="high"]').count(), 1)
  assert.match(await td.locator('.head .chip').first().innerText(), /Вчера/)
  assert.equal(await td.locator('.body [contenteditable="true"]').count(), 1, `${label}: заметка задачи редактируется сразу`)
  await td.locator('.head label[for="sheet-none"]').click()
  await page.locator('label.row[for="ctl-0"]').click()
  assert.match(await noteText('#ctl-0 ~ aside.sheet .body'), /^Подправить для Музыки баг/)
  await page.locator('#ctl-0 ~ aside.sheet .head label[for="sheet-none"]').click()

  // 13a. Ключевые встречи на главном экране: только не-ритуалы, с повесткой; клик — заметка.
  await page.locator('#today').scrollIntoViewIfNeeded()
  assert.equal(await page.locator('label.row[for^="meet-"]').count(), 1, `${label}: одна ключевая встреча (дейлик не показан)`)
  assert.match(await page.locator('label.row[for="meet-0"]').innerText(), /11:00–11:30[\s\S]*VK: бюджет Q4[\s\S]*Бюджет под переезд виджета/)
  await page.locator('label.row[for="meet-0"]').click()
  assert.match(await noteText('#meet-0 ~ aside.sheet .body'), /^VK: бюджет Q4[\s\S]*Повестка[\s\S]*Что получить[\s\S]*Источники/)
  await page.locator('#meet-0 ~ aside.sheet .head label[for="sheet-none"]').click()

  // ——— Слайд «Риски» ———
  await page.locator('#risks').scrollIntoViewIfNeeded()
  const rtab = page.locator('label.edge[for="risks-note"]')
  await rtab.waitFor({ state: 'visible' })
  assert.equal(await rtab.textContent(), 'Актуализация рисков')
  assert.equal(await page.locator('#risks .cols-head span').allTextContents().then(a => a.join('|')), 'OKR|Название|Последствия')
  assert.equal(await page.locator('#risks label.row').count(), 3)
  await page.locator('label.row[for="risk-0"]').click()
  assert.match(await noteText('#risk-0 ~ aside.sheet .body'), /^Вебхук заказов не работает[\s\S]*Описание[\s\S]*Последствия[\s\S]*Владелец[\s\S]*Источники/, `${label}: детальное описание риска`)
  await page.locator('#risk-0 ~ aside.sheet .head label[for="sheet-none"]').click()
  await rtab.click()
  assert.match(await noteText('#risks-note-sheet .body'), /^Актуализация рисков 2026-09-11[\s\S]*Новые[\s\S]*Изменились[\s\S]*Сняты[\s\S]*Нужно решение/)
  assert.equal(await page.locator('#risks-note-sheet .body [contenteditable="true"]').count(), 1)
  await page.locator('#risks-note-sheet .head label[for="risks-note"]').click()

  // ——— Слайды команд: один слайд — одна команда ———
  assert.equal(await page.locator('.slide[data-team]').count(), 2, `${label}: два слайда команд`)
  await page.locator('#team-0').scrollIntoViewIfNeeded()
  assert.equal(await page.locator('#team-0 > header h2').textContent(), 'Команда Live')
  assert.equal(await page.locator('#team-0 .cols-head span').allTextContents().then(a => a.join('|')), 'История|Что сделано|Что осталось|Следующий шаг')
  assert.match(await page.locator('label.row[for="story-0-0"]').innerText(), /PO-133[\s\S]*раскатано на 50%[\s\S]*мониторинг 3 дня[\s\S]*2026-09-15 · проверить долю ошибок < 0.5% в Grafana · Юмшанов/)
  await page.locator('label.row[for="story-0-0"]').click()
  assert.match(await noteText('#story-0-0 ~ aside.sheet .body'), /^PO-133 Переключение 50\/50[\s\S]*Что сделано[\s\S]*Что осталось[\s\S]*Блокаторы[\s\S]*Следующий шаг[\s\S]*Пульс спринта[\s\S]*Источники/, `${label}: заметка истории за спринт`)
  await page.locator('#story-0-0 ~ aside.sheet .head label[for="sheet-none"]').click()
  await page.locator('label.edge[for="team-0-comment"]').click()
  const cm = await noteText('#team-0-comment-sheet .body')
  assert.match(cm, /^Комментарий по команде Live[\s\S]*PO-133[\s\S]*Что уже сделано: раскатано[\s\S]*Что осталось: мониторинг[\s\S]*Какие есть блокаторы: нет[\s\S]*Какой следующий шаг: 2026-09-15[\s\S]*PO-134[\s\S]*ждём спецификацию TicketsCloud/, `${label}: сводка по историям по умолчанию`)
  await page.locator('#team-0-comment-sheet .head label[for="team-0-comment"]').click()
  await page.locator('label.edge[for="team-0-agree"]').click()
  const ag = page.locator('#team-0-agree-sheet')
  assert.match(await noteText('#team-0-agree-sheet .body'), /^Договорённости с командой Live[\s\S]*схема БД Live\.Процессинг · от Юмшанов · 2026-09-15 · для Ишманов[\s\S]*доступ к логам MRS/)
  const boxes = ag.locator('.body input[type="checkbox"], .body .box')
  assert.equal(await boxes.count(), 2, `${label}: реестр — чеклист`)
  await page.locator('#team-0-agree-sheet .head label[for="team-0-agree"]').click()
  await page.locator('#team-1').scrollIntoViewIfNeeded()
  assert.equal(await page.locator('#team-1 > header h2').textContent(), 'Команда GDS')
  assert.equal(await page.locator('#team-1 label.row').count(), 1)

  // 13. Тема едина: слайды тёмные, как панели.
  const bg = await page.locator('.slide').first().evaluate(el => getComputedStyle(el).backgroundColor)
  assert.equal(bg, 'rgb(20, 21, 24)', `${label}: слайды тёмные`)

  assert.deepEqual(errors, [], `${label}: ошибок в консоли нет`)
  await ctx.close()
  console.log(`ok — ${label}`)
}

async function mobile(browser, { javaScriptEnabled, viewport }) {
  // Узкий экран (панель dsh / телефон): лента, навигация чипами, карточки в столбик, панели на весь экран.
  const label = `mobile ${viewport.width}×${viewport.height}, ${javaScriptEnabled ? 'JS включён' : 'JS выключен'}`
  const ctx = await browser.newContext({ javaScriptEnabled, viewport })
  const page = await ctx.newPage()
  const errors = []
  page.on('pageerror', e => errors.push(String(e)))
  await page.goto(url)

  // 1. Ничего не уезжает за правый край; слайды — лента без snap; навигация сверху видна.
  const overflow = await page.evaluate(() => { const d = document.querySelector('.deck'); return d.scrollWidth - d.clientWidth })
  assert.equal(overflow, 0, `${label}: нет горизонтальной прокрутки`)
  assert.equal(await page.locator('.deck').evaluate(el => getComputedStyle(el).scrollSnapType), 'none', `${label}: без scroll-snap`)
  const nav = page.locator('nav.mnav')
  assert.equal(await nav.evaluate(el => getComputedStyle(el).display), 'flex', `${label}: навигация чипами`)
  assert.equal(await nav.locator('a').allTextContents().then(a => a.join('|')), '2026-09-11|Ретро|Сегодня|Риски|Live|GDS|Решения')
  assert.equal(await nav.evaluate(el => getComputedStyle(el).position), 'sticky')
  assert.equal(await page.locator('h1').filter({ hasText: /^Утро/ }).count(), 0, `${label}: титула нет`)

  // 2. Слайд «Сегодня» — виджеты в один столбец, вкладки стали кнопками; разделы — отдельные карточки с полосой.
  await page.locator('#today').scrollIntoViewIfNeeded()
  assert.equal(await page.locator('#today').evaluate(el => getComputedStyle(el).borderRadius), '10px', `${label}: раздел — карточка`)
  const cols = await page.locator('#today .widgets').evaluate(el => getComputedStyle(el).gridTemplateColumns.split(' ').length)
  assert.equal(cols, 1, `${label}: один столбец`)
  const pill = page.locator('label.edge[for="plan-note"]')
  const box = await pill.boundingBox()
  assert.ok(box.width > box.height, `${label}: вкладка стала горизонтальной кнопкой`)
  assert.equal(await pill.evaluate(el => getComputedStyle(el).writingMode), 'horizontal-tb')

  // 3. Строки не ниже 44px, заголовок переносится, а не обрезается.
  const rows = page.locator('#today label.row')
  for (let i = 0; i < await rows.count(); i++) {
    const b = await rows.nth(i).boundingBox()
    assert.ok(b.height >= 44, `${label}: строка ${i} высотой ${b.height}`)
  }

  // 4. Таблица историй — карточки с подписями полей; таблица md — карточки с data-label.
  await page.locator('#team-0').scrollIntoViewIfNeeded()
  assert.equal(await page.locator('#team-0 .cols-head').evaluate(el => getComputedStyle(el).display), 'none')
  assert.equal(await page.locator('label.row[for="story-0-0"]').evaluate(el => getComputedStyle(el).display), 'block')
  assert.match(await page.locator('label.row[for="story-0-0"] .c').first().evaluate(el => getComputedStyle(el, '::before').content), /Что сделано/)
  const decisionsId = await nav.locator('a', { hasText: 'Решения' }).getAttribute('href')   // раздел из markdown
  await page.locator(decisionsId).scrollIntoViewIfNeeded()
  assert.equal(await page.locator(`${decisionsId} ul.decisions li`).count() > 0, true)

  // 5. Панель — на весь экран, шапка прилипает, подложки нет; ✕ закрывает.
  await page.locator('#today').scrollIntoViewIfNeeded()
  await page.locator('label.row[for="todo-0"]').click()
  const sheet = page.locator('#todo-0 ~ aside.sheet')
  await sheet.waitFor({ state: 'visible' })
  const sb = await sheet.boundingBox()
  assert.ok(Math.abs(sb.width - viewport.width) <= 1, `${label}: панель во всю ширину (${sb.width})`)
  assert.equal(await sheet.locator('.head').evaluate(el => getComputedStyle(el).position), 'sticky')
  assert.equal(await page.locator('#todo-0 ~ .scrim').evaluate(el => getComputedStyle(el).display), 'none')
  if (javaScriptEnabled) {
    // 6. Редактор и «/»-меню работают в узком экране.
    const ed = sheet.locator('.editor')
    await ed.locator('> *').last().click()
    await page.keyboard.press('End'); await page.keyboard.press('Enter'); await page.keyboard.type('/')
    const menu = sheet.locator('.menu')
    await menu.waitFor({ state: 'visible' })
    const mb = await menu.boundingBox()
    assert.ok(mb.x + mb.width <= viewport.width, `${label}: меню не вылезает за экран`)
    await menu.locator('button', { hasText: 'Пункт с галочкой' }).click()
    await page.keyboard.type('мобильный пункт')
    assert.match(await page.evaluate(() => localStorage.getItem('morning-note-2026-09-11-todo-0')), /- \[ \] мобильный пункт/)
  }
  await sheet.locator('.head label[for="sheet-none"]').click()
  assert.equal(await visible(page, '#todo-0 ~ aside.sheet'), false)

  // 7. Навигация: чип ведёт к разделу.
  await nav.locator('a', { hasText: 'Риски' }).click()
  await page.waitForTimeout(300)
  const risksTop = await page.locator('#risks').evaluate(el => el.getBoundingClientRect().top)
  assert.ok(risksTop < 120 && risksTop > -50, `${label}: переход к разделу (top=${risksTop})`)

  assert.deepEqual(errors, [], `${label}: ошибок нет`)
  await ctx.close()
  console.log(`ok — ${label}`)
}

async function emptyData(browser) {
  // 7. Пустые данные: «Данных не найдено» в обоих виджетах и в заметке, ничего лишнего.
  const empty = resolve(here, 'out', 'empty.html')
  const emptyMd = resolve(here, 'out', 'empty.md')
  const { writeFileSync, readFileSync } = await import('node:fs')
  writeFileSync(emptyMd, readFileSync(resolve(here, 'sample.md')))
  writeFileSync(resolve(here, 'out', 'empty.retro.json'), JSON.stringify({ date: '2026-09-10', tasks: [], activity: [] }))
  writeFileSync(resolve(here, 'out', 'empty.today.json'), JSON.stringify({ date: '2026-09-11', tasks: [], controls: [], calendar: [] }))
  writeFileSync(resolve(here, 'out', 'empty.risks.json'), JSON.stringify({ date: '2026-09-11', risks: [] }))
  writeFileSync(resolve(here, 'out', 'empty.teams.json'), JSON.stringify({ date: '2026-09-11', teams: [] }))
  execFileSync('python3', [resolve(here, '..', 'render.py'), emptyMd, '-o', empty], { stdio: 'inherit' })
  const ctx = await browser.newContext({ javaScriptEnabled: false })
  const page = await ctx.newPage()
  await page.goto(pathToFileURL(empty).href)
  assert.equal(await page.locator('#retro .widget .empty').count(), 2)
  assert.equal(await page.locator('label.row').count(), 0)
  await page.locator('label.edge[for="retro-note"]').click()
  const heads = await page.locator('#retro-note-sheet .note-view h2').allInnerTexts()
  assert.equal(heads.length, 4, 'заготовка ретро есть и без данных')
  assert.equal(await page.locator('#retro-note-sheet .note-view li').count(), 0, 'ничего не придумано')
  assert.equal(await page.locator('#retro-note-sheet .note-view h1.title').innerText(), 'Ретро 2026-09-10')
  await page.locator('#retro-note-sheet .head label[for="retro-note"]').click()
  await page.locator('#today').scrollIntoViewIfNeeded()
  assert.equal(await page.locator('#today .widget .empty').count(), 3)
  await page.locator('label.edge[for="today-calendar"]').click()
  assert.equal(await page.locator('#today-calendar-sheet .cal .empty').innerText(), 'Данных не найдено')
  await page.locator('#risks').scrollIntoViewIfNeeded()
  assert.equal(await page.locator('#risks .widget .empty').count(), 1)
  assert.equal(await page.locator('.slide[data-team]').count(), 0, 'без команд — секция из markdown остаётся')
  assert.match(await page.locator('.slide[data-kind="team"]').innerText(), /НЕТ ДАННЫХ: историй/)
  await ctx.close()
  console.log('ok — пустые данные')
}

const browser = await chromium.launch()
try {
  await scenario(browser, { javaScriptEnabled: true })
  await scenario(browser, { javaScriptEnabled: false })
  await scenario(browser, { javaScriptEnabled: false, viewport: { width: 800, height: 900 } })
  await mobile(browser, { javaScriptEnabled: true, viewport: { width: 420, height: 900 } })
  await mobile(browser, { javaScriptEnabled: false, viewport: { width: 390, height: 844 } })
  await emptyData(browser)
} finally {
  await browser.close()
}
