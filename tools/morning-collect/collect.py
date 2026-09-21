#!/usr/bin/env python3
"""Сбор и классификация данных для утреннего отчёта `/morning` — детерминированно, без LLM.

Заменяет шаги 1–2 навыка (сбор + классификация): один вызов вместо ~20 шагов
`backlog … --json | jq …`, которые модель делала сама. Итог — один JSON-снимок
`GROUND/PULSE/morning/<дата>.data.json`, из которого навык пишет отчёт.

Использование (cwd — корень воркспейса, где лежат `backlog/` и `GROUND/`):
  collect.py                       # сегодня по МСК, пишет GROUND/PULSE/morning/<today>.data.json
  collect.py --date 2026-09-21     # отчёт за другой день
  collect.py --force               # пересобрать, даже если снимок свежий
  collect.py --max-age 0           # то же самое
  collect.py --stdout              # напечатать JSON, файл не писать

Снимок моложе `--max-age` секунд (по умолчанию 3600) не пересобирается — так
повторный `/morning` после обрыва не тратит минуты на то же самое.

Источники ровно те, что разрешены навыку: `backlog task list --json`,
`backlog milestone list --plain`, `backlog task <id> --json` (только для задач
на сегодня и ближайших договорённостей, не больше `--detail`), календарь
`tools/calendar-today/today.py`, прошлые отчёты `GROUND/PULSE/morning/`,
последний `GROUND/RESULTS/*sprint-report*.md`, заметки `GROUND/PULSE/*` за вчера.
Чего нет — в снимке `null`/пустой список и причина в `sources`. Ничего не
додумывается и не пишется в Backlog.md.

Код выхода 1 — только если недоступен Backlog.md (без него отчёта нет).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import subprocess
import sys
import time
from pathlib import Path
from zoneinfo import ZoneInfo

MSK = ZoneInfo("Europe/Moscow")
CLOSED = {"Done", "Cancelled"}
KIND_PREFIX = "okr-kind:"
KR_PREFIX = "okr-kr:"
CONTROL_HORIZON_DAYS = 7
TOOLS_DIR = Path(__file__).resolve().parents[1]
CALENDAR = TOOLS_DIR / "calendar-today" / "today.py"


# ---------- утилиты ----------

def run(cmd: list[str], cwd: Path, timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)


def first_line(text: str) -> str:
    for line in text.splitlines():
        if line.strip():
            return line.strip()
    return ""


def msk_date(iso: str | None) -> str | None:
    """`2026-09-20T21:30:00Z` → дата по МСК (`2026-09-21`). None → None."""
    if not iso:
        return None
    try:
        t = dt.datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=dt.timezone.utc)
    return t.astimezone(MSK).date().isoformat()


def kind_of(task: dict) -> str | None:
    for label in task.get("labels") or []:
        if label.startswith(KIND_PREFIX):
            return label[len(KIND_PREFIX):]
    return None


def kr_of(task: dict) -> str | None:
    for label in task.get("labels") or []:
        if label.startswith(KR_PREFIX):
            return label[len(KR_PREFIX):]
    return None


def is_open(task: dict) -> bool:
    return task.get("status") not in CLOSED


def days_between(a: str, b: str) -> int:
    return (dt.date.fromisoformat(a) - dt.date.fromisoformat(b)).days


def slim(task: dict, today: str) -> dict:
    """Строка задачи для снимка: только то, что нужно отчёту."""
    due = task.get("dueDate")
    return {
        "id": task["id"],
        "title": task.get("title"),
        "status": task.get("status"),
        "type": task.get("type"),
        "kind": kind_of(task),
        "kr": kr_of(task),
        "priority": task.get("priority"),
        "assignees": task.get("assignees") or [],
        "milestone": task.get("milestone"),
        "due": due,
        "overdue_days": days_between(today, due) if due and due <= today else 0,
        "created_msk": msk_date(task.get("createdAt")),
        "updated_msk": msk_date(task.get("updatedAt")),
        "labels": task.get("labels") or [],
    }


# ---------- источники ----------

def load_tasks(ws: Path) -> tuple[list[dict], str | None]:
    r = run(["backlog", "task", "list", "--json"], ws)
    if r.returncode != 0:
        return [], f"backlog task list --json: код {r.returncode}: {first_line(r.stderr)}"
    try:
        data = json.loads(r.stdout)
    except json.JSONDecodeError as e:
        return [], f"backlog task list --json: не JSON ({e})"
    tasks = data["tasks"] if isinstance(data, dict) else data
    return tasks, None


def load_milestones(ws: Path) -> tuple[list[dict], str | None]:
    r = run(["backlog", "milestone", "list", "--plain"], ws)
    if r.returncode != 0:
        return [], f"backlog milestone list: код {r.returncode}: {first_line(r.stderr)}"
    out = []
    # `  m-1: Objective 1 (0/9 done)`
    for m in re.finditer(r"^\s*(m-\d+):\s*(.+?)\s*\((\d+)/(\d+) done\)\s*$", r.stdout, re.M):
        out.append({"id": m.group(1), "title": m.group(2), "done": int(m.group(3)), "total": int(m.group(4))})
    return out, None


def load_task_detail(ws: Path, task_id: str) -> dict | None:
    r = run(["backlog", "task", task_id, "--json"], ws, timeout=60)
    if r.returncode != 0:
        return None
    try:
        t = json.loads(r.stdout)["task"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return None
    comments = []
    for c in t.get("comments") or []:
        if isinstance(c, dict):
            comments.append({"date": c.get("date") or c.get("createdAt"), "author": c.get("author"), "text": c.get("text") or c.get("content")})
        else:
            comments.append({"text": str(c)})
    return {
        "path": t.get("path"),
        "description": t.get("description"),
        "acceptance_criteria": [ac if isinstance(ac, str) else ac.get("text") for ac in t.get("acceptanceCriteria") or []],
        "implementation_notes": t.get("implementationNotes"),
        "comments": comments,
    }


def load_calendar(ws: Path, date: str) -> dict:
    """Календарь на дату: {"ok", "error", "events"}. Код 1 → error = первая строка stderr."""
    if not CALENDAR.exists():
        return {"ok": False, "error": f"нет {CALENDAR}", "events": []}
    try:
        r = run([sys.executable, str(CALENDAR), "--date", date, "--json"], ws, timeout=90)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "today.py: таймаут 90 с", "events": []}
    if r.returncode != 0:
        return {"ok": False, "error": first_line(r.stderr) or f"today.py: код {r.returncode}", "events": []}
    try:
        events = json.loads(r.stdout)
    except json.JSONDecodeError:
        return {"ok": False, "error": "today.py --json: не JSON", "events": []}
    if isinstance(events, dict):
        events = events.get("events", events)
    return {"ok": True, "error": None, "events": events}


def find_prev_report(ws: Path, today: str) -> Path | None:
    d = ws / "GROUND" / "PULSE" / "morning"
    if not d.is_dir():
        return None
    prev = sorted(p for p in d.glob("????-??-??.md") if p.stem < today)
    return prev[-1] if prev else None


def parse_prev_report(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    # план на день = строки таблицы «### Задачи» прошлого отчёта
    plan_ids: list[str] = []
    m = re.search(r"^### Задачи\s*$(.*?)(?=^##|\Z)", text, re.M | re.S)
    if m:
        for row in m.group(1).splitlines():
            if row.startswith("|") and not row.startswith("|---") and "Задача" not in row.split("|")[1]:
                ids = re.findall(r"\bPO-\d+\b", row.split("|")[1])
                if ids:
                    plan_ids.append(ids[0])
    teams = re.search(r"^## Статус по командам\s*$(.*?)(?=^## |\Z)", text, re.M | re.S)
    kpi = re.search(r"^KPI:.*$", text, re.M)
    return {
        "path": str(path.relative_to(path.parents[3])) if len(path.parents) > 3 else str(path),
        "date": path.stem,
        "kpi": kpi.group(0) if kpi else None,
        "plan_ids": plan_ids,
        "teams_section": teams.group(1).strip() if teams else None,
    }


def find_sprint_report(ws: Path) -> dict | None:
    d = ws / "GROUND" / "RESULTS"
    if not d.is_dir():
        return None
    files = [p for p in d.glob("*sprint-report*.md")]
    if not files:
        return None
    path = max(files, key=lambda p: p.stat().st_mtime)
    text = path.read_text(encoding="utf-8")
    fm: dict[str, str] = {}
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if m:
        for line in m.group(1).splitlines():
            if ":" in line and not line.startswith(" "):
                k, v = line.split(":", 1)
                fm[k.strip()] = v.strip()
    def section(title: str) -> str | None:
        s = re.search(r"^##\s+" + re.escape(title) + r".*?$(.*?)(?=^##|\Z)", text, re.M | re.S)
        return s.group(1).strip() if s else None
    summary = re.search(r"^\*\*Итог[^*]*\*\*\s*(.+)$", text, re.M)
    return {
        "path": str(path.relative_to(ws)),
        "frontmatter": fm,
        "summary": summary.group(1).strip() if summary else None,
        "key_risks": section("Ключевые риски"),
        "open_questions": section("Открытые вопросы"),
    }


def find_pulse_notes(ws: Path, day: str) -> list[dict]:
    out = []
    for sub in ("summaries", "radar", "daybook"):
        d = ws / "GROUND" / "PULSE" / sub
        if not d.is_dir():
            continue
        for p in sorted(d.rglob("*")):
            if p.is_file() and day in p.name and p.suffix in (".md", ".txt"):
                try:
                    head = p.read_text(encoding="utf-8", errors="replace")[:1500]
                except OSError:
                    head = ""
                out.append({"path": str(p.relative_to(ws)), "kind": sub, "head": head})
    return out


# ---------- классификация ----------

def classify(tasks: list[dict], today: str, yesterday: str, plan_ids: list[str]) -> dict:
    horizon = (dt.date.fromisoformat(today) + dt.timedelta(days=CONTROL_HORIZON_DAYS)).isoformat()
    by_id = {t["id"]: t for t in tasks}
    potask = [t for t in tasks if t.get("type") == "potask"]
    okr = [t for t in tasks if t.get("type") == "okr"]
    bft = [t for t in tasks if t.get("type") == "bft"]
    stories = [t for t in tasks if t.get("type") == "story"]
    kr_title = {t["id"]: t.get("title") for t in okr}

    def open_kind(kind: str | None) -> list[dict]:
        return [t for t in potask if is_open(t) and kind_of(t) == kind]

    task_like = open_kind("task") + open_kind(None)
    tasks_today = sorted(
        (slim(t, today) for t in task_like if t.get("dueDate") and t["dueDate"] <= today),
        key=lambda s: (s["due"], s["id"]),
    )
    tasks_later = sorted(
        (slim(t, today) for t in task_like if not (t.get("dueDate") and t["dueDate"] <= today)),
        key=lambda s: (s["due"] or "9999", s["id"]),
    )

    controls_all = [slim(t, today) for t in open_kind("control")]
    controls_soon = sorted(
        (c for c in controls_all if c["due"] is None or c["due"] <= horizon),
        key=lambda c: (0 if c["overdue_days"] else 1, c["due"] or "9999", c["id"]),
    )
    controls_later = [c for c in controls_all if c not in controls_soon]

    risks_open = [slim(t, today) for t in open_kind("risk")]
    risk_groups: dict[str, dict] = {}
    for r in sorted(risks_open, key=lambda r: (r["kr"] or "~", r["id"])):
        key = r["kr"] or "none"
        g = risk_groups.setdefault(key, {"kr": r["kr"], "kr_title": kr_title.get(r["kr"]) if r["kr"] else None,
                                         "count": 0, "without_owner": 0, "risks": []})
        g["count"] += 1
        if not r["assignees"]:
            g["without_owner"] += 1
        g["risks"].append(r)

    done_yesterday = [slim(t, today) for t in tasks if not is_open(t) and msk_date(t.get("updatedAt")) == yesterday]
    created_yesterday = [slim(t, today) for t in tasks if msk_date(t.get("createdAt")) == yesterday]
    touched_yesterday = [slim(t, today) for t in tasks
                         if is_open(t) and msk_date(t.get("updatedAt")) == yesterday and msk_date(t.get("createdAt")) != yesterday]

    # ретро-счётчики по плану прошлого отчёта: Done → сделано; открыта и срок в будущем
    # или без срока → перенесено; открыта и срок прошёл → сорвано; нет в Backlog → пропала
    retro_plan = []
    for pid in plan_ids:
        t = by_id.get(pid)
        if t is None:
            retro_plan.append({"id": pid, "outcome": "missing"})
            continue
        s = slim(t, today)
        if not is_open(t):
            outcome = "done"
        elif s["due"] and s["due"] <= today:
            outcome = "failed"
        else:
            outcome = "moved"
        retro_plan.append({"id": pid, "outcome": outcome, "status": s["status"], "due": s["due"], "updated_msk": s["updated_msk"]})
    counts = {k: sum(1 for r in retro_plan if r["outcome"] == k) for k in ("done", "moved", "failed", "missing")}
    counts["plan"] = len(retro_plan)

    bft_open = [t for t in bft if is_open(t)]
    bft_by_status: dict[str, int] = {}
    for t in bft_open:
        bft_by_status[t.get("status") or "?"] = bft_by_status.get(t.get("status") or "?", 0) + 1

    stories_out = []
    for t in stories:
        s = slim(t, today)
        s["team"] = next((l[5:] for l in s["labels"] if l.startswith("team:")), None)
        s["sprint"] = next((l[7:] for l in s["labels"] if l.startswith("sprint:")), None)
        stories_out.append(s)

    referenced_krs = {r["kr"] for r in risks_open if r["kr"]} | {s["kr"] for s in tasks_today + controls_soon + done_yesterday if s["kr"]}
    krs = {t["id"]: {"title": t.get("title"), "milestone": t.get("milestone"), "status": t.get("status")}
           for t in okr if t["id"] in referenced_krs}

    return {
        "kpi": {
            "overdue": sum(1 for s in tasks_today if s["overdue_days"] > 0),
            "today": len(tasks_today),
            "risks_without_owner": sum(1 for r in risks_open if not r["assignees"]),
            "closed_yesterday": len(done_yesterday),
            "overdue_controls": sum(1 for c in controls_soon if c["overdue_days"] > 0),
        },
        "retro": {
            "plan": retro_plan,
            "counts": counts,
            "done_yesterday": done_yesterday,
            "created_yesterday": created_yesterday,
            "touched_yesterday": touched_yesterday,
        },
        "tasks_today": tasks_today,
        "tasks_later": tasks_later,
        "controls_soon": controls_soon,
        "controls_later": controls_later,
        "risks": {"groups": list(risk_groups.values()), "open_total": len(risks_open)},
        "krs": krs,
        "stories": stories_out,
        "bft": {"open_total": len(bft_open), "by_status": bft_by_status},
        "totals": {
            "tasks": len(tasks),
            "potask_open": sum(1 for t in potask if is_open(t)),
            "task_open": len(task_like),
            "control_open": len(controls_all),
            "risk_open": len(risks_open),
            "okr": len(okr),
            "story": len(stories),
        },
    }


# ---------- сборка ----------

def collect(ws: Path, today: str, detail_limit: int) -> dict:
    yesterday = (dt.date.fromisoformat(today) - dt.timedelta(days=1)).isoformat()
    sources: dict[str, str | None] = {}

    tasks, err = load_tasks(ws)
    if err:
        raise SystemExit(f"collect: Backlog.md недоступен — {err}")
    sources["backlog"] = "backlog task list --json"

    milestones, m_err = load_milestones(ws)
    sources["milestones"] = m_err or "backlog milestone list --plain"

    prev_path = find_prev_report(ws, today)
    prev = parse_prev_report(prev_path) if prev_path else None
    sources["prev_report"] = str(prev_path.relative_to(ws)) if prev_path else None

    sprint = find_sprint_report(ws)
    sources["sprint_report"] = sprint["path"] if sprint else None

    pulse = find_pulse_notes(ws, yesterday)
    sources["pulse_yesterday"] = f"{len(pulse)} файлов" if pulse else None

    cal_today = load_calendar(ws, today)
    cal_yesterday = load_calendar(ws, yesterday)
    sources["calendar"] = "tools/calendar-today/today.py" if cal_today["ok"] else f"нет: {cal_today['error']}"

    data = classify(tasks, today, yesterday, prev["plan_ids"] if prev else [])

    # детали — только там, где отчёту нужны описание/AC: задачи сегодня и ближайшие договорённости
    details: dict[str, dict] = {}
    for s in data["tasks_today"] + data["controls_soon"]:
        if len(details) >= detail_limit:
            break
        d = load_task_detail(ws, s["id"])
        if d:
            details[s["id"]] = d
    sources["details"] = f"backlog task <id> --json × {len(details)} (лимит {detail_limit})"

    return {
        "schema": "morning-data/1",
        "generated_at": dt.datetime.now(MSK).isoformat(timespec="seconds"),
        "today": today,
        "yesterday": yesterday,
        "workspace": str(ws),
        "sources": sources,
        "calendar": {"today": cal_today, "yesterday": cal_yesterday},
        "milestones": milestones,
        "prev_report": prev,
        "sprint_report": sprint,
        "pulse_yesterday": pulse,
        "details": details,
        **data,
    }


def summary_line(d: dict) -> str:
    k = d["kpi"]; c = d["retro"]["counts"]
    cal = "ок" if d["calendar"]["today"]["ok"] else f"нет ({d['calendar']['today']['error']})"
    return (f"collect: {d['today']} · просрочено {k['overdue']} · сегодня {k['today']} · рисков без владельца "
            f"{k['risks_without_owner']} · закрыто вчера {k['closed_yesterday']} · ретро план {c['plan']}/сделано "
            f"{c['done']}/перенесено {c['moved']}/сорвано {c['failed']} · договорённостей 7 дн {len(d['controls_soon'])} · "
            f"календарь: {cal} · прошлый отчёт: {d['sources']['prev_report'] or 'нет'}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Снимок данных для /morning (Backlog.md, календарь, GROUND).")
    ap.add_argument("--date", help="ГГГГ-ММ-ДД, по умолчанию сегодня по МСК")
    ap.add_argument("--workspace", type=Path, default=Path.cwd(), help="корень воркспейса с backlog/ и GROUND/")
    ap.add_argument("--out", type=Path, help="куда писать (по умолчанию GROUND/PULSE/morning/<дата>.data.json)")
    ap.add_argument("--max-age", type=int, default=3600, help="секунд; свежий снимок не пересобирается (0 — всегда)")
    ap.add_argument("--force", action="store_true", help="то же, что --max-age 0")
    ap.add_argument("--detail", type=int, default=20, help="максимум вызовов backlog task <id> --json")
    ap.add_argument("--stdout", action="store_true", help="печатать JSON вместо записи файла")
    a = ap.parse_args(argv)

    ws = a.workspace.resolve()
    if not (ws / "backlog").is_dir():
        print(f"collect: в {ws} нет каталога backlog/ — запускать из корня воркспейса или --workspace", file=sys.stderr)
        return 1
    today = a.date or dt.datetime.now(MSK).date().isoformat()
    try:
        dt.date.fromisoformat(today)
    except ValueError:
        print(f"collect: --date {today!r} не ГГГГ-ММ-ДД", file=sys.stderr)
        return 1
    out = a.out or ws / "GROUND" / "PULSE" / "morning" / f"{today}.data.json"
    max_age = 0 if a.force else a.max_age

    if not a.stdout and max_age > 0 and out.exists() and time.time() - out.stat().st_mtime < max_age:
        try:
            cached = json.loads(out.read_text(encoding="utf-8"))
            if cached.get("today") == today:
                print(f"collect: снимок свежий ({int(time.time() - out.stat().st_mtime)} с), пересборка пропущена — {out}")
                print(summary_line(cached))
                return 0
        except (json.JSONDecodeError, KeyError):
            pass

    data = collect(ws, today, a.detail)
    text = json.dumps(data, ensure_ascii=False, indent=1)
    if a.stdout:
        print(text)
        return 0
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text + "\n", encoding="utf-8")
    print(f"collect: записан {out} ({len(text) // 1024} КБ)")
    print(summary_line(data))
    return 0


if __name__ == "__main__":
    sys.exit(main())
