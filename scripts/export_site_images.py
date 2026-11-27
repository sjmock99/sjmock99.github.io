#!/usr/bin/env python3
"""Download every image from a website, at full size (made for Webflow sites; works on most simple sites).

    python3 scripts/export_site_images.py https://example.webflow.io ~/code/example/photos

Follows links within the site, collects images from <img src/srcset>, lazy-load attributes, CSS backgrounds and
share images, and keeps only each image's original: Webflow also serves shrunken copies named name-p-500.jpg etc.
Files that are byte-for-byte the same are saved once. Writes manifest.csv next to the images: each file, where it
came from and which pages use it. Only use it on sites you own or may copy from.
"""
import argparse
import csv
import hashlib
import html
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

UA = {"User-Agent": "Mozilla/5.0 (site image export)"}
IMG_EXT = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".svg", ".avif")


def get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
        return r.read(), r.headers.get_content_type()


def original(u):
    return re.sub(r"-p-\d+(\.\w+)$", r"\1", u)


def image_urls(text, base):
    found = set(re.findall(r'(?:src|data-src|href|content)="([^"]+)"', text))
    for srcset in re.findall(r'srcset="([^"]+)"', text):
        found.update(part.strip().split(" ")[0] for part in srcset.split(","))
    found.update(re.findall(r'url\(\s*["\']?([^"\')]+)["\']?\s*\)', text))
    out = set()
    for u in found:
        u = urllib.parse.urljoin(base, html.unescape(u).strip())
        if u.startswith("http") and urllib.parse.urlparse(u).path.lower().endswith(IMG_EXT):
            out.add(original(u))
    return out


def crawl(root):
    host = urllib.parse.urlparse(root).netloc
    pages, seen, images, css_done = [root.rstrip("/") + "/"], set(), {}, set()
    while pages:
        page = pages.pop(0)
        if page in seen:
            continue
        seen.add(page)
        try:
            text = get(page)[0].decode("utf-8", "replace")
        except Exception as e:
            print(f"skip page {page}: {e}")
            continue
        for u in image_urls(text, page):
            images.setdefault(u, set()).add(urllib.parse.urlparse(page).path or "/")
        for css in re.findall(r'<link[^>]+href="([^"]+\.css)"', text):
            css = urllib.parse.urljoin(page, css)
            if css not in css_done:
                css_done.add(css)
                try:
                    for u in image_urls(get(css)[0].decode("utf-8", "replace"), css):
                        images.setdefault(u, set()).add("(stylesheet)")
                except Exception as e:
                    print(f"skip stylesheet {css}: {e}")
        for href in re.findall(r'href="([^"#?]+)"', text):
            p = urllib.parse.urlparse(urllib.parse.urljoin(page, href))
            if p.netloc == host and not p.path.lower().endswith(IMG_EXT + (".css", ".js", ".xml", ".ico")):
                u = f"{p.scheme}://{p.netloc}{p.path}"
                if u not in seen:
                    pages.append(u)
        time.sleep(0.3)
    print(f"{len(seen)} pages, {len(images)} images")
    return images


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("site"); p.add_argument("out")
    a = p.parse_args()
    out = Path(a.out).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    rows, used, by_hash = [], set(), {}
    for u, pages in sorted(crawl(a.site).items()):
        name = urllib.parse.unquote(urllib.parse.urlparse(u).path.rsplit("/", 1)[-1])
        name = re.sub(r"^[0-9a-f]{20,}_", "", name)  # Webflow's long id prefix
        name = re.sub(r"[^\w.\-]+", "_", name) or "image"
        try:
            data, ctype = get(u)
        except Exception as e:
            print(f"failed {u}: {e}")
            continue
        if not (ctype.startswith("image/") or name.lower().endswith(".svg")):
            print(f"not an image ({ctype}): {u}")
            continue
        h = hashlib.sha1(data).hexdigest()
        if h in by_hash:  # the same file uploaded twice: keep one, note both pages
            r = by_hash[h]
            r["pages"] = " ".join(sorted(set(r["pages"].split()) | pages))
            continue
        stem, _, ext = name.rpartition(".")
        final, n = name, 1
        while final.lower() in used:
            n += 1
            final = f"{stem}_{n}.{ext}"
        used.add(final.lower())
        (out / final).write_bytes(data)
        by_hash[h] = r = {"file": final, "bytes": len(data), "url": u, "pages": " ".join(sorted(pages))}
        rows.append(r)
        time.sleep(0.1)
    with open(out / "manifest.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["file", "bytes", "url", "pages"])
        w.writeheader(); w.writerows(rows)
    print(f"saved {len(rows)} images to {out} (see manifest.csv)")


if __name__ == "__main__":
    main()
