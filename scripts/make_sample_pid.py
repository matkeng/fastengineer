"""Generate the P&ID samples used by the tests, CI and the UI demo:

  samples/pid-sample.pdf          2 sheets with a text layer (sheet 2 has /Rotate 90)
  samples/pid-sample-scanned.pdf  the same sheets as images only (exercises OCR)
  samples/pid-templates.json      a starter template library cropped from sheet 1

Expected tags (11 unique): FV-1023 FV-1024 FT-1023 PT-1025 TT-1026A LIC-1030 PI-1041
PSV-1040 (sheet 1), FT-2001 PT-2002 FV-2001 (sheet 2; FT-1023 repeats there).
The title block holds tag-like text (PID-100, SHT-01) that the library's exclusion area removes.

Run: python scripts/make_sample_pid.py
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import fitz

from workbench_core.pid.models import DPI
from workbench_core.pid.render import decode_gray, encode_png
from workbench_core.pid.render import render_pages
from workbench_core.pid.templates import crop, erase_words

OUT = Path(__file__).resolve().parents[1] / "samples"
W, H = 1191, 842  # A3 landscape, points
R = 16            # bubble radius
FONT = "helv"
ZOOM = DPI / 72
TITLE_AREA = [850 / W, 690 / H, 1180 / W, 830 / H]  # fractions of the displayed sheet


class Sheet:
    """Draw in displayed (upright) coordinates, whatever the page's /Rotate is."""

    def __init__(self, page: fitz.Page):
        self.page = page
        self.m = page.derotation_matrix
        self.shape = page.new_shape()

    def p(self, x: float, y: float) -> fitz.Point:
        return fitz.Point(x, y) * self.m

    def line(self, a, b, dashes=None, width=0.8):
        self.shape.draw_line(self.p(*a), self.p(*b))
        self.shape.finish(color=(0, 0, 0), width=width, dashes=dashes)

    def poly(self, pts, fill=None):
        self.shape.draw_polyline([self.p(*q) for q in pts] + [self.p(*pts[0])])
        self.shape.finish(color=(0, 0, 0), width=0.8, fill=fill, closePath=True)

    def circle(self, c, r):
        self.shape.draw_circle(self.p(*c), r)
        self.shape.finish(color=(0, 0, 0), width=0.8)

    def text(self, c, s, size=7.0):
        """Centred on c (displayed frame), upright."""
        w = fitz.get_text_length(s, fontname=FONT, fontsize=size)
        self.shape.insert_text(self.p(c[0] - w / 2, c[1] + size * 0.35), s, fontname=FONT, fontsize=size,
                               rotate=self.page.rotation)

    def bubble(self, c, letters, number, panel=False):
        x, y = c
        self.circle(c, R)
        if panel:
            self.line((x - R, y), (x + R, y))
        self.text((x, y - 5), letters)
        self.text((x, y + 7), number)

    def valve(self, c, control=False):
        x, y = c
        self.poly([(x - 14, y - 8), (x - 14, y + 8), (x, y)])
        self.poly([(x + 14, y - 8), (x + 14, y + 8), (x, y)])
        if control:
            self.line((x, y), (x, y - 14))
            self.shape.draw_sector(self.p(x, y - 14), self.p(x + 9, y - 14), 180 if not self.page.rotation else -180)
            self.shape.finish(color=(0, 0, 0), width=0.8)
            self.line((x - 9, y - 14), (x + 9, y - 14))

    def title_block(self, w, h, number, sheet):
        x0, y0 = 850 / W * w, 690 / H * h
        x1, y1 = 1180 / W * w, 830 / H * h
        for a, b in (((x0, y0), (x1, y0)), ((x1, y0), (x1, y1)), ((x1, y1), (x0, y1)), ((x0, y1), (x0, y0))):
            self.line(a, b, width=1.5)
        bw = x1 - x0
        self.text((x0 + 0.3 * bw, y0 + 30), "DRAWING NO.", 9)
        self.text((x0 + 0.3 * bw, y0 + 50), number, 12)
        self.text((x0 + 0.75 * bw, y0 + 50), sheet, 12)
        self.text((x0 + 0.3 * bw, y0 + 90), "REV C", 9)
        self.text((x0 + 0.75 * bw, y0 + 90), "DRAWN MK", 9)

    def commit(self):
        self.shape.commit()


def sheet1(doc: fitz.Document) -> dict:
    page = doc.new_page(width=W, height=H)
    s = Sheet(page)
    y = 300
    s.line((80, y), (1010, y), width=1.2)
    s.valve((250, y))
    s.valve((450, y), control=True)
    s.valve((650, y))
    s.valve((850, y), control=True)
    for vx, num in ((450, "1023"), (850, "1024")):
        s.line((vx, y - 23), (vx, y - 45 + R), dashes="[3 2] 0")
        s.bubble((vx, y - 45 - 0), "FV", num)
    for (bx, by), letters, num in (((350, 200), "FT", "1023"), ((570, 200), "PT", "1025"),
                                   ((750, 200), "TT", "1026A")):
        s.line((bx, y), (bx, by + R))
        s.bubble((bx, by), letters, num)
    s.bubble((300, 500), "LIC", "1030", panel=True)
    s.bubble((500, 500), "PI", "1041")
    s.line((500, 500 - R), (500, y))
    s.text((900, 500), "PSV-1040", 8)
    s.line((900, 490), (900, y))
    s.title_block(W, H, "PID-100", "SHT-01")
    s.commit()
    return {"bubble": (350, 200), "control": (450, y), "valve": (250, y)}


def sheet2(doc: fitz.Document) -> None:
    page = doc.new_page(width=W, height=H)
    page.set_rotation(90)  # displayed portrait: 842 x 1191
    w, h = H, W
    s = Sheet(page)
    x = 300
    s.line((x, 80), (x, 900), width=1.2)
    s.line((x, 600), (600, 600), width=1.2)
    s.valve((450, 600), control=True)
    s.line((450, 600 - 23), (450, 555 + R), dashes="[3 2] 0")
    s.bubble((450, 555), "FV", "2001")
    for (bx, by), letters, num in (((200, 300), "FT", "2001"), ((200, 450), "PT", "2002"),
                                   ((200, 750), "FT", "1023")):
        s.line((bx + R, by), (x, by))
        s.bubble((bx, by), letters, num)
    s.title_block(w, h, "PID-101", "SHT-02")
    s.commit()


def scanned(src: fitz.Document) -> fitz.Document:
    out = fitz.open()
    for page in src:
        pix = page.get_pixmap(dpi=DPI, colorspace=fitz.csGRAY)
        r = page.rect  # displayed size
        new = out.new_page(width=r.width, height=r.height)
        new.insert_image(new.rect, pixmap=pix)
    return out


def templates(doc: fitz.Document, at: dict) -> list[dict]:
    first = next(render_pages(doc.tobytes()))
    gray = erase_words(decode_gray(first.png), first.words)  # templates are cut text-free, like the UI does

    def cut(cx, cy, hw, top, bottom):
        return crop(gray, [(cx - hw) * ZOOM, (cy - top) * ZOOM, (cx + hw) * ZOOM, (cy + bottom) * ZOOM])

    pad = 2.5
    bub = cut(*at["bubble"], R + pad, R + pad, R + pad)
    ctl = cut(*at["control"], 14 + pad, 23 + pad, 8 + pad)
    vlv = cut(*at["valve"], 14 + pad, 8 + pad, 8 + pad)
    bh, bw = bub.shape
    out = []
    for i, (desc, img, extra) in enumerate((
        ("Instrument bubble", bub, {"tag_format": "{Function}-{Number}", "points": [
            {"name": "Function", "x": bw / 2, "y": bh / 2 - 5 * ZOOM, "min_overlap": 0.5},
            {"name": "Number", "x": bw / 2, "y": bh / 2 + 7 * ZOOM, "min_overlap": 0.5}]}),
        ("Control valve", ctl, {"variants": {"rot90": True, "rot270": True}}),
        ("Valve", vlv, {"variants": {"rot90": True}}),
    )):
        out.append({"desc": desc, "drawing_type": "PID", "block_set": "FIR", "priority": i, "threshold": 0.7,
                    "buffer_space": 3, "use_mask": True, **extra,
                    "image_png": base64.b64encode(encode_png(img)).decode()})
    return out


def main() -> None:
    OUT.mkdir(exist_ok=True)
    doc = fitz.open()
    at = sheet1(doc)
    sheet2(doc)
    doc.save(OUT / "pid-sample.pdf", garbage=3, deflate=True)
    scanned(doc).save(OUT / "pid-sample-scanned.pdf", garbage=3, deflate=True)
    lib = {"format": "drawing-workbench-pid-templates", "version": 1, "templates": templates(doc, at),
           "exclusions": {"PID/FIR": {"words": [], "areas": [TITLE_AREA]}}}
    (OUT / "pid-templates.json").write_text(json.dumps(lib, indent=1))
    print("Wrote", ", ".join(p.name for p in sorted(OUT.glob("pid-*"))))


if __name__ == "__main__":
    main()
