#!/usr/bin/env python3
"""Слайды утреннего отчёта из его markdown. Детерминированно, без LLM.

  render.py GROUND/PULSE/morning/2026-09-11.md            # → рядом .html
  render.py report.md -o out.html
  render.py report.md --stdout

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
.slide{box-sizing:border-box;min-height:100vh;scroll-snap-align:start;background:#fff;padding:48px 64px;display:flex;flex-direction:column;border-bottom:8px solid #111}
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
@media(max-width:800px){.slide{padding:28px 20px}.kpis{grid-template-columns:repeat(2,1fr)}h1{font-size:32px}}
@media print{.deck{overflow:visible}.slide{page-break-after:always;min-height:auto;border:0}}
"""

JS = """
const deck=document.querySelector('.deck');const slides=[...document.querySelectorAll('.slide')];
document.addEventListener('keydown',e=>{const i=Math.round(deck.scrollTop/window.innerHeight);
if(['ArrowDown','ArrowRight','PageDown',' '].includes(e.key)){e.preventDefault();slides[Math.min(i+1,slides.length-1)].scrollIntoView({behavior:'smooth'})}
if(['ArrowUp','ArrowLeft','PageUp'].includes(e.key)){e.preventDefault();slides[Math.max(i-1,0)].scrollIntoView({behavior:'smooth'})}});
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


def render(md: str) -> str:
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
    for n, (name, body) in enumerate(sections, start=2):
        cls = ' class="decisions"' if name.startswith("Нужны решения") else ""
        inner = render_body(body)
        if cls:
            inner = inner.replace("<ul>", "<ul class=\"decisions\">", 1)
        slides.append(
            f'<section class="slide"><header><h2>{inline(name)}</h2><span class="n">{n} / {total}</span></header>{inner}</section>'
        )
    return (
        "<!doctype html>\n<html lang=\"ru\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        f"<title>{html.escape(title)}</title><style>{CSS}</style></head><body><div class=\"deck\">\n"
        + "\n".join(slides)
        + f"\n</div><script>{JS}</script></body></html>\n"
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source", help="markdown отчёта")
    ap.add_argument("-o", "--output", help="куда писать html (по умолчанию рядом, .html)")
    ap.add_argument("--stdout", action="store_true")
    args = ap.parse_args()
    src = Path(args.source)
    try:
        out = render(src.read_text(encoding="utf-8"))
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
