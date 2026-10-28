"""Builds index.html from everything in reports/.

For each file in reports/ (HTML, PDF, or anything else):
  title   -> the page's <title>, else the PDF's title, else the filename
  comment -> <meta name="description">, else a sidecar file with the same
             name ending in .txt (e.g. skynet.pdf -> skynet.txt), else blank
  date    -> the date the file was first added; order is by exact upload time

Optional overrides go in reports/_meta.json, keyed by filename:
  {"skynet.pdf": {"title": "...", "comment": "...", "date": "2026-10-23"}}
"""
import html, json, re, subprocess, time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/New_York")

ROOT = Path(__file__).parent
REPORTS = ROOT / "reports"
SKIP = {"_meta.json", ".gitkeep", ".DS_Store"}


def first_added(path):
    """Exact time (unix seconds) the file was first committed."""
    out = subprocess.run(
        ["git", "log", "--diff-filter=A", "--follow", "--format=%at", "--", str(path)],
        capture_output=True, text=True, cwd=ROOT,
    ).stdout.split()
    return int(out[-1]) if out else int(time.time())


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


def fetch_json(url, tries=4):
    import urllib.request
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "jerelevance-site"})
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.load(r)
        except Exception as e:
            print(f"  retry {attempt + 1} for {url}: {e}")
            time.sleep(2 * (attempt + 1))
    return None


def build_image_pool():
    """Collects every image/GIF block from the channels in channels.txt."""
    path = ROOT / "channels.txt"
    if not path.exists():
        return
    links = [l.strip().rstrip("/") for l in path.read_text().splitlines()
             if l.strip() and not l.strip().startswith("#")]
    pool, seen = [], set()
    for link in links:
        slug = link.split("/")[-1]
        page = 1
        while True:
            data = fetch_json(f"https://api.are.na/v2/channels/{slug}/contents?per=100&page={page}")
            if not data:
                print(f"  skipped {slug} (Are.na didn't answer)")
                break
            blocks = data.get("contents") or []
            for b in blocks:
                img = b.get("image") or {}
                if b.get("class") != "Image" or b.get("id") in seen:
                    continue
                gif = img.get("content_type") == "image/gif"
                src = (img.get("original") if gif else img.get("display") or img.get("large") or {}).get("url")
                if src:
                    seen.add(b["id"])
                    pool.append({"id": b["id"], "src": src, "channel": link})
            if len(blocks) < 100:
                break
            page += 1
            time.sleep(0.5)
        time.sleep(0.5)
    (ROOT / "images.json").write_text(json.dumps(pool))
    print(f"images.json: {len(pool)} images from {len(links)} channels")


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
        ts = first_added(f)
        items.append({
            "ts": ts,
            "href": f"reports/{f.name}",
            "title": o.get("title") or title or pretty(f.name),
            "comment": o.get("comment") or comment or "",
            "date": o.get("date") or datetime.fromtimestamp(ts, TZ).date().isoformat(),
        })

    # Newest upload on top (highest number); oldest at the bottom is 01
    items.sort(key=lambda i: i["ts"], reverse=True)

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
    build_image_pool()
