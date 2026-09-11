/**
 * Утренний бриф PO как плагин DeepSeek Harness.
 *
 * Плагин не собирает данные сам — он подключает каталог `skills/` репозитория
 * poh-morning-status как отдельный корень навыков (`/morning`, `/mts-link-sync`).
 * Сбор и разбор живут в SKILL.md: модель читает Backlog.md через штатные
 * инструменты харнесса (`mcp__backlog__*`), плагину права записи не нужны.
 *
 * Почему отдельный провайдер, а не строка в `customSkillDirs` профиля: у
 * `skill-filesystem` один список корней на строку, и вторая patch-строка с тем же
 * id затирает первую — так уже терялись po-helper-навыки. Изолированный провайдер
 * с собственным именем регистрируется рядом и ничего не затирает; путь к
 * навыкам он знает сам, по расположению пакета, и не требует правки профиля на
 * каждой машине.
 *
 * @module poh-morning-plugin
 */

import { existsSync, statSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import type { Context } from '@deepseek-ai/cordis'
import z from '@deepseek-ai/schemastery'
import * as skillFilesystem from '@deepseek-ai/dsh-skill-filesystem'

/** Имя строки cordis. */
export const name = 'morning-status'

/** Провайдер навыков регистрируется в `ctx.skills`; без службы навыков строка ждёт. */
export const inject = ['skills']

/** Имя навыка утреннего отчёта в каталоге. */
export const MORNING_SKILL = 'morning'

/**
 * Фразы, по которым модель обязана поднять навык `morning`, а не собирать план
 * сама. Слэш `/morning` харнесс резолвит без подсказки; текст — нет: без правила
 * модель на «план на сегодня» уходит в `backlog` напрямую и отдаёт список задач
 * вместо отчёта (проверено 2026-09-11).
 */
export const DEFAULT_TRIGGERS: readonly string[] = [
  'morning',
  'план на сегодня',
  'утренний отчёт',
  'утренний бриф',
  'что на сегодня',
  'с чего начать день',
  'что горит',
]

/**
 * Место правила среди секций системного промпта. Число, а не имя из
 * `getSectionOrder`: тот знает только секции самого харнесса. 710 — сразу после
 * правила записи задач PO (700, poh-okr-plugin) и до описаний инструментов (800+):
 * маршрутизация должна читаться раньше, чем модель увидит `backlog` в терминале.
 */
const ROUTING_ORDER = 710

/** Имя провайдера по умолчанию — под ним навыки видны в каталоге харнесса. */
export const DEFAULT_PROVIDER_NAME = 'poh-morning-status'

/** Конфигурация строки. */
export interface Config {
  /**
   * Каталог с навыками (`<name>/SKILL.md`). По умолчанию — `../skills` относительно
   * пакета, то есть `skills/` в корне репозитория poh-morning-status.
   */
  skillsDir?: string
  /** Имя провайдера навыков; менять только при конфликте с другим провайдером. */
  providerName?: string
  /** Фразы-триггеры навыка `morning` в свободном тексте; пустой список — без правила. */
  triggers?: string[]
  /** Порядок секции маршрутизации в системном промпте. */
  order?: number
}

/** Схема конфигурации для загрузчика cordis. */
export const Config: z<Config> = z.object({
  skillsDir: z.string(),
  providerName: z.string().min(1).default(DEFAULT_PROVIDER_NAME),
  triggers: z.array(z.string()).default([...DEFAULT_TRIGGERS]),
  order: z.number().default(ROUTING_ORDER),
})

/** Форма службы системного промпта, которой нам достаточно. */
interface SystemPromptLike {
  section: (section: { name: string; order: number; text: string }) => () => void
}

/**
 * Текст правила маршрутизации для системного промпта.
 * @param triggers - фразы, по которым поднимается навык.
 * @returns текст секции или пустую строку, если триггеров нет.
 */
export function routingPolicy(triggers: readonly string[]): string {
  const phrases = triggers.map(t => t.trim()).filter(t => t !== '')
  if (phrases.length === 0) return ''
  return [
    '# Утренний отчёт PO',
    `Если сообщение пользователя целиком или по смыслу — одна из фраз: ${phrases.map(p => `«${p}»`).join(', ')},`,
    `первым действием вызови инструмент \`skill\` с name="${MORNING_SKILL}" и дальше следуй его инструкциям.`,
    'Не собирай план дня сам через `backlog` в терминале и не отвечай списком задач: формат, источники и порядок сбора задаёт навык.',
    'Явная команда `/morning` — тот же навык.',
  ].join('\n')
}

/**
 * Каталог навыков по умолчанию: `skills/` рядом с пакетом плагина.
 * Считается от реального расположения собранного `lib/index.js`, поэтому одинаково
 * работает и для симлинка `link:` в профиле, и для установленного пакета.
 */
export function defaultSkillsDir(moduleUrl: string = import.meta.url): string {
  return resolve(dirname(fileURLToPath(moduleUrl)), '..', '..', 'skills')
}

/**
 * Разрешить каталог навыков из конфигурации.
 * @param configured - значение `skillsDir` из конфигурации, если задано.
 * @param moduleUrl - URL модуля плагина, от которого считается умолчание.
 */
export function resolveSkillsDir(configured: string | undefined, moduleUrl?: string): string {
  return configured === undefined || configured === '' ? defaultSkillsDir(moduleUrl) : resolve(configured)
}

/** Поднять провайдер навыков утреннего брифа. */
export function apply(ctx: Context, config: Config = {}): void {
  const skillsDir = resolveSkillsDir(config.skillsDir)
  const providerName = config.providerName ?? DEFAULT_PROVIDER_NAME
  // Отсутствующий каталог — громко в лог, но без падения: несобранный или
  // неверно подключённый плагин не должен ронять весь харнесс.
  if (!existsSync(skillsDir) || !statSync(skillsDir).isDirectory()) {
    ctx.logger.error(`poh-morning-plugin: каталог навыков не найден: ${skillsDir} (задайте skillsDir)`)
    return
  }
  ctx.logger.info(`poh-morning-plugin: навыки из ${skillsDir} как провайдер "${providerName}"`)
  ctx.plugin(skillFilesystem, {
    providerName,
    // Только свой корень: проектные и пользовательские корни уже обслуживает
    // провайдер базового бандла, дублировать их под вторым именем нельзя.
    includeDefaultRoots: false,
    customSkillDirs: [skillsDir],
  })

  // Правило маршрутизации — отложенной инъекцией: композиция без системного
  // промпта (одни тесты провайдера) должна подниматься без него.
  const policy = routingPolicy(config.triggers ?? DEFAULT_TRIGGERS)
  if (policy === '') return
  ctx.inject(['systemPrompt'], (scoped: Context) => {
    const systemPrompt = scoped.get('systemPrompt') as unknown as SystemPromptLike
    scoped.effect(
      () => systemPrompt.section({
        name: 'morning:routing',
        order: config.order ?? ROUTING_ORDER,
        text: policy,
      }),
      'poh-morning-plugin: маршрутизация на навык morning',
    )
  })
}
