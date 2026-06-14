"""
confirm_server.py — spin up a localhost page for interactive pre-move confirmation.
User checks/unchecks individual files, hits Confirm, server receives selection,
shuts down, returns the confirmed subset to main.py.

No external dependencies — uses stdlib http.server + threading.
"""
from __future__ import annotations

import json
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from .models import FileInfo, FileDecision, Destination


def _file_size_str(size: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.0f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


def _serialize(items: list[tuple[FileInfo, FileDecision]]) -> list[dict]:
    out = []
    for i, (fi, dec) in enumerate(items):
        out.append({
            "id": i,
            "name": dec.new_name or fi.path.name,
            "dir": str(fi.path.parent),
            "size": _file_size_str(fi.size),
            "category": dec.category,
            "destination": dec.destination.value,
            "reason": dec.reason,
        })
    return out


_PAGE = """\
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>CleanWave — confirm moves</title>
<style>
  :root {{
    --bg:       #181511;
    --surface:  #211e19;
    --border:   #2e2a24;
    --text:     #e2d9c8;
    --muted:    #7a7060;
    --amber:    #c9a96e;
    --red:      #d97070;
    --orange:   #d4895a;
    --purple:   #9b8ab8;
    --green:    #7aad7a;
    --font:     -apple-system, "Segoe UI", system-ui, sans-serif;
    --mono:     "SF Mono", "Fira Code", "Cascadia Code", monospace;
  }}
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

  body {{
    background: var(--bg);
    color: var(--text);
    font-family: var(--font);
    font-size: 14px;
    line-height: 1.6;
    min-height: 100vh;
    padding-bottom: 6rem;
  }}

  header {{
    padding: 2rem 2.5rem 1.5rem;
    border-bottom: 1px solid var(--border);
    display: flex;
    align-items: baseline;
    gap: 1.5rem;
    flex-wrap: wrap;
  }}
  header h1 {{ font-size: 1.1rem; font-weight: 600; letter-spacing: 0.08em; text-transform: uppercase; color: var(--amber); }}
  header .meta {{ color: var(--muted); font-size: 0.8rem; font-family: var(--mono); }}

  .controls {{
    padding: 1rem 2.5rem;
    display: flex;
    gap: 1rem;
    flex-wrap: wrap;
    align-items: center;
    border-bottom: 1px solid var(--border);
    background: var(--surface);
    position: sticky;
    top: 0;
    z-index: 10;
  }}

  .controls input[type=search] {{
    background: var(--bg);
    border: 1px solid var(--border);
    color: var(--text);
    padding: 0.35rem 0.75rem;
    border-radius: 4px;
    font-family: var(--mono);
    font-size: 0.8rem;
    width: 240px;
    outline: none;
  }}
  .controls input[type=search]:focus {{ border-color: var(--amber); }}

  .filter-btns {{ display: flex; gap: 0.4rem; flex-wrap: wrap; }}
  .filter-btn {{
    padding: 0.25rem 0.65rem;
    border-radius: 3px;
    border: 1px solid var(--border);
    background: transparent;
    color: var(--muted);
    font-size: 0.75rem;
    cursor: pointer;
    font-family: var(--font);
    transition: all 0.1s;
  }}
  .filter-btn:hover {{ color: var(--text); }}
  .filter-btn.all.active       {{ color: var(--text); border-color: var(--text); }}
  .filter-btn.junk.active      {{ color: var(--red); border-color: var(--red); }}
  .filter-btn.duplicate.active {{ color: var(--amber); border-color: var(--amber); }}
  .filter-btn.old_file.active  {{ color: var(--orange); border-color: var(--orange); }}
  .filter-btn.vague.active     {{ color: var(--purple); border-color: var(--purple); }}

  .bulk-btns {{ display: flex; gap: 0.4rem; }}
  .bulk-btn {{
    padding: 0.25rem 0.65rem;
    border-radius: 3px;
    border: 1px solid var(--border);
    background: transparent;
    color: var(--muted);
    font-size: 0.75rem;
    cursor: pointer;
    font-family: var(--font);
  }}
  .bulk-btn:hover {{ color: var(--text); border-color: var(--text); }}

  .stats {{ margin-left: auto; color: var(--muted); font-size: 0.78rem; font-family: var(--mono); }}

  .table-wrap {{ padding: 0 2.5rem; overflow-x: auto; }}

  table {{ width: 100%; border-collapse: collapse; margin-top: 1.5rem; }}
  th {{
    text-align: left;
    padding: 0.5rem 0.75rem;
    font-size: 0.7rem;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--muted);
    border-bottom: 1px solid var(--border);
    white-space: nowrap;
    cursor: pointer;
    user-select: none;
  }}
  th:hover {{ color: var(--text); }}
  th.sorted-asc::after  {{ content: " ↑"; }}
  th.sorted-desc::after {{ content: " ↓"; }}
  th.no-sort {{ cursor: default; }}
  th.no-sort:hover {{ color: var(--muted); }}

  td {{ padding: 0.5rem 0.75rem; border-bottom: 1px solid var(--border); vertical-align: middle; }}
  tr:last-child td {{ border-bottom: none; }}
  tr {{ transition: background 0.1s; }}
  tr:hover td {{ background: var(--surface); }}
  tr.hidden {{ display: none; }}
  tr.unchecked td {{ opacity: 0.35; }}
  tr.unchecked td:first-child {{ opacity: 1; }}

  .cb-cell {{ width: 2rem; }}
  input[type=checkbox] {{
    width: 1rem; height: 1rem;
    accent-color: var(--amber);
    cursor: pointer;
  }}

  .name {{ font-family: var(--mono); font-size: 0.82rem; color: var(--text); max-width: 260px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
  .name .dir {{ display: block; color: var(--muted); font-size: 0.72rem; margin-top: 0.1rem; }}

  .badge {{ display: inline-block; padding: 0.15rem 0.5rem; border-radius: 3px; font-size: 0.7rem; font-weight: 500; }}
  .cat-junk      {{ background: #3a1f1f; color: var(--red); }}
  .cat-duplicate {{ background: #2e2510; color: var(--amber); }}
  .cat-old_file  {{ background: #2e2010; color: var(--orange); }}
  .cat-vague     {{ background: #221d30; color: var(--purple); }}

  .dest {{ font-family: var(--mono); font-size: 0.75rem; color: var(--muted); }}
  .dest.deletion {{ color: var(--red); }}
  .dest.old       {{ color: var(--orange); }}

  .reason {{ color: var(--muted); font-size: 0.78rem; max-width: 280px; }}
  .size {{ font-family: var(--mono); font-size: 0.78rem; color: var(--muted); white-space: nowrap; text-align: right; }}

  /* sticky footer bar */
  .footer {{
    position: fixed;
    bottom: 0; left: 0; right: 0;
    background: var(--surface);
    border-top: 1px solid var(--border);
    padding: 1rem 2.5rem;
    display: flex;
    align-items: center;
    gap: 1.5rem;
  }}
  .footer-count {{ font-family: var(--mono); font-size: 0.85rem; color: var(--muted); }}
  .footer-count span {{ color: var(--text); }}

  .btn-confirm {{
    margin-left: auto;
    padding: 0.55rem 1.75rem;
    background: var(--amber);
    color: #181511;
    border: none;
    border-radius: 4px;
    font-weight: 600;
    font-size: 0.85rem;
    cursor: pointer;
    letter-spacing: 0.04em;
    transition: opacity 0.1s;
  }}
  .btn-confirm:hover {{ opacity: 0.85; }}
  .btn-confirm:disabled {{ opacity: 0.3; cursor: default; }}

  .btn-cancel {{
    padding: 0.55rem 1.2rem;
    background: transparent;
    color: var(--muted);
    border: 1px solid var(--border);
    border-radius: 4px;
    font-size: 0.85rem;
    cursor: pointer;
  }}
  .btn-cancel:hover {{ color: var(--red); border-color: var(--red); }}

  #overlay {{
    display: none;
    position: fixed; inset: 0;
    background: rgba(0,0,0,0.7);
    z-index: 100;
    align-items: center;
    justify-content: center;
  }}
  #overlay.visible {{ display: flex; }}
  .modal {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 2rem;
    max-width: 340px;
    text-align: center;
  }}
  .modal h2 {{ font-size: 1rem; color: var(--amber); margin-bottom: 0.75rem; }}
  .modal p {{ color: var(--muted); font-size: 0.85rem; margin-bottom: 1.5rem; }}
  .modal-btns {{ display: flex; gap: 0.75rem; justify-content: center; }}

  .done-screen {{
    display: none;
    position: fixed; inset: 0;
    background: var(--bg);
    z-index: 200;
    align-items: center;
    justify-content: center;
    flex-direction: column;
    gap: 1rem;
    text-align: center;
  }}
  .done-screen.visible {{ display: flex; }}
  .done-screen .wave {{ font-size: 3rem; }}
  .done-screen h2 {{ color: var(--amber); letter-spacing: 0.05em; }}
  .done-screen p {{ color: var(--muted); font-size: 0.85rem; }}
</style>
</head>
<body>

<header>
  <h1>🌊 cleanwave</h1>
  <span class="meta">uncheck files you want to skip, then confirm</span>
</header>

<div class="controls">
  <input type="search" id="search" placeholder="filter by name or path…" oninput="applyFilters()">
  <div class="filter-btns">
    <button class="filter-btn all active" onclick="setFilter('all',this)">all</button>
    <button class="filter-btn junk"       onclick="setFilter('junk',this)">junk</button>
    <button class="filter-btn duplicate"  onclick="setFilter('duplicate',this)">duplicates</button>
    <button class="filter-btn old_file"   onclick="setFilter('old_file',this)">old files</button>
    <button class="filter-btn vague"      onclick="setFilter('vague',this)">vague</button>
  </div>
  <div class="bulk-btns">
    <button class="bulk-btn" onclick="checkVisible(true)">check all</button>
    <button class="bulk-btn" onclick="checkVisible(false)">uncheck all</button>
  </div>
  <span class="stats" id="stats"></span>
</div>

<div class="table-wrap">
  <table id="filetable">
    <thead>
      <tr>
        <th class="no-sort cb-cell"></th>
        <th onclick="sortBy('name')" data-col="name">file</th>
        <th onclick="sortBy('category')" data-col="category">category</th>
        <th onclick="sortBy('destination')" data-col="destination">destination</th>
        <th onclick="sortBy('size')" data-col="size">size</th>
        <th class="no-sort">reason</th>
      </tr>
    </thead>
    <tbody id="tbody"></tbody>
  </table>
</div>

<div class="footer">
  <span class="footer-count">moving <span id="fc">0</span> of <span id="ft">0</span> files</span>
  <button class="btn-cancel" onclick="doCancel()">cancel</button>
  <button class="btn-confirm" id="btn-confirm" onclick="showConfirmModal()">confirm moves →</button>
</div>

<div id="overlay">
  <div class="modal">
    <h2>move these files?</h2>
    <p id="modal-desc"></p>
    <div class="modal-btns">
      <button class="btn-cancel" onclick="closeModal()">go back</button>
      <button class="btn-confirm" onclick="doConfirm()">yes, move them</button>
    </div>
  </div>
</div>

<div class="done-screen" id="done">
  <div class="wave">🌊</div>
  <h2>done — check your terminal</h2>
  <p>you can close this tab.</p>
</div>

<script>
const DATA = {data_json};
const checked = new Set(DATA.map(f => f.id));

let currentFilter = 'all';
let currentSort = {{ col: null, asc: true }};

function esc(s) {{
  return String(s)
    .replace(/&/g,'&amp;').replace(/</g,'&lt;')
    .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}}

function renderAll() {{
  const tbody = document.getElementById('tbody');
  tbody.innerHTML = '';
  DATA.forEach(f => {{
    const destClass = f.destination === 'deletion_approval' ? 'deletion'
                    : f.destination === 'old_files' ? 'old' : '';
    const tr = document.createElement('tr');
    tr.dataset.id = f.id;
    tr.dataset.cat = f.category;
    tr.dataset.name = (f.name + f.dir).toLowerCase();
    tr.dataset.col_name = f.name;
    tr.dataset.col_category = f.category;
    tr.dataset.col_destination = f.destination;
    tr.dataset.col_size = f.size;
    tr.innerHTML = `
      <td class="cb-cell"><input type="checkbox" checked data-id="${{f.id}}" onchange="toggle(${{f.id}}, this.checked)"></td>
      <td class="name">${{esc(f.name)}}<span class="dir">${{esc(f.dir)}}</span></td>
      <td><span class="badge cat-${{f.category}}">${{f.category}}</span></td>
      <td class="dest ${{destClass}}">${{f.destination}}/</td>
      <td class="size">${{f.size}}</td>
      <td class="reason">${{esc(f.reason)}}</td>
    `;
    tbody.appendChild(tr);
  }});
  updateFooter();
  applyFilters();
}}

function toggle(id, val) {{
  if (val) checked.add(id); else checked.delete(id);
  const tr = document.querySelector(`tr[data-id="${{id}}"]`);
  if (tr) tr.classList.toggle('unchecked', !val);
  updateFooter();
}}

function checkVisible(val) {{
  document.querySelectorAll('#tbody tr:not(.hidden)').forEach(tr => {{
    const id = parseInt(tr.dataset.id);
    const cb = tr.querySelector('input[type=checkbox]');
    if (cb) cb.checked = val;
    if (val) checked.add(id); else checked.delete(id);
    tr.classList.toggle('unchecked', !val);
  }});
  updateFooter();
}}

function updateFooter() {{
  document.getElementById('fc').textContent = checked.size;
  document.getElementById('ft').textContent = DATA.length;
  document.getElementById('btn-confirm').disabled = checked.size === 0;
}}

function setFilter(cat, btn) {{
  currentFilter = cat;
  document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  applyFilters();
}}

function applyFilters() {{
  const q = document.getElementById('search').value.toLowerCase();
  let visible = 0;
  document.querySelectorAll('#tbody tr').forEach(tr => {{
    const catMatch = currentFilter === 'all' || tr.dataset.cat === currentFilter;
    const nameMatch = !q || tr.dataset.name.includes(q);
    const show = catMatch && nameMatch;
    tr.classList.toggle('hidden', !show);
    if (show) visible++;
  }});
  document.getElementById('stats').textContent =
    `${{visible}} / ${{DATA.length}} shown`;
}}

function sortBy(col) {{
  document.querySelectorAll('th[data-col]').forEach(th => th.classList.remove('sorted-asc','sorted-desc'));
  currentSort.asc = currentSort.col === col ? !currentSort.asc : true;
  currentSort.col = col;
  const th = document.querySelector(`th[data-col="${{col}}"]`);
  th.classList.add(currentSort.asc ? 'sorted-asc' : 'sorted-desc');
  const rows = Array.from(document.querySelectorAll('#tbody tr'));
  rows.sort((a, b) => {{
    const av = a.dataset[`col_${{col}}`] || '';
    const bv = b.dataset[`col_${{col}}`] || '';
    return currentSort.asc ? av.localeCompare(bv) : bv.localeCompare(av);
  }});
  const tbody = document.getElementById('tbody');
  rows.forEach(r => tbody.appendChild(r));
}}

function showConfirmModal() {{
  const n = checked.size;
  document.getElementById('modal-desc').textContent =
    `${{n}} file${{n === 1 ? '' : 's'}} will be moved. this can't be undone from here — check deletion_approval/ to recover anything.`;
  document.getElementById('overlay').classList.add('visible');
}}

function closeModal() {{
  document.getElementById('overlay').classList.remove('visible');
}}

async function doConfirm() {{
  closeModal();
  try {{
    await fetch('/confirm', {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify({{ selected: Array.from(checked) }})
    }});
  }} catch(e) {{
    // server shuts down mid-response which causes a fetch error — that's expected
  }}
  document.getElementById('done').classList.add('visible');
}}

async function doCancel() {{
  try {{
    await fetch('/cancel', {{ method: 'POST' }});
  }} catch(e) {{}}
  document.getElementById('done').classList.add('visible');
  document.querySelector('.done-screen h2').textContent = 'cancelled — nothing moved';
}}

renderAll();
</script>
</body>
</html>
"""


class _Handler(BaseHTTPRequestHandler):
    """Minimal HTTP handler — serves the page, receives /confirm or /cancel."""

    server: "_ConfirmServer"  # type: ignore[assignment]

    def log_message(self, fmt, *args):
        pass  # silence default access log

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
        else:  # /cancel
            self.server.cancelled = True

        # Respond before shutting down so the JS fetch completes
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
    """
    Serve the interactive confirm page on localhost, block until the user
    confirms or cancels.

    Returns the confirmed subset of actionable, or None if cancelled.
    """
    data = _serialize(actionable)
    page = _PAGE.format(data_json=json.dumps(data, ensure_ascii=False))

    server = _ConfirmServer(page, port)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    url = f"http://127.0.0.1:{port}"
    webbrowser.open(url)

    server.done_event.wait()

    if server.cancelled:
        return None

    confirmed = [
        item for i, item in enumerate(actionable)
        if i in server.selected_ids
    ]
    return confirmed
