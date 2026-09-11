# poh-morning-plugin

Плагин DeepSeek Harness для утреннего брифа PO. Подключает каталог `../skills`
этого репозитория как отдельный провайдер навыков харнесса (`/morning`,
`/mts-link-sync`) и добавляет в системный промпт правило маршрутизации: фразы
«план на сегодня», «утренний отчёт», «morning» и подобные поднимают навык
`morning`, а не самодельный список задач через `backlog` в терминале.

Данных плагин не собирает и в Backlog.md не пишет: сбор описан в
[`skills/morning/SKILL.md`](../skills/morning/SKILL.md), модель читает Backlog.md
штатными инструментами харнесса `mcp__backlog__*` (строка `backlog-md` профиля).

## Демо

1. `http://127.0.0.1:3082` → новый чат.
2. Ввести `/morning` или текст «план на сегодня».
3. Ответ — отчёт из Backlog.md: просроченное, сегодня, риски, договорённости,
   требования (БФТ), цели квартала, план дня. Дальше — STOP: правки в планнер
   только после подтверждения по пункту.

## Почему плагин, а не строка `customSkillDirs`

У `@deepseek-ai/dsh-skill-filesystem` один список корней на строку профиля, и
вторая patch-строка с тем же id затирает первую — так уже терялись po-helper-навыки.
Плагин поднимает второй экземпляр провайдера под своим именем
(`poh-morning-status`, `includeDefaultRoots: false`) и сам находит `skills/` по
расположению пакета: на другой машине ничего в профиле переписывать не нужно.

Слэш `/morning` харнесс резолвит без подсказок. Свободный текст — нет: без
секции промпта модель на «план на сегодня» уходит в `backlog` напрямую (проверено
2026-09-11). Секция `morning:routing`, порядок 710 — сразу после правила записи
задач PO из poh-okr-plugin (700).

## Конфигурация

```yaml
- id: morning-status
  config:
    skillsDir: ''                    # пусто — skills/ рядом с пакетом
    providerName: poh-morning-status
    triggers: ['morning', 'план на сегодня', 'утренний отчёт', 'утренний бриф',
               'что на сегодня', 'с чего начать день', 'что горит']
    order: 710
```

Пустой `triggers` выключает секцию промпта, провайдер навыков остаётся.

## Установка в профиль (workspace ishmanov-cortex)

Штатная `dsh plugin add` сломана (issue #37 kibarik/mts-po-workspace), поэтому вручную:

```sh
cd poh-morning-plugin && pnpm install && pnpm build
ln -s "$PWD" <cortex>/harness-ui-plugins/poh-morning-plugin
# <cortex>/harness-ui/.dsh-data/profiles/web/package.json:
#   dependencies["poh-morning-plugin"] = "link:<cortex>/harness-ui-plugins/poh-morning-plugin"
#   dsh.profile.bundles += "poh-morning-plugin"
cd <cortex>/harness-ui/.dsh-data/profiles/web && pnpm install
launchctl kickstart -k gui/$UID/ru.poh.dsh-harness
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:3082/   # 200
```

Корень `poh-morning-status/skills` из строки `skill-filesystem` профиля при этом
убирается — иначе навыки будут в каталоге дважды.

## Сборка и тесты

```sh
pnpm build   # tsc → lib/
pnpm test    # проверяет умолчание skillsDir, frontmatter каждого навыка, текст правила
```

Тест frontmatter не формальность: провайдер харнесса требует `name` и
`description` в SKILL.md, Claude Code — нет, поэтому навык может работать там и
молча пропасть здесь.
