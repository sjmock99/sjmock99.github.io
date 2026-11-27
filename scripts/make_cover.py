#!/usr/bin/env python3
"""Turn a tall (portrait) photo into a wide project cover without cropping it.

The cover shows as a wide banner on the project page (at most 520 px tall) and as a 16:10 card on the homepage,
so a portrait photo gets its top and bottom cut off. This fits the whole photo into a wide frame (about 2.1:1)
and fills the sides:

    python3 scripts/make_cover.py photo.jpg cover.jpg                  # sides: a darkened blur of the photo
    python3 scripts/make_cover.py photo.png cover.jpg --fill backdrop  # sides: the plain studio backdrop
    python3 scripts/make_cover.py photo.png cover.jpg --fill backdrop --edge right

--fill blur suits busy scenes (it was made for the LED lamp). --fill backdrop suits a plain studio backdrop: it
continues the backdrop's colour row by row from one edge of the photo, so pick the --edge (left or right) that is
clean backdrop all the way down; the default is left. Then put the cover first in the page's 📷 Photos toggle.
"""
import argparse

from PIL import Image, ImageEnhance, ImageFilter, ImageOps


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("src"); p.add_argument("out")
    p.add_argument("--fill", choices=("blur", "backdrop"), default="blur")
    p.add_argument("--edge", choices=("left", "right"), default="left", help="for --fill backdrop")
    p.add_argument("--ratio", type=float, default=2.1, help="width / height (default 2.1)")
    p.add_argument("--height", type=int, default=1250)
    a = p.parse_args()

    im = ImageOps.exif_transpose(Image.open(a.src)).convert("RGB")
    H = min(a.height, im.height)
    W = int(H * a.ratio)
    fg = im.resize((int(im.width * H / im.height), H), Image.LANCZOS)
    if fg.width >= W:
        raise SystemExit("the photo is already at least this wide; use it as it is")

    if a.fill == "blur":
        bg = ImageOps.fit(im, (W, H)).filter(ImageFilter.GaussianBlur(40))
        bg = ImageEnhance.Brightness(bg).enhance(0.45)
        mask = None
    else:
        x0 = 2 if a.edge == "left" else fg.width - 22
        strip = fg.crop((x0, 0, x0 + 20, H)).resize((1, H), Image.BOX).filter(ImageFilter.GaussianBlur(12))
        bg = strip.resize((W, H))
        mask = Image.new("L", fg.size, 255)  # feather the seams over 30 px
        for x in range(30):
            v = int(255 * (x + 1) / 31)
            for xx in (x, fg.width - 1 - x):
                mask.paste(v, (xx, 0, xx + 1, H))
    bg.paste(fg, ((W - fg.width) // 2, 0), mask)
    bg.save(a.out, quality=90)
    print(f"{a.out}: {W}x{H}")


if __name__ == "__main__":
    main()
