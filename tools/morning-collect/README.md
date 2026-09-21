# morning-collect

Снимок данных для утреннего отчёта `/morning` — детерминированный сбор и
классификация без LLM. Один вызов вместо ~20 шагов `backlog … --json | jq …`,
которые модель раньше делала сама (3–4 минуты хода и потеря всего при обрыве).

```sh
cd <воркспейс с backlog/ и GROUND/>
python3 <poh-morning-status>/tools/morning-collect/collect.py            # → GROUND/PULSE/morning/<сегодня>.data.json
python3 …/collect.py --date 2026-09-21                                    # за другой день
python3 …/collect.py --force                                              # пересобрать свежий снимок
python3 …/collect.py --stdout | jq .kpi                                   # без записи файла
```

## Что читает

Ровно то, что разрешено навыку: `backlog task list --json`, `backlog milestone
list --plain`, `backlog task <id> --json` (только задачи на сегодня и ближайшие
договорённости, `--detail`, по умолчанию ≤ 20), календарь
`../calendar-today/today.py` на сегодня и вчера, прошлый отчёт
`GROUND/PULSE/morning/<дата>.md` (план дня = строки его таблицы «Задачи»),
последний `GROUND/RESULTS/*sprint-report*.md`, заметки `GROUND/PULSE/{summaries,
radar,daybook}` с датой вчера в имени. В Backlog.md ничего не пишет.

## Что отдаёт

`schema: morning-data/1`. Ключи — см. таблицу в `skills/morning/SKILL.md`, шаг 1.
Коротко: `kpi`, `retro` (план прошлого отчёта с исходом `done/moved/failed/missing`,
закрытое/заведённое/правленое вчера), `tasks_today` (просроченные первыми,
`overdue_days`), `tasks_later`, `controls_soon`/`controls_later` (горизонт 7 дней +
без срока), `risks.groups` по KR с `kr_title` и `without_owner`, `details[id]`
(описание, AC, комментарии), `stories`, `sprint_report`, `prev_report`,
`pulse_yesterday`, `calendar.{today,yesterday}` (`ok`/`error`/`events`), `bft`,
`totals`, `milestones`, `krs`, `sources`.

Даты закрытия/создания — по МСК (`updated_msk`, `created_msk`): `updatedAt`
в Backlog.md хранится в UTC, вчера 21:30Z — это уже сегодня.

## Кэш и обрывы

Снимок моложе `--max-age` секунд (по умолчанию 3600) не пересобирается — повторный
`/morning` после перезапуска харнесса или закрытой вкладки начинает с готового
файла. `--force` или `--max-age 0` — пересобрать.

Код выхода 1 только без Backlog.md (или вне воркспейса). Календарь недоступен —
это не ошибка: `calendar.today.ok: false`, `error` — первая строка stderr `today.py`,
навык показывает `[НЕТ ДАННЫХ: календарь — …]`.

## Проверить

```sh
python3 -m unittest discover -s test          # 9 тестов: классификация, МСК-даты, парсер прошлого отчёта, CLI
```

Проверено 2026-09-21 на воркспейсе ishmanov-cortex (179 задач): 6 с, 32 КБ,
счётчики совпали с ручным разбором модели из прерванной сессии.
