#!/usr/bin/env python3
"""Слайды утреннего отчёта из его markdown. Детерминированно, без LLM.

  render.py GROUND/PULSE/morning/2026-09-11.md            # → рядом .html
  render.py report.md -o out.html
  render.py report.md --stdout

Если рядом лежит `<имя>.retro.json` (пишет навык), слайд «Ретро» становится
интерактивным: виджеты Activity (созвоны за вчера) и Tasks (сделанное, с id или без)
с панелью карточки справа — в ней обязательно «Источник»; вкладка «Описать ретро»
слева живёт внутри слайда и видна только на нём. Панели и заметка открываются через
CSS `:target` — работают и там, где скрипты запрещены; JS нужен только стрелкам и
автосохранению заметки в localStorage.
Пустые данные — «Данных не найдено», ничего не додумывается. Строка без `source`
— код выхода 1.

Формат входа — шаблон навыка `morning` (skills/morning/SKILL.md):
  # Утро {дата}            → титул
  KPI: a {n} · b {m} · …   → карточки на титуле
  ## Раздел                → один слайд
  ### Подраздел, таблицы GFM, списки `- `, **жирная строка**, [НЕТ ДАННЫХ: …]
Последний слайд — раздел «Нужны решения». Код выхода 1, если нет заголовка
`# ` или ни одного `## `: значит, отчёт не по шаблону — чинить отчёт.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from pathlib import Path

ID_RE = re.compile(r"\b(PO-\d+(?:…PO-\d+|…\d+)?|GDSLV-\d+)\b")
LATE_RE = re.compile(r"\s·\s(−\d+ д)")
KPI_RE = re.compile(r"^KPI:\s*(.+)$")

CSS = """
:root{--ink:#1b1b1f;--muted:#6b6f76;--line:#e3e5e8;--soft:#f6f7f8;--red:#b3261e;--amber:#8a5a00;--amber-bg:#fff4e5}
html,body{margin:0;height:100%;background:#111;color:var(--ink);font:16px/1.4 -apple-system,"Segoe UI",Roboto,sans-serif}
.deck{height:100%;overflow-y:auto;scroll-snap-type:y mandatory}
.slide{position:relative;box-sizing:border-box;min-height:100vh;scroll-snap-align:start;background:#fff;padding:48px 64px;display:flex;flex-direction:column;border-bottom:8px solid #111}
.slide>header{display:flex;justify-content:space-between;align-items:baseline;border-bottom:2px solid var(--ink);padding-bottom:8px;margin-bottom:22px}
.slide h2{font-size:28px;margin:0}.slide .n{color:var(--muted);font-size:14px}
h1{font-size:44px;margin:0 0 8px}.sub{color:var(--muted);font-size:18px;margin-bottom:40px}
.kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:20px}
.kpi{border:1px solid var(--line);border-radius:8px;padding:18px 20px}
.kpi b{display:block;font-size:40px;line-height:1;margin-bottom:6px}.kpi span{color:var(--muted);font-size:14px}
.kpi.red b{color:var(--red)}
table{border-collapse:collapse;width:100%;font-size:16px;margin:4px 0 14px}
th,td{text-align:left;padding:10px 12px;border-bottom:1px solid var(--line);vertical-align:top}
th{color:var(--muted);font-weight:600;background:var(--soft);font-size:14px}
.id{font-family:ui-monospace,Menlo,monospace;white-space:nowrap}
.late{display:inline-block;color:#fff;background:var(--red);border-radius:4px;padding:1px 6px;font-size:12px;margin-left:6px;vertical-align:middle}
.high{color:var(--red);font-weight:600}
.nodata{background:var(--amber-bg);color:var(--amber);padding:10px 14px;border-radius:6px;margin:0 0 14px}
.kr{font-weight:600;margin:8px 0 6px}
h3{font-size:15px;color:var(--muted);text-transform:uppercase;letter-spacing:.04em;margin:18px 0 8px}
ul{margin:0 0 12px;padding-left:20px}li{margin:4px 0}
.decisions li{font-size:20px;margin:10px 0}
.foot{margin-top:auto;padding-top:24px;color:var(--muted);font-size:14px}
code{font-family:ui-monospace,Menlo,monospace;font-size:14px;background:var(--soft);padding:1px 4px;border-radius:3px}
/* ретро: виджеты и панели по мотивам TaskSheet poh-okr-plugin */
.widgets{display:grid;grid-template-columns:1fr 1fr;gap:20px;margin-bottom:22px}
.widget{border:1px solid var(--line);border-radius:10px;overflow:hidden}
.widget>h4{margin:0;padding:10px 14px;font-size:13px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted);background:var(--soft);display:flex;justify-content:space-between}
.widget .empty{padding:14px;color:var(--muted);font-size:14px}
.row{display:flex;align-items:center;gap:10px;width:100%;box-sizing:border-box;padding:9px 14px;border:0;border-top:1px solid var(--line);background:transparent;text-align:left;cursor:pointer;font:inherit;color:var(--ink);text-decoration:none}
.row:hover{background:var(--soft)}
.row .t{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.row .m{color:var(--muted);font-size:13px;white-space:nowrap}
.check{flex-shrink:0;width:18px;height:18px;border-radius:50%;border:1.5px solid var(--muted);display:inline-flex;align-items:center;justify-content:center}
.check[data-done]{background:#8b8f96;border-color:#8b8f96}
.check[data-done]::after{content:"";width:9px;height:5px;margin-top:-2px;border-left:1.5px solid #fff;border-bottom:1.5px solid #fff;transform:rotate(-45deg)}
.check[data-priority=high]{border-color:#e5484d}.check[data-priority=medium]{border-color:#4c8dff}
.edge{position:absolute;left:0;top:50%;z-index:40;text-decoration:none;display:block;writing-mode:vertical-rl;transform:translateY(-50%) rotate(180deg);background:#d2302a;color:#fff;border:0;padding:16px 8px;font:600 13px/1 -apple-system,"Segoe UI",Roboto,sans-serif;letter-spacing:.08em;text-transform:uppercase;cursor:pointer}
.edge:hover{background:#b3261e}
.sheet .src{margin-top:18px;padding-top:12px;border-top:1px solid #2a2b2f;font-size:13px;color:#8b8f96;word-break:break-all}.sheet .src b{color:#d5d6da;font-weight:600}
.sheet .saved{padding:6px 18px;font-size:12px;color:#8b8f96}
.sheet{position:fixed;top:0;bottom:0;width:440px;max-width:96vw;display:none;flex-direction:column;z-index:44;background:#111214;color:#f0f0f2;box-shadow:0 0 24px rgba(0,0,0,.35);font-size:15px}
.sheet:target,.sheet[data-open]{display:flex}.sheet.right{right:0;border-left:1px solid #2a2b2f}.sheet.left{left:0;border-right:1px solid #2a2b2f}
.sheet .head{display:flex;align-items:center;gap:10px;padding:12px 16px;border-bottom:1px solid #2a2b2f}
.sheet .body{flex:1;overflow-y:auto;padding:14px 18px}
.sheet .title{font-size:20px;font-weight:700;line-height:1.3;padding-bottom:8px}
.sheet .desc{font-size:15px;line-height:1.55;color:#d5d6da;white-space:pre-wrap}
.sheet .foot{display:flex;align-items:center;gap:8px;padding:10px 14px;border-top:1px solid #2a2b2f;font-size:12px;color:#8b8f96}
.sheet .foot .grow{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.sheet .chip{display:inline-flex;align-items:center;gap:6px;padding:3px 8px;border-radius:8px;color:#4c8dff;font-size:14px}
.sheet a.ib{text-decoration:none}
.sheet .ib{width:28px;height:28px;border:0;border-radius:6px;background:transparent;color:#8b8f96;cursor:pointer;font-size:16px;display:inline-flex;align-items:center;justify-content:center}
.sheet .ib:hover{background:#1e1f23;color:#f0f0f2}
.sheet .flag{color:#e5484d}
.sheet textarea{flex:1;width:100%;box-sizing:border-box;resize:none;border:0;outline:0;background:transparent;color:#f0f0f2;font:15px/1.55 -apple-system,"Segoe UI",Roboto,sans-serif;padding:14px 18px}
@media(max-width:800px){.widgets{grid-template-columns:1fr}.slide{padding:28px 20px}.kpis{grid-template-columns:repeat(2,1fr)}h1{font-size:32px}}
@media print{.deck{overflow:visible}.slide{page-break-after:always;min-height:auto;border:0}}
"""

JS = """
const deck=document.querySelector('.deck');const slides=[...document.querySelectorAll('.slide')];
document.addEventListener('keydown',e=>{if(e.target.closest&&e.target.closest('textarea,input,[contenteditable]'))return;const i=Math.round(deck.scrollTop/window.innerHeight);
if(['ArrowDown','ArrowRight','PageDown',' '].includes(e.key)){e.preventDefault();slides[Math.min(i+1,slides.length-1)].scrollIntoView({behavior:'smooth'})}
if(['ArrowUp','ArrowLeft','PageUp'].includes(e.key)){e.preventDefault();slides[Math.max(i-1,0)].scrollIntoView({behavior:'smooth'})}
if(e.key==='Escape'){document.querySelectorAll('.sheet[data-open]').forEach(s=>s.removeAttribute('data-open'))}});
const drawer=document.getElementById('retro-note');
if(drawer){const key='morning-retro-'+drawer.dataset.date;const ta=drawer.querySelector('textarea');const saved=drawer.querySelector('.saved');
let stored=null;try{stored=localStorage.getItem(key)}catch(_){}
if(stored!==null)ta.value=stored;
ta.addEventListener('input',()=>{try{localStorage.setItem(key,ta.value);saved.textContent='сохранено в браузере '+new Date().toLocaleTimeString('ru-RU',{hour:'2-digit',minute:'2-digit'})}catch(_){saved.textContent='localStorage недоступен'}});}
"""


def inline(text: str) -> str:
    """Экранирование + подсветка id, бейдж просрочки, `код`, **жирный**."""
    out = html.escape(text, quote=False)
    out = re.sub(r"`([^`]+)`", r"<code>\1</code>", out)
    out = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", out)
    out = LATE_RE.sub(r' <span class="late">\1</span>', out)
    out = ID_RE.sub(r'<span class="id">\1</span>', out)
    return out


def cell(text: str) -> str:
    t = text.strip()
    cls = ' class="high"' if t == "HIGH" else ""
    return f"<td{cls}>{inline(t)}</td>"


def strip_frontmatter(lines: list[str]) -> list[str]:
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                return lines[i + 1:]
    return lines


def render_body(lines: list[str]) -> str:
    """Строки одного раздела → HTML."""
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        if not line.strip():
            i += 1
            continue
        if line.startswith("### "):
            out.append(f"<h3>{inline(line[4:])}</h3>")
            i += 1
        elif line.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                rows.append(lines[i])
                i += 1
            head = [c for c in rows[0].strip().strip("|").split("|")]
            body = [r for r in rows[2:]] if len(rows) > 1 and set(rows[1].replace("|", "").strip()) <= set("-: ") else rows[1:]
            out.append("<table><tr>" + "".join(f"<th>{inline(h.strip())}</th>" for h in head) + "</tr>")
            for r in body:
                out.append("<tr>" + "".join(cell(c) for c in r.strip().strip("|").split("|")) + "</tr>")
            out.append("</table>")
        elif line.startswith("- "):
            items = []
            while i < len(lines) and lines[i].startswith("- "):
                items.append(lines[i][2:])
                i += 1
            out.append("<ul>" + "".join(f"<li>{inline(x)}</li>" for x in items) + "</ul>")
        elif line.lstrip("(").startswith("[НЕТ ДАННЫХ"):
            out.append(f'<div class="nodata">{inline(line.strip("() "))}</div>')
            i += 1
        elif line.startswith("**") and line.rstrip().endswith("**"):
            out.append(f'<p class="kr">{inline(line.strip("*"))}</p>')
            i += 1
        elif line.startswith("Прочее:"):
            out.append(f'<div class="foot">{inline(line)}</div>')
            i += 1
        else:
            out.append(f"<p>{inline(line)}</p>")
            i += 1
    return "\n".join(out)


NOT_FOUND = "Данных не найдено"


def validate_retro(data: dict) -> None:
    """Каждая строка Tasks/Activity обязана нести `source`: панель показывает его всегда."""
    for kind in ("tasks", "activity"):
        for i, item in enumerate(data.get(kind, [])):
            if not str(item.get("source", "")).strip():
                raise ValueError(f"retro.json: {kind}[{i}] без поля source — откуда сведения?")
            if not str(item.get("title", "")).strip():
                raise ValueError(f"retro.json: {kind}[{i}] без title")


RETRO_ANCHOR = "retro"


def task_sheet(i: int, t: dict) -> str:
    pr = t.get("priority") or ""
    return (
        f'<aside class="sheet right" id="task-{i}" role="dialog"><div class="head">'
        f'<span class="check" data-done{" data-priority=\"" + html.escape(pr) + "\"" if pr else ""}></span>'
        f'<span class="chip">&#128197; {html.escape(t.get("done_at") or t.get("due") or "")}</span>'
        f'<span class="flag">{"&#9873;" if pr == "high" else ""}</span><span style="flex:1"></span>'
        f'<a class="ib" href="#{RETRO_ANCHOR}" aria-label="закрыть">&#8250;</a></div>'
        f'<div class="body"><div class="title">{html.escape(t.get("title", ""))}</div>'
        f'<div class="desc">{html.escape(t.get("description") or "")}</div>'
        f'<div class="src"><b>Источник:</b> {html.escape(t["source"])}</div></div>'
        f'<div class="foot"><span class="ib">&#9993;</span><span class="ib">&#127991;</span>'
        f'<span class="id">{html.escape(t.get("id") or "без id")}</span>'
        f'<span class="grow">{"&middot; " + html.escape(t["kr_title"]) if t.get("kr_title") else ""}</span>'
        f'<a class="ib" href="#{RETRO_ANCHOR}" aria-label="закрыть">&#10005;</a></div></aside>'
    )


def event_sheet(i: int, date: str, e: dict) -> str:
    span = html.escape(e.get("start", "")) + (f'–{html.escape(e["end"])}' if e.get("end") else "")
    who = ", ".join(e.get("with", []))
    return (
        f'<aside class="sheet right" id="event-{i}" role="dialog"><div class="head">'
        f'<span class="chip">&#128197; {html.escape(date)} {span}</span><span style="flex:1"></span>'
        f'<a class="ib" href="#{RETRO_ANCHOR}" aria-label="закрыть">&#8250;</a></div>'
        f'<div class="body"><div class="title">{html.escape(e.get("title", ""))}</div>'
        f'<div class="desc">{html.escape(who)}\n\n{html.escape(e.get("agenda") or "")}</div>'
        f'<div class="src"><b>Источник:</b> {html.escape(e["source"])}</div></div>'
        f'<div class="foot"><span class="grow">{html.escape(e.get("organizer") or "")}</span>'
        f'<a class="ib" href="#{RETRO_ANCHOR}" aria-label="закрыть">&#10005;</a></div></aside>'
    )


def retro_block(data: dict) -> tuple[str, str]:
    """Интерактивная часть слайда ретро без JS: панели и заметка открываются через :target."""
    validate_retro(data)
    date = data.get("date", "")
    activity = data.get("activity", [])
    tasks = data.get("tasks", [])
    act_rows = "".join(
        f'<a class="row" href="#event-{i}"><span class="m">{html.escape(e.get("start", ""))}</span>'
        f'<span class="t">{html.escape(e.get("title", ""))}</span>'
        f'<span class="m">{html.escape(", ".join(e.get("with", [])[:2]))}{" …" if len(e.get("with", [])) > 2 else ""}</span></a>'
        for i, e in enumerate(activity)
    ) or f'<div class="empty">{NOT_FOUND}</div>'
    task_rows = "".join(
        f'<a class="row" href="#task-{i}"><span class="check" data-done'
        f'{" data-priority=\"" + html.escape(t["priority"]) + "\"" if t.get("priority") else ""}></span>'
        + (f'<span class="id">{html.escape(t["id"])}</span>' if t.get("id") else "")
        + f'<span class="t">{html.escape(t.get("title", ""))}</span>'
        f'<span class="m">{html.escape(t.get("kr", "") or "")}</span></a>'
        for i, t in enumerate(tasks)
    ) or f'<div class="empty">{NOT_FOUND}</div>'
    widgets = (
        f'<a class="edge" href="#retro-note">Описать ретро</a>'
        f'<div class="widgets"><div class="widget"><h4><span>Activity</span><span>{len(activity)}</span></h4>{act_rows}</div>'
        f'<div class="widget"><h4><span>Tasks</span><span>{len(tasks)}</span></h4>{task_rows}</div></div>'
    )
    chrome = (
        "".join(task_sheet(i, t) for i, t in enumerate(tasks))
        + "".join(event_sheet(i, date, e) for i, e in enumerate(activity))
        + f'<aside class="sheet left" id="retro-note" role="dialog" aria-label="Ретро" data-date="{html.escape(date)}">'
        f'<div class="head"><span class="title" style="padding:0;font-size:16px">Ретро {html.escape(date)}</span><span style="flex:1"></span>'
        f'<a class="ib" href="#{RETRO_ANCHOR}" aria-label="закрыть">&#10005;</a></div>'
        f'<textarea spellcheck="false" placeholder="{NOT_FOUND}">{html.escape(data.get("note_draft") or "")}</textarea>'
        '<div class="saved"></div></aside>'
    )
    return widgets, chrome


def render(md: str, retro: dict | None = None) -> str:
    lines = strip_frontmatter(md.splitlines())
    title = next((l[2:].strip() for l in lines if l.startswith("# ")), None)
    if title is None:
        raise ValueError("нет заголовка `# Утро …`")
    kpis: list[tuple[str, str]] = []
    for l in lines:
        m = KPI_RE.match(l.strip())
        if m:
            for part in m.group(1).split("·"):
                words = part.strip().rsplit(" ", 1)
                if len(words) == 2:
                    kpis.append((words[0], words[1]))
            break
    sections: list[tuple[str, list[str]]] = []
    cur: list[str] | None = None
    for l in lines:
        if l.startswith("## "):
            cur = []
            sections.append((l[3:].strip(), cur))
        elif cur is not None and not l.startswith("# ") and not KPI_RE.match(l.strip()):
            cur.append(l)
    if not sections:
        raise ValueError("нет ни одного раздела `## `")

    total = len(sections) + 1
    slides = []
    subtitle = " · ".join(name.split(" — ")[0] for name, _ in sections)
    cards = "".join(
        f'<div class="kpi{" red" if v != "0" and ("просроч" in k or "риск" in k) else ""}"><b>{html.escape(v)}</b><span>{html.escape(k)}</span></div>'
        for k, v in kpis
    )
    slides.append(
        f'<section class="slide"><h1>{inline(title)}</h1><div class="sub">{html.escape(subtitle)}</div>'
        f'<div class="kpis">{cards}</div><div class="foot">Стрелки или прокрутка — следующий слайд. {total} слайдов.</div></section>'
    )
    chrome = ""
    for n, (name, body) in enumerate(sections, start=2):
        cls = ' class="decisions"' if name.startswith("Нужны решения") else ""
        inner = render_body(body)
        if cls:
            inner = inner.replace("<ul>", "<ul class=\"decisions\">", 1)
        attr = ""
        if retro is not None and name.startswith("Ретро"):
            widgets, chrome = retro_block(retro)
            inner = widgets + inner
            attr = f' id="{RETRO_ANCHOR}" data-retro'
        slides.append(
            f'<section class="slide"{attr}><header><h2>{inline(name)}</h2><span class="n">{n} / {total}</span></header>{inner}</section>'
        )
    return (
        "<!doctype html>\n<html lang=\"ru\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        f"<title>{html.escape(title)}</title><style>{CSS}</style></head><body><div class=\"deck\">\n"
        + "\n".join(slides)
        + f"\n</div>{chrome}<script>{JS}</script></body></html>\n"
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source", help="markdown отчёта")
    ap.add_argument("-o", "--output", help="куда писать html (по умолчанию рядом, .html)")
    ap.add_argument("--stdout", action="store_true")
    args = ap.parse_args()
    src = Path(args.source)
    sidecar = src.with_suffix(".retro.json")
    retro = None
    if sidecar.exists():
        try:
            retro = json.loads(sidecar.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            print(f"render: {sidecar}: битый JSON ({e}); слайд ретро без виджетов", file=sys.stderr)
    try:
        out = render(src.read_text(encoding="utf-8"), retro)
    except ValueError as e:
        print(f"render: {src}: {e}", file=sys.stderr)
        return 1
    if args.stdout:
        sys.stdout.write(out)
        return 0
    dst = Path(args.output) if args.output else src.with_suffix(".html")
    dst.write_text(out, encoding="utf-8")
    print(dst)
    return 0


if __name__ == "__main__":
    sys.exit(main())
