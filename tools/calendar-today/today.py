#!/usr/bin/env python3
"""Созвоны PO на день из Google-календаря «MTS Exchange» (read-only).

Календарь наполняет poh-scheduller (Exchange → Google, односторонне). Здесь только
чтение: токен, client id/secret и id календаря берутся из чекаута poh-scheduller,
ничего не пишется ни в Google, ни в Exchange.

Использование:
  today.py                 # события на сегодня (МСК)
  today.py --date 2026-09-11
  today.py --status        # офлайн-диагностика конфигурации, код выхода 1 при проблеме
  today.py --json          # машинный вывод

Код выхода 1 при любой проблеме (нет токена, протух refresh-токен, нет сети) с
внятной причиной в stderr — молчаливый пустой день недопустим: бриф покажет пробел
явно, а не «созвонов нет».
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path

TZ = "Europe/Moscow"
GAPI = "https://www.googleapis.com/calendar/v3"
SCOPES = ["https://www.googleapis.com/auth/calendar"]


def scheduller_dir() -> Path:
    return Path(os.environ.get("POH_SCHEDULLER_DIR", "~/projects/poh-org/poh-scheduller")).expanduser()


def read_env(path: Path) -> dict[str, str]:
    """Минимальный парсер .env: KEY=value, без интерполяции."""
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def check(root: Path) -> tuple[list[str], dict[str, Path | str]]:
    """Список проблем + найденные пути. Без сети."""
    problems: list[str] = []
    env = read_env(root / ".env")
    paths: dict[str, Path | str] = {
        "token": root / "state" / "google.token",
        "client_id": root / "secrets" / "google_client_id",
        "client_secret": root / "secrets" / "google_client_secret",
        "calendar": env.get("GCAL_ID", ""),
    }
    if not root.exists():
        problems.append(f"чекаут poh-scheduller не найден: {root} (задайте POH_SCHEDULLER_DIR)")
        return problems, paths
    for key in ("token", "client_id", "client_secret"):
        p = paths[key]
        assert isinstance(p, Path)
        if not p.exists():
            problems.append(f"нет файла {key}: {p}")
    if not paths["calendar"]:
        problems.append(f"GCAL_ID не задан в {root / '.env'}")
    return problems, paths


def credentials(paths: dict[str, Path | str]):
    from google.auth.transport.requests import Request  # type: ignore
    from google.oauth2.credentials import Credentials  # type: ignore

    tok = json.loads(Path(paths["token"]).read_text())
    creds = Credentials(
        token=tok.get("access_token"),
        refresh_token=tok["refresh_token"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=Path(paths["client_id"]).read_text().strip(),
        client_secret=Path(paths["client_secret"]).read_text().strip(),
        scopes=SCOPES,
    )
    creds.refresh(Request())
    return creds


def fetch(day: dt.date, paths: dict[str, Path | str]) -> list[dict]:
    import requests  # type: ignore

    creds = credentials(paths)
    r = requests.get(
        f"{GAPI}/calendars/{paths['calendar']}/events",
        headers={"Authorization": f"Bearer {creds.token}"},
        params={
            "timeMin": f"{day}T00:00:00+03:00",
            "timeMax": f"{day}T23:59:59+03:00",
            "singleEvents": "true",
            "orderBy": "startTime",
            "timeZone": TZ,
            "maxResults": 50,
        },
        timeout=30,
    )
    r.raise_for_status()
    return r.json().get("items", [])


def person(a: dict) -> str:
    return a.get("displayName") or a.get("email") or "?"


def render(events: list[dict]) -> list[dict]:
    rows = []
    for e in events:
        if e.get("status") == "cancelled":
            continue
        start = e["start"].get("dateTime") or e["start"].get("date")
        end = e["end"].get("dateTime") or e["end"].get("date")
        attendees = [person(a) for a in e.get("attendees", []) if not a.get("self")]
        rows.append({
            "start": start[11:16] if "T" in start else "весь день",
            "end": end[11:16] if "T" in end else "",
            "title": e.get("summary") or "(без названия)",
            "organizer": person(e.get("organizer", {})),
            "attendees": attendees,
            "agenda": (e.get("description") or "").strip(),
            "location": e.get("location") or "",
            "response": next((a.get("responseStatus") for a in e.get("attendees", []) if a.get("self")), ""),
        })
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--date", help="ГГГГ-ММ-ДД, по умолчанию сегодня по МСК")
    ap.add_argument("--status", action="store_true", help="только диагностика, без сети")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    root = scheduller_dir()
    problems, paths = check(root)
    if args.status:
        print(f"poh-scheduller: {root}")
        print(f"календарь: {paths['calendar'] or '—'}")
        print(f"токен: {paths['token']} {'есть' if Path(paths['token']).exists() else 'нет'}")
        if problems:
            print("Проблемы:")
            for p in problems:
                print(f"  - {p}")
            return 1
        print("Конфигурация в порядке; живость токена проверяется только сетевым вызовом.")
        return 0
    if problems:
        for p in problems:
            print(f"calendar-today: {p}", file=sys.stderr)
        return 1

    day = dt.date.fromisoformat(args.date) if args.date else dt.datetime.now(
        dt.timezone(dt.timedelta(hours=3))).date()
    try:
        rows = render(fetch(day, paths))
    except Exception as e:  # noqa: BLE001 — любая причина должна быть видна PO
        msg = str(e)
        hint = ""
        if "invalid_grant" in msg:
            hint = " — refresh-токен Google протух; PO перевыпускает его: `python3 google_token_bootstrap.py` в poh-scheduller"
        print(f"calendar-today: не удалось прочитать календарь: {msg}{hint}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps({"date": day.isoformat(), "events": rows}, ensure_ascii=False, indent=2))
        return 0
    print(f"Созвоны {day.isoformat()}: {len(rows)}")
    for r in rows:
        who = ", ".join(r["attendees"][:6]) + (" …" if len(r["attendees"]) > 6 else "")
        span = f"{r['start']}–{r['end']}" if r["end"] else r["start"]
        print(f"- {span} · {r['title']} · орг. {r['organizer']}" + (f" · {who}" if who else ""))
        if r["agenda"]:
            first = r["agenda"].splitlines()[0][:160]
            print(f"    повестка: {first}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
