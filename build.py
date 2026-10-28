"""Builds index.html from everything in reports/.

For each file in reports/ (HTML, PDF, or anything else):
  title   -> the page's <title>, else the PDF's title, else the filename
  comment -> <meta name="description">, else a sidecar file with the same
             name ending in .txt (e.g. skynet.pdf -> skynet.txt), else blank
  date    -> the date the file was first added to the repo

Optional overrides go in reports/_meta.json, keyed by filename:
  {"skynet.pdf": {"title": "...", "comment": "...", "date": "2026-10-23"}}
"""
import html, json, re, subprocess
from datetime import date
from pathlib import Path

ROOT = Path(__file__).parent
REPORTS = ROOT / "reports"
SKIP = {"_meta.json", ".gitkeep", ".DS_Store"}


def first_added(path):
    out = subprocess.run(
        ["git", "log", "--diff-filter=A", "--follow", "--format=%as", "--", str(path)],
        capture_output=True, text=True, cwd=ROOT,
    ).stdout.split()
    return out[-1] if out else date.today().isoformat()


def from_html(path):
    text = path.read_text(errors="ignore")
    t = re.search(r"<title[^>]*>(.*?)</title>", text, re.S | re.I)
    d = re.search(r'<meta\s+name=["\']description["\']\s+content=["\'](.*?)["\']', text, re.I)
    return (html.unescape(t.group(1).strip()) if t else None,
            html.unescape(d.group(1).strip()) if d else None)


def from_pdf(path):
    try:
        from pypdf import PdfReader
        m = PdfReader(str(path)).metadata or {}
        return (m.get("/Title") or None, m.get("/Subject") or None)
    except Exception:
        return (None, None)


def pretty(name):
    return re.sub(r"[-_]+", " ", Path(name).stem).strip().title()


def main():
    overrides = {}
    if (REPORTS / "_meta.json").exists():
        overrides = json.loads((REPORTS / "_meta.json").read_text())

    sidecars = {p for p in REPORTS.glob("*.txt")
                if any(q.stem == p.stem and q.suffix != ".txt" for q in REPORTS.iterdir())}

    items = []
    for f in REPORTS.iterdir():
        if not f.is_file() or f.name in SKIP or f in sidecars:
            continue
        title, comment = (None, None)
        if f.suffix.lower() in (".html", ".htm"):
            title, comment = from_html(f)
        elif f.suffix.lower() == ".pdf":
            title, comment = from_pdf(f)
        side = f.with_suffix(".txt")
        if side in sidecars:
            comment = side.read_text().strip() or comment
        o = overrides.get(f.name, {})
        items.append({
            "href": f"reports/{f.name}",
            "title": o.get("title") or title or pretty(f.name),
            "comment": o.get("comment") or comment or "",
            "date": o.get("date") or first_added(f),
        })

    items.sort(key=lambda i: (i["date"], i["title"]), reverse=True)

    rows = "\n".join(
        f'    <li><a href="{html.escape(i["href"])}">{html.escape(i["title"])}</a>'
        f'<span class="note">{html.escape(i["comment"])}</span>'
        f'<time datetime="{i["date"]}">{i["date"].replace("-", ".")}</time></li>'
        for i in items
    )
    page = (ROOT / "template.html").read_text().replace("<!-- LIST -->", rows)
    (ROOT / "index.html").write_text(page)
    print(f"Built index.html with {len(items)} entries")


if __name__ == "__main__":
    main()
