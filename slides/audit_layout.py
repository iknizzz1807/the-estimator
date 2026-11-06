"""Audit card/chip geometry in a compiled deck.

Detects text that overflows its enclosing rectangle or sits off-centre.
Works from the PDF, so it does not need anyone to look at the rendered slides.

Usage:
    python audit_layout.py main-bizops.pdf main.pdf
"""
from __future__ import annotations

import argparse
import re
import sys
import unicodedata
from pathlib import Path

import pymupdf

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def norm(text: str) -> str:
    """Normalise text for source lookup (ligatures, dashes, spaces)."""
    text = unicodedata.normalize("NFKD", text)
    text = text.replace("\ufb01", "fi").replace("\ufb02", "fl")
    text = text.replace("\u2013", "-").replace("\u2014", "-")
    text = text.replace("\u2018", "'").replace("\u2019", "'")
    text = text.replace("\u201c", '"').replace("\u201d", '"')
    text = text.replace("\u00b7", ".")
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def source_index(tex_files: list[Path]) -> list[tuple[str, int, str]]:
    rows = []
    for path in tex_files:
        if path.name.startswith("_"):
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            n = norm(line)
            if len(n) >= 4:
                rows.append((path.name, lineno, n))
    return rows


def find_source(rows, text: str) -> str:
    n = norm(text)
    if len(n) < 4:
        return ""
    for name, lineno, line in rows:
        if n in line:
            return f"{name}:{lineno}"
    # try the longest fragment (labels split across TeX macros)
    for size in (12, 10, 8, 6, 4):
        if len(n) < size:
            continue
        frag = n[:size]
        for name, lineno, line in rows:
            if frag in line:
                return f"{name}:{lineno}"
    return ""


def rects(page):
    out = []
    for drawing in page.get_drawings():
        r = drawing["rect"]
        if r.width < 5 or r.height < 5:
            continue
        if r.width > page.rect.width * 0.95 and r.height > page.rect.height * 0.95:
            continue
        out.append(r)
    return out


def audit_page(page, rows, page_no: int):
    boxes = rects(page)
    problems = []
    for block in page.get_text("dict")["blocks"]:
        if block.get("type") != 0:
            continue
        for line in block["lines"]:
            text = " ".join(span["text"] for span in line["spans"]).strip()
            if not text:
                continue
            if max(span["size"] for span in line["spans"]) > 20:
                continue
            lx0, ly0, lx1, ly1 = line["bbox"]
            cx, cy = (lx0 + lx1) / 2, (ly0 + ly1) / 2
            # smallest rectangle whose interior contains the line centre
            candidates = [
                r for r in boxes
                if r.x0 - 1 <= cx <= r.x1 + 1 and r.y0 - 1 <= cy <= r.y1 + 1
            ]
            if not candidates:
                continue
            r = min(candidates, key=lambda b: b.width * b.height)
            left, right = lx0 - r.x0, r.x1 - lx1
            top, bottom = ly0 - r.y0, r.y1 - ly1
            text_w, text_h = lx1 - lx0, ly1 - ly0
            # A fill/box that is just the text's own background is not a card.
            if (r.width <= text_w + 1.5 and r.height <= text_h + 2.0
                    and min(left, right, top, bottom) > -1.5):
                continue
            reasons = []
            if min(left, right) < -0.5:
                reasons.append(f"overflow-x {min(left, right):+.1f}pt")
            if min(top, bottom) < -0.5:
                reasons.append(f"overflow-y {min(top, bottom):+.1f}pt")
            short = text_h < 20 and r.height <= 20
            centred = abs(left - right) < 3
            if short and centred and abs(top - bottom) > 1.5:
                reasons.append(f"off-centre-y top={top:.1f} bottom={bottom:.1f}")
            if reasons:
                problems.append({
                    "page": page_no,
                    "text": text,
                    "rect": tuple(round(v, 2) for v in r),
                    "bbox": tuple(round(v, 2) for v in line["bbox"]),
                    "reasons": reasons,
                    "source": find_source(rows, text),
                })
    return problems


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("pdfs", nargs="+")
    ap.add_argument("--tex-dir", default=".")
    ap.add_argument("--max", type=int, default=200)
    args = ap.parse_args()

    tex_dir = Path(args.tex_dir)
    rows = source_index(sorted(tex_dir.glob("*.tex")))
    total = 0
    for pdf in args.pdfs:
        doc = pymupdf.open(pdf)
        problems = []
        for pno, page in enumerate(doc, 1):
            problems.extend(audit_page(page, rows, pno))
        print(f"\n=== {pdf} ({len(doc)} pages) ===")
        if not problems:
            print("OK: no card/chip geometry issues")
        for p in problems[: args.max]:
            print(f"p{p['page']:02d} {p['text']!r}  {p['source']}")
            print(f"     rect={p['rect']} text={p['bbox']}")
            print(f"     {', '.join(p['reasons'])}")
        if len(problems) > args.max:
            print(f"... {len(problems) - args.max} more")
        total += len(problems)
        doc.close()
    print(f"\nTotal issues: {total}")
    return 1 if total else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # pragma: no cover
        print(f"audit failed: {exc}", file=sys.stderr)
        raise
