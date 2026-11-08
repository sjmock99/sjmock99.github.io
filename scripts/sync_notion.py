#!/usr/bin/env python3
"""Pull the Notion Engineering Wiki and write the site's generated files: assets/data/skills.json (skills, projects,
experience), the resume / skills / projects regions of index.html, one page per project in projects/, and the
project photos in assets/img/projects/ (copied, since Notion's own file links expire after about an hour).

Read-only against Notion. Standard library only; with Pillow installed (pip install pillow) photos are also
resized to web sizes, otherwise they're copied as they are.

    python3 scripts/sync_notion.py                 # only Public pages
    SHOW_ALL=true python3 scripts/sync_notion.py   # ignore Public (dev)
    PREVIEW=true python3 scripts/sync_notion.py    # drafts too, written to .preview/ only (see scripts/admin.py)

The key comes from $NOTION_TOKEN, or else from the file ~/.notion_token.
"""
import hashlib
import html
import io
import json
import math
import mimetypes
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

DATA_SOURCE_ID = "2878f022-083c-8115-8062-000b4bbbb400"
DATABASE_ID = "2878f022083c8015a0ddde278a3c5e1d"
NOTION_VERSION = "2025-09-03"
API = "https://api.notion.com/v1"

# Discipline hubs: the roots of the tree. They have no Parent skill and are always shown.
HUBS = {
    "4038f022083c81189869f42fa0a06ba6": "Mechanical",
    "4038f022083c8166a9b2fcd4495d12d2": "Electrical",
    "4038f022083c8114a338c414bce9fda6": "Software",
    "4038f022083c816ba41df0761731bca6": "Systems",
    "4038f022083c811fb594ceb95406688b": "Other",
}

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets" / "data" / "skills.json"
# Drafts preview: the same layout as the site, holding only the generated files (the admin serves the rest from
# the repo). Listed in .gitignore, so it's never committed.
PREVIEW = ROOT / ".preview"
TOKEN_FILE = Path.home() / ".notion_token"


class NotionError(Exception):
    pass


def get_token():
    token = os.environ.get("NOTION_TOKEN", "").strip()
    if not token and TOKEN_FILE.exists():
        token = TOKEN_FILE.read_text().strip()
    if not token:
        raise NotionError("No Notion key: set NOTION_TOKEN or create ~/.notion_token")
    return token


def request(method, path, body=None):
    token = get_token()
    req = urllib.request.Request(
        API + path,
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={
            "Authorization": f"Bearer {token}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        },
    )
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                time.sleep(0.35)  # stay under Notion's ~3 requests/second
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code in (429, 502, 503) and attempt < 4:
                time.sleep(float(e.headers.get("Retry-After", 2 ** attempt)))
                continue
            raise NotionError(f"Notion API {e.code} on {path}: {e.read().decode(errors='replace')}")
        except (urllib.error.URLError, TimeoutError) as e:  # network blip: retry, then give a clean error
            if attempt < 4:
                time.sleep(2 ** attempt)
                continue
            raise NotionError(f"Couldn't reach Notion ({getattr(e, 'reason', e)})")


def query_all():
    pages, cursor = [], None
    while True:
        # Sorting matters: Notion's unsorted query can leave out pages created in the last few minutes.
        body = {"page_size": 100, "sorts": [{"timestamp": "created_time", "direction": "ascending"}]}
        if cursor:
            body["start_cursor"] = cursor
        res = request("POST", f"/data_sources/{DATA_SOURCE_ID}/query", body)
        # The wiki can also return databases nested inside it (e.g. a wish list); keep only pages.
        pages += [r for r in res["results"] if r.get("object") == "page"]
        if not res.get("has_more"):
            return pages + recent_missing(pages)
        cursor = res["next_cursor"]


def recent_missing(pages):
    """Notion's query index can lag several minutes behind new pages, but search sees them at once.
    Return recently edited wiki pages that the query left out."""
    have = {p["id"] for p in pages}
    # Search also returns the wiki's templates (Reference, Project, …); those aren't real pages.
    have |= {t["id"] for t in request("GET", f"/data_sources/{DATA_SOURCE_ID}/templates")["templates"]}
    res = request("POST", "/search", {
        "filter": {"property": "object", "value": "page"},
        "sort": {"timestamp": "last_edited_time", "direction": "descending"},
        "page_size": 100,
    })
    in_wiki = lambda parent: (parent.get("data_source_id") == DATA_SOURCE_ID
                              or (parent.get("database_id") or "").replace("-", "") == DATABASE_ID)
    return [p for p in res["results"]
            if p["id"] not in have and in_wiki(p["parent"]) and not p.get("in_trash") and not p.get("archived")]


def relation_ids(page, name):
    """Relation values are truncated (~25 items) in query results; fetch the full list if so."""
    prop = page["properties"].get(name)
    if not prop:
        return []
    ids = [r["id"] for r in prop.get("relation", [])]
    if prop.get("has_more"):
        ids, cursor = [], None
        while True:
            q = f"?start_cursor={cursor}" if cursor else ""
            res = request("GET", f"/pages/{page['id']}/properties/{prop['id']}{q}")
            ids += [r["relation"]["id"] for r in res["results"]]
            if not res.get("has_more"):
                break
            cursor = res["next_cursor"]
    return [i.replace("-", "") for i in ids]


def plain(p, name):
    return "".join(t["plain_text"] for t in p.get(name, {}).get("rich_text", [])).strip()


def to_record(page):
    p = page["properties"]
    title = "".join(t["plain_text"] for t in p.get("Page", {}).get("title", [])).strip()
    date = p.get("Date", {}).get("date") or {}
    return {
        "id": page["id"].replace("-", ""),
        "name": title,
        "url": page.get("url"),
        "types": [o["name"] for o in p.get("Type", {}).get("multi_select", [])],
        "parent": (relation_ids(page, "Parent skill") or [None])[0],
        "rating": p.get("Rating", {}).get("number"),  # None = unrated; never coerce to 0
        "target": p.get("Target", {}).get("number"),
        "public": p.get("Public", {}).get("checkbox", False),
        "featured": p.get("Featured", {}).get("checkbox", False),
        # Ticked on pages Claude wrote or changed, until the owner has read them (only the admin uses it).
        "needs_review": p.get("Needs review", {}).get("checkbox", False),
        "cover": page.get("cover"),  # the page's own cover image (Notion's "Add cover"), or None
        "icon": page.get("icon"),  # the page icon; an uploaded / linked image is a job's or school's logo
        # Public-facing description shown on the website (a property, separate from the private page body).
        "blurb": plain(p, "Blurb"),
        "skills_used": relation_ids(page, "Skills used"),
        # Projects / Experience / Education
        "role": plain(p, "Role"),
        "organization": plain(p, "Organization"),
        "location": plain(p, "Location"),
        "link": p.get("Link", {}).get("url"),
        "start": date.get("start"),
        "end": date.get("end"),
    }


# ---- 🌐 Public section: the part of a page body that's shown on the website ----
# A heading containing "🌐 Public" (everything after it, up to the next heading of the same or a higher level),
# or a toggle / toggle heading with that title (everything inside it). The rest of the page stays private.

def block_children(block_id):
    out, cursor = [], None
    while True:
        q = f"?page_size=100&start_cursor={cursor}" if cursor else "?page_size=100"
        res = request("GET", f"/blocks/{block_id}/children{q}")
        out += res["results"]
        if not res.get("has_more"):
            return out
        cursor = res["next_cursor"]


def block_text(b):
    return "".join(t["plain_text"] for t in b.get(b["type"], {}).get("rich_text", []))


def caption(b):
    return "".join(t["plain_text"] for t in b["image"].get("caption", [])).strip()


def is_public_marker(b):
    return b["type"] in ("heading_1", "heading_2", "heading_3", "toggle") and re.search(r"🌐\s*public", block_text(b), re.I)


def is_toggle(b):
    return b["type"] == "toggle" or (b["type"].startswith("heading_") and b[b["type"]].get("is_toggleable"))


def is_photos_marker(b):
    """The "📷 Photos" toggle inside a 🌐 Public section: its images become the project's gallery."""
    t = block_text(b).strip()
    return is_toggle(b) and ("📷" in t or t.lower() in ("photos", "photo", "gallery"))


def is_placeholder(b):
    """Template hints like "(what it is and why you built it)": a whole line in brackets is never published."""
    t = block_text(b).strip()
    return len(t) > 1 and t[0] == "(" and t[-1] == ")"


def rich_html(rich):
    out = []
    for t in rich:
        s, a = html.escape(t["plain_text"]), t.get("annotations", {})
        if a.get("code"): s = f"<code>{s}</code>"
        if a.get("bold"): s = f"<b>{s}</b>"
        if a.get("italic"): s = f"<i>{s}</i>"
        if a.get("strikethrough"): s = f"<s>{s}</s>"
        href = t.get("href") or ""
        if href.startswith(("http://", "https://")):
            s = f'<a href="{html.escape(href)}" target="_blank" rel="noopener">{s}</a>'
        out.append(s)
    return "".join(out)


def heading_level(b):
    return int(b["type"][-1]) if b["type"].startswith("heading_") and not b[b["type"]].get("is_toggleable") else None


def blocks_html(blocks, media=None):
    """Notion blocks -> a small, safe subset of HTML (paragraphs, lists, sub-headings, quotes, dividers).
    Bracketed template hints, the 📷 Photos toggle and sub-headings with nothing under them are left out, so a
    half-filled page still looks tidy. media(block) -> HTML for a photo, video or embed; without it they're skipped."""
    blocks = [b for b in blocks if not is_placeholder(b) and not is_photos_marker(b)]
    def empty_heading(i):
        lv = heading_level(blocks[i])
        if lv is None:
            return False
        nxt = blocks[i + 1] if i + 1 < len(blocks) else None
        return nxt is None or (heading_level(nxt) or 9) <= lv
    blocks = [b for i, b in enumerate(blocks) if not empty_heading(i)]
    out, i = [], 0
    while i < len(blocks):
        b, kind = blocks[i], blocks[i]["type"]
        if kind in ("bulleted_list_item", "numbered_list_item"):
            tag, items = "ul" if kind == "bulleted_list_item" else "ol", []
            while i < len(blocks) and blocks[i]["type"] == kind:
                li = blocks[i]
                sub = blocks_html(block_children(li["id"]), media) if li.get("has_children") else ""
                items.append(f"<li>{rich_html(li[kind]['rich_text'])}{sub}</li>")
                i += 1
            out.append(f"<{tag}>{''.join(items)}</{tag}>")
            continue
        body = rich_html(b.get(kind, {}).get("rich_text", []))
        if kind == "paragraph" and body:
            out.append(f"<p>{body}</p>")
        elif kind.startswith("heading_"):
            out.append(f"<h5>{body}</h5>")
        elif kind == "quote":
            out.append(f"<blockquote>{body}</blockquote>")
        elif kind == "divider":
            out.append("<hr>")
        elif kind == "toggle":
            out.append(f"<p><b>{body}</b></p>")
        elif kind in ("image", "video", "embed") and media:
            out.append(media(b))
        if kind in ("toggle", "quote", "paragraph") and b.get("has_children"):
            out.append(blocks_html(block_children(b["id"]), media))
        i += 1
    return "".join(out)


def public_section(page_id):
    """The blocks of the page's 🌐 Public section, or None if it has none."""
    blocks = block_children(page_id)
    for i, b in enumerate(blocks):
        if not is_public_marker(b):
            continue
        if is_toggle(b):
            return block_children(b["id"]) if b.get("has_children") else []
        level, section = int(b["type"][-1]), []
        for nb in blocks[i + 1:]:
            if nb["type"].startswith("heading_") and int(nb["type"][-1]) <= level:
                break
            section.append(nb)
        return section
    return None


def public_html(page_id):
    """HTML for the page's 🌐 Public section, or None if it has none."""
    section = public_section(page_id)
    return None if section is None else blocks_html(section)

# ---- Photos: downloaded into the site, since Notion's file links expire after about an hour ----

try:
    from PIL import Image, ImageChops, ImageOps
except ImportError:  # still works without Pillow: photos are just copied at full size
    Image = None

IMG_DIR = "assets/img/projects"  # relative to the site root; one folder per project
SIZES = {"sm": 800, "lg": 1600}  # longest side in px: cards and thumbnails, full view
LOGO_DIR = "assets/img/logos"  # job / school logos (the Notion page icons)
LOGO_SIZES = {"sm": 96, "lg": 192}
MANAGED = (IMG_DIR, LOGO_DIR)  # the only folders the sync writes into and cleans up
MAX_BYTES = 40 * 1024 * 1024
WEB_TYPES = {"image/jpeg": ".jpg", "image/png": ".png", "image/gif": ".gif", "image/webp": ".webp", "image/avif": ".avif",
             "image/svg+xml": ".svg"}
KEEP_AS_IS = (".gif", ".svg")  # animations, and drawings that are already any size
# Short clips uploaded to Notion are copied too (longer videos belong on YouTube, which embeds instead).
VIDEO_TYPES = {"video/mp4": ".mp4", "video/webm": ".webm", "video/quicktime": ".mov"}
VIDEO_MAX = 20 * 1024 * 1024  # git keeps every version of a file forever, so big videos would bloat the repo


def file_source(obj):
    """A Notion file object (page cover or image block) -> (url, key). Uploaded files get a new signed URL on
    every read, so the key that identifies the photo is the URL without its query string."""
    kind = (obj or {}).get("type")
    url = (obj.get(kind) or {}).get("url", "") if kind in ("file", "external") else ""
    if not url.startswith(("http://", "https://")):
        return None
    return url, url.split("?", 1)[0] if kind == "file" else url


def trim_logo(im):
    """Crop the empty border around a logo (transparent, or the colour of its corner) and centre it on a square with a
    small margin, so every logo fills its square slot the same way however much padding its file came with."""
    alpha = im.mode == "RGBA"
    if alpha and im.getchannel("A").getextrema()[0] < 255:
        mask, fill = im.getchannel("A").point(lambda v: 255 if v > 16 else 0), (0, 0, 0, 0)
    else:
        fill = im.getpixel((0, 0))
        mask = ImageChops.difference(im.convert("RGB"), Image.new("RGB", im.size, im.convert("RGB").getpixel((0, 0))))
        mask = mask.convert("L").point(lambda v: 255 if v > 24 else 0)
    box = mask.getbbox()
    if not box:
        return im
    w, h = box[2] - box[0], box[3] - box[1]
    side = int(max(w, h) * 1.08) + 1
    square = Image.new(im.mode, (side, side), fill)
    square.paste(im.crop(box), ((side - w) // 2, (side - h) // 2))
    return square


class Photos:
    """Saves photos and logos into a folder under <root> (one of MANAGED), reusing any already saved (in root, or
    for a preview also in the repo), and afterwards deletes the ones nothing uses any more."""

    def __init__(self, root, reuse=None):
        self.root, self.reuse, self.used, self.failed = root, reuse, set(), []

    def get(self, obj, rel, caption="", sizes=SIZES):
        """rel: the folder, relative to the site root. -> {"sm", "lg", "caption"} with paths relative to the site
        root, or None if it can't be had."""
        src = file_source(obj)
        if not src:
            return None
        # Logos are trimmed (trim_logo), so they get their own names: a browser never shows an untrimmed cached copy.
        name = hashlib.sha1((src[1] + ("|trimmed" if sizes is LOGO_SIZES else "")).encode()).hexdigest()[:12]
        try:
            files = self.saved(rel, name, sizes) or self.save(self.download(src[0]), rel, name, sizes)
        except (OSError, ValueError) as e:  # urllib errors are OSErrors
            self.failed.append(f"{rel.rsplit('/', 1)[-1]}: {e}")
            return None
        return {**files, "caption": caption}

    def saved(self, rel, name, sizes):
        for base in filter(None, (self.root, self.reuse)):
            d = base / rel
            if (d / f"{name}-sm.webp").exists() and (d / f"{name}-lg.webp").exists():
                return self.use(base, rel, f"{name}-sm.webp", f"{name}-lg.webp")
            original = next((f for f in d.glob(f"{name}.*") if f.suffix in WEB_TYPES.values()), None) if d.is_dir() else None
            if original:
                # Saved before Pillow was available: make the web sizes from it now (no new download).
                if Image and base == self.root and original.suffix not in KEEP_AS_IS:
                    return self.save((original.read_bytes(), "image/" + original.suffix[1:]), rel, name, sizes)
                return self.use(base, rel, original.name, original.name)
        return None

    def use(self, base, rel, sm, lg):
        if base == self.root:
            self.used.update({f"{rel}/{sm}", f"{rel}/{lg}"})
        return {"sm": f"{rel}/{sm}", "lg": f"{rel}/{lg}"}

    def get_video(self, obj, rel):
        """A video file (uploaded to Notion, or linked directly) -> its path relative to the site root, or None.
        Copied as is; anything over VIDEO_MAX is skipped with a note to put it on YouTube instead."""
        src = file_source(obj)
        if not src:
            return None
        name = hashlib.sha1(src[1].encode()).hexdigest()[:12]
        for base in filter(None, (self.root, self.reuse)):
            for ext in VIDEO_TYPES.values():
                if (base / rel / f"{name}{ext}").exists():
                    return self.use(base, rel, f"{name}{ext}", f"{name}{ext}")["sm"]
        try:
            data, ctype = self.download(src[0], VIDEO_MAX, "video is over 20 MB: put it on YouTube and paste the link instead")
            ext = VIDEO_TYPES.get(ctype) or next((x for x in VIDEO_TYPES.values() if src[1].lower().endswith(x)), None)
            if not ext:
                raise ValueError(f"not a video browsers can play ({ctype}); save it as MP4")
        except (OSError, ValueError) as e:
            self.failed.append(f"{rel.rsplit('/', 1)[-1]}: {e}")
            return None
        (self.root / rel).mkdir(parents=True, exist_ok=True)
        (self.root / rel / f"{name}{ext}").write_bytes(data)
        return self.use(self.root, rel, f"{name}{ext}", f"{name}{ext}")["sm"]

    @staticmethod
    def download(url, limit=MAX_BYTES, too_big="photo is over 40 MB"):
        req = urllib.request.Request(url, headers={"User-Agent": "sjmock99.github.io photo sync"})
        with urllib.request.urlopen(req, timeout=120) as r:
            if int(r.headers.get("Content-Length") or 0) > limit:  # don't fetch what we'd throw away
                raise ValueError(too_big)
            ctype, data = r.headers.get_content_type(), r.read(limit + 1)
        if len(data) > limit:
            raise ValueError(too_big)
        return data, ctype

    def save(self, got, rel, name, sizes):
        data, ctype = got
        d = self.root / rel
        d.mkdir(parents=True, exist_ok=True)
        if Image and WEB_TYPES.get(ctype) not in KEEP_AS_IS:
            try:
                im = ImageOps.exif_transpose(Image.open(io.BytesIO(data)))  # phone photos: apply the rotation
                alpha = im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info)
                im = im.convert("RGBA" if alpha else "RGB")
                if sizes is LOGO_SIZES:
                    im = trim_logo(im)
                for size, px in sizes.items():
                    copy = im.copy()
                    copy.thumbnail((px, px))
                    # Logos are tiny and have sharp edges: keep them exact rather than compressed.
                    copy.save(d / f"{name}-{size}.webp", "WEBP", quality=82, method=4, lossless=sizes is LOGO_SIZES)
                return self.use(self.root, rel, f"{name}-sm.webp", f"{name}-lg.webp")
            except Exception:  # e.g. an iPhone HEIC photo Pillow can't read: keep the original below
                pass
        ext = WEB_TYPES.get(ctype)
        if not ext:
            raise ValueError(f"not a photo browsers can show ({ctype}); save it as JPG or PNG")
        (d / f"{name}{ext}").write_bytes(data)
        return self.use(self.root, rel, f"{name}{ext}", f"{name}{ext}")

    def remove_unused(self):
        gone = 0
        for base in (self.root / d for d in MANAGED):
            for f in sorted(base.rglob("*"), reverse=True) if base.is_dir() else []:  # files before their folders
                if f.is_file() and f.relative_to(self.root).as_posix() not in self.used:
                    f.unlink()
                    gone += 1
                elif f.is_dir() and not any(f.iterdir()):
                    f.rmdir()
        return gone


def slugify(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:60].rstrip("-") or "project"


def video_link(url):
    """A YouTube or Vimeo address -> ("youtube" | "vimeo", id, tall), or None. tall: a YouTube Short (vertical)."""
    m = re.match(r"https?://(?:www\.|m\.)?(?:youtube\.com/(?:watch\?(?:.*&)?v=|shorts/|embed/|live/)|youtu\.be/)([A-Za-z0-9_-]{11})", url or "")
    if m:
        return "youtube", m.group(1), "/shorts/" in url
    m = re.match(r"https?://(?:www\.|player\.)?vimeo\.com/(?:video/)?(\d+)", url or "")
    return ("vimeo", m.group(1), False) if m else None


def block_video(b):
    """A video / embed block -> ("link", (service, id, tall)) for YouTube / Vimeo, ("file", file object) for a
    video file, or None."""
    obj = b.get(b["type"]) or {}
    url = obj.get("url") if b["type"] == "embed" else (obj.get("external") or {}).get("url")
    link = video_link(url)
    if link:
        return "link", link
    return ("file", obj) if b["type"] == "video" else None


def media_caption(b):
    return "".join(t["plain_text"] for t in (b.get(b["type"]) or {}).get("caption", [])).strip()


def project_content(it, cover, photos):
    """Fill in a project's write-up and media from its page: "details" (HTML of the 🌐 Public section, with any photos
    and videos in it), "gallery" (the 📷 Photos toggle: photos, clips and YouTube / Vimeo links) and "cover" (the
    page cover, else the first gallery photo, else a video's thumbnail). "videos" counts the videos on the page."""
    section = public_section(it["id"])
    it["has_public"] = section is not None
    section = section or []
    rel = f"{IMG_DIR}/{it['slug']}"
    videos = 0
    def media(b):
        nonlocal videos
        if b["type"] == "image":
            ph = photos.get(b["image"], rel, caption(b))
            return figure(ph, "pj-figure") if ph else ""
        v = block_video(b)
        if not v:
            return ""
        src = photos.get_video(v[1], rel) if v[0] == "file" else None
        if v[0] == "file" and not src:
            return ""
        videos += 1
        return video_html(v[1] if v[0] == "link" else None, src, media_caption(b))
    it["details"] = blocks_html(section, media)
    marker = next((b for b in section if is_photos_marker(b)), None)
    gallery, thumbs = [], []
    if marker and marker.get("has_children"):
        for b in block_children(marker["id"]):
            if b["type"] == "image":
                ph = photos.get(b["image"], rel, caption(b))
                if ph:
                    gallery.append({**ph, "kind": "image"})
            elif b["type"] in ("video", "embed"):
                v = block_video(b)
                if v and v[0] == "file":
                    src = photos.get_video(v[1], rel)
                    if src:
                        gallery.append({"kind": "clip", "src": src, "caption": media_caption(b)})
                elif v:
                    service, vid, tall = v[1]
                    # The video's own thumbnail, copied like a photo (YouTube serves one at a fixed address).
                    thumb = photos.get({"type": "external", "external": {"url": f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"}}, rel) \
                        if service == "youtube" else None
                    url = f"https://www.youtube.com/watch?v={vid}" if service == "youtube" else f"https://vimeo.com/{vid}"
                    gallery.append({"kind": "link", "url": url, "thumb": thumb, "caption": media_caption(b)})
                    if thumb:
                        thumbs.append(thumb)
    videos += sum(1 for g in gallery if g["kind"] != "image")
    it["cover"] = photos.get(cover, rel) if cover else None
    first_photo = next((g for g in gallery if g["kind"] == "image"), None)
    if not it["cover"] and first_photo:
        gallery.remove(first_photo)  # the first photo leads the page instead of repeating in the grid
        it["cover"] = first_photo
    if not it["cover"] and thumbs:
        it["cover"] = {**thumbs[0], "caption": ""}  # no photos at all: a video's thumbnail stands in on the card
        it["cover_is_thumb"] = True
    it["gallery"], it["videos"] = gallery, videos


def video_html(link, src, cap):
    """A video in the write-up: YouTube / Vimeo as their player (built only from the parsed id, never an arbitrary
    address), or a copied clip as a <video> with controls."""
    e = html.escape
    capt = f"<figcaption>{e(cap)}</figcaption>" if cap else ""
    if link:
        service, vid, tall = link
        url = (f"https://www.youtube-nocookie.com/embed/{vid}" if service == "youtube" else f"https://player.vimeo.com/video/{vid}")
        return (f'<figure class="pj-video{" pj-video-tall" if tall else ""}"><span class="pj-frame">'
                f'<iframe src="{url}" title="{e(cap or "Video")}" loading="lazy" allowfullscreen '
                f'allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share" '
                f'referrerpolicy="strict-origin-when-cross-origin"></iframe></span>{capt}</figure>')
    return f'<figure class="pj-figure pj-clip"><video src="{e(src)}" controls preload="metadata" playsinline></video>{capt}</figure>'


def gallery_item(g):
    """One square in the photo grid: a photo, a clip that plays silently on a loop, or a video's thumbnail with a
    play button. All open in the lightbox (GLightbox plays clips and YouTube / Vimeo itself)."""
    e, cap = html.escape, g["caption"]
    desc = f' data-description="{e(cap)}"' if cap else ""
    if g["kind"] == "image":
        return figure(g, "pj-thumb", "sm")
    play = '<span class="pj-play" aria-hidden="true"><i class="bi bi-play-fill"></i></span>'
    if g["kind"] == "clip":
        return (f'<figure class="pj-thumb"><a class="glightbox" data-gallery="project" href="{e(g["src"])}"{desc} aria-label="Play video">'
                f'<video src="{e(g["src"])}" muted loop autoplay playsinline preload="metadata"></video>{play}</a></figure>')
    inner = f'<img src="{e(g["thumb"]["sm"])}" alt="" loading="lazy">' if g["thumb"] else '<span class="pj-ph"></span>'
    return (f'<figure class="pj-thumb"><a class="glightbox" data-gallery="project" href="{e(g["url"])}"{desc} aria-label="Play video">'
            f'{inner}{play}</a></figure>')


def figure(ph, cls, size="lg"):
    """A photo that opens in the lightbox (GLightbox, already on the site); all of a page's photos page through together."""
    e, cap = html.escape, ph["caption"]
    return (f'<figure class="{cls}"><a class="glightbox" data-gallery="project" href="{e(ph["lg"])}"'
            f'{f" data-description={chr(34)}{e(cap)}{chr(34)}" if cap else ""}>'
            f'<img src="{e(ph[size])}" alt="{e(cap)}" loading="lazy"></a>'
            f'{f"<figcaption>{e(cap)}</figcaption>" if cap else ""}</figure>')


def is_skill(r):
    """Type contains Reference, or no Type at all but a Parent skill (e.g. a page made with plain + New)."""
    return "Reference" in r["types"] or (not r["types"] and bool(r["parent"]))


def build(records, show_all):
    visible = lambda r: show_all or r["public"]
    candidates = {
        r["id"]: r for r in records
        if is_skill(r) and (r["id"] in HUBS or r["parent"])
    }

    # Keep a skill only if its whole Parent chain reaches a hub through visible pages.
    keep = {}
    def reaches_hub(rid, seen=()):
        if rid in keep:
            return keep[rid]
        r = candidates.get(rid)
        if r is None or rid in seen:
            ok = False
        elif rid in HUBS:
            ok = True
        else:
            ok = visible(r) and reaches_hub(r["parent"], seen + (rid,))
        keep[rid] = ok
        return ok

    skills = [
        {"id": r["id"], "name": r["name"] or HUBS.get(r["id"], "Untitled"),
         "parent": None if r["id"] in HUBS else r["parent"],
         "rating": r["rating"], "target": r["target"], "blurb": r["blurb"]}
        for r in candidates.values() if reaches_hub(r["id"])
    ]
    skill_ids = {s["id"] for s in skills}

    def item(r, **extra):
        return {"id": r["id"], "name": r["name"], "blurb": r["blurb"], "organization": r["organization"],
                "start": r["start"], "end": r["end"], **extra,
                "skills": [s for s in r["skills_used"] if s in skill_ids]}
    projects = [
        item(r, link=r["link"], featured=r["featured"])
        for r in records
        if "Project" in r["types"] and visible(r)
        and not r["name"].lower().startswith("[old - delete]")
    ]
    # Each project gets a page at projects/<slug>.html; a clash of names gets part of the page id added.
    taken = set()
    for it in sorted(projects, key=lambda p: p["id"]):
        slug = slugify(it["name"])
        it["slug"] = slug if slug not in taken else f"{slug}-{it['id'][:6]}"
        taken.add(it["slug"])
    # Jobs and degrees. No end date on a job means it's current.
    experience = [
        item(r, kind="education" if "Education" in r["types"] else "work", role=r["role"], location=r["location"])
        for r in records
        if ("Experience" in r["types"] or "Education" in r["types"]) and visible(r)
    ]
    skills.sort(key=lambda s: s["name"].lower())
    projects.sort(key=lambda p: p["name"].lower())
    experience.sort(key=lambda e: e["start"] or "", reverse=True)
    return skills, projects, experience


# ---- Homepage resume + skills preview: written into index.html between <!-- notion:<name>:start ... --> and <!-- notion:<name>:end --> ----

INDEX = OUT.parent.parent.parent / "index.html"
HUB_KEYS = {"Mechanical": "mech", "Electrical": "elec", "Software": "soft", "Systems": "sys", "Other": "oth"}
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
MAX_CHIPS = 12  # more than this and the card links to the graph for the rest


def date_range(it):
    """Same format as skill-graph.js: "Sep 2024 - Sep 2025", "Feb 2026 - Present"; degrees show years only."""
    if not it["start"]:
        return ""
    f = (lambda d: d[:4]) if it["kind"] == "education" else (lambda d: f"{MONTHS[int(d[5:7]) - 1]} {d[:4]}")
    end = f(it["end"]) if it["end"] else ("Present" if it["kind"] == "work" else "")
    return f"{f(it['start'])} - {end}" if end and end != f(it["start"]) else f(it["start"])


def top_level_class(h, cls):
    """Add class="cls" to the outermost <ul>/<ol> tags of a details fragment (nested lists keep their own look)."""
    out, depth, pos = [], 0, 0
    for m in re.finditer(r"<(/?)(ul|ol)>", h):
        out.append(h[pos:m.start()])
        if m.group(1):
            depth -= 1
            out.append(m.group(0))
        else:
            out.append(f'<{m.group(2)} class="{cls}">' if depth == 0 else m.group(0))
            depth += 1
        pos = m.end()
    return "".join(out) + h[pos:]


def disc_key(s, by_id):
    """"mech", "soft", … for the discipline hub a skill sits under."""
    seen = set()
    while s["parent"] and s["parent"] in by_id and s["id"] not in seen:
        seen.add(s["id"])
        s = by_id[s["parent"]]
    return HUB_KEYS.get(s["name"], "oth")


def skill_chips(it, skills, limit=MAX_CHIPS):
    """Chips for the skills an item used, strongest first. With a limit, the rest are left to a skill graph link."""
    by_id = {s["id"]: s for s in skills}
    disc = lambda s: disc_key(s, by_id)
    used = sorted((by_id[i] for i in it["skills"] if i in by_id),
                  key=lambda s: (-(s["rating"] or 0), s["name"].lower()))
    if not used:
        return ""
    e = html.escape
    def chip(s):
        title = f"{s['name']} · Lv {s['rating']:g}" if s["rating"] else s["name"]
        return (f'<a class="rs-chip" href="skills.html#skill={s["id"]}" title="{e(title)}">'
                f'<span class="rs-dot rs-{disc(s)}"></span>{e(s["name"])}</a>')
    chips = "".join(chip(s) for s in used[:limit])
    if not limit:
        return f'<div class="rs-skills">{chips}</div>'
    more = f"+{len(used) - limit} more in the skill graph" if len(used) > limit else "See these in the skill graph"
    return (f'<div class="rs-skills">{chips}</div>'
            f'<a class="rs-more" href="skills.html#item={it["id"]}">{more} →</a>')


def experience_html(items, skills):
    e, out = html.escape, []
    logos = any(i.get("logo") for i in items)
    for n, it in enumerate(i for i in items if i["kind"] == "work"):
        org = ": ".join(x for x in (it["organization"], it["location"]) if x) or it["name"]
        bullets = top_level_class(it.get("details") or "", "achievements").strip()
        out.append(f"""
                <div class="experience-card" id="exp-{it["id"]}" data-aos="zoom-in" data-aos-delay="{max(300, 500 - n * 100)}">
                  <div class="card-header">
                    {logo_html(it, "exp-logo") if logos else ""}
                    <div class="role-info">
                      <h3>{e(it["role"] or it["name"])}</h3>
                      <h4>{e(org)}</h4>
                    </div>
                    <div class="exp-side">
                      <span class="duration">{e(date_range(it))}</span>
                      {toggle(it) if bullets else ""}
                    </div>
                  </div>
                  <div class="card-body">
                    {f"<p>{e(it['blurb'])}</p>" if it["blurb"] else ""}
                    {skill_chips(it, skills)}
                    {f'<div class="exp-more" id="exp-more-{it["id"]}" hidden>{bullets}</div>' if bullets else ""}
                  </div>
                </div>""")
    return "".join(out)


def logo_html(it, cls):
    """A job's / school's logo (its Notion page icon), else its initials in a small badge (NASA, UCLA, RS…)."""
    if it.get("logo"):
        sm, lg = (html.escape(it["logo"][k]) for k in ("sm", "lg"))
        # The bigger copy on sharp (high-density) screens, so small logos stay crisp.
        srcset = f' srcset="{sm} 1x, {lg} 2x"' if lg != sm else ""
        return f'<img class="{cls}" src="{sm}"{srcset} alt="" loading="lazy">'
    words = re.findall(r"[A-Za-z0-9]+", it["organization"] or it["name"]) or ["?"]
    if words[0].isupper() and len(words[0]) <= 4:
        initials = words[0]
    else:
        initials = "".join(w[0].upper() for w in words if w.lower() not in ("of", "the", "and", "at", "for"))[:2]
    return f'<span class="{cls} logo-initials" aria-hidden="true">{html.escape(initials)}</span>'


def toggle(it):
    """The "See more ⌄" / "See less ⌃" button under a job's dates that opens its bullets (assets/js/resume.js)."""
    label = html.escape(f"{it['role']}, {it['organization']}")
    return (f'<button class="exp-toggle" type="button" aria-expanded="false" aria-controls="exp-more-{it["id"]}" title="{label}">'
            f'<span class="exp-show">See more</span><span class="exp-hide">See less</span>'
            f'<i class="bi bi-chevron-down" aria-hidden="true"></i></button>')


def education_html(items, skills):
    """Degrees as compact cards side by side. A "GPA …" bullet becomes a badge on the card."""
    e, out = html.escape, []
    logos = any(i.get("logo") for i in items)
    edu = [i for i in items if i["kind"] == "education"]
    for n, it in enumerate(edu):
        school = f'{it["organization"]} ({it["location"]})' if it["location"] else it["organization"]
        details = it.get("details") or ""
        gpa = re.search(r"<li>\s*GPA:?\s*([0-9.]+)(?:\s*/\s*[0-9.]+)?\s*</li>", details)
        if gpa:
            details = details.replace(gpa.group(0), "", 1).replace("<ul></ul>", "")
        out.append(f"""
                <div class="edu-card" data-aos="fade-up" data-aos-delay="{200 + n * 100}">
                  <div class="edu-card-head">
                    {logo_html(it, "edu-logo") if logos else ""}
                    <div>
                      <h3>{e(it["role"] or it["name"])}</h3>
                      <h4>{e(school)}</h4>
                    </div>
                  </div>
                  <div class="edu-card-meta">
                    <span class="edu-year">{e(date_range(it))}</span>
                    {f'<span class="edu-gpa">{e(gpa.group(1))} GPA</span>' if gpa else ""}
                  </div>
                  {f"<p>{e(it['blurb'])}</p>" if it["blurb"] else ""}
                  {top_level_class(details, "edu-details")}
                  {skill_chips(it, skills)}
                </div>""")
    return "".join(out)


def month_no(d):
    return int(d[:4]) * 12 + int(d[5:7]) - 1


def duration(n):
    y, m = divmod(n, 12)
    return " ".join(x for x in (f"{y} yr" if y else "", f"{m} mo" if m else "") if x) or "1 mo"


def degree_short(it):
    r = (it["role"] or "").lower()
    return "Bachelor's" if r.startswith("bachelor") else "Master's" if r.startswith("master") else \
        "PhD" if r.startswith(("doctor", "ph")) else it["organization"] or it["name"]


def timeline_html(items, today=None):
    """Professional Experience timeline: one row per job (newest first) on a shared time axis, degrees as a strip
    on top. A job with no end date runs to this month, so the chart moves once a month, not on every sync.
    Clicking a row opens that job's card (assets/js/resume.js)."""
    jobs = [i for i in items if i["kind"] == "work" and i["start"]]
    if not jobs:
        return ""
    edu = [i for i in items if i["kind"] == "education" and i["start"]]
    now = month_no(today or datetime.now(timezone.utc).strftime("%Y-%m-01"))
    # Ends are inclusive months (Sep 2024 - Sep 2025 covers September 2025). A degree with no end shows one year.
    end = lambda i: month_no(i["end"]) + 1 if i["end"] else now + 1 if i["kind"] == "work" else month_no(i["start"]) + 12
    first = min(month_no(i["start"]) for i in jobs + edu) // 12 * 12
    last = (max([now] + [end(i) - 1 for i in jobs + edu]) // 12 + 1) * 12  # through the end of the latest year
    span = last - first
    pct = lambda m: f"{(m - first) / span * 100:.2f}%"
    bar = lambda i, cls, inner="": (f'<span class="{cls}" style="left:{pct(month_no(i["start"]))};'
                                    f'width:{(end(i) - month_no(i["start"])) / span * 100:.2f}%">{inner}</span>')
    e = html.escape
    logos = any(i.get("logo") for i in items)
    logo = lambda i: logo_html(i, "tl-logo") if logos else ""
    years = "".join(f'<span style="left:{pct(y * 12)}"><b>{y}</b><i>’{y % 100:02d}</i></span>' for y in range(first // 12, last // 12))
    rows = []
    if edu:
        segs = "".join(bar(i, "tl-bar tl-edu", f"<span>{e(degree_short(i))}</span>") for i in edu)
        rows.append(f'<li class="tl-row tl-row-edu"><span class="tl-label">{logo(edu[0])}<span class="tl-text"><b>Education</b><small>{e(" · ".join(dict.fromkeys(i["organization"] for i in edu)))}</small></span></span>'
                    f'<span class="tl-track">{segs}</span></li>')
    for i in jobs:
        n = end(i) - month_no(i["start"])
        current = not i["end"]
        tip = f'{i["role"]}, {i["organization"]} · {date_range(i)} ({duration(n)})'
        rows.append(f'<li><a class="tl-row" href="#exp-{i["id"]}" title="{e(tip)}">'
                    f'<span class="tl-label">{logo(i)}<span class="tl-text"><b>{e(i["organization"] or i["name"])}</b><small>{e(i["role"])}</small></span></span>'
                    f'<span class="tl-track">{bar(i, "tl-bar" + (" tl-now" if current else ""))}</span></a></li>')
    return f"""
              <div class="tl" role="group" aria-label="Timeline of my jobs and degrees">
                <div class="tl-axis" aria-hidden="true"><span class="tl-label"></span><span class="tl-years">{years}<span class="tl-today" style="left:{pct(now + 0.5)}">Today</span></span></div>
                <div class="tl-body">
                  <span class="tl-grid" aria-hidden="true">{"".join(f'<i style="left:{pct(y * 12)}"></i>' for y in range(first // 12 + 1, last // 12))}<i class="tl-today-line" style="left:{pct(now + 0.5)}"></i></span>
                  <ol class="tl-rows">{"".join(rows)}</ol>
                </div>
              </div>"""


def skill_map_html(skills):
    """About section: a small, still picture of the skill graph (a radial tree, like skills.html's Graph view):
    one dot per skill, coloured by discipline, bigger = rated higher. Hovering a "What I do" row or a legend entry
    lights up its disciplines (assets/js/skill-map.js); clicking the panel opens the full graph."""
    kids = {}
    for s in skills:
        kids.setdefault(s["parent"], []).append(s)
    for v in kids.values():
        v.sort(key=lambda s: s["name"].lower())
    order = list(HUBS.values())
    hubs = sorted(kids.get(None, []), key=lambda h: order.index(h["name"]) if h["name"] in order else len(order))
    if not hubs:
        return ""
    # Leaves spread evenly around the circle (with a gap between disciplines); a parent sits at its children's
    # average angle; the ring is the depth in the tree.
    depth, angle, key, leaves, spans = {}, {}, {}, [], []
    def walk(s, d, k):
        depth[s["id"]], key[s["id"]] = d, k
        for c in kids.get(s["id"], []):
            walk(c, d + 1, k)
        if not kids.get(s["id"]):
            leaves.append(s["id"])
    GAP = 2
    for h in hubs:
        start = len(leaves)
        walk(h, 1, HUB_KEYS.get(h["name"], "oth"))
        spans.append((start, len(leaves)))
    slots = len(leaves) + GAP * len(hubs)
    for n, (a, b) in enumerate(spans):
        for i in range(a, b):
            angle[leaves[i]] = (i + GAP * n + GAP / 2) / slots * 2 * math.pi
    def place(s):
        cs = kids.get(s["id"], [])
        if cs:
            angle[s["id"]] = sum(place(c) for c in cs) / len(cs)
        return angle[s["id"]]
    for h in hubs:
        place(h)
    R, deepest = 100, max(depth.values())
    xy = lambda i: (R * depth[i] / deepest * math.sin(angle[i]), -R * depth[i] / deepest * math.cos(angle[i]))
    by_id = {s["id"]: s for s in skills}
    groups = []
    for h in hubs:
        k = key[h["id"]]
        members = [s for s in skills if key.get(s["id"]) == k]
        lines, dots = [], []
        for s in members:
            x, y = xy(s["id"])
            px, py = xy(s["parent"]) if s["parent"] in by_id else (0, 0)
            lines.append(f'<line x1="{px:.1f}" y1="{py:.1f}" x2="{x:.1f}" y2="{y:.1f}"/>')
            r = 5.5 if s is h else 1.6 + (s["rating"] or 0) * 0.55
            dots.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r:.1f}"{" class=" + chr(34) + "sm-hub" + chr(34) if s is h else ""}/>')
        groups.append(f'<g class="sm-d" data-d="{k}" style="--c:var(--rs-{k})">{"".join(lines)}{"".join(dots)}</g>')
    e = html.escape
    legend = "".join(f'<li data-discs="{key[h["id"]]}"><i style="background:var(--rs-{key[h["id"]]})"></i>{e(h["name"])}'
                     f'<b>{sum(1 for s in skills if key.get(s["id"]) == key[h["id"]] and s is not h)}</b></li>' for h in hubs)
    return f"""
          <a class="intro-panel skill-map" href="skills.html" data-aos="fade-up" data-aos-delay="250" aria-label="Open my skill graph">
            <p class="intro-panel-t">Skill map</p>
            <span class="sm-body">
              <svg class="sm-svg" viewBox="-108 -108 216 216" aria-hidden="true"><circle class="sm-root" r="3"/>{"".join(groups)}</svg>
              <span class="sm-side">
                <ul class="sm-legend">{legend}</ul>
                <span class="sm-cta">Explore the skill graph <i class="bi bi-arrow-right"></i></span>
              </span>
            </span>
          </a>"""


def logos_html(items):
    """About section: a "Worked at" panel of job logos (not on the page at the moment: put the notion:logos markers
    back in index.html to show it), newest first, one per organization (two JPL jobs show once),
    in two rows scrolling opposite ways (assets/css/about.css); one row when there are only a few. Each row's list
    is there twice so the loop is seamless, and repeated when short so it always fills the width. Each logo jumps
    to its job in the resume."""
    seen, jobs = set(), []
    for i in items:  # already newest first
        if i["kind"] == "work" and i.get("logo") and i["organization"] not in seen:
            seen.add(i["organization"])
            jobs.append(i)
    if not jobs:
        return ""
    e = html.escape
    skip = ' tabindex="-1"'  # the second copy is only for the loop: keyboard focus skips it
    # rep: a repeat that's only there to fill the width (hidden when the strip stands still)
    item = lambda i, hidden, rep: (f'<li{" class={chr(34)}wa-rep{chr(34)}" if rep else ""}><a href="#exp-{i["id"]}"{skip if hidden else ""} title="{e(i["organization"])}">'
                                   f'{logo_html(i, "wa-logo")}<span>{e(i["organization"])}</span></a></li>')
    def row(group, reverse):
        loop = group * -(-6 // len(group))  # at least 6 per copy
        half = lambda hidden: "".join(item(i, hidden, n >= len(group)) for n, i in enumerate(loop))
        return f"""
            <div class="marquee{" marquee-rev" if reverse else ""}" style="--n:{len(loop)}">
              <div class="marquee-track">
                <ul class="marquee-list">{half(False)}</ul>
                <ul class="marquee-list" aria-hidden="true">{half(True)}</ul>
              </div>
            </div>"""
    rows = [jobs[0::2], jobs[1::2]] if len(jobs) >= 4 else [jobs]
    return f"""
          <div class="intro-panel worked-at" data-aos="fade-up" data-aos-delay="250">
            <p class="intro-panel-t">Worked at</p>{"".join(row(g, n == 1) for n, g in enumerate(rows))}
          </div>"""

BANDS = ["Lv 4–5", "Lv 3", "Lv 2", "Lv 1", "Not rated"]
SHADE = [100, 68, 42, 20]  # % of the discipline color per band: darker = stronger (same as skill-graph.js)


def band(r):
    return 4 if r is None else 0 if r >= 4 else 1 if r >= 3 else 2 if r >= 2 else 3


def skills_html(skills, projects, experience):
    """Homepage Skills section: counts, each discipline's skills by level band, strongest skills, link to the graph.
    Counts only, never averages, so adding a new Lv 1 skill shows as breadth rather than lowering a score."""
    e, by_id = html.escape, {s["id"]: s for s in skills}
    def hub_of(s):
        seen = set()
        while s["parent"] and s["parent"] in by_id and s["id"] not in seen:
            seen.add(s["id"])
            s = by_id[s["parent"]]
        return s
    tree = [s for s in skills if s["parent"]]  # everything but the hubs, like the graph's counts
    mixes = []
    for hub in (s for s in skills if not s["parent"]):
        c = [0] * 5
        for s in tree:
            if hub_of(s) is hub:
                c[band(s["rating"])] += 1
        if sum(c):
            mixes.append((hub, HUB_KEYS.get(hub["name"], "oth"), c))
    mixes.sort(key=lambda m: (-m[2][0], -sum(m[2])))
    widest = max((sum(c) for _, _, c in mixes), default=1)
    def bar(key, c):
        segs = "".join(
            f'<i class="sk-none rs-b-{key}" style="flex:{k}" title="{BANDS[i]}: {k}"></i>' if i == 4 else
            f'<i style="flex:{k};background:color-mix(in srgb, var(--rs-{key}) {SHADE[i]}%, var(--surface-color))" title="{BANDS[i]}: {k}"></i>'
            for i, k in enumerate(c) if k)
        return f'<span class="sk-mix" style="width:{sum(c) / widest * 100:.0f}%">{segs}</span>'
    rows = "".join(f'''<a class="sk-disc" href="skills.html#disc={key}" title="{e(hub["name"])}: {e(", ".join(f"{k} at {BANDS[i]}" for i, k in enumerate(c) if k))}">
                <span class="sk-name"><span class="rs-dot rs-{key}"></span>{e(hub["name"])}</span>
                <span class="sk-track">{bar(key, c)}</span>
                <span class="sk-val">{sum(c)}</span></a>''' for hub, key, c in mixes)
    legend = "".join(
        f'<span><i class="sk-none"></i>{b}</span>' if i == 4 else
        f'<span><i style="background:color-mix(in srgb, var(--heading-color) {SHADE[i]}%, var(--surface-color))"></i>{b}</span>'
        for i, b in enumerate(BANDS))
    top = sorted((s for s in tree if s["rating"]), key=lambda s: (-s["rating"], s["name"].lower()))[:12]
    chips = "".join(
        f'<a class="rs-chip" href="skills.html#skill={s["id"]}"><span class="rs-dot rs-{HUB_KEYS.get(hub_of(s)["name"], "oth")}"></span>'
        f'{e(s["name"])}<span class="sk-lv">{s["rating"]:g}</span></a>' for s in top)
    jobs = sum(1 for x in experience if x["kind"] == "work")
    return f"""
      <div class="container" data-aos="fade-up" data-aos-delay="100">
        <div class="sk-preview">
          <div class="sk-stats">
            <div><b>{len(tree)}</b>skills</div>
            <div><b>{len(mixes)}</b>disciplines</div>
            <div><b>{jobs}</b>jobs</div>
            <div><b>{len(projects)}</b>projects</div>
          </div>
          <div class="sk-cols">
            <div>
              <h3>Skills by discipline and level</h3>
              {rows}
              <p class="sk-legend" aria-hidden="true">{legend}</p>
            </div>
            <div>
              <h3>Strongest skills</h3>
              <div class="rs-skills">{chips}</div>
            </div>
          </div>
          <a class="sk-cta" href="skills.html">Explore the full skill graph <i class="bi bi-arrow-right"></i></a>
        </div>
      </div>"""


# ---- Projects: the homepage grid and a page per project (projects/<slug>.html) ----

PH_ICONS = {"mech": "bi-gear-wide-connected", "elec": "bi-lightning-charge", "soft": "bi-code-slash",
            "sys": "bi-diagram-3", "oth": "bi-stars"}
GENERATED = "<!-- generated by scripts/sync_notion.py from Notion; edit the project there, not here -->"


def project_dates(it, months=True):
    if not it["start"]:
        return ""
    f = (lambda d: f"{MONTHS[int(d[5:7]) - 1]} {d[:4]}") if months else (lambda d: d[:4])
    a, b = f(it["start"]), f(it["end"]) if it["end"] else ""
    return f"{a} - {b}" if b and b != a else a


def ordered_projects(projects):
    """Featured first, then newest first (undated at the end)."""
    by_date = sorted(sorted(projects, key=lambda p: p["name"].lower()), key=lambda p: p["start"] or "", reverse=True)
    return sorted(by_date, key=lambda p: not p["featured"])


def used_skills(it, by_id):
    return sorted((by_id[i] for i in it["skills"] if i in by_id), key=lambda s: (-(s["rating"] or 0), s["name"].lower()))


def main_disc(it, by_id):
    keys = [disc_key(s, by_id) for s in used_skills(it, by_id)]
    return max(keys, key=keys.count) if keys else "oth"  # a tie goes to the discipline of its strongest skill


def photo_count(it):
    photos = sum(1 for g in it["gallery"] if g["kind"] == "image")
    return photos + (1 if it["cover"] and not it.get("cover_is_thumb") else 0)


def projects_html(projects, skills):
    e, by_id = html.escape, {s["id"]: s for s in skills}
    cards = []
    for it in ordered_projects(projects):
        key, used = main_disc(it, by_id), used_skills(it, by_id)
        img = (f'<img src="{e(it["cover"]["sm"])}" alt="" loading="lazy">' if it["cover"] else
               f'<span class="pj-ph" style="--pj-c:var(--rs-{key})"><i class="bi {PH_ICONS[key]}"></i></span>')
        n, v = photo_count(it), it.get("videos", 0)
        counts = " ".join(x for x in (f'<i class="bi bi-images"></i> {n}' if n > 1 else "", f'<i class="bi bi-play-fill"></i> {v}' if v else "") if x)
        tags = "".join(f'<span><i class="rs-dot rs-{disc_key(s, by_id)}"></i>{e(s["name"])}</span>' for s in used[:4])
        if len(used) > 4:
            tags += f'<span class="pj-more">+{len(used) - 4}</span>'
        meta = " · ".join(x for x in (project_dates(it, months=False), it["organization"]) if x)
        cards.append(f"""
            <a class="pj-card" href="projects/{e(it["slug"])}.html">
              <span class="pj-card-img">{img}{'<span class="pj-badge">Featured</span>' if it["featured"] else ""}{f'<span class="pj-count">{counts}</span>' if counts else ""}</span>
              <span class="pj-card-body">
                {f'<span class="pj-card-meta">{e(meta)}</span>' if meta else ""}
                <h3>{e(it["name"])}</h3>
                {f"<p>{e(it['blurb'])}</p>" if it["blurb"] else ""}
                {f'<span class="pj-tags">{tags}</span>' if tags else ""}
              </span>
            </a>""")
    if not cards:
        return """
      <div class="container"><p class="pj-empty">Projects are on their way.</p></div>"""
    return f"""
      <div class="container" data-aos="fade-up" data-aos-delay="100">
        <div class="pj-grid">{"".join(cards)}
        </div>
      </div>"""


def link_label(url):
    host = re.sub(r"^https?://(www\.)?", "", url).split("/")[0].lower()
    return ("bi-github", "Code on GitHub") if "github.com" in host else \
        ("bi-youtube", "Watch the video") if "youtube.com" in host or "youtu.be" in host else ("bi-box-arrow-up-right", "Visit the link")


def site_parts(index_html):
    """The homepage's <head>, header, footer, skill graph pop-up and scripts, with links adjusted for pages one folder down."""
    up = lambda h: re.sub(r'(href|src)="(?=assets/|index\.html|skills\.html)', r'\1="../', h).replace('href="#', 'href="../index.html#')
    grab = lambda pat: up(re.search(pat, index_html, re.S).group(0))
    return {"up": up, "head": grab(r"<head>.*?</head>"), "header": grab(r'<header id="header".*?</header>'),
            "footer": grab(r'<footer id="footer".*?</footer>'), "popup": grab(r"<!-- popup:skills:start -->.*?<!-- popup:skills:end -->"),
            "scripts": "\n  ".join(up(m) for m in re.findall(r'<script src="assets/(?:vendor/[^"]+|js/main\.js|js/site-popups\.js[^"]*)"></script>', index_html))}


def project_page(it, prev, nxt, skills, parts):
    e = html.escape
    kicker = " · ".join(x for x in ("Project", it["organization"], project_dates(it)) if x)
    actions = []
    if it["link"]:
        icon, label = link_label(it["link"])
        actions.append(f'<a class="pj-btn" href="{e(it["link"])}" target="_blank" rel="noopener"><i class="bi {icon}"></i> {label}</a>')
    if it["skills"]:
        actions.append(f'<a class="pj-btn pj-btn-ghost" href="skills.html#item={it["id"]}"><i class="bi bi-diagram-3"></i> Its skills in the skill graph</a>')
    gallery = "".join(gallery_item(g) for g in it["gallery"])
    chips = skill_chips(it, skills, limit=None)
    nav = "".join(f'<a class="pj-nav-{side}" href="{e(p["slug"])}.html"><span>{label}</span>{e(p["name"])}</a>'
                  for side, label, p in (("prev", "← Previous", prev), ("next", "Next →", nxt)) if p)
    body = f"""
  <main class="main">
    <section class="section pj-page">
      <div class="container">
        <a class="pj-back" href="index.html#projects"><i class="bi bi-arrow-left"></i> All projects</a>
        <header class="pj-head">
          <p class="pj-kicker">{e(kicker)}</p>
          <h1>{e(it["name"])}</h1>
          {f'<p class="pj-lede">{e(it["blurb"])}</p>' if it["blurb"] else ""}
          {f'<div class="pj-actions">{"".join(actions)}</div>' if actions else ""}
          {f'<div class="pj-skills"><p class="pj-skills-t">Skills used</p>{chips}</div>' if chips else ""}
        </header>
        {figure(it["cover"], "pj-hero") if it["cover"] and not it.get("cover_is_thumb") else ""}
        {f'<div class="pj-body">{it["details"]}</div>' if it["details"] else ""}
        {f'<h2 class="pj-h">{"Photos & videos" if any(g["kind"] != "image" for g in it["gallery"]) else "Photos"}</h2><div class="pj-gallery">{gallery}</div>' if gallery else ""}
        {f'<nav class="pj-nav" aria-label="More projects">{nav}</nav>' if nav else ""}
      </div>
    </section>
  </main>"""
    head = re.sub(r"<title>.*?</title>", f"<title>{e(it['name'])} · Stephen Mock</title>", parts["head"], count=1, flags=re.S)
    head = re.sub(r'<meta name="description" content="[^"]*">', f'<meta name="description" content="{e(it["blurb"])}">', head, count=1)
    # Opened in the homepage's pop-up (?embed=1): no site header / footer. Set before anything draws.
    head = head.replace("</head>", """  <script>if (/[?&]embed=1(&|$)/.test(location.search)) document.documentElement.classList.add("pj-embed");</script>
</head>""", 1)
    return f"""<!DOCTYPE html>
<html lang="en">
{GENERATED}
{head}

<body class="project-page">

  {parts["header"]}
{parts["up"](body)}

  {parts["footer"]}

  <!-- Scroll Top (main.js expects it; without it the script stops before the photo lightbox is set up) -->
  <a href="#" id="scroll-top" class="scroll-top d-flex align-items-center justify-content-center"><i class="bi bi-arrow-up-short"></i></a>

  {parts["popup"]}

  {parts["scripts"]}
</body>

</html>
"""


def write_projects(root, projects, skills, index_html):
    """Write projects/<slug>.html for each project and delete pages of projects that are gone. Returns how many changed."""
    d, order, parts = root / "projects", ordered_projects(projects), site_parts(index_html)
    wanted = {f"{it['slug']}.html": project_page(it, order[i - 1] if i else None, order[i + 1] if i + 1 < len(order) else None,
                                                 skills, parts) for i, it in enumerate(order)}
    changed = 0
    if wanted:
        d.mkdir(parents=True, exist_ok=True)
    for name, page in wanted.items():
        f = d / name
        if not f.exists() or f.read_text(encoding="utf-8") != page:
            f.write_text(page, encoding="utf-8")
            changed += 1
    for f in (d.glob("*.html") if d.is_dir() else []):
        if f.name not in wanted and GENERATED in f.read_text(encoding="utf-8"):
            f.unlink()
            changed += 1
    return changed


def write_index(root, skills, projects, experience):
    """Fill the generated regions of index.html (the repo's copy is the source; root is where it's written).
    Returns (changed, the page)."""
    page = INDEX.read_text(encoding="utf-8")
    for name, body in (("skillmap", skill_map_html(skills)),
                       ("logos", logos_html(experience)),
                       ("timeline", timeline_html(experience)),
                       ("experience", experience_html(experience, skills)),
                       ("education", education_html(experience, skills)),
                       ("skills", skills_html(skills, projects, experience)),
                       ("projects", projects_html(projects, skills))):
        pat = re.compile(rf"(<!-- notion:{name}:start[^>]*-->).*?(\n[ \t]*<!-- notion:{name}:end -->)", re.S)
        page = pat.sub(lambda m: m.group(1) + body + m.group(2), page, count=1)
    out = root / "index.html"
    changed = not out.exists() or out.read_text(encoding="utf-8") != page
    if changed:
        out.write_text(page, encoding="utf-8")
    return changed, page


def fetch_records():
    return [to_record(p) for p in query_all()]


def sync(records, show_all, preview=False):
    """Write the site's generated files from already-fetched records. Returns a short summary.
    preview: include drafts (non-Public pages) and write into .preview/ instead of the site."""
    root = PREVIEW if preview else ROOT
    show_all = show_all or preview
    skills, projects, experience = build(records, show_all)
    # The detailed write-up for each project / job comes from its page body (the 🌐 Public section).
    missing, no_photos = [], []
    photos = Photos(root, reuse=ROOT if preview else None)
    icons = {r["id"]: r["icon"] for r in records}
    for it in experience:
        it["details"] = public_html(it["id"])
        if it["details"] is None:
            missing.append(it["name"])
        # The page icon, if it's an image (an emoji icon isn't a logo).
        logo = photos.get(icons.get(it["id"]), LOGO_DIR, sizes=LOGO_SIZES)
        it["logo"] = logo and {"sm": logo["sm"], "lg": logo["lg"]}
    covers = {r["id"]: r["cover"] for r in records}
    for it in projects:
        project_content(it, covers.get(it["id"]), photos)
        if not it.pop("has_public"):
            missing.append(it["name"])
        if not it["cover"]:
            no_photos.append(it["name"])

    hubs = sum(1 for s in skills if s["parent"] is None)
    summary = (f"{len(records)} wiki pages -> {hubs} hubs, {len(skills) - hubs} skills, "
               f"{len(projects)} projects, {len(experience)} experience"
               + (" (preview, drafts included)" if preview else f" (SHOW_ALL={show_all})"))
    if missing:
        summary += "\nno 🌐 Public section yet: " + ", ".join(missing)
    if no_photos:
        summary += "\nno photos yet: " + ", ".join(no_photos)
    if photos.failed:
        summary += "\ncouldn't get these photos (will retry next time): " + "; ".join(photos.failed)
    if hubs != len(HUBS):
        summary += f"\nwarning: expected {len(HUBS)} hubs; check the integration can see every hub page"

    root.mkdir(exist_ok=True)
    index_changed, index_page = write_index(root, skills, projects, experience)
    if index_changed:
        summary += f"\nupdated {INDEX.name}"
    pages = write_projects(root, projects, skills, index_page)
    if pages:
        summary += f"\nupdated {pages} project page{'s' if pages > 1 else ''}"
    gone = photos.remove_unused()
    if gone:
        summary += f"\nremoved {gone} photo file{'s' if gone > 1 else ''} no longer used"
    if photos.used and not Image:
        summary += "\nnote: Pillow isn't installed, so photos were copied at full size (pip install pillow)"

    # The graph only needs a project's summary; the write-up and photos live on its page.
    projects = [{k: v for k, v in it.items() if k not in ("details", "gallery", "slug", "cover_is_thumb")}
                | {"page": f"projects/{it['slug']}.html", "cover": it["cover"] and it["cover"]["sm"], "photos": photo_count(it), "videos": it.get("videos", 0)}
                for it in projects]
    out = root / OUT.relative_to(ROOT)
    old = json.loads(out.read_text()) if out.exists() else {}
    if (old.get("source") == "notion" and old.get("skills") == skills and old.get("projects") == projects
            and old.get("experience") == experience):
        return summary + "\nno changes to skills.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "source": "notion",
        "skills": skills,
        "projects": projects,
        "experience": experience,
    }, indent=1, ensure_ascii=False) + "\n")
    return summary + f"\nwrote {out}"


def main():
    show_all = os.environ.get("SHOW_ALL", "").lower() == "true"
    preview = os.environ.get("PREVIEW", "").lower() == "true"
    try:
        print(sync(fetch_records(), show_all, preview))
    except NotionError as e:
        sys.exit(str(e))


if __name__ == "__main__":
    main()
