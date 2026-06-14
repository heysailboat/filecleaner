"""
preview_html.py — generate a self-contained HTML preview for --dry-run.
Opens automatically in the default browser. No server, no dependencies.
"""
from __future__ import annotations

import datetime
import json
import webbrowser
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
    for fi, dec in items:
        out.append({
            "name": dec.new_name or fi.path.name,
            "original_name": fi.path.name,
            "dir": str(fi.path.parent),
            "size": _file_size_str(fi.size),
            "category": dec.category,
            "destination": dec.destination.value,
            "reason": dec.reason,
        })
    return out


_HTML = """\
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>CleanWave dry run — {date}</title>
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
  }}

  header {{
    padding: 2rem 2.5rem 1.5rem;
    border-bottom: 1px solid var(--border);
    display: flex;
    align-items: baseline;
    gap: 1.5rem;
    flex-wrap: wrap;
  }}

  header h1 {{
    font-size: 1.1rem;
    font-weight: 600;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--amber);
  }}

  header .meta {{
    color: var(--muted);
    font-size: 0.8rem;
    font-family: var(--mono);
  }}

  .dry-run-badge {{
    margin-left: auto;
    padding: 0.2rem 0.7rem;
    border: 1px solid var(--amber);
    color: var(--amber);
    border-radius: 3px;
    font-size: 0.7rem;
    letter-spacing: 0.1em;
    text-transform: uppercase;
  }}

  .controls {{
    padding: 1rem 2.5rem;
    display: flex;
    gap: 1rem;
    flex-wrap: wrap;
    align-items: center;
    border-bottom: 1px solid var(--border);
    background: var(--surface);
  }}

  .controls input[type=search] {{
    background: var(--bg);
    border: 1px solid var(--border);
    color: var(--text);
    padding: 0.35rem 0.75rem;
    border-radius: 4px;
    font-family: var(--mono);
    font-size: 0.8rem;
    width: 260px;
    outline: none;
  }}
  .controls input[type=search]:focus {{
    border-color: var(--amber);
  }}

  .filter-btns {{
    display: flex;
    gap: 0.4rem;
    flex-wrap: wrap;
  }}

  .filter-btn {{
    padding: 0.25rem 0.65rem;
    border-radius: 3px;
    border: 1px solid var(--border);
    background: transparent;
    color: var(--muted);
    font-size: 0.75rem;
    cursor: pointer;
    transition: all 0.1s;
    font-family: var(--font);
  }}
  .filter-btn:hover, .filter-btn.active {{
    border-color: currentColor;
  }}
  .filter-btn.all.active    {{ color: var(--text); border-color: var(--text); }}
  .filter-btn.junk.active   {{ color: var(--red); border-color: var(--red); }}
  .filter-btn.duplicate.active {{ color: var(--amber); border-color: var(--amber); }}
  .filter-btn.old_file.active  {{ color: var(--orange); border-color: var(--orange); }}
  .filter-btn.vague.active     {{ color: var(--purple); border-color: var(--purple); }}

  .stats {{
    margin-left: auto;
    color: var(--muted);
    font-size: 0.78rem;
    font-family: var(--mono);
  }}

  .table-wrap {{
    padding: 0 2.5rem 4rem;
    overflow-x: auto;
  }}

  table {{
    width: 100%;
    border-collapse: collapse;
    margin-top: 1.5rem;
  }}

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
  th .sort-arrow {{ opacity: 0.3; margin-left: 0.3em; }}
  th.sorted-asc .sort-arrow::after  {{ content: "↑"; opacity: 1; }}
  th.sorted-desc .sort-arrow::after {{ content: "↓"; opacity: 1; }}
  th .sort-arrow::after {{ content: "↕"; }}

  td {{
    padding: 0.5rem 0.75rem;
    border-bottom: 1px solid var(--border);
    vertical-align: middle;
  }}

  tr:last-child td {{ border-bottom: none; }}
  tr {{ transition: background 0.1s; }}
  tr:hover td {{ background: var(--surface); }}
  tr.hidden {{ display: none; }}

  .name {{
    font-family: var(--mono);
    font-size: 0.82rem;
    color: var(--text);
    max-width: 280px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }}
  .name .dir {{
    display: block;
    color: var(--muted);
    font-size: 0.72rem;
    margin-top: 0.1rem;
  }}

  .badge {{
    display: inline-block;
    padding: 0.15rem 0.5rem;
    border-radius: 3px;
    font-size: 0.7rem;
    font-weight: 500;
    letter-spacing: 0.04em;
  }}
  .cat-junk      {{ background: #3a1f1f; color: var(--red); }}
  .cat-duplicate {{ background: #2e2510; color: var(--amber); }}
  .cat-old_file  {{ background: #2e2010; color: var(--orange); }}
  .cat-vague     {{ background: #221d30; color: var(--purple); }}

  .dest {{
    font-family: var(--mono);
    font-size: 0.75rem;
    color: var(--muted);
  }}
  .dest.deletion {{ color: var(--red); }}
  .dest.old       {{ color: var(--orange); }}

  .reason {{
    color: var(--muted);
    font-size: 0.78rem;
    max-width: 300px;
  }}

  .size {{
    font-family: var(--mono);
    font-size: 0.78rem;
    color: var(--muted);
    white-space: nowrap;
    text-align: right;
  }}

  .empty-state {{
    text-align: center;
    padding: 4rem 2rem;
    color: var(--muted);
    font-size: 0.9rem;
    display: none;
  }}
</style>
</head>
<body>

<header>
  <h1>🌊 cleanwave</h1>
  <span class="meta">{date} &nbsp;·&nbsp; {count} files flagged &nbsp;·&nbsp; {scan_dirs}</span>
  <span class="dry-run-badge">dry run</span>
</header>

<div class="controls">
  <input type="search" id="search" placeholder="filter by name or path…" oninput="applyFilters()">
  <div class="filter-btns">
    <button class="filter-btn all active" onclick="setFilter('all', this)">all</button>
    <button class="filter-btn junk"      onclick="setFilter('junk', this)">junk</button>
    <button class="filter-btn duplicate" onclick="setFilter('duplicate', this)">duplicates</button>
    <button class="filter-btn old_file"  onclick="setFilter('old_file', this)">old files</button>
    <button class="filter-btn vague"     onclick="setFilter('vague', this)">vague</button>
  </div>
  <span class="stats" id="stats"></span>
</div>

<div class="table-wrap">
  <table id="filetable">
    <thead>
      <tr>
        <th onclick="sortBy('name')" data-col="name">file <span class="sort-arrow"></span></th>
        <th onclick="sortBy('category')" data-col="category">category <span class="sort-arrow"></span></th>
        <th onclick="sortBy('destination')" data-col="destination">destination <span class="sort-arrow"></span></th>
        <th onclick="sortBy('size')" data-col="size">size <span class="sort-arrow"></span></th>
        <th>reason</th>
      </tr>
    </thead>
    <tbody id="tbody"></tbody>
  </table>
  <div class="empty-state" id="empty">nothing matches that filter.</div>
</div>

<script>
const DATA = {data_json};

let currentFilter = 'all';
let currentSort = {{ col: null, asc: true }};

function renderAll() {{
  const tbody = document.getElementById('tbody');
  tbody.innerHTML = '';
  DATA.forEach((f, i) => {{
    const destClass = f.destination === 'deletion_approval' ? 'deletion'
                    : f.destination === 'old_files' ? 'old' : '';
    const tr = document.createElement('tr');
    tr.dataset.idx = i;
    tr.dataset.cat = f.category;
    tr.dataset.name = (f.name + f.dir).toLowerCase();
    tr.innerHTML = `
      <td class="name">
        ${{esc(f.name)}}
        <span class="dir">${{esc(f.dir)}}</span>
      </td>
      <td><span class="badge cat-${{f.category}}">${{f.category}}</span></td>
      <td class="dest ${{destClass}}">${{f.destination}}/</td>
      <td class="size">${{f.size}}</td>
      <td class="reason">${{esc(f.reason)}}</td>
    `;
    tbody.appendChild(tr);
  }});
  applyFilters();
}}

function esc(s) {{
  return String(s)
    .replace(/&/g,'&amp;').replace(/</g,'&lt;')
    .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
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
  const total = DATA.length;
  document.getElementById('stats').textContent =
    visible === total ? `${{total}} files` : `${{visible}} / ${{total}} shown`;
  document.getElementById('empty').style.display = visible === 0 ? 'block' : 'none';
}}

function sortBy(col) {{
  const ths = document.querySelectorAll('th[data-col]');
  ths.forEach(th => th.classList.remove('sorted-asc','sorted-desc'));
  if (currentSort.col === col) {{
    currentSort.asc = !currentSort.asc;
  }} else {{
    currentSort = {{ col, asc: true }};
  }}
  const th = document.querySelector(`th[data-col="${{col}}"]`);
  th.classList.add(currentSort.asc ? 'sorted-asc' : 'sorted-desc');

  const rows = Array.from(document.querySelectorAll('#tbody tr'));
  rows.sort((a, b) => {{
    const ai = parseInt(a.dataset.idx), bi = parseInt(b.dataset.idx);
    const av = DATA[ai][col] || '', bv = DATA[bi][col] || '';
    return currentSort.asc ? av.localeCompare(bv) : bv.localeCompare(av);
  }});
  const tbody = document.getElementById('tbody');
  rows.forEach(r => tbody.appendChild(r));
}}

renderAll();
</script>
</body>
</html>
"""


def generate_and_open(
    actionable: list[tuple[FileInfo, FileDecision]],
    scan_dirs: list[str],
    output_dir: Path | None = None,
) -> Path:
    """
    Write dry-run HTML to ~/.cleanwave/ and open it in the default browser.
    Returns the path to the written file.
    """
    data = _serialize(actionable)
    date_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

    html = _HTML.format(
        date=date_str,
        count=len(data),
        scan_dirs=", ".join(scan_dirs),
        data_json=json.dumps(data, ensure_ascii=False),
    )

    out_dir = output_dir or (Path.home() / ".cleanwave")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"dryrun_{stamp}.html"
    out_path.write_text(html, encoding="utf-8")

    webbrowser.open(out_path.as_uri())
    return out_path
