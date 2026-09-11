import { test } from 'node:test'
import assert from 'node:assert/strict'
import { existsSync, readdirSync, readFileSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { pathToFileURL } from 'node:url'
import { DEFAULT_PROVIDER_NAME, defaultSkillsDir, resolveSkillsDir } from '../src/index.js'

// Умолчание считается от собранного lib/index.js: подставляем его URL явно,
// чтобы тест не зависел от того, откуда запущен транспилированный файл.
const builtModuleUrl = pathToFileURL(resolve(import.meta.dirname, '..', '..', 'lib', 'index.js')).href

test('умолчание — skills/ в корне репозитория', () => {
  const dir = defaultSkillsDir(builtModuleUrl)
  assert.equal(dir, resolve(import.meta.dirname, '..', '..', '..', 'skills'))
  assert.ok(existsSync(dir), `каталог навыков должен существовать: ${dir}`)
})

test('явный skillsDir имеет приоритет, пустая строка — как отсутствие', () => {
  assert.equal(resolveSkillsDir('/tmp/x', builtModuleUrl), '/tmp/x')
  assert.equal(resolveSkillsDir('', builtModuleUrl), defaultSkillsDir(builtModuleUrl))
  assert.equal(resolveSkillsDir(undefined, builtModuleUrl), defaultSkillsDir(builtModuleUrl))
})

// Провайдер харнесса требует name и description во frontmatter (Claude Code — нет),
// поэтому навык может работать там и молча пропасть здесь. Ловим до старта харнесса.
test('каждый навык несёт name и description во frontmatter', () => {
  const dir = defaultSkillsDir(builtModuleUrl)
  const skills = readdirSync(dir, { withFileTypes: true }).filter(e => e.isDirectory()).map(e => e.name)
  assert.ok(skills.includes('morning'), 'навык morning обязателен')
  for (const skill of skills) {
    const text = readFileSync(join(dir, skill, 'SKILL.md'), 'utf8')
    const match = /^---\n([\s\S]*?)\n---/.exec(text)
    assert.ok(match, `${skill}: нет frontmatter`)
    const nameLine = /^name:\s*(\S+)/m.exec(match[1])
    assert.ok(nameLine && nameLine[1] === skill, `${skill}: name во frontmatter должен совпадать с каталогом`)
    assert.match(match[1], /^description:\s*\S/m, `${skill}: нет description`)
  }
})

test('имя провайдера по умолчанию стабильно', () => {
  assert.equal(DEFAULT_PROVIDER_NAME, 'poh-morning-status')
})

test('правило маршрутизации называет инструмент skill и навык morning', async () => {
  const { routingPolicy, DEFAULT_TRIGGERS, MORNING_SKILL } = await import('../src/index.js')
  const text = routingPolicy(DEFAULT_TRIGGERS)
  assert.match(text, /`skill`/)
  assert.match(text, new RegExp(`name="${MORNING_SKILL}"`))
  assert.match(text, /«план на сегодня»/)
  assert.equal(routingPolicy([]), '')
  assert.equal(routingPolicy(['  ', '']), '')
})
