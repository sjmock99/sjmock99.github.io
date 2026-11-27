#!/usr/bin/env python3
"""Put local photos and PDFs on a project's Notion page, and set photo captions, for the site sync to pick up.

Uses the same Notion key as sync_notion.py ($NOTION_TOKEN, or the file ~/.notion_token). Never commit the key.

    # Photos go at the end of the page's 📷 Photos toggle (the first one there is the page's cover).
    python3 scripts/upload_to_notion.py photos <page> cover.jpg a.png "b.jpg=Caption for b"

    # A PDF goes right after the "Documentation" heading in the 🌐 Public section (else at the end of the section).
    python3 scripts/upload_to_notion.py pdf <page> deck.pdf --caption "Slides: requirements, design, results"

    # Set a photo's caption; with --link its tile on the site opens that page instead of the lightbox.
    python3 scripts/upload_to_notion.py caption <page> Frame_46 "Meet the team" --link https://www.instagram.com/p/...

<page> is the page's Notion link or id. Notion refuses files over 5 MB on this workspace's plan, so photos are
shrunk first (2400 px on the long side, JPEG unless they have transparency) and a PDF that's too big is refused
with a pointer to scripts/shrink_pdf.py.
"""
import argparse
import io
import json
import mimetypes
import re
import sys
import urllib.request
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sync_notion as notion  # noqa: E402  (request(), the token, the 🌐 Public / 📷 Photos helpers)

MAX_BYTES = 5 * 1024 * 1024
PHOTO_PX = 2400


def page_id(ref):
    m = re.search(r"([0-9a-f]{32})(?:\?|$|#)", ref.replace("-", ""))
    if not m:
        sys.exit(f"not a Notion page link or id: {ref}")
    return m.group(1)


def public_block(pid):
    """The 🌐 Public toggle heading (whose children are the section), or None."""
    return next((b for b in notion.block_children(pid) if notion.is_public_marker(b) and notion.is_toggle(b)), None)


def photos_toggle(pid):
    pub = public_block(pid)
    kids = notion.block_children(pub["id"]) if pub and pub.get("has_children") else []
    t = next((b for b in kids if notion.is_photos_marker(b)), None)
    if not t:
        sys.exit("no 📷 Photos toggle inside the page's 🌐 Public section (use the project template)")
    return t


def shrink_photo(path):
    """-> (bytes, filename, content type), within PHOTO_PX and the upload limit."""
    data = path.read_bytes()
    try:
        from PIL import Image, ImageOps
    except ImportError:
        if len(data) > MAX_BYTES:
            sys.exit(f"{path.name} is over 5 MB and Pillow isn't installed to shrink it (pip install pillow)")
        return data, path.name, mimetypes.guess_type(path.name)[0] or "image/jpeg"
    im = ImageOps.exif_transpose(Image.open(io.BytesIO(data)))
    if max(im.size) <= PHOTO_PX and len(data) <= MAX_BYTES and path.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
        return data, path.name, mimetypes.guess_type(path.name)[0] or "image/jpeg"
    im.thumbnail((PHOTO_PX, PHOTO_PX))
    alpha = im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info)
    out = io.BytesIO()
    if alpha:
        im.save(out, "PNG", optimize=True)
        name, ctype = path.stem + ".png", "image/png"
    else:
        im.convert("RGB").save(out, "JPEG", quality=88)
        name, ctype = path.stem + ".jpg", "image/jpeg"
    if out.tell() > MAX_BYTES:
        sys.exit(f"{path.name} is still over 5 MB after shrinking")
    return out.getvalue(), name, ctype


def upload(data, filename, ctype):
    """Notion's two-step upload: create the upload, then send the bytes. -> the upload's id."""
    up = notion.request("POST", "/file_uploads", {"filename": filename, "content_type": ctype})
    boundary = uuid.uuid4().hex
    body = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n'
            f"Content-Type: {ctype}\r\n\r\n").encode() + data + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(
        f"{notion.API}/file_uploads/{up['id']}/send", data=body, method="POST",
        headers={"Authorization": f"Bearer {notion.get_token()}", "Notion-Version": notion.NOTION_VERSION,
                 "Content-Type": f"multipart/form-data; boundary={boundary}"})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            res = json.load(r)
    except urllib.error.HTTPError as e:
        sys.exit(f"upload of {filename} failed: {e.code} {e.read().decode(errors='replace')}")
    if res.get("status") != "uploaded":
        sys.exit(f"upload of {filename} didn't finish: {res}")
    return up["id"]


def rich(text, link=None):
    return [{"type": "text", "text": {"content": text, **({"link": {"url": link}} if link else {})}}] if text else []


def append(parent, blocks, after=None):
    body = {"children": blocks}
    if after:
        body["position"] = {"type": "after_block", "after_block": {"id": after}}
    return notion.request("PATCH", f"/blocks/{parent}/children", body)


def cmd_photos(a):
    toggle = photos_toggle(page_id(a.page))
    for spec in a.files:
        path_s, _, cap = spec.partition("=")
        path = Path(path_s)
        data, name, ctype = shrink_photo(path)
        fid = upload(data, name, ctype)
        append(toggle["id"], [{"type": "image", "image": {"type": "file_upload", "file_upload": {"id": fid},
                                                          "caption": rich(cap.strip())}}])
        print(f"added {path.name}" + (f" ({len(data) // 1024} KB as {name})" if name != path.name else ""))


def cmd_pdf(a):
    path = Path(a.file)
    data = path.read_bytes()
    if len(data) > MAX_BYTES:
        sys.exit(f"{path.name} is {len(data) / 1048576:.1f} MB; Notion takes 5 MB at most. "
                 f'Shrink it first: python3 scripts/shrink_pdf.py "{path}" smaller.pdf')
    pub = public_block(page_id(a.page))
    if not pub:
        sys.exit("the page has no 🌐 Public section")
    kids = notion.block_children(pub["id"])
    heading = next((b for b in kids if b["type"].startswith("heading_") and "documentation" in notion.block_text(b).lower()), None)
    # Before the 📷 Photos toggle if there's no Documentation heading, so photos stay last.
    photos = next((i for i, b in enumerate(kids) if notion.is_photos_marker(b)), None)
    after = heading["id"] if heading else (kids[photos - 1]["id"] if photos else None)
    fid = upload(data, path.name, "application/pdf")
    append(pub["id"], [{"type": "pdf", "pdf": {"type": "file_upload", "file_upload": {"id": fid},
                                               "caption": rich(a.caption or "")}}], after=after)
    print(f"added {path.name} ({len(data) / 1048576:.1f} MB)")


def cmd_caption(a):
    toggle = photos_toggle(page_id(a.page))
    for b in notion.block_children(toggle["id"]):
        if b["type"] != "image":
            continue
        url = (b["image"].get("file") or b["image"].get("external") or {}).get("url", "")
        if a.name.lower() in url.split("?")[0].rsplit("/", 1)[-1].lower():
            notion.request("PATCH", f"/blocks/{b['id']}", {"image": {"caption": rich(a.text, a.link)}})
            print("caption set" + (f", links to {a.link}" if a.link else ""))
            return
    sys.exit(f"no photo whose file name contains {a.name!r} in the 📷 Photos toggle")


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("photos", help="add photos to the 📷 Photos toggle")
    s.add_argument("page"); s.add_argument("files", nargs="+", help='file, or "file=Caption"')
    s.set_defaults(fn=cmd_photos)
    s = sub.add_parser("pdf", help="add a PDF under Documentation")
    s.add_argument("page"); s.add_argument("file"); s.add_argument("--caption")
    s.set_defaults(fn=cmd_pdf)
    s = sub.add_parser("caption", help="set a photo's caption (and link)")
    s.add_argument("page"); s.add_argument("name", help="part of the photo's file name")
    s.add_argument("text"); s.add_argument("--link")
    s.set_defaults(fn=cmd_caption)
    a = p.parse_args()
    try:
        a.fn(a)
    except notion.NotionError as e:
        sys.exit(str(e))


if __name__ == "__main__":
    main()
