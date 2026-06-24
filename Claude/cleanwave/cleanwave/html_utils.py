"""
html_utils.py — shared helpers for safely embedding data in HTML output.
"""


def _script_json(obj) -> str:
    """
    Serialize obj to JSON safe for embedding inside an inline <script> element.
    json.dumps alone does NOT escape <, >, &, U+2028, U+2029 — all of which
    can break or escape the script block when file paths are in the data.
    """
    import json
    return (
        json.dumps(obj, ensure_ascii=False)
        .replace("<",      "\\u003c")
        .replace(">",      "\\u003e")
        .replace("&",      "\\u0026")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )