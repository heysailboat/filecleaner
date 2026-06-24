"""
preview_html.py — self-contained HTML for --dry-run, with summary bar + duplicate grouping
"""
from __future__ import annotations

import datetime
import json
import webbrowser
from pathlib import Path
import html as _html

from .models import FileInfo, FileDecision, Destination
from .html_utils import _script_json


def _size_str(size: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.0f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


def _serialize(items: list[tuple[FileInfo, FileDecision]]) -> list[dict]:
    # group duplicates by their base name (strip DUPLICATE_ prefix)
    # so the JS can render them grouped
    out = []
    for fi, dec in items:
        name = dec.new_name or fi.path.name
        group_id = None
        if dec.category == "duplicate" and dec.new_name:
            # group key = the original filename without DUPLICATE_ prefix
            group_id = fi.path.name
        out.append({
            "name":        name,
            "dir":         str(fi.path.parent),
            "size":        _size_str(fi.size),
            "category":    dec.category,
            "subcategory": dec.subcategory,
            "destination": dec.destination.value,
            "reason":      dec.reason,
            "group_id":    group_id,
        })
    return out


_HTML = '''\
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>cleanwave dry run — {date}</title>
<style>
:root {{
  --bg:      #181511;
  --surface: #211e19;
  --border:  #2e2a24;
  --text:    #e2d9c8;
  --muted:   #7a7060;
  --amber:   #c9a96e;
  --red:     #d97070;
  --orange:  #d4895a;
  --purple:  #9b8ab8;
  --green:   #7aad7a;
  --font:    -apple-system,"Segoe UI",system-ui,sans-serif;
  --mono:    "SF Mono","Fira Code","Cascadia Code",monospace;
}}
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
body{{background:var(--bg);color:var(--text);font-family:var(--font);font-size:14px;line-height:1.6;min-height:100vh}}

header{{padding:1.5rem 2.5rem 1rem;border-bottom:1px solid var(--border);display:flex;align-items:baseline;gap:1.5rem;flex-wrap:wrap}}
header h1{{font-size:1.1rem;font-weight:600;letter-spacing:.08em;text-transform:uppercase;color:var(--amber)}}
header .meta{{color:var(--muted);font-size:.8rem;font-family:var(--mono)}}
.dry-badge{{margin-left:auto;padding:.2rem .7rem;border:1px solid var(--amber);color:var(--amber);border-radius:3px;font-size:.7rem;letter-spacing:.1em;text-transform:uppercase}}

/* summary bar */
.summary{{padding:.85rem 2.5rem;background:var(--surface);border-bottom:1px solid var(--border);display:flex;gap:1.5rem;flex-wrap:wrap;align-items:center}}
.chip{{display:inline-flex;align-items:center;gap:.45rem;padding:.25rem .7rem;border-radius:20px;font-size:.75rem;font-weight:500;border:1px solid}}
.chip-junk     {{background:#3a1f1f;color:var(--red);border-color:#5a2e2e}}
.chip-dup      {{background:#2e2510;color:var(--amber);border-color:#4a3a18}}
.chip-old      {{background:#2e2010;color:var(--orange);border-color:#4a3018}}
.chip-vague    {{background:#221d30;color:var(--purple);border-color:#3a3050}}
.chip .n       {{font-family:var(--mono);font-weight:700}}

.controls{{padding:.85rem 2.5rem;display:flex;gap:.75rem;flex-wrap:wrap;align-items:center;border-bottom:1px solid var(--border)}}
.controls input[type=search]{{background:var(--bg);border:1px solid var(--border);color:var(--text);padding:.35rem .75rem;border-radius:4px;font-family:var(--mono);font-size:.8rem;width:250px;outline:none}}
.controls input[type=search]:focus{{border-color:var(--amber)}}
.filter-btns{{display:flex;gap:.35rem;flex-wrap:wrap}}
.fbtn{{padding:.22rem .6rem;border-radius:3px;border:1px solid var(--border);background:transparent;color:var(--muted);font-size:.72rem;cursor:pointer;font-family:var(--font);transition:all .1s}}
.fbtn:hover{{color:var(--text)}}
.fbtn.all.on   {{color:var(--text);border-color:var(--text)}}
.fbtn.junk.on  {{color:var(--red);border-color:var(--red)}}
.fbtn.dup.on   {{color:var(--amber);border-color:var(--amber)}}
.fbtn.old.on   {{color:var(--orange);border-color:var(--orange)}}
.fbtn.vague.on {{color:var(--purple);border-color:var(--purple)}}
.stats{{margin-left:auto;color:var(--muted);font-size:.75rem;font-family:var(--mono)}}

.table-wrap{{padding:0 2.5rem 4rem;overflow-x:auto}}
table{{width:100%;border-collapse:collapse;margin-top:1.25rem}}
th{{text-align:left;padding:.45rem .7rem;font-size:.68rem;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);border-bottom:1px solid var(--border);white-space:nowrap;cursor:pointer;user-select:none}}
th:hover{{color:var(--text)}}
th.sa::after{{content:" ↕";opacity:.3}}
th.asc::after{{content:" ↑"}}
th.desc::after{{content:" ↓"}}
td{{padding:.45rem .7rem;border-bottom:1px solid var(--border);vertical-align:middle}}
tr:last-child td{{border-bottom:none}}
tr:hover td{{background:var(--surface)}}
tr.hidden{{display:none}}

/* duplicate grouping */
tr.dup-group-start td{{border-top:1px solid #3a3020}}
tr.dup-member td:first-child{{padding-left:1.5rem}}
.dup-leader-label{{font-size:.65rem;color:var(--amber);margin-left:.4rem;opacity:.7}}

.fname{{font-family:var(--mono);font-size:.8rem;color:var(--text);max-width:280px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.fdir{{display:block;color:var(--muted);font-size:.7rem;margin-top:.05rem}}
.badge{{display:inline-block;padding:.12rem .45rem;border-radius:3px;font-size:.68rem;font-weight:500}}
.cat-junk     {{background:#3a1f1f;color:var(--red)}}
.cat-duplicate{{background:#2e2510;color:var(--amber)}}
.cat-old_file {{background:#2e2010;color:var(--orange)}}
.cat-vague    {{background:#221d30;color:var(--purple)}}
.dest{{font-family:var(--mono);font-size:.72rem;color:var(--muted)}}
.dest.del{{color:var(--red)}}.dest.old{{color:var(--orange)}}
.reason{{color:var(--muted);font-size:.75rem;max-width:280px}}
.size{{font-family:var(--mono);font-size:.75rem;color:var(--muted);white-space:nowrap;text-align:right}}
.empty{{text-align:center;padding:4rem 2rem;color:var(--muted);font-size:.9rem;display:none}}
</style>
</head>
<body>

<header>
  <h1>🌊 cleanwave</h1>
  <span class="meta">{date} &nbsp;·&nbsp; {scan_dirs}</span>
  <span class="dry-badge">dry run</span>
</header>

<div class="summary" id="summary"></div>

<div class="controls">
  <input type="search" id="search" placeholder="filter by name or path…" oninput="applyFilters()">
  <div class="filter-btns">
    <button class="fbtn all on"  onclick="setFilter('all',this)">all</button>
    <button class="fbtn junk"    onclick="setFilter('junk',this)">junk</button>
    <button class="fbtn dup"     onclick="setFilter('duplicate',this)">duplicates</button>
    <button class="fbtn old"     onclick="setFilter('old_file',this)">old files</button>
    <button class="fbtn vague"   onclick="setFilter('vague',this)">vague</button>
  </div>
  <span class="stats" id="stats"></span>
</div>

<div class="table-wrap">
  <table>
    <thead><tr>
      <th class="sa" onclick="sortBy('name',this)"   data-col="name">file</th>
      <th class="sa" onclick="sortBy('category',this)" data-col="category">category</th>
      <th class="sa" onclick="sortBy('destination',this)" data-col="destination">destination</th>
      <th class="sa" onclick="sortBy('size',this)"   data-col="size">size</th>
      <th>reason</th>
    </tr></thead>
    <tbody id="tbody"></tbody>
  </table>
  <div class="empty" id="empty">nothing matches.</div>
</div>

<script>
const DATA = {data_json};
let currentFilter = 'all', sortCol = null, sortAsc = true;

function esc(s){{return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;')}}

function buildSummary(){{
  const counts = {{}};
  DATA.forEach(f=>{{counts[f.category]=(counts[f.category]||0)+1}});
  const chips = [
    ['junk','chip-junk','🗑 junk'],
    ['duplicate','chip-dup','⚭ duplicates'],
    ['old_file','chip-old','📦 old files'],
    ['vague','chip-vague','? vague'],
  ];
  const el = document.getElementById('summary');
  let html = `<span style="color:var(--muted);font-size:.78rem;font-family:var(--mono)">${{DATA.length}} files flagged</span>`;
  chips.forEach(([cat,cls,label])=>{{
    if(counts[cat]) html+=`<span class="chip ${{cls}}"><span class="n">${{counts[cat]}}</span>${{label}}</span>`;
  }});
  el.innerHTML = html;
}}

function renderAll(){{
  const tbody = document.getElementById('tbody');
  tbody.innerHTML = '';

  // group duplicates together
  const dups = {{}};
  DATA.forEach((f,i)=>{{if(f.group_id){{(dups[f.group_id]=dups[f.group_id]||[]).push(i)}}}});
  const rendered = new Set();

  DATA.forEach((f,i)=>{{
    if(rendered.has(i)) return;
    rendered.add(i);

    const isGroupLeader = f.group_id && dups[f.group_id] && dups[f.group_id][0]===i;
    const members = f.group_id ? dups[f.group_id] : [];

    appendRow(f, i, members.length>0 ? 'dup-group-start' : '');

    if(isGroupLeader){{
      members.slice(1).forEach(mi=>{{
        if(!rendered.has(mi)){{
          rendered.add(mi);
          appendRow(DATA[mi], mi, 'dup-member');
        }}
      }});
    }}
  }});

  applyFilters();
}}

function appendRow(f, i, extraClass){{
  const destClass = f.destination==='deletion_approval'?'del':f.destination==='old_files'?'old':'';
  const tr = document.createElement('tr');
  if(extraClass) tr.className = extraClass;
  tr.dataset.idx = i;
  tr.dataset.cat = f.category;
  tr.dataset.name = (f.name+f.dir).toLowerCase();
  tr.dataset.col_name = f.name;
  tr.dataset.col_category = f.category;
  tr.dataset.col_destination = f.destination;
  tr.dataset.col_size = f.size;
  tr.innerHTML=`
    <td class="fname">${{esc(f.name)}}<span class="fdir">${{esc(f.dir)}}</span></td>
    <td><span class="badge cat-${{f.category}}">${{f.category}}</span></td>
    <td class="dest ${{destClass}}">${{f.destination}}/</td>
    <td class="size">${{f.size}}</td>
    <td class="reason">${{esc(f.reason)}}</td>`;
  document.getElementById('tbody').appendChild(tr);
}}

function setFilter(cat,btn){{
  currentFilter=cat;
  document.querySelectorAll('.fbtn').forEach(b=>b.classList.remove('on'));
  btn.classList.add('on');
  applyFilters();
}}

function applyFilters(){{
  const q=document.getElementById('search').value.toLowerCase();
  let visible=0;
  document.querySelectorAll('#tbody tr').forEach(tr=>{{
    const ok=(currentFilter==='all'||tr.dataset.cat===currentFilter)&&(!q||tr.dataset.name.includes(q));
    tr.classList.toggle('hidden',!ok);
    if(ok) visible++;
  }});
  const t=DATA.length;
  document.getElementById('stats').textContent=visible===t?`${{t}} files`:`${{visible}} / ${{t}} shown`;
  document.getElementById('empty').style.display=visible===0?'block':'none';
}}

function sortBy(col,th){{
  document.querySelectorAll('th[data-col]').forEach(t=>{{t.classList.remove('asc','desc');t.classList.add('sa')}});
  sortAsc = sortCol===col?!sortAsc:true;
  sortCol = col;
  th.classList.remove('sa');
  th.classList.add(sortAsc?'asc':'desc');
  const rows=[...document.querySelectorAll('#tbody tr')];
  rows.sort((a,b)=>{{
    const av=a.dataset['col_'+col]||'',bv=b.dataset['col_'+col]||'';
    return sortAsc?av.localeCompare(bv):bv.localeCompare(av);
  }});
  const tbody=document.getElementById('tbody');
  rows.forEach(r=>tbody.appendChild(r));
}}

buildSummary();
renderAll();
</script>
</body></html>
'''


def generate_and_open(
    actionable: list[tuple[FileInfo, FileDecision]],
    scan_dirs: list[str],
    output_dir: Path | None = None,
) -> Path:
    data     = _serialize(actionable)
    date_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    stamp    = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

    page_html = _HTML.format(
      date=_html.escape(date_str),
      scan_dirs=_html.escape(", ".join(scan_dirs)),
      data_json=_script_json(data),
    )

    out_dir = output_dir or (Path.home() / ".cleanwave")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"dryrun_{stamp}.html"
    out_path.write_text(page_html, encoding="utf-8")
    webbrowser.open(out_path.as_uri())
    return out_path
