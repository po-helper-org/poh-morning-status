#!/usr/bin/env python3
"""Слайды утреннего отчёта из его markdown. Детерминированно, без LLM.

  render.py GROUND/PULSE/morning/2026-09-11.md            # → рядом .html
  render.py report.md -o out.html
  render.py report.md --stdout

Если рядом лежит `<имя>.retro.json` (пишет навык), слайд «Ретро» становится
интерактивным: виджеты Activity и Tasks, каждая строка открывает свою заметку —
блочный редактор (порт BlockEditor poh-okr-plugin): первая строка — название,
«/» — меню блоков, чеклисты, раздел «## Источники» обязателен. Панели — скрытые
radio/checkbox + label; без JS заметка показывается статичным рендером.
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
import datetime as dt
import html
import json
import re
import sys
from pathlib import Path

ID_RE = re.compile(r"\b(PO-\d+(?:…PO-\d+|…\d+)?|GDSLV-\d+)\b")
LATE_RE = re.compile(r"\s·\s(−\d+ д)")
KPI_RE = re.compile(r"^KPI:\s*(.+)$")

CSS = """
:root{--bg:#0f1012;--card:#141518;--ink:#e6e7ea;--muted:#8b8f96;--line:#2a2b2f;--soft:#1a1b1f;--red:#e5484d;--green:#1f9d55;--blue:#4c8dff;--amber:#e0a538;--amber-bg:#2a2210}
html,body{margin:0;height:100%;background:var(--bg);color:var(--ink);font:16px/1.4 -apple-system,"Segoe UI",Roboto,sans-serif}
.deck{height:100%;overflow-y:auto;scroll-snap-type:y mandatory}
.slide{position:relative;box-sizing:border-box;min-height:100vh;scroll-snap-align:start;background:var(--card);padding:48px 64px;display:flex;flex-direction:column;border-bottom:8px solid var(--bg)}
.slide>header{display:flex;justify-content:space-between;align-items:baseline;border-bottom:2px solid var(--line);padding-bottom:8px;margin-bottom:22px}
.slide h2{font-size:28px;margin:0}.slide .n{color:var(--muted);font-size:14px}
h1{font-size:44px;margin:0 0 8px}.sub{color:var(--muted);font-size:18px;margin-bottom:40px}
.kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:20px}
.kpi{border:1px solid var(--line);border-radius:8px;padding:18px 20px;background:var(--soft)}
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
/* виджеты слайда: строки открывают заметки */
.widgets{display:grid;grid-template-columns:1fr 1fr;gap:20px;margin-bottom:22px}
.widget{border:1px solid var(--line);border-radius:10px;overflow:hidden;background:var(--soft)}
.widget>h4{margin:0;padding:10px 14px;font-size:13px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted);background:var(--bg);display:flex;justify-content:space-between}
.widget .empty{padding:14px;color:var(--muted);font-size:14px}
.row{display:flex;align-items:center;gap:10px;width:100%;box-sizing:border-box;padding:9px 14px;border:0;border-top:1px solid var(--line);background:transparent;text-align:left;cursor:pointer;font:inherit;color:var(--ink);text-decoration:none}
.row:hover{background:#1e1f23}
.row .t{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.row .m{color:var(--muted);font-size:13px;white-space:nowrap}
.check{flex-shrink:0;width:18px;height:18px;border-radius:50%;border:1.5px solid var(--muted);display:inline-flex;align-items:center;justify-content:center}
.check[data-done]{background:var(--muted);border-color:var(--muted)}
.check[data-done]::after{content:"";width:9px;height:5px;margin-top:-2px;border-left:1.5px solid #fff;border-bottom:1.5px solid #fff;transform:rotate(-45deg)}
.check[data-priority=high]{border-color:var(--red)}.check[data-priority=medium]{border-color:var(--blue)}
/* вкладки на левом краю слайда: видны только на своём слайде */
.edge{position:absolute;left:0;z-index:40;text-decoration:none;display:block;box-sizing:border-box;writing-mode:vertical-rl;transform:rotate(180deg);background:var(--red);color:#fff;border:0;padding:16px 8px;font:600 13px/1 -apple-system,"Segoe UI",Roboto,sans-serif;letter-spacing:.08em;text-transform:uppercase;cursor:pointer;border-radius:0 6px 6px 0}
.edge[data-color=green]{background:var(--green)}.edge[data-color=blue]{background:var(--blue)}.edge[data-color=amber]{background:#b8860b}.edge[data-color=gray]{background:#4b4f58}
.widgets.one{grid-template-columns:1fr}.widget.wide{grid-column:1/-1}
.row.cols{display:grid;align-items:start;gap:14px}.row.cols>span{white-space:normal;overflow:hidden}
.row.cols .c{color:#c9ccd2;font-size:14px}.row.cols .h{font-weight:600}
.widget .cols-head{display:grid;gap:14px;padding:8px 14px;font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:.04em;border-top:1px solid var(--line)}
.row .ag{display:block;color:var(--muted);font-size:13px;white-space:normal;margin-top:2px}
.edge:hover{filter:brightness(1.15)}
.sheet{position:fixed;top:0;bottom:0;width:440px;max-width:92vw;display:none;flex-direction:column;z-index:44;background:#111214;color:#f0f0f2;box-shadow:0 0 24px rgba(0,0,0,.35);font-size:15px}
.toggle{position:absolute;opacity:0;width:0;height:0;pointer-events:none}
.toggle:checked~.sheet{display:flex}
.item{display:contents}
/* открытая панель не накрывает виджеты: слайд ретро ужимается на её ширину */
/* панель поверх экрана: подложка закрывает её кликом, задний слайд не меняется */
.scrim{display:none;position:fixed;inset:0;z-index:43;background:rgba(0,0,0,.45);cursor:pointer}
.toggle:checked~.scrim{display:block}
label.row,label.edge,label.ib{cursor:pointer}.sheet.right{right:0;border-left:1px solid #2a2b2f}.sheet.left{left:0;border-right:1px solid #2a2b2f}
.sheet .head{display:flex;align-items:center;gap:10px;padding:12px 16px;border-bottom:1px solid #2a2b2f}
.sheet .body{flex:1;overflow-y:auto;padding:14px 18px}
.sheet .title{font-size:20px;font-weight:700;line-height:1.3;padding-bottom:8px}
.sheet .foot{display:flex;align-items:center;gap:8px;padding:10px 14px;border-top:1px solid #2a2b2f;font-size:12px;color:#8b8f96}
.sheet a.ib{text-decoration:none}
.sheet .ib{width:28px;height:28px;border:0;border-radius:6px;background:transparent;color:#8b8f96;cursor:pointer;font-size:16px;display:inline-flex;align-items:center;justify-content:center}
.sheet .ib:hover{background:#1e1f23;color:#f0f0f2}
.sheet .saved{font-size:12px;color:#8b8f96;margin-left:auto}
.sheet .chip{display:inline-flex;align-items:center;gap:6px;padding:3px 8px;border-radius:8px;color:#4c8dff;font-size:14px}
.sheet .flag{color:#e5484d;font-size:16px}.sheet .flag[data-p=medium]{color:#4c8dff}.sheet .flag[data-p=low]{color:#2F9E6E}.sheet .flag[data-p=none]{color:#8b8f96}
.sheet .check{border-color:#8b8f96}.sheet .check[data-done]{background:#8b8f96;border-color:#8b8f96}
.nojs{position:fixed;left:0;right:0;bottom:0;z-index:30;background:#8a5a00;color:#fff;padding:8px 14px;font-size:13px;text-align:center}
.note-view[contenteditable]{outline:none;min-height:40vh}
/* календарь дня в левой панели */
.cal{padding:6px 0}.cal .ev{display:grid;grid-template-columns:96px 1fr;gap:12px;padding:10px 18px;border-bottom:1px solid var(--line)}
.cal .ev .tm{color:var(--blue);font-size:14px;white-space:nowrap}.cal .ev .tt{font-size:15px;color:var(--ink)}.cal .ev .wh{font-size:13px;color:var(--muted);margin-top:2px}.cal .ev .ag{font-size:13px;color:#b9bcc3;margin-top:4px;white-space:pre-wrap}
.cal .empty{padding:14px 18px;color:var(--muted)}
/* заметка: блочный редактор (порт BlockEditor poh-okr-plugin); без JS — статичный рендер .md */
.md{font-size:15px;line-height:1.55;color:#e6e7ea}.md h1{font-size:20px;margin:0 0 10px}.md h2{font-size:17px;margin:14px 0 6px}.md h3{font-size:15px;margin:12px 0 4px;color:#b9bcc3}
.md p{margin:6px 0}.md ul,.md ol{margin:4px 0 8px;padding-left:22px}.md li{margin:3px 0}.md ul.todo{list-style:none;padding-left:0}
.md li.todo{display:flex;align-items:flex-start;gap:8px}.md li.todo input{margin:5px 0 0;accent-color:#4c8dff}.md li.todo:has(input:checked) span{color:#8b8f96;text-decoration:line-through}
.md code{background:#1e1f23;padding:1px 4px;border-radius:3px;font-size:13px}.md blockquote{margin:6px 0;padding-left:10px;border-left:2px solid #3a3b40;color:#b9bcc3}
.md hr{border:0;height:1px;background:#2a2b2f;margin:12px 0}.md .empty{color:#8b8f96}
.editor{outline:none;font-size:15px;line-height:1.6;color:#e6e7ea;counter-reset:num;min-height:40vh}
.editor>*{margin:0;padding:2px 0;position:relative;min-height:1.6em}
.editor [data-block=title]{font-size:20px;font-weight:700;line-height:1.3;padding-bottom:8px;margin-bottom:6px;border-bottom:1px solid #2a2b2f}
.editor [data-block=title]:empty::before{content:"Название";color:#8b8f96}
.editor[data-empty] [data-block=text]:empty::before{content:attr(data-placeholder);color:#8b8f96}
.editor [data-block=h1]{font-size:20px;font-weight:700;padding-top:10px}.editor [data-block=h2]{font-size:17px;font-weight:700;padding-top:8px}.editor [data-block=h3]{font-size:15px;font-weight:600;padding-top:6px;color:#b9bcc3}
.editor [data-block=bullet],.editor [data-block=number]{padding-left:22px}
.editor [data-block=bullet]::before{content:"•";position:absolute;left:6px;color:#4c8dff}
.editor [data-block=number]{counter-increment:num}.editor [data-block=number]::before{content:counter(num) ".";position:absolute;left:2px;color:#8b8f96;font-size:13px}
.editor [data-block=quote]{padding-left:12px;color:#b9bcc3;border-left:2px solid #3a3b40}
.editor [data-block=divider]{padding:0;height:1px;background:#2a2b2f;margin:12px 0;min-height:1px}
.editor [data-block=todo]{position:relative;padding-left:26px;min-height:24px}
.editor .box{position:absolute;left:0;top:5px;width:16px;height:16px;border-radius:4px;border:1.5px solid #8b8f96;background:transparent;cursor:pointer;padding:0;display:flex;align-items:center;justify-content:center;user-select:none}
.editor .box[data-on]{background:#4c8dff;border-color:#4c8dff}.editor .box[data-on]::after{content:"";width:8px;height:4px;margin-top:-2px;border-left:1.5px solid #fff;border-bottom:1.5px solid #fff;transform:rotate(-45deg)}
.editor [data-block=todo][data-done]{color:#8b8f96;text-decoration:line-through}.editor [data-block=todo][data-done] .box{text-decoration:none}
.menu{position:absolute;z-index:60;min-width:260px;background:#1a1b1f;border:1px solid #2a2b2f;border-radius:10px;padding:6px;box-shadow:0 10px 30px rgba(0,0,0,.5)}
.menu button{display:flex;align-items:center;gap:14px;width:100%;border:0;background:transparent;color:#e6e7ea;font:15px/1.2 inherit;padding:9px 12px;border-radius:6px;text-align:left;cursor:pointer}
.menu button:hover,.menu button[data-active]{background:#26272c}.menu .g{width:22px;color:#8b8f96;font-size:13px;text-align:center}
@media(max-width:800px){.widgets{grid-template-columns:1fr}.slide{padding:28px 20px}.kpis{grid-template-columns:repeat(2,1fr)}h1{font-size:32px}}
@media print{.deck{overflow:visible}.slide{page-break-after:always;min-height:auto;border:0}}
"""

JS = r"""
const deck=document.querySelector('.deck');const slides=[...document.querySelectorAll('.slide')];
document.addEventListener('keydown',e=>{if(e.target.closest&&e.target.closest('textarea,input,[contenteditable]'))return;const i=Math.round(deck.scrollTop/window.innerHeight);
if(['ArrowDown','ArrowRight','PageDown',' '].includes(e.key)){e.preventDefault();slides[Math.min(i+1,slides.length-1)].scrollIntoView({behavior:'smooth'})}
if(['ArrowUp','ArrowLeft','PageUp'].includes(e.key)){e.preventDefault();slides[Math.max(i-1,0)].scrollIntoView({behavior:'smooth'})}
if(e.key==='Escape'){document.querySelectorAll('.sheet[data-open]').forEach(s=>s.removeAttribute('data-open'))}});
// ——— Блочный редактор заметки (порт BlockEditor из poh-okr-plugin, без React) ———
const TYPES=[['text','T','Текст'],['h1','H1','Заголовок 1'],['h2','H2','Заголовок 2'],['h3','H3','Заголовок 3'],['bullet','•','Маркированный список'],['number','1.','Нумерованный список'],['todo','☑','Пункт с галочкой'],['quote','❝','Цитата'],['divider','—','Разделитель']];
const CONT=new Set(['bullet','number','todo']);
function parseLine(l){if(/^(-{3,}|\*{3,}|_{3,})$/.test(l.trim()))return{type:'divider',text:'',done:false};let m;
if((m=/^[-*]\s+\[([ xX])\]\s?(.*)$/.exec(l)))return{type:'todo',text:m[2],done:m[1].toLowerCase()==='x'};
for(const [re,t] of [[/^###\s+(.*)$/,'h3'],[/^##\s+(.*)$/,'h2'],[/^#\s+(.*)$/,'h1'],[/^>\s?(.*)$/,'quote'],[/^[-*]\s+(.*)$/,'bullet'],[/^\d+[.)]\s+(.*)$/,'number']]){if((m=re.exec(l)))return{type:t,text:m[1],done:false}}
return{type:'text',text:l,done:false}}
function fmt(b){switch(b.type){case'title':return b.text;case'divider':return'---';case'h1':return'# '+b.text;case'h2':return'## '+b.text;case'h3':return'### '+b.text;case'bullet':return'- '+b.text;case'number':return'1. '+b.text;case'quote':return'> '+b.text;case'todo':return`- [${b.done?'x':' '}] `+b.text;default:return b.text}}
function shortcut(t){for(const [re,type] of [[/^###\s(.*)$/,'h3'],[/^##\s(.*)$/,'h2'],[/^#\s(.*)$/,'h1'],[/^>\s(.*)$/,'quote'],[/^[-*]\s\[[ xX]?\]\s?(.*)$/,'todo'],[/^\[[ xX]?\]\s?(.*)$/,'todo'],[/^[-*]\s(.*)$/,'bullet'],[/^\d+[.)]\s(.*)$/,'number']]){const m=re.exec(t);if(m)return{type,rest:m[1]}}return null}
function mountEditor(host,markdown,onChange){
const root=document.createElement('div');root.className='editor';root.contentEditable='true';root.spellcheck=false;
const lines=String(markdown||'').replace(/\r\n?/g,'\n').split('\n');
// Первая строка — название: неделимая часть заметки, любой длины.
const title=lines.shift()||'';const rest=lines.length?lines.map(parseLine):[{type:'text',text:'',done:false}];
const node=(b)=>{const n=document.createElement('div');n.setAttribute('data-block',b.type);
if(b.type==='divider'){n.contentEditable='false';return n}
if(b.type==='todo'){if(b.done)n.setAttribute('data-done','');const box=document.createElement('button');box.type='button';box.className='box';box.contentEditable='false';if(b.done)box.setAttribute('data-on','');
box.addEventListener('mousedown',e=>e.preventDefault());box.addEventListener('click',()=>{const on=!n.hasAttribute('data-done');n.toggleAttribute('data-done',on);box.toggleAttribute('data-on',on);emit()});
n.append(document.createTextNode(b.text),box);return n}
if(b.type==='text')n.setAttribute('data-placeholder','Текст, «/» — блоки');n.textContent=b.text;return n};
root.append(node({type:'title',text:title.replace(/^#\s+/,''),done:false}),...rest.map(node));
const text=n=>n.textContent||'';
const read=()=>[...root.children].map(n=>({type:n.getAttribute('data-block')||'text',text:text(n),done:n.hasAttribute('data-done')}));
const serialize=()=>{const ls=read().map(fmt);while(ls.length>1&&ls[ls.length-1].trim()==='')ls.pop();return ls.join('\n')};
const markEmpty=()=>{const only=root.children.length===2?root.children[1]:null;root.toggleAttribute('data-empty',!!only&&only.getAttribute('data-block')==='text'&&text(only).trim()==='')};
const emit=()=>{markEmpty();onChange(serialize(),text(root.firstElementChild))};
const cur=()=>{const sel=getSelection();if(!sel||!sel.rangeCount)return null;let n=sel.getRangeAt(0).startContainer;while(n&&n.parentElement&&n.parentElement!==root)n=n.parentElement;return n&&n.parentElement===root?n:null};
const focus=n=>{const r=document.createRange();const sel=getSelection();if(n.getAttribute('data-block')==='todo'){let t=n.firstChild;if(!t||t.nodeType!==3){t=document.createTextNode('');n.prepend(t)}r.setStart(t,t.textContent.length);r.collapse(true)}else{r.selectNodeContents(n);r.collapse(false)}sel.removeAllRanges();sel.addRange(r)};
let menu=null;const closeMenu=()=>{if(menu){menu.remove();menu=null}};
const setType=(n,type)=>{if(n.getAttribute('data-block')==='title')return;const rep=node({type,text:type==='divider'?'':text(n),done:false});n.replaceWith(rep);
if(type==='divider'){const after=node({type:'text',text:'',done:false});rep.after(after);focus(after)}else focus(rep);emit()};
const openMenu=(n)=>{closeMenu();menu=document.createElement('div');menu.className='menu';let active=0;
TYPES.forEach(([type,g,label],i)=>{const b=document.createElement('button');b.type='button';b.innerHTML=`<span class="g">${g}</span><span>${label}</span>`;if(i===0)b.setAttribute('data-active','');
b.addEventListener('mousedown',e=>e.preventDefault());b.addEventListener('click',()=>{n.textContent='';closeMenu();setType(n,type)});menu.append(b)});
menu.style.top=(n.offsetTop+n.offsetHeight+4)+'px';menu.style.left=n.offsetLeft+'px';host.append(menu);
const key=e=>{if(!menu){document.removeEventListener('keydown',key,true);return}const items=[...menu.querySelectorAll('button')];
if(e.key==='ArrowDown'||e.key==='ArrowUp'){e.preventDefault();e.stopPropagation();items[active].removeAttribute('data-active');active=(active+(e.key==='ArrowDown'?1:-1)+items.length)%items.length;items[active].setAttribute('data-active','')}
else if(e.key==='Enter'){e.preventDefault();e.stopPropagation();items[active].click();document.removeEventListener('keydown',key,true)}
else if(e.key==='Escape'){e.preventDefault();e.stopPropagation();closeMenu();if(text(n)==='/'){n.textContent='';focus(n);emit()}document.removeEventListener('keydown',key,true)}};
document.addEventListener('keydown',key,true)};
root.addEventListener('input',()=>{const n=cur();if(n){const t=text(n);const type=n.getAttribute('data-block');
if(type==='todo'){const box=n.querySelector('.box');if(box&&box.textContent){const stray=box.textContent;box.textContent='';let tn=n.firstChild;if(!tn||tn.nodeType!==3){tn=document.createTextNode('');n.prepend(tn)}tn.textContent+=stray;focus(n)}}
if(type!=='title'){if(t==='/'){openMenu(n);return}
if(menu&&t!=='/')closeMenu();
if(type==='text'){if(/^-{3,}$/.test(t.trim())){setType(n,'divider');return}const sc=shortcut(t);if(sc){n.textContent=sc.rest;setType(n,sc.type);return}}}}
emit()});
root.addEventListener('beforeinput',e=>{const n=cur();if(!n)return;const type=n.getAttribute('data-block')||'text';
if(e.inputType==='insertParagraph'||e.inputType==='insertLineBreak'){e.preventDefault();if(menu)return;
if(CONT.has(type)&&text(n).trim()===''){setType(n,'text');return}
const created=node({type:CONT.has(type)?type:'text',text:'',done:false});n.after(created);focus(created);emit();return}
if(e.inputType==='deleteContentBackward'&&type!=='title'&&text(n).trim()===''){e.preventDefault();
if(type!=='text'){setType(n,'text');return}const prev=n.previousElementSibling;if(!prev)return;n.remove();focus(prev);emit()}});
markEmpty();host.removeAttribute('contenteditable');host.replaceChildren(root);return{serialize}}
// при смене слайда открытые панели закрываются: вкладки принадлежат своему слайду
(()=>{let active=null;const io=new IntersectionObserver(es=>{es.forEach(en=>{if(en.isIntersecting&&active!==en.target){if(active!==null){document.querySelectorAll('.toggle:checked').forEach(t=>{t.checked=false});const none=document.getElementById('sheet-none');if(none)none.checked=true}active=en.target}})},{threshold:.6});slides.forEach(sl=>io.observe(sl))})();
document.querySelectorAll('.note').forEach(note=>{const key='morning-note-'+note.dataset.key;const src=note.querySelector('textarea.src');const host=note.querySelector('.note-view');const saved=note.querySelector('.saved');
let stored=null;try{stored=localStorage.getItem(key)}catch(_){}
const initial=stored??(src?src.value:'');
const rowTitle=note.dataset.row?document.querySelector(`label.row[for="${note.dataset.row}"] .t`):null;
mountEditor(host,initial,(mdText,title)=>{try{localStorage.setItem(key,mdText);saved.textContent='сохранено '+new Date().toLocaleTimeString('ru-RU',{hour:'2-digit',minute:'2-digit'})}catch(_){saved.textContent='localStorage недоступен'}
if(rowTitle)rowTitle.textContent=title});
if(stored!==null&&rowTitle)rowTitle.textContent=initial.split('\n')[0]});
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


def validate_notes(data: dict, kinds: tuple[str, ...]) -> None:
    """Каждая заметка: первая строка — название, внутри обязателен раздел «Источники»."""
    for kind in kinds:
        for i, item in enumerate(data.get(kind, [])):
            note = str(item.get("note", ""))
            first = note.strip().splitlines()[0:1]
            if not first or not first[0].strip():
                raise ValueError(f"json: {kind}[{i}] без note — первая строка заметки и есть название")
            if not re.search(r"^#{1,3}\s*Источники\s*$", note, re.M | re.I):
                raise ValueError(f"json: {kind}[{i}]: в note нет раздела «## Источники» — откуда сведения?")


RETRO_TEMPLATE = (
    "## Что было сделано\n\n## Как это влияет на цели спринта\n\n"
    "## Как это влияет на цели квартала\n\n## Что не получилось сделать\n"
)
PLAN_TEMPLATE = "## Задачи\n\n## Созвоны\n\n## Договорённости\n\n## Риски\n"

H_RE = re.compile(r"^(#{1,3})\s+(.*)$")
TODO_RE = re.compile(r"^\s*[-*]\s+\[([ xX])\]\s+(.*)$")
UL_RE = re.compile(r"^\s*[-*]\s+(.*)$")
OL_RE = re.compile(r"^\s*\d+[.)]\s+(.*)$")
Q_RE = re.compile(r"^>\s?(.*)$")


DIVIDER_RE = re.compile(r"^(-{3,}|\*{3,}|_{3,})$")


def md_to_html(src: str, first_is_title: bool = False) -> str:
    """Markdown заметки → HTML: заголовки, списки, чеклисты, цитаты, разделители, **жирный**, `код`.
    Статичный рендер для просмотра без JS; с JS вместо него монтируется блочный редактор."""
    out: list[str] = []
    state: str | None = None
    lines = src.splitlines()
    if first_is_title and lines:
        out.append(f'<h1 class="title">{inline(lines[0].lstrip("# ").strip()) or NOT_FOUND}</h1>')
        lines = lines[1:]

    def close() -> None:
        nonlocal state
        if state:
            out.append(f"</{state.split(' ')[0]}>")
            state = None

    for raw in lines:
        line = raw.rstrip()
        if DIVIDER_RE.match(line.strip()):
            close(); out.append("<hr>")
        elif (m := H_RE.match(line)):
            close(); out.append(f"<h{len(m[1])}>{inline(m[2])}</h{len(m[1])}>")
        elif (m := TODO_RE.match(line)):
            if state != 'ul class="todo"':
                close(); out.append('<ul class="todo">'); state = 'ul class="todo"'
            out.append(f'<li class="todo"><input type="checkbox"{"" if m[1] == " " else " checked"}><span>{inline(m[2])}</span></li>')
        elif (m := UL_RE.match(line)):
            if state != "ul":
                close(); out.append("<ul>"); state = "ul"
            out.append(f"<li>{inline(m[1])}</li>")
        elif (m := OL_RE.match(line)):
            if state != "ol":
                close(); out.append("<ol>"); state = "ol"
            out.append(f"<li>{inline(m[1])}</li>")
        elif (m := Q_RE.match(line)):
            close(); out.append(f"<blockquote>{inline(m[1])}</blockquote>")
        elif line.strip() == "":
            close()
        else:
            close(); out.append(f"<p>{inline(line)}</p>")
    close()
    return "".join(out) or f'<p class="empty">{NOT_FOUND}</p>'


def day_label(value: str, today: str) -> str:
    """Дата чипа как в okr-плагине: «Сегодня», «Вчера», иначе ДД.ММ."""
    if not value:
        return ""
    try:
        d = dt.date.fromisoformat(value); t = dt.date.fromisoformat(today)
    except ValueError:
        return value
    delta = (d - t).days
    if delta == 0:
        return "Сегодня"
    if delta == -1:
        return "Вчера"
    if delta == 1:
        return "Завтра"
    return d.strftime("%d.%m")


def head_chips(item: dict | None, report_date: str) -> str:
    """Шапка панели: чек, дата, приоритет — референс TaskSheet poh-okr-plugin. Без данных — пусто."""
    if item is None:
        return ""
    done = item.get("done_at") or ""
    due = item.get("due") or ""
    pr = item.get("priority") or ""
    date = day_label(done or due, report_date)
    parts = [f'<span class="check"{" data-done" if done else ""} aria-label="{"сделано" if done else "открыто"}"></span>']
    if date:
        parts.append(f'<span class="chip" title="{html.escape(done or due)}">&#128197; {html.escape(date)}</span>')
    if item.get("start"):
        parts.append(f'<span class="chip">{html.escape(item["start"])}{"–" + html.escape(item["end"]) if item.get("end") else ""}</span>')
    if pr:
        parts.append(f'<span class="flag" data-p="{html.escape(pr)}" title="приоритет {html.escape(pr)}">&#9873;</span>')
    return "".join(parts)


def note_panel(key: str, side: str, text: str, close_for: str, row: str = "", head: str = "") -> str:
    """Панель-заметка: шапка с чипами, дальше заметка. Первая строка — название, «Источники» — раздел внутри.
    Без JS — статичный рендер; с JS монтируется редактор из markdown в скрытом <textarea class=src>."""
    payload = html.escape(text)   # в textarea сущности декодируются, теги не парсятся
    return (
        f'<aside class="sheet {side} note" role="dialog" data-key="{html.escape(key)}"{f" data-row=\"{row}\"" if row else ""}>'
        f'<div class="head">{head}<span style="flex:1"></span>'
        '<noscript><span class="chip" style="color:#e0a538;font-size:12px" title="Откройте файл в Safari или Chrome">без скриптов: только текст, меню «/» недоступно</span></noscript>'
        f'<label class="ib" for="{close_for}" role="button" aria-label="закрыть">&#10005;</label></div>'
        f'<div class="body"><textarea class="src" hidden>{payload}</textarea>'
        f'<div class="note-view md" contenteditable="true" spellcheck="false">{md_to_html(text, first_is_title=True)}</div></div>'
        f'<div class="foot"><span class="saved"></span></div></aside>'
    )


def item(input_id: str, row: str, sheet: str) -> str:
    """Строка виджета + её панель: скрытый radio, label-строка, панель — без JS и без переходов."""
    return (
        f'<div class="item"><input class="toggle" type="radio" name="sheet" id="{input_id}">'
        f'<label class="row" for="{input_id}">{row}</label><label class="scrim" for="sheet-none" aria-hidden="true"></label>{sheet}</div>'
    )


def note_title(note: str) -> str:
    return note.strip().splitlines()[0].lstrip("# ").strip()


def resolve_today(data: dict, fallback_shift: int) -> tuple[str, str]:
    """(дата данных, «сегодня» для чипов). Ретро: today = date + 1, сегодня: today = date."""
    date = data.get("date", "")
    today = data.get("today") or (
        (dt.date.fromisoformat(date) + dt.timedelta(days=fallback_shift)).isoformat()
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", date) else date
    )
    return date, today


def widget(title: str, rows: list[str]) -> str:
    return (
        f'<div class="widget"><h4><span>{html.escape(title)}</span><span>{len(rows)}</span></h4>'
        + ("".join(rows) or f'<div class="empty">{NOT_FOUND}</div>') + "</div>"
    )


def note_rows(prefix: str, items: list[dict], date: str, today: str, kind: str) -> list[str]:
    """Строки виджета с заметками: kind — task (чек, id, kr/срок) или event (время, участники)."""
    rows = []
    for i, it in enumerate(items):
        rid = f"{prefix}-{i}"
        if kind == "event":
            label = (f'<span class="m">{html.escape(it.get("start", ""))}</span><span class="t">{html.escape(note_title(it["note"]))}</span>'
                     f'<span class="m">{html.escape(", ".join(it.get("with", [])[:2]))}{" …" if len(it.get("with", [])) > 2 else ""}</span>')
            head = head_chips({"done_at": date, "start": it.get("start", ""), "end": it.get("end", "")}, today)
        else:
            done = it.get("done_at")
            pr = it.get("priority") if not done else None
            meta = it.get("kr") or (day_label(it.get("due", ""), today) if it.get("due") else "")
            label = (f'<span class="check"{" data-done" if done else ""}{f" data-priority=\"{html.escape(pr)}\"" if pr else ""}></span>'
                     + (f'<span class="id">{html.escape(it["id"])}</span>' if it.get("id") else "")
                     + f'<span class="t">{html.escape(note_title(it["note"]))}</span><span class="m">{html.escape(meta)}</span>')
            head = head_chips(it, today)
        rows.append(item(rid, label, note_panel(f"{date}-{rid}", "right", it["note"], "sheet-none", rid, head)))
    return rows


def edge_note(edge_id: str, label: str, color: str, top: str, key: str, text: str, head: str) -> tuple[str, str]:
    """Вкладка на краю слайда + левая панель-заметка (checkbox-hack)."""
    tab = f'<label class="edge" data-color="{color}" style="top:{top}" for="{edge_id}" role="button">{html.escape(label)}</label>'
    sheet = (
        f'<div class="item"><input class="toggle left-toggle" type="checkbox" id="{edge_id}"><label class="scrim" for="{edge_id}" aria-hidden="true"></label>'
        + note_panel(key, "left", text, edge_id, "", head).replace('class="sheet left note"', f'class="sheet left note" id="{edge_id}-sheet"')
        + "</div>"
    )
    return tab, sheet


def calendar_sheet(edge_id: str, label: str, top: str, date: str, events: list[dict]) -> tuple[str, str]:
    """Вкладка «Календарь» + левая панель со списком созвонов дня (только чтение)."""
    tab = f'<label class="edge" data-color="blue" style="top:{top}" for="{edge_id}" role="button">{html.escape(label)}</label>'
    evs = "".join(
        f'<div class="ev"><div class="tm">{html.escape(e.get("start", ""))}{"–" + html.escape(e["end"]) if e.get("end") else ""}</div>'
        f'<div><div class="tt">{html.escape(e.get("title", ""))}</div>'
        + (f'<div class="wh">{html.escape(", ".join(e.get("with", [])))}</div>' if e.get("with") else "")
        + (f'<div class="ag">{html.escape(e["agenda"])}</div>' if e.get("agenda") else "")
        + "</div></div>"
        for e in events
    ) or f'<div class="empty">{NOT_FOUND}</div>'
    sheet = (
        f'<div class="item"><input class="toggle left-toggle" type="checkbox" id="{edge_id}"><label class="scrim" for="{edge_id}" aria-hidden="true"></label>'
        f'<aside class="sheet left" role="dialog" id="{edge_id}-sheet" aria-label="{html.escape(label)}">'
        f'<div class="head"><span class="chip">&#128197; {html.escape(date)}</span><span class="chip">{len(events)} созвон.</span><span style="flex:1"></span>'
        f'<label class="ib" for="{edge_id}" role="button" aria-label="закрыть">&#10005;</label></div>'
        f'<div class="body" style="padding:0"><div class="cal">{evs}</div></div></aside></div>'
    )
    return tab, sheet


def compose_note(item: dict, title_key: str, sections: list[tuple[str, str]]) -> str:
    """Заметка из полей: первая строка — название, разделы по ключам, «Источники» из sources.
    Если у элемента уже есть `note` — берётся как есть."""
    if item.get("note"):
        return item["note"]
    lines = [str(item.get(title_key, "")).strip()]
    for key, heading in sections:
        val = item.get(key)
        if not val:
            continue
        lines.append(f"## {heading}")
        if isinstance(val, list):
            lines.extend(f"- {v}" for v in val)
        else:
            lines.append(str(val))
        lines.append("")
    src = item.get("sources") or []
    if src:
        lines.append("## Источники")
        lines.extend(f"- {v}" for v in src)
    return "\n".join(lines).strip() + "\n"


def table_rows(prefix: str, items: list[dict], notes: list[str], cols: list[str], widths: str, date: str, today: str, heads: list[str]) -> list[str]:
    """Табличные строки виджета: каждая — label с колонками, клик открывает заметку."""
    rows = []
    for i, (it, note, head) in enumerate(zip(items, notes, heads)):
        rid = f"{prefix}-{i}"
        cells = "".join(
            f'<span class="{"t h" if j == 0 else "c"}">{inline(str(it.get(c, "") or "—"))}</span>' for j, c in enumerate(cols)
        )
        rows.append(item(rid, cells, note_panel(f"{date}-{rid}", "right", note, "sheet-none", rid, head)).replace(
            '<label class="row" for=', f'<label class="row cols" style="grid-template-columns:{widths}" for=', 1))
    return rows


def cols_head(names: list[str], widths: str) -> str:
    return f'<div class="cols-head" style="grid-template-columns:{widths}">' + "".join(f"<span>{html.escape(n)}</span>" for n in names) + "</div>"


def table_widget(title: str, names: list[str], widths: str, rows: list[str]) -> str:
    body = (cols_head(names, widths) + "".join(rows)) if rows else f'<div class="empty">{NOT_FOUND}</div>'
    return f'<div class="widget wide"><h4><span>{html.escape(title)}</span><span>{len(rows)}</span></h4>{body}</div>'


def retro_block(data: dict) -> tuple[str, str]:
    """Слайд ретро: Activity/Tasks с заметками, вкладка «Описать ретро» (красная)."""
    validate_notes(data, ("tasks", "activity"))
    date, today = resolve_today(data, 1)
    act = note_rows("event", data.get("activity", []), date, today, "event")
    tasks = note_rows("task", data.get("tasks", []), date, today, "task")
    note = data.get("note_draft") or ""
    if not note.strip():
        note = f"Ретро {date}\n" + RETRO_TEMPLATE
    elif not note.lstrip().startswith("Ретро"):
        note = f"Ретро {date}\n" + note
    tab, sheet = edge_note("retro-note", "Описать ретро", "red", "50%", f"{date}-retro", note, head_chips({"done_at": date}, today))
    return tab + f'<div class="widgets">{widget("Activity", act)}{widget("Tasks", tasks)}</div>', sheet


def today_block(data: dict) -> tuple[str, str]:
    """Слайд «Сегодня»: Задачи/Договорённости с заметками, вкладки «План на сегодня» (зелёная) и «Календарь»."""
    validate_notes(data, ("tasks", "controls"))
    date, today = resolve_today(data, 0)
    tasks = note_rows("todo", data.get("tasks", []), date, today, "task")
    controls = note_rows("ctl", data.get("controls", []), date, today, "task")
    plan = data.get("plan_draft") or ""
    if not plan.strip():
        plan = f"План на сегодня {date}\n" + PLAN_TEMPLATE
    elif not plan.lstrip().startswith("План"):
        plan = f"План на сегодня {date}\n" + plan
    tab1, sheet1 = edge_note("plan-note", "План на сегодня", "green", "38%", f"{date}-plan", plan, head_chips({"due": date}, today))
    calendar = data.get("calendar", [])
    tab2, sheet2 = calendar_sheet("today-calendar", "Календарь", "62%", date, calendar)
    # ключевые встречи — созвоны с key: true (не ритуалы): время, тема, повестка; клик — заметка
    key_events = [e for e in calendar if e.get("key")]
    for e in key_events:
        e.setdefault("note", compose_note(e, "title", [("agenda", "Повестка"), ("goal", "Что получить")]))
        if "## Источники" not in e["note"] and e.get("source"):
            e["note"] += f"\n## Источники\n- {e['source']}\n"
    validate_notes({"meetings": key_events}, ("meetings",))
    meetings = []
    for i, e in enumerate(key_events):
        rid = f"meet-{i}"
        label = (f'<span class="m">{html.escape(e.get("start", ""))}{"–" + html.escape(e["end"]) if e.get("end") else ""}</span>'
                 f'<span class="t">{html.escape(e.get("title", ""))}'
                 + (f'<span class="ag">{html.escape(e["agenda"])}</span>' if e.get("agenda") else "") + '</span>'
                 f'<span class="m">{html.escape(", ".join(e.get("with", [])[:2]))}</span>')
        meetings.append(item(rid, label, note_panel(f"{date}-{rid}", "right", e["note"], "sheet-none", rid,
                                                   head_chips({"due": date, "start": e.get("start", ""), "end": e.get("end", "")}, today))))
    widgets = (f'<div class="widgets">{widget("Мои задачи", tasks)}{widget("Договорённости", controls)}'
               + widget("Ключевые встречи", meetings).replace('class="widget"', 'class="widget wide"', 1) + "</div>")
    return tab1 + tab2 + widgets, sheet1 + sheet2


def risks_block(data: dict) -> tuple[str, str]:
    """Слайд рисков: таблица OKR · Название · Последствия, клик — описание; слева «Актуализация рисков»."""
    date, today = resolve_today(data, 0)
    risks = data.get("risks", [])
    notes = [compose_note(r, "title", [("description", "Описание"), ("consequence", "Последствия"), ("owner", "Владелец"), ("status", "Статус")]) for r in risks]
    validate_notes({"risks": [{"note": n} for n in notes]}, ("risks",))
    heads = [head_chips({"priority": r.get("priority"), "due": r.get("due")}, today) if (r.get("priority") or r.get("due")) else "" for r in risks]
    rows = table_rows("risk", risks, notes, ["kr", "title", "consequence"], "1fr 2fr 2fr", date, today, heads)
    note = data.get("review_draft") or ""
    if not note.strip():
        note = f"Актуализация рисков {date}\n## Новые\n\n## Изменились\n\n## Сняты\n\n## Нужно решение\n"
    elif not note.lstrip().startswith("Актуализация"):
        note = f"Актуализация рисков {date}\n" + note
    tab, sheet = edge_note("risks-note", "Актуализация рисков", "amber", "50%", f"{date}-risks", note, head_chips({"due": date}, today))
    return tab + f'<div class="widgets one">{table_widget("Риски по OKR", ["OKR", "Название", "Последствия"], "1fr 2fr 2fr", rows)}</div>', sheet


def team_summary(team: dict) -> str:
    """Сводный текст по историям команды — умолчание заметки «Комментарий»."""
    lines = []
    for st in team.get("stories", []):
        lines.append(f"## {st.get('id', '')} {st.get('title', '')}".strip())
        for key, heading in (("done", "Что уже сделано"), ("left", "Что осталось"), ("blockers", "Какие есть блокаторы"), ("next", "Какой следующий шаг")):
            val = st.get(key)
            if isinstance(val, dict):
                val = " · ".join(str(v) for v in (val.get("date"), val.get("text"), val.get("who")) if v)
            lines.append(f"{heading}: {val or '—'}")
        lines.append("")
    return "\n".join(lines)


def teams_blocks(data: dict) -> list[tuple[str, str, str]]:
    """По слайду на команду: (название слайда, содержимое, панели)."""
    date, today = resolve_today(data, 0)
    out = []
    for k, team in enumerate(data.get("teams", [])):
        name = team.get("name", f"Команда {k + 1}")
        stories = team.get("stories", [])
        for st in stories:
            nx = st.get("next")
            if isinstance(nx, dict):
                st["next_text"] = " · ".join(str(v) for v in (nx.get("date"), nx.get("text"), nx.get("who")) if v)
            else:
                st["next_text"] = nx or ""
            st["story"] = f"{st.get('id', '')} {st.get('title', '')}".strip()
        notes = [compose_note(st, "story", [("done", "Что сделано"), ("left", "Что осталось"), ("blockers", "Блокаторы"), ("next_text", "Следующий шаг"), ("pulse", "Пульс спринта")]) for st in stories]
        validate_notes({"stories": [{"note": n} for n in notes]}, ("stories",))
        heads = [head_chips({"due": (st.get("next") or {}).get("date") if isinstance(st.get("next"), dict) else "", "priority": st.get("priority")}, today) for st in stories]
        rows = table_rows(f"story-{k}", stories, notes, ["story", "done", "left", "next_text"], "1.6fr 1.4fr 1.4fr 1.6fr", date, today, heads)
        comment = team.get("comment_draft") or ""
        if not comment.strip():
            comment = f"Комментарий по команде {name} {date}\n" + team_summary(team)
        elif not comment.lstrip().startswith("Комментарий"):
            comment = f"Комментарий по команде {name} {date}\n" + comment
        agreements = team.get("agreements_draft") or ""
        if not agreements.strip():
            agreements = f"Договорённости с командой {name}\n" + "".join(
                f"- [{'x' if a.get('done') else ' '}] {a.get('what', '')} · от {a.get('from', '—')} · {a.get('when', '—')} · для {a.get('to', '—')}\n"
                for a in team.get("agreements", [])
            )
        elif not agreements.lstrip().startswith("Договорённости"):
            agreements = f"Договорённости с командой {name}\n" + agreements
        tab1, sheet1 = edge_note(f"team-{k}-comment", "Комментарий", "green", "38%", f"{date}-team-{k}-comment", comment, head_chips({"due": date}, today))
        tab2, sheet2 = edge_note(f"team-{k}-agree", "Договорённости", "gray", "62%", f"{date}-team-{k}-agree", agreements, "")
        sprint = data.get("sprint", "")
        body = tab1 + tab2 + f'<div class="widgets one">{table_widget(f"Истории {sprint}".strip(), ["История", "Что сделано", "Что осталось", "Следующий шаг"], "1.6fr 1.4fr 1.4fr 1.6fr", rows)}</div>'
        out.append((f"Команда {name}", body, sheet1 + sheet2))
    return out





def render(md: str, retro: dict | None = None, today: dict | None = None, risks: dict | None = None, teams: dict | None = None) -> str:
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

    if teams is not None and teams.get("teams"):
        # «Статус по командам» разворачивается в слайд на команду
        expanded: list[tuple[str, list[str]]] = []
        for name, body in sections:
            if name.startswith("Статус по командам"):
                expanded.extend((f"__team__{k}", []) for k in range(len(teams["teams"])))
            else:
                expanded.append((name, body))
        sections = expanded
    total = len(sections) + 1
    slides = []
    team_slides = teams_blocks(teams) if teams is not None and teams.get("teams") else []
    subtitle = " · ".join(
        (team_slides[int(name[8:])][0] if name.startswith("__team__") else name.split(" — ")[0]) for name, _ in sections
    )
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
            inner, extra = retro_block(retro)   # таблица из markdown не нужна: ретро живёт в заметках
            chrome += extra
            attr = ' id="retro" data-widgets data-retro'
        elif today is not None and name.startswith("Сегодня"):
            inner, extra = today_block(today)   # созвоны — в панели «Календарь»
            chrome += extra
            attr = ' id="today" data-widgets data-today'
        elif risks is not None and name.startswith("Риски"):
            inner, extra = risks_block(risks)
            chrome += extra
            attr = ' id="risks" data-widgets data-risks'
        elif name.startswith("__team__"):
            k = int(name[8:])
            name, inner, extra = team_slides[k]
            chrome += extra
            attr = f' id="team-{k}" data-widgets data-team'
        slides.append(
            f'<section class="slide"{attr}><header><h2>{inline(name)}</h2><span class="n">{n} / {total}</span></header>{inner}</section>'
        )
    return (
        "<!doctype html>\n<html lang=\"ru\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        f"<title>{html.escape(title)}</title><style>{CSS}</style></head><body>"
        "<noscript><div class=\"nojs\">Скрипты отключены: заметки только для чтения, правка и меню «/» недоступны. Откройте файл в Safari или Chrome.</div></noscript><div class=\"deck\">\n"
        + "\n".join(slides)
        + ("\n</div><input class=\"toggle\" type=\"radio\" name=\"sheet\" id=\"sheet-none\" checked>" if chrome else "\n</div>")
        + f"{chrome}<script>{JS}</script></body></html>\n"
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source", help="markdown отчёта")
    ap.add_argument("-o", "--output", help="куда писать html (по умолчанию рядом, .html)")
    ap.add_argument("--stdout", action="store_true")
    args = ap.parse_args()
    src = Path(args.source)
    def sidecar(suffix: str) -> dict | None:
        path = src.with_suffix(suffix)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            print(f"render: {path}: битый JSON ({e}); слайд без виджетов", file=sys.stderr)
            return None
    try:
        out = render(src.read_text(encoding="utf-8"), sidecar(".retro.json"), sidecar(".today.json"), sidecar(".risks.json"), sidecar(".teams.json"))
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
