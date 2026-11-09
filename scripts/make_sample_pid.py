# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""Generate the P&ID example: sample drawings and the starter library the app ships with.

  samples/pid-sample.pdf          2 sheets with a text layer (sheet 2 has /Rotate 90)
  samples/pid-sample-scanned.pdf  the same sheets as images only (exercises OCR)
  samples/pid-library.json        the "P&ID instruments" library (templates + tag rules)
  core/src/workbench_core/symbols/starter.py   the same library, built into the engine

Expected tags (11 unique): FV-1023 FV-1024 FT-1023 PT-1025 TT-1026A LIC-1030 PI-1041
PSV-1040 (sheet 1), FT-2001 PT-2002 FV-2001 (sheet 2; FT-1023 repeats there). The title
block holds tag-like text (PID-100, SHT-01) that the library's ignored area removes.

The PDFs are written by a small writer below (no PDF library needed); rendering uses the
app's own PDFium-based renderer. Run: python scripts/make_sample_pid.py
"""

from __future__ import annotations

import base64
import json
import math
import zlib
from pathlib import Path

from workbench_core.symbols.models import DPI
from workbench_core.symbols.render import decode_gray, encode_png, render_pages
from workbench_core.symbols.templates import crop, erase_words

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "samples"
STARTER = ROOT / "core/src/workbench_core/symbols/starter.py"
W, H = 1191, 842  # A3 landscape, points
R = 16            # bubble radius
ZOOM = DPI / 72
TITLE_AREA = [850 / W, 690 / H, 1180 / W, 830 / H]  # fractions of the displayed sheet
ISA_PATTERN = r"(?P<function>[A-Z]{1,5})[- ]?(?P<loop>\d{2,6})(?P<suffix>[A-Z]{0,2})"
ISA_FORMAT = "{function}-{loop}{suffix}"

# Helvetica advance widths (1/1000 em) for the characters used.
_HELV = {" ": 278, "-": 333, ".": 278, **{d: 556 for d in "0123456789"},
         **dict(zip("ABCDEFGHIJKLMNOPQRSTUVWXYZ",
                    [667, 667, 722, 722, 667, 611, 778, 722, 278, 500, 667, 556, 833, 722, 778, 667,
                     778, 722, 667, 611, 722, 667, 944, 667, 667, 611]))}


def text_width(s: str, size: float) -> float:
    return sum(_HELV.get(ch, 600) for ch in s) * size / 1000


class Sheet:
    """Draws in displayed (upright, top-left origin) coordinates, whatever the /Rotate."""

    def __init__(self, width: float, height: float, rotate: int = 0):
        self.rotate = rotate
        self.mw, self.mh = (width, height) if rotate == 0 else (height, width)  # MediaBox (unrotated)
        self.ops: list[str] = []

    def p(self, x: float, y: float) -> tuple[float, float]:
        return (x, self.mh - y) if self.rotate == 0 else (y, x)  # rotate 90: see render._to_pixels

    def _pt(self, x, y) -> str:
        u, v = self.p(x, y)
        return f"{u:.2f} {v:.2f}"

    def stroke(self, width=0.8, dashes: str | None = None):
        self.ops.append(f"{width} w {dashes or '[] 0'} d S")

    def line(self, a, b, width=0.8, dashes=None):
        self.ops.append(f"{self._pt(*a)} m {self._pt(*b)} l")
        self.stroke(width, dashes)

    def poly(self, pts):
        self.ops.append(" ".join([f"{self._pt(*pts[0])} m"] + [f"{self._pt(*q)} l" for q in pts[1:]]) + " h")
        self.stroke()

    def _arc(self, cx, cy, r, a0, a1):
        """Bezier segments for an arc (angles in degrees, display frame, y down)."""
        segs = max(1, math.ceil(abs(a1 - a0) / 90))
        step = (a1 - a0) / segs
        k = 4 / 3 * math.tan(math.radians(step) / 4)
        out = []
        for i in range(segs):
            t0, t1 = math.radians(a0 + i * step), math.radians(a0 + (i + 1) * step)
            p0 = (cx + r * math.cos(t0), cy + r * math.sin(t0))
            p3 = (cx + r * math.cos(t1), cy + r * math.sin(t1))
            p1 = (p0[0] - k * r * math.sin(t0), p0[1] + k * r * math.cos(t0))
            p2 = (p3[0] + k * r * math.sin(t1), p3[1] - k * r * math.cos(t1))
            out.append((p0, p1, p2, p3))
        return out

    def circle(self, c, r):
        segs = self._arc(c[0], c[1], r, 0, 360)
        self.ops.append(f"{self._pt(*segs[0][0])} m " + " ".join(
            f"{self._pt(*a)} {self._pt(*b)} {self._pt(*d)} c" for _, a, b, d in segs) + " h")
        self.stroke()

    def dome(self, c, r):
        """The top half of a circle, closed by its diameter (a valve actuator)."""
        segs = self._arc(c[0], c[1], r, 180, 360)  # y down: 180->360 is the upper half
        self.ops.append(f"{self._pt(*segs[0][0])} m " + " ".join(
            f"{self._pt(*a)} {self._pt(*b)} {self._pt(*d)} c" for _, a, b, d in segs) + " h")
        self.stroke()

    def text(self, c, s, size=7.0):
        """Centred on c, upright on the displayed sheet."""
        x, y = c[0] - text_width(s, size) / 2, c[1] + size * 0.35
        u, v = self.p(x, y)
        a, b, cc, d = (1, 0, 0, 1) if self.rotate == 0 else (0, 1, -1, 0)
        esc = s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        self.ops.append(f"BT /F1 {size} Tf {a} {b} {cc} {d} {u:.2f} {v:.2f} Tm ({esc}) Tj ET")

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
            self.dome((x, y - 14), 9)

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


def write_pdf(pages: list[dict]) -> bytes:
    """pages: {"mediabox": (w, h), "rotate": int, "content": bytes, "image": (w, h, gray bytes) | None}."""
    objs: list[bytes] = []

    def add(body: bytes) -> int:
        objs.append(body)
        return len(objs)

    def stream(d: str, data: bytes) -> bytes:
        z = zlib.compress(data, 9)
        return f"<< {d} /Length {len(z)} /Filter /FlateDecode >>\nstream\n".encode() + z + b"\nendstream"

    font = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    pages_id = len(objs) + 1 + 2 * len(pages) + sum(1 for p in pages if p.get("image")) + 1
    kids = []
    for p in pages:
        res = f"/Font << /F1 {font} 0 R >>"
        if p.get("image"):
            iw, ih, raw = p["image"]
            im = add(stream(f"/Type /XObject /Subtype /Image /Width {iw} /Height {ih} /ColorSpace /DeviceGray "
                            "/BitsPerComponent 8", raw))
            res += f" /XObject << /Im1 {im} 0 R >>"
        content = add(stream("", p["content"]))
        mw, mh = p["mediabox"]
        kids.append(add(f"<< /Type /Page /Parent {pages_id} 0 R /MediaBox [0 0 {mw:g} {mh:g}] /Rotate {p['rotate']} "
                        f"/Resources << {res} >> /Contents {content} 0 R >>".encode()))
    catalog = add(f"<< /Type /Catalog /Pages {pages_id} 0 R >>".encode())
    assert len(objs) + 1 == pages_id, (len(objs), pages_id)
    add(f"<< /Type /Pages /Kids [{' '.join(f'{k} 0 R' for k in kids)}] /Count {len(kids)} >>".encode())
    out = bytearray(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root {catalog} 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


def sheet1() -> Sheet:
    s = Sheet(W, H)
    y = 300
    s.line((80, y), (1010, y), width=1.2)
    s.valve((250, y))
    s.valve((450, y), control=True)
    s.valve((650, y))
    s.valve((850, y), control=True)
    for vx, num in ((450, "1023"), (850, "1024")):
        s.line((vx, y - 23), (vx, y - 45 + R), dashes="[3 2] 0")
        s.bubble((vx, y - 45), "FV", num)
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
    return s


def sheet2() -> Sheet:
    w, h = H, W  # displayed portrait
    s = Sheet(w, h, rotate=90)
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
    return s


AT = {"bubble": (350, 200), "control": (450, 300), "valve": (250, 300)}


def library(pdf: bytes) -> dict:
    first = next(render_pages(pdf))
    gray = erase_words(decode_gray(first.png), first.words)  # templates are cut text-free, like the UI does

    def cut(cx, cy, hw, top, bottom):
        return crop(gray, [(cx - hw) * ZOOM, (cy - top) * ZOOM, (cx + hw) * ZOOM, (cy + bottom) * ZOOM])

    pad = 2.5
    bub = cut(*AT["bubble"], R + pad, R + pad, R + pad)
    ctl = cut(*AT["control"], 14 + pad, 23 + pad, 8 + pad)
    vlv = cut(*AT["valve"], 14 + pad, 8 + pad, 8 + pad)
    bh, bw = bub.shape
    templates = []
    for i, (desc, img, extra) in enumerate((
        ("Instrument bubble", bub, {"tag_format": "{Function}{Number}", "points": [
            {"name": "Function", "x": round(bw / 2, 1), "y": round(bh / 2 - 5 * ZOOM, 1), "min_overlap": 0.5},
            {"name": "Number", "x": round(bw / 2, 1), "y": round(bh / 2 + 7 * ZOOM, 1), "min_overlap": 0.5}]}),
        ("Control valve", ctl, {"variants": {"rot90": True, "rot270": True}}),
        ("Valve", vlv, {"variants": {"rot90": True}}),
    )):
        templates.append({"desc": desc, "priority": i, "threshold": 0.7, "buffer_space": 3, "mask_mode": "auto",
                          **extra, "image_png": base64.b64encode(encode_png(img)).decode()})
    return {
        "format": "drawing-workbench-symbol-library", "version": 2,
        "library": {
            "name": "P&ID instruments (ISA)",
            "description": "Example library: instrument bubbles, control valves and valves, with ISA-5.1 style "
                           "tags such as FT-1023 or TT-1026A. Copy it or make your own library for other drawings.",
            "tag_pattern": ISA_PATTERN, "tag_format": ISA_FORMAT, "pattern_scan": True, "scan_stacked": True,
            "min_pdf_words": 5, "default_threshold": 0.7,
            "exclusion": {"words": [], "areas": [TITLE_AREA]},
        },
        "templates": templates,
    }


def scanned(pdf: bytes) -> bytes:
    pages = []
    for p in render_pages(pdf):
        gray = decode_gray(p.png)
        h, w = gray.shape
        pw, ph = w / ZOOM, h / ZOOM
        pages.append({"mediabox": (pw, ph), "rotate": 0, "image": (w, h, gray.tobytes()),
                      "content": f"q {pw:.3f} 0 0 {ph:.3f} 0 0 cm /Im1 Do Q".encode()})
    return write_pdf(pages)


def main() -> None:
    OUT.mkdir(exist_ok=True)
    sheets = [sheet1(), sheet2()]
    pdf = write_pdf([{"mediabox": (s.mw, s.mh), "rotate": s.rotate, "content": "\n".join(s.ops).encode()}
                     for s in sheets])
    (OUT / "pid-sample.pdf").write_bytes(pdf)
    (OUT / "pid-sample-scanned.pdf").write_bytes(scanned(pdf))
    lib = library(pdf)
    (OUT / "pid-library.json").write_text(json.dumps(lib, indent=1))
    STARTER.write_text(
        "# SPDX-License-Identifier: AGPL-3.0-only\n# Copyright (C) 2026 Matthew Kelly\n"
        '"""The P&ID example library the app ships with (generated by scripts/make_sample_pid.py)."""\n\n'
        "import json\n\n"
        f"STARTER_LIBRARY = json.loads({json.dumps(json.dumps(lib))})\n")
    print("Wrote", ", ".join(p.name for p in sorted(OUT.glob("pid-*"))), "and", STARTER.name)


if __name__ == "__main__":
    main()
