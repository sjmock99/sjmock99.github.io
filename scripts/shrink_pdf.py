#!/usr/bin/env python3
"""Make a PDF small enough to upload to Notion (5 MB on this plan) and put on a project page.

    python3 scripts/shrink_pdf.py "deck.pdf" "deck web.pdf"            # aim under 4.8 MB
    python3 scripts/shrink_pdf.py "deck.pdf" "deck web.pdf" --max-mb 3

First it recompresses the images inside the PDF, which keeps text selectable. If that isn't enough (decks exported
from Figma or Canva often hide their weight in pattern fills it can't touch), it rebuilds the PDF from a sharp
JPEG of each page: it looks the same, but the text is no longer selectable or searchable.

Needs PyMuPDF, local only (not for the GitHub workflow):  pip install --user pymupdf
"""
import argparse
import os
import sys

try:
    import pymupdf
except ImportError:
    sys.exit("needs PyMuPDF:  pip install --user pymupdf")

pymupdf.TOOLS.mupdf_display_errors(False)  # odd PDFs print hundreds of harmless warnings


def size_mb(path):
    return os.path.getsize(path) / 1048576


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("src"); p.add_argument("out")
    p.add_argument("--max-mb", type=float, default=4.8)
    a = p.parse_args()
    if not os.path.isfile(a.src):
        sys.exit(f"no such file: {a.src}")
    if os.path.abspath(a.src) == os.path.abspath(a.out):
        sys.exit("write to a new file; the original is kept as it is")
    print(f"{a.src}: {size_mb(a.src):.1f} MB")

    # 1. Recompress the images; the text stays text.
    for dpi, q in ((150, 80), (110, 70)):
        doc = pymupdf.open(a.src)
        doc.rewrite_images(dpi_threshold=dpi + 10, dpi_target=dpi, quality=q)
        doc.save(a.out, garbage=4, deflate=True)
        print(f"  images at {dpi} dpi: {size_mb(a.out):.1f} MB")
        if size_mb(a.out) <= a.max_mb:
            print(f"done: {a.out} (text still selectable)")
            return

    # 2. Rebuild from page images.
    src = pymupdf.open(a.src)
    for width, q in ((2200, 82), (1920, 78), (1600, 72), (1280, 68)):
        out = pymupdf.open()
        for page in src:
            zoom = width / page.rect.width
            jpg = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False).tobytes("jpeg", jpg_quality=q)
            new = out.new_page(width=page.rect.width, height=page.rect.height)
            new.insert_image(new.rect, stream=jpg)
        out.save(a.out, garbage=4, deflate=True)
        print(f"  pages as {width} px images: {size_mb(a.out):.1f} MB")
        if size_mb(a.out) <= a.max_mb:
            print(f"done: {a.out} ({src.page_count} pages; text is now part of the images)")
            return
    sys.exit(f"couldn't get under {a.max_mb} MB; split the PDF or drop some pages")


if __name__ == "__main__":
    main()
