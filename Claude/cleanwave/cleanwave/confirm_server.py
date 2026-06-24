"""
confirm_server.py — localhost confirm page with summary bar + duplicate grouping
"""
from __future__ import annotations

import json
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from .models import FileInfo, FileDecision, Destination
from .html_utils import _script_json


def _size_str(size: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.0f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


def _serialize(items: list[tuple[FileInfo, FileDecision]]) -> list[dict]:
    out = []
    for i, (fi, dec) in enumerate(items):
        name = dec.new_name or fi.path.name
        group_id = fi.path.name if (dec.category == "duplicate" and dec.new_name) else None
        out.append({
            "id":          i,
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


_PAGE = '''\
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>cleanwave — confirm moves</title>
<style>
:root{{
  --bg:#181511;--surface:#211e19;--border:#2e2a24;--text:#e2d9c8;
  --muted:#7a7060;--amber:#c9a96e;--red:#d97070;--orange:#d4895a;
  --purple:#9b8ab8;--green:#7aad7a;
  --font:-apple-system,"Segoe UI",system-ui,sans-serif;
  --mono:"SF Mono","Fira Code","Cascadia Code",monospace;
}}
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
body{{background:var(--bg);color:var(--text);font-family:var(--font);font-size:14px;line-height:1.6;min-height:100vh;padding-bottom:5.5rem}}

header{{padding:1.5rem 2.5rem 1rem;border-bottom:1px solid var(--border);display:flex;align-items:baseline;gap:1.5rem;flex-wrap:wrap}}
header h1{{font-size:1.1rem;font-weight:600;letter-spacing:.08em;text-transform:uppercase;color:var(--amber)}}
header .meta{{color:var(--muted);font-size:.8rem;font-family:var(--mono)}}

.summary{{padding:.85rem 2.5rem;background:var(--surface);border-bottom:1px solid var(--border);display:flex;gap:1.5rem;flex-wrap:wrap;align-items:center}}
.chip{{display:inline-flex;align-items:center;gap:.45rem;padding:.25rem .7rem;border-radius:20px;font-size:.75rem;font-weight:500;border:1px solid}}
.chip-junk  {{background:#3a1f1f;color:var(--red);border-color:#5a2e2e}}
.chip-dup   {{background:#2e2510;color:var(--amber);border-color:#4a3a18}}
.chip-old   {{background:#2e2010;color:var(--orange);border-color:#4a3018}}
.chip-vague {{background:#221d30;color:var(--purple);border-color:#3a3050}}
.chip .n    {{font-family:var(--mono);font-weight:700}}

.controls{{padding:.85rem 2.5rem;display:flex;gap:.75rem;flex-wrap:wrap;align-items:center;border-bottom:1px solid var(--border);background:var(--surface);position:sticky;top:0;z-index:10}}
.controls input[type=search]{{background:var(--bg);border:1px solid var(--border);color:var(--text);padding:.35rem .75rem;border-radius:4px;font-family:var(--mono);font-size:.8rem;width:230px;outline:none}}
.controls input[type=search]:focus{{border-color:var(--amber)}}
.filter-btns{{display:flex;gap:.35rem;flex-wrap:wrap}}
.fbtn{{padding:.22rem .6rem;border-radius:3px;border:1px solid var(--border);background:transparent;color:var(--muted);font-size:.72rem;cursor:pointer;font-family:var(--font);transition:all .1s}}
.fbtn:hover{{color:var(--text)}}
.fbtn.all.on  {{color:var(--text);border-color:var(--text)}}
.fbtn.junk.on {{color:var(--red);border-color:var(--red)}}
.fbtn.dup.on  {{color:var(--amber);border-color:var(--amber)}}
.fbtn.old.on  {{color:var(--orange);border-color:var(--orange)}}
.fbtn.vague.on{{color:var(--purple);border-color:var(--purple)}}
.bulk-btns{{display:flex;gap:.35rem}}
.bbtn{{padding:.22rem .6rem;border-radius:3px;border:1px solid var(--border);background:transparent;color:var(--muted);font-size:.72rem;cursor:pointer;font-family:var(--font)}}
.bbtn:hover{{color:var(--text);border-color:var(--text)}}
.stats{{margin-left:auto;color:var(--muted);font-size:.75rem;font-family:var(--mono)}}

.table-wrap{{padding:0 2.5rem;overflow-x:auto}}
table{{width:100%;border-collapse:collapse;margin-top:1.25rem}}
th{{text-align:left;padding:.45rem .7rem;font-size:.68rem;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);border-bottom:1px solid var(--border);white-space:nowrap;cursor:pointer;user-select:none}}
th.no-sort{{cursor:default}}
th.no-sort:hover{{color:var(--muted)}}
th:not(.no-sort):hover{{color:var(--text)}}
th.asc::after{{content:" ↑"}} th.desc::after{{content:" ↓"}}
td{{padding:.45rem .7rem;border-bottom:1px solid var(--border);vertical-align:middle}}
tr:last-child td{{border-bottom:none}}
tr:hover td{{background:var(--surface)}}
tr.hidden{{display:none}}
tr.unchecked td{{opacity:.35}} tr.unchecked td:first-child{{opacity:1}}
tr.dup-group-start td{{border-top:1px solid #3a3020}}
tr.dup-member td:nth-child(2){{padding-left:1.5rem}}
.cb-cell{{width:2rem}}
input[type=checkbox]{{width:1rem;height:1rem;accent-color:var(--amber);cursor:pointer}}
.fname{{font-family:var(--mono);font-size:.8rem;color:var(--text);max-width:260px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.fdir{{display:block;color:var(--muted);font-size:.7rem;margin-top:.05rem}}
.badge{{display:inline-block;padding:.12rem .45rem;border-radius:3px;font-size:.68rem;font-weight:500}}
.cat-junk     {{background:#3a1f1f;color:var(--red)}}
.cat-duplicate{{background:#2e2510;color:var(--amber)}}
.cat-old_file {{background:#2e2010;color:var(--orange)}}
.cat-vague    {{background:#221d30;color:var(--purple)}}
.dest{{font-family:var(--mono);font-size:.72rem;color:var(--muted)}}
.dest.del{{color:var(--red)}} .dest.old{{color:var(--orange)}}
.reason{{color:var(--muted);font-size:.75rem;max-width:270px}}
.size{{font-family:var(--mono);font-size:.75rem;color:var(--muted);white-space:nowrap;text-align:right}}

.footer{{position:fixed;bottom:0;left:0;right:0;background:var(--surface);border-top:1px solid var(--border);padding:1rem 2.5rem;display:flex;align-items:center;gap:1.5rem}}
.fc{{font-family:var(--mono);font-size:.85rem;color:var(--muted)}}
.fc span{{color:var(--text)}}
.btn-confirm{{margin-left:auto;padding:.55rem 1.75rem;background:var(--amber);color:#181511;border:none;border-radius:4px;font-weight:600;font-size:.85rem;cursor:pointer;letter-spacing:.04em;transition:opacity .1s}}
.btn-confirm:hover{{opacity:.85}} .btn-confirm:disabled{{opacity:.3;cursor:default}}
.btn-cancel{{padding:.55rem 1.2rem;background:transparent;color:var(--muted);border:1px solid var(--border);border-radius:4px;font-size:.85rem;cursor:pointer}}
.btn-cancel:hover{{color:var(--red);border-color:var(--red)}}

#overlay{{display:none;position:fixed;inset:0;background:rgba(0,0,0,.7);z-index:100;align-items:center;justify-content:center}}
#overlay.on{{display:flex}}
.modal{{background:var(--surface);border:1px solid var(--border);border-radius:6px;padding:2rem;max-width:340px;text-align:center}}
.modal h2{{font-size:1rem;color:var(--amber);margin-bottom:.75rem}}
.modal p{{color:var(--muted);font-size:.85rem;margin-bottom:1.5rem}}
.modal-btns{{display:flex;gap:.75rem;justify-content:center}}
.done{{display:none;position:fixed;inset:0;background:var(--bg);z-index:200;align-items:center;justify-content:center;flex-direction:column;gap:1rem;text-align:center}}
.done.on{{display:flex}}
.done .wave{{font-size:3rem}}
.done h2{{color:var(--amber);letter-spacing:.05em}}
.done p{{color:var(--muted);font-size:.85rem}}
</style>
</head>
<body>

<header>
  <h1>🌊 cleanwave</h1>
  <span class="meta">uncheck files you want to skip, then confirm</span>
</header>

<div class="summary" id="summary"></div>

<div class="controls">
  <input type="search" id="search" placeholder="filter by name or path…" oninput="applyFilters()">
  <div class="filter-btns">
    <button class="fbtn all on" onclick="setFilter('all',this)">all</button>
    <button class="fbtn junk"   onclick="setFilter('junk',this)">junk</button>
    <button class="fbtn dup"    onclick="setFilter('duplicate',this)">duplicates</button>
    <button class="fbtn old"    onclick="setFilter('old_file',this)">old files</button>
    <button class="fbtn vague"  onclick="setFilter('vague',this)">vague</button>
  </div>
  <div class="bulk-btns">
    <button class="bbtn" onclick="checkVisible(true)">check all</button>
    <button class="bbtn" onclick="checkVisible(false)">uncheck all</button>
  </div>
  <span class="stats" id="stats"></span>
</div>

<div class="table-wrap">
  <table>
    <thead><tr>
      <th class="no-sort cb-cell"></th>
      <th onclick="sortBy('name',this)"        data-col="name">file</th>
      <th onclick="sortBy('category',this)"    data-col="category">category</th>
      <th onclick="sortBy('destination',this)" data-col="destination">destination</th>
      <th onclick="sortBy('size',this)"        data-col="size">size</th>
      <th class="no-sort">reason</th>
    </tr></thead>
    <tbody id="tbody"></tbody>
  </table>
</div>

<div class="footer">
  <span class="fc">moving <span id="fc">0</span> of <span id="ft">0</span> files</span>
  <button class="btn-cancel" onclick="doCancel()">cancel</button>
  <button class="btn-confirm" id="btnok" onclick="showModal()">confirm moves →</button>
</div>

<div id="overlay">
  <div class="modal">
    <h2>move these files?</h2>
    <p id="mdesc"></p>
    <div class="modal-btns">
      <button class="btn-cancel" onclick="closeModal()">go back</button>
      <button class="btn-confirm" onclick="doConfirm()">yes, move them</button>
    </div>
  </div>
</div>

<div class="done" id="done">
  <div class="wave">🌊</div>
  <h2>done — check your terminal</h2>
  <p>you can close this tab.</p>
</div>

<script>
const DATA = {data_json};
const checked = new Set(DATA.map(f=>f.id));
let currentFilter='all', sortCol=null, sortAsc=true;

function esc(s){{return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;')}}

function buildSummary(){{
  const counts={{}};
  DATA.forEach(f=>{{counts[f.category]=(counts[f.category]||0)+1}});
  const chips=[['junk','chip-junk','🗑 junk'],['duplicate','chip-dup','⚭ duplicates'],['old_file','chip-old','📦 old files'],['vague','chip-vague','? vague']];
  const el=document.getElementById('summary');
  let html=`<span style="color:var(--muted);font-size:.78rem;font-family:var(--mono)">${{DATA.length}} files flagged</span>`;
  chips.forEach(([cat,cls,label])=>{{if(counts[cat])html+=`<span class="chip ${{cls}}"><span class="n">${{counts[cat]}}</span>${{label}}</span>`;}});
  el.innerHTML=html;
}}

function renderAll(){{
  const tbody=document.getElementById('tbody');
  tbody.innerHTML='';
  const dups={{}};
  DATA.forEach((f,i)=>{{if(f.group_id){{(dups[f.group_id]=dups[f.group_id]||[]).push(i)}}}});
  const rendered=new Set();
  DATA.forEach((f,i)=>{{
    if(rendered.has(i)) return;
    rendered.add(i);
    const members=f.group_id?dups[f.group_id]:[];
    appendRow(f,i,members.length>0?'dup-group-start':'');
    if(f.group_id&&members[0]===i){{
      members.slice(1).forEach(mi=>{{if(!rendered.has(mi)){{rendered.add(mi);appendRow(DATA[mi],mi,'dup-member');}}}}); 
    }}
  }});
  updateFooter();
  applyFilters();
}}

function appendRow(f,i,extraClass){{
  const destClass=f.destination==='deletion_approval'?'del':f.destination==='old_files'?'old':'';
  const tr=document.createElement('tr');
  if(extraClass) tr.className=extraClass;
  tr.dataset.id=f.id; tr.dataset.cat=f.category;
  tr.dataset.name=(f.name+f.dir).toLowerCase();
  tr.dataset.col_name=f.name; tr.dataset.col_category=f.category;
  tr.dataset.col_destination=f.destination; tr.dataset.col_size=f.size;
  tr.innerHTML=`
    <td class="cb-cell"><input type="checkbox" checked data-id="${{f.id}}" onchange="toggle(${{f.id}},this.checked)"></td>
    <td class="fname">${{esc(f.name)}}<span class="fdir">${{esc(f.dir)}}</span></td>
    <td><span class="badge cat-${{f.category}}">${{f.category}}</span></td>
    <td class="dest ${{destClass}}">${{f.destination}}/</td>
    <td class="size">${{f.size}}</td>
    <td class="reason">${{esc(f.reason)}}</td>`;
  document.getElementById('tbody').appendChild(tr);
}}

function toggle(id,val){{
  if(val)checked.add(id);else checked.delete(id);
  document.querySelector(`tr[data-id="${{id}}"]`)?.classList.toggle('unchecked',!val);
  updateFooter();
}}

function checkVisible(val){{
  document.querySelectorAll('#tbody tr:not(.hidden)').forEach(tr=>{{
    const id=parseInt(tr.dataset.id);
    const cb=tr.querySelector('input[type=checkbox]');
    if(cb)cb.checked=val;
    if(val)checked.add(id);else checked.delete(id);
    tr.classList.toggle('unchecked',!val);
  }});
  updateFooter();
}}

function updateFooter(){{
  document.getElementById('fc').textContent=checked.size;
  document.getElementById('ft').textContent=DATA.length;
  document.getElementById('btnok').disabled=checked.size===0;
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
    if(ok)visible++;
  }});
  document.getElementById('stats').textContent=`${{visible}} / ${{DATA.length}} shown`;
}}

function sortBy(col,th){{
  document.querySelectorAll('th[data-col]').forEach(t=>t.classList.remove('asc','desc'));
  sortAsc=sortCol===col?!sortAsc:true; sortCol=col;
  th.classList.add(sortAsc?'asc':'desc');
  const rows=[...document.querySelectorAll('#tbody tr')];
  rows.sort((a,b)=>{{const av=a.dataset['col_'+col]||'',bv=b.dataset['col_'+col]||'';return sortAsc?av.localeCompare(bv):bv.localeCompare(av);}});
  const tbody=document.getElementById('tbody');
  rows.forEach(r=>tbody.appendChild(r));
}}

function showModal(){{
  const n=checked.size;
  document.getElementById('mdesc').textContent=`${{n}} file${{n===1?'':'s'}} will be moved. check deletion_approval/ to recover anything.`;
  document.getElementById('overlay').classList.add('on');
}}
function closeModal(){{document.getElementById('overlay').classList.remove('on')}}

async function doConfirm(){{
  closeModal();
  try{{await fetch('/confirm',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{selected:[...checked]}})}})}}catch(e){{}}
  document.getElementById('done').classList.add('on');
}}

async function doCancel(){{
  try{{await fetch('/cancel',{{method:'POST'}})}}catch(e){{}}
  document.getElementById('done').classList.add('on');
  document.querySelector('.done h2').textContent='cancelled — nothing moved';
}}

buildSummary();
renderAll();
</script>
</body></html>
'''


class _Handler(BaseHTTPRequestHandler):
    server: "_ConfirmServer"

    def log_message(self, fmt, *args):
        pass

    def do_GET(self):
        body = self.server.page.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length)

        if self.path == "/confirm":
            try:
                payload = json.loads(raw)
                self.server.selected_ids = set(payload.get("selected", []))
                self.server.cancelled = False
            except Exception:
                self.server.cancelled = True
        else:
            self.server.cancelled = True

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok":true}')

        threading.Thread(target=self.server.shutdown, daemon=True).start()
        self.server.done_event.set()


class _ConfirmServer(HTTPServer):
    def __init__(self, page: str, port: int):
        super().__init__(("127.0.0.1", port), _Handler)
        self.page = page
        self.selected_ids: set[int] = set()
        self.cancelled = False
        self.done_event = threading.Event()


def run_confirm(
    actionable: list[tuple[FileInfo, FileDecision]],
    port: int = 7234,
) -> list[tuple[FileInfo, FileDecision]] | None:
    data = _serialize(actionable)
    page = _PAGE.format(data_json=_script_json(data))

    server = _ConfirmServer(page, port)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    webbrowser.open(f"http://127.0.0.1:{port}")
    server.done_event.wait()

    if server.cancelled:
        return None

    return [item for i, item in enumerate(actionable) if i in server.selected_ids]
