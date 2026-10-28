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


def build_image_pool(list_file="channels.txt", out_file="images.json"):
    """Collects every image/GIF block from the Are.na channels listed in list_file."""
    path = ROOT / list_file
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
    (ROOT / out_file).write_text(json.dumps(pool))
    print(f"{out_file}: {len(pool)} images from {len(links)} channels")


def _walk(o, items, tokens):
    if isinstance(o, dict):
        if "musicResponsiveListItemRenderer" in o:
            items.append(o["musicResponsiveListItemRenderer"])
            return
        tok = (o.get("continuationCommand") or {}).get("token") or (o.get("nextContinuationData") or {}).get("continuation")
        if tok:
            tokens.append(tok)
        for v in o.values():
            _walk(v, items, tokens)
    elif isinstance(o, list):
        for v in o:
            _walk(v, items, tokens)


def _ytm(body, tries=3):
    import urllib.request
    body = {"context": {"client": {"clientName": "WEB_REMIX", "clientVersion": "1.20261027.10.00",
                                   "hl": "en", "gl": "US"}}, **body}
    for attempt in range(tries):
        try:
            req = urllib.request.Request(
                "https://music.youtube.com/youtubei/v1/browse?prettyPrint=false",
                data=json.dumps(body).encode(), method="POST",
                headers={"Content-Type": "application/json", "Origin": "https://music.youtube.com",
                         "Referer": "https://music.youtube.com/",
                         "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                                       "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except Exception as e:
            print(f"  retry {attempt + 1} for playlist: {e}")
            time.sleep(3 * (attempt + 1))
    return None


def _clean(title, artist, ugc):
    """Plain YouTube uploads come in as 'Artist - Song (Official Video)' by some channel."""
    if ugc:
        title = re.sub(r"\s*[\(\[](official|lyric|lyrics|audio|music video|hd|hq|visualizer)[^\)\]]*[\)\]]",
                       "", title, flags=re.I).strip()
        m = re.match(r"^([^()\[\]]+?)\s+[-\u2013\u2014]\s+(.+)$", title)
        if m:
            artist, title = m.group(1).strip(), m.group(2).strip()
    return title, artist


def build_songs(list_file="playlist.txt", out_file="songs.json"):
    """Every track in the YouTube Music playlist, for the song of the day.
    If YouTube doesn't answer, the songs.json already in the repo is kept."""
    path = ROOT / list_file
    if not path.exists():
        return
    lines = [l.strip() for l in path.read_text().splitlines() if l.strip() and not l.startswith("#")]
    pid = re.search(r"list=([\w-]+)", lines[0]).group(1) if lines else None
    if not pid:
        return
    items, tokens, seen = [], [], set()
    data = _ytm({"browseId": "VL" + pid})
    if data:
        _walk(data, items, tokens)
    while tokens and len(seen) < 200:
        t = tokens.pop(0)
        if t in seen:
            continue
        seen.add(t)
        page = _ytm({"continuation": t})
        if page:
            _walk(page, items, tokens)
    songs, ids = [], set()

    def text(col):
        return "".join(r.get("text", "") for r in
                       ((col or {}).get("musicResponsiveListItemFlexColumnRenderer", {}).get("text", {}).get("runs") or []))

    for r in items:
        vid = (r.get("playlistItemData") or {}).get("videoId")
        if not vid or vid in ids:
            continue
        ids.add(vid)
        cols = r.get("flexColumns") or [{}, {}]
        ugc = "MUSIC_VIDEO_TYPE_UGC" in json.dumps(r.get("overlay") or {})
        title, artist = _clean(text(cols[0]), text(cols[1]) if len(cols) > 1 else "", ugc)
        songs.append({"id": vid, "title": title, "artist": artist})
    if len(songs) < 10:
        print(f"{out_file}: YouTube gave {len(songs)} songs, keeping the old list")
        return
    (ROOT / out_file).write_text(json.dumps(songs, ensure_ascii=False))
    print(f"{out_file}: {len(songs)} songs")


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
    build_image_pool()                          # daily image
    build_image_pool("tarot.txt", "tarot.json")  # tarot deck
    build_songs()                               # song of the day
