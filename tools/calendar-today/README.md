# calendar-today

Созвоны PO на день из Google-календаря «MTS Exchange», который наполняет
[poh-scheduller](https://github.com/po-helper-org/poh-scheduller) (Exchange → Google,
односторонне). Только чтение; в Google и Exchange ничего не пишется.

```sh
python3 today.py --status              # офлайн-диагностика конфигурации
python3 today.py                       # сегодня по МСК
python3 today.py --date 2026-09-11 --json
```

Берёт из чекаута poh-scheduller (`POH_SCHEDULLER_DIR`, по умолчанию
`~/projects/poh-org/poh-scheduller`): `state/google.token`, `secrets/google_client_id`,
`secrets/google_client_secret`, `GCAL_ID` из `.env`. Нужны `google-auth` и `requests`
(есть у `/opt/homebrew/bin/python3`).

Любая проблема — код выхода 1 и причина в stderr. Протухший refresh-токен
(`invalid_grant`) перевыпускает PO: `python3 google_token_bootstrap.py` в poh-scheduller;
скриптом это не обходится. Навык `/morning` в этом случае показывает
`[НЕТ ДАННЫХ: календарь — …]`, а не пустой день.

Проверено 2026-09-11: `--status` и путь отказа (`invalid_grant`). Успешное чтение
событий вживую не прогонялось — токен на машине протух.
