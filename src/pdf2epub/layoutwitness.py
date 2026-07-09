"""Optional layout witness — a THIRD analyze-time witness (advisory only).

A forked-in idea from datalab's marker/surya: a vision layout model reads a page
RENDER and returns labelled region boxes (Table / Figure / Section-header /
Footnote / Page-header / Page-footer / Caption / List-item / Text / Title …).
pdf2epub uses it the way it already uses poppler pdftotext: an independent
witness that FLAGS structure for the conversion agent, never co-authors the
build. Its output lands in ``books/<slug>/analysis/layout/`` (git-ignored,
regenerable) and reaches a build only if the agent transcribes a judgment into
book.yaml. ``build`` never reads it, so byte-reproducibility and the
never-invent-words rule are untouched — same boundary the engine-agreement flag
observes, one rung up: text engines witness *text*, this witnesses *structure*.

Backend: a DocLayNet-trained object detector loaded in-process through
``transformers`` (torch, CPU). surya/marker themselves will not install on this
toolchain — both pin ``Pillow<11`` against the repo's Pillow 12 and Pillow 10 has
no cp314 wheel — but the DocLayNet taxonomy the detector emits is the same one
surya was trained on. Heavy imports (torch/transformers) are LAZY: importing this
module costs nothing, and nothing is imported unless the agent passes ``--layout``.
Absent backend -> ``LayoutUnavailable``; callers skip with a hint, never crash.
"""

from __future__ import annotations

import io
import json
import os
import random
import re
import time
from dataclasses import dataclass
from pathlib import Path

# Render DPI for the model input. Only sets the pixel<->point scale, so a modest
# value bounds CPU memory/time without changing the coordinate math.
LAYOUT_DPI = 150

# DocLayNet object-detection checkpoint. Overridable so a slow/absent model can
# be swapped without a code change. Labels are matched by keyword (below), so any
# DocLayNet-taxonomy checkpoint works regardless of exact label spelling.
_MODEL_ID = os.environ.get("PDF2EPUB_LAYOUT_MODEL", "Aryn/deformable-detr-DocLayNet")
_THRESHOLD = float(os.environ.get("PDF2EPUB_LAYOUT_THRESHOLD", "0.4"))

# label keyword -> witness bucket (checked in this order; toc before figure so
# "Table-of-contents" is not swallowed by the "table" keyword)
_TOC = ("table-of-contents", "tableofcontents", "contents", "toc")
_FIGURE = ("table", "figure", "picture", "image")
_FOOTER = ("page-footer", "pagefooter")   # NOT bare "footer": Section-* is a heading
_HEADER = ("page-header", "pageheader")    # NOT bare "header": Section-header is a heading
_FOOTNOTE = ("footnote",)
_HEADING = ("section-header", "sectionheader", "title", "heading")


class LayoutUnavailable(RuntimeError):
    """The optional ML backend (transformers + torch) could not be imported."""


@dataclass(slots=True)
class LayoutBox:
    page: int                                  # 1-based physical page
    label: str                                 # raw model label
    rect: tuple[float, float, float, float]    # extract-space pt, top-origin
    position: int                              # reading order within the page
    confidence: float

    def as_dict(self) -> dict:
        return {"page": self.page, "label": self.label, "rect": list(self.rect),
                "position": self.position, "confidence": self.confidence}


def layout_available() -> bool:
    """True iff the backend can be imported. The import is heavy (pulls torch),
    so call this only inside the --layout branch."""
    try:
        import torch  # noqa: F401
        import transformers  # noqa: F401
    except Exception:
        return False
    return True


def _bucket(label: str) -> str:
    lo = label.lower().replace(" ", "-").replace("_", "-")
    if any(k in lo for k in _TOC):
        return "toc"
    if any(k in lo for k in _FIGURE):
        return "figure"
    if any(k in lo for k in _FOOTER):
        return "footer"
    if any(k in lo for k in _HEADER):
        return "header"
    if any(k in lo for k in _FOOTNOTE):
        return "footnote"
    if any(k in lo for k in _HEADING):
        return "heading"
    return "text"


# ----------------------------------------------------------------- model

_MODEL = None
_PROC = None


def _load():
    global _MODEL, _PROC
    if _MODEL is None:
        os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
        from transformers import AutoImageProcessor, AutoModelForObjectDetection
        from transformers.utils import logging as hf_logging
        hf_logging.set_verbosity_error()      # keep init output clean
        hf_logging.disable_progress_bar()     # env var alone is too late here
        _PROC = AutoImageProcessor.from_pretrained(_MODEL_ID)
        _MODEL = AutoModelForObjectDetection.from_pretrained(_MODEL_ID)
        _MODEL.eval()
    return _MODEL, _PROC


def _render(pdf, pno: int, dpi: int):
    """Full-page render (no clip): pixel (px,py) maps to extract-space point
    (px*72/dpi, py*72/dpi) — same top-origin CropBox space as the span bboxes,
    so no matrix/offset is needed (see figures.py region path)."""
    from PIL import Image
    page = pdf[pno - 1]
    pix = page.get_pixmap(dpi=dpi)
    return Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")


def _boxes_from_detections(scores, labels, boxes_px, id2label, pno: int,
                           dpi: int) -> list[LayoutBox]:
    """Pure: pixel detections -> extract-space LayoutBoxes in reading order.
    Pixel (px) -> point (px*72/dpi); no matrix/offset (full-page render shares
    the span-bbox top-origin CropBox space). Unit-tested without the model."""
    scale = 72.0 / dpi
    boxes: list[LayoutBox] = []
    for score, label, box in zip(scores, labels, boxes_px):
        x0, x1 = sorted((round(box[0] * scale, 2), round(box[2] * scale, 2)))
        y0, y1 = sorted((round(box[1] * scale, 2), round(box[3] * scale, 2)))
        if x1 - x0 < 1 or y1 - y0 < 1:
            continue
        boxes.append(LayoutBox(page=pno, label=str(id2label[int(label)]),
                               rect=(x0, y0, x1, y1), position=0,
                               confidence=round(float(score), 3)))
    # reading order: banded top-to-bottom, then left-to-right
    boxes.sort(key=lambda b: (round(b.rect[1] / 10.0), b.rect[0]))
    for i, b in enumerate(boxes):
        b.position = i
    return boxes


def _detect(image, pno: int, dpi: int) -> list[LayoutBox]:
    import torch
    model, proc = _load()
    inputs = proc(images=image, return_tensors="pt")
    with torch.no_grad():
        outputs = model(**inputs)
    sizes = torch.tensor([[image.height, image.width]])
    res = proc.post_process_object_detection(
        outputs, target_sizes=sizes, threshold=_THRESHOLD)[0]
    return _boxes_from_detections(res["scores"].tolist(), res["labels"].tolist(),
                                  res["boxes"].tolist(), model.config.id2label,
                                  pno, dpi)


# ---------------------------------------------------------- page selection

# Auto-escalation thresholds (tunable via env). The witness runs once at init,
# so `all` is a one-time ~2.1s/page cost; scan it whenever the book plausibly
# hides a table/figure outside the flagged set.
AUTO_ALL_MAX_PAGES = int(os.environ.get("PDF2EPUB_LAYOUT_AUTO_ALL_MAX", "300"))
_RULED_MIN_RULES = int(os.environ.get("PDF2EPUB_LAYOUT_RULED_MIN", "3"))
_FIGURE_LIST_RE = re.compile(
    r"(?i)\b(?:list|table) of "
    r"(?:tables|figures|illustrations|plates|maps|charts)\b")


def structure_suspect_pages(doc, a, drawings_dense=frozenset()) -> set[int]:
    """Cheap deterministic 'likely holds a table/figure' set. flagged_pages is a
    capped render queue that misses clean text tables (high engine agreement, no
    PUA) — exactly where a hand-authored figure_regions matters most. Reuses
    existing signals + a tabular smell + vector-ruled pages (drawings_dense)."""
    s: set[int] = (set(a.column_suspect_pages) | set(a.image_only_pages)
                   | set(a.figure_pages_proposal) | set(drawings_dense))
    for p in doc.pages:
        if p.n_images > 0:
            s.add(p.number)
        tw = p.trim[2] - p.trim[0]
        if tw > 0 and sum(1 for ln in p.lines if (ln.x1 - ln.x0) < 0.4 * tw) >= 8:
            s.add(p.number)  # rows of short aligned runs — tabular smell
    return {p for p in s if 1 <= p <= doc.n_pages}


def default_pages(doc, a, drawings_dense=frozenset()) -> set[int]:
    return set(a.flagged_pages) | structure_suspect_pages(doc, a, drawings_dense)


def toc_has_figure_list(doc, a) -> bool:
    """High-precision 'this book is figure/table-heavy' flag: the printed TOC /
    outline advertises a List of Tables/Figures/Illustrations/Plates."""
    texts = [e.get("text", "") for e in a.toc_entries]
    texts += [e.get("text", "") for e in a.headings]
    texts += [o.title for o in doc.outline]
    return any(_FIGURE_LIST_RE.search(t) for t in texts if t)


def drawings_dense_pages(pdf_path, doc, *, min_rules=_RULED_MIN_RULES,
                         min_len=30.0) -> set[int]:
    """Pages carrying a ruled grid: >= min_rules distinct horizontal OR vertical
    rule positions from long LINE strokes. Rects are ignored — books frame pages
    with decorative rectangles (BoK: ~10/page) that would swamp a segment count;
    real ruled tables draw their rows/cols as many distinct parallel lines
    (BoK p.26: 7 row rules vs 0-1 on prose pages). Catches ruled tables/diagrams
    that carry no raster image, so the other structure-suspect signals miss them.
    Opens the PDF; cheap (ms/page)."""
    import fitz
    dense: set[int] = set()
    pdf = fitz.open(str(pdf_path))
    try:
        for i in range(doc.n_pages):
            try:
                drawings = pdf[i].get_drawings()
            except Exception:
                continue
            hs: set[int] = set()
            vs: set[int] = set()
            for d in drawings:
                for it in d.get("items", ()):
                    if it[0] != "l":
                        continue
                    p1, p2 = it[1], it[2]
                    if abs(p1.y - p2.y) < 1.0 and abs(p1.x - p2.x) >= min_len:
                        hs.add(round(p1.y))            # horizontal rule (row)
                    elif abs(p1.x - p2.x) < 1.0 and abs(p1.y - p2.y) >= min_len:
                        vs.add(round(p1.x))            # vertical rule (column)
            if len(hs) >= min_rules or len(vs) >= min_rules:
                dense.add(i + 1)
    finally:
        pdf.close()
    return dense


def auto_pages(doc, a, drawings_dense=frozenset()) -> tuple[set[int], str]:
    """Evidence-gated default: scan ALL when the book plausibly hides a
    table/figure outside the flagged set — small enough that all is cheap, a TOC
    list-of-tables/figures, or vector-ruled pages. Else flagged+suspect."""
    reasons = []
    if doc.n_pages <= AUTO_ALL_MAX_PAGES:
        reasons.append(f"<={AUTO_ALL_MAX_PAGES}pp")
    if toc_has_figure_list(doc, a):
        reasons.append("TOC lists tables/figures")
    if drawings_dense:
        reasons.append(f"{len(drawings_dense)} vector-ruled page(s)")
    if reasons:
        return set(range(1, doc.n_pages + 1)), "auto=all (" + "; ".join(reasons) + ")"
    return default_pages(doc, a, drawings_dense), "auto=flagged+structure-suspect"


def _parse_spec(spec: str) -> list[int]:
    out: list[int] = []
    for tok in re.split(r"[,\s]+", spec.strip()):
        if not tok:
            continue
        if "-" in tok:
            lo, hi = tok.split("-", 1)
            out.extend(range(int(lo), int(hi) + 1))
        else:
            out.append(int(tok))
    return out


def resolve_pages(spec, doc, a, drawings_dense=frozenset()) -> tuple[list[int], str]:
    """None/'auto' -> evidence-gated (auto_pages); 'flagged'/'default' -> the
    subset; 'all'; '+sample:N' seeded top-up; or an explicit '26'/'322-336'."""
    n = doc.n_pages
    if spec in (None, "", "auto"):
        pages, desc = auto_pages(doc, a, drawings_dense)
    elif spec in ("flagged", "default"):
        pages = default_pages(doc, a, drawings_dense)
        desc = "flagged + structure-suspect"
    elif spec == "all":
        pages, desc = set(range(1, n + 1)), "all pages"
    elif isinstance(spec, str) and spec.startswith("+sample:"):
        k = int(spec.split(":", 1)[1])
        base = default_pages(doc, a, drawings_dense)
        rest = [p for p in range(1, n + 1) if p not in base]
        rng = random.Random(int(doc.sha256[:16], 16) if doc.sha256 else 0)
        rng.shuffle(rest)
        pages = base | set(rest[:k])
        desc = f"flagged + structure-suspect + {min(k, len(rest))} seeded-sample"
    else:
        pages, desc = set(_parse_spec(str(spec))), f"explicit ({spec})"
    return sorted(p for p in pages if 1 <= p <= n), desc


# --------------------------------------------------------------- driver

def run_layout_witness(pdf_path, pages, dpi: int = LAYOUT_DPI, *,
                       overlay_dir: Path | None = None,
                       timings: dict | None = None) -> dict[int, list[LayoutBox]]:
    if not layout_available():
        raise LayoutUnavailable(
            "layout backend not installed (need transformers + torch)")
    import fitz
    if timings is not None:
        t0 = time.perf_counter()
        _load()
        timings["model_load_s"] = round(time.perf_counter() - t0, 2)
    result: dict[int, list[LayoutBox]] = {}
    pdf = fitz.open(str(pdf_path))
    try:
        for pno in pages:
            tr = time.perf_counter()
            image = _render(pdf, pno, dpi)
            td = time.perf_counter()
            boxes = _detect(image, pno, dpi)
            te = time.perf_counter()
            result[pno] = boxes
            if timings is not None:
                timings.setdefault("pages", []).append(
                    {"page": pno, "render_s": round(td - tr, 3),
                     "predict_s": round(te - td, 3), "boxes": len(boxes)})
            if overlay_dir is not None:
                _write_overlay(image, boxes, Path(overlay_dir) / f"p{pno:04d}.png", dpi)
    finally:
        pdf.close()
    return result


def _write_overlay(image, boxes, out: Path, dpi: int) -> None:
    from PIL import ImageDraw
    out.parent.mkdir(parents=True, exist_ok=True)
    im = image.copy()
    draw = ImageDraw.Draw(im)
    k = dpi / 72.0
    for b in boxes:
        x0, y0, x1, y1 = (v * k for v in b.rect)
        draw.rectangle([x0, y0, x1, y1], outline=(220, 30, 30), width=2)
        draw.text((x0 + 2, max(0.0, y0 - 11)),
                  f"{b.label} {b.confidence:.2f}", fill=(220, 30, 30))
    im.save(out, optimize=True)


# --------------------------------------------------------- evidence + report

def write_layout_evidence(doc, a, boxes_by_page, scanned, desc, out_dir) -> None:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    n = doc.n_pages
    payload = {
        "model": _MODEL_ID,
        "dpi": LAYOUT_DPI,
        "coverage": {"scanned": sorted(scanned), "n_scanned": len(scanned),
                     "n_pages": n, "n_not_scanned": n - len(scanned),
                     "selection": desc},
        "pages": {str(p): [b.as_dict() for b in boxes_by_page.get(p, [])]
                  for p in sorted(boxes_by_page)},
    }
    (out_dir / "layout.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1))
    (out_dir / "report.md").write_text(
        _report_md(doc, a, boxes_by_page, scanned, desc))


def _report_md(doc, a, boxes_by_page, scanned, desc) -> str:
    n = doc.n_pages
    all_boxes = [b for p in sorted(boxes_by_page) for b in boxes_by_page[p]]
    figs = [b for b in all_boxes if _bucket(b.label) == "figure"]
    L: list[str] = []
    w = L.append
    w("# Layout witness — ADVISORY (a third witness, not a co-author)")
    w("")
    w(f"Backend `{_MODEL_ID}` @ {LAYOUT_DPI} dpi. Rects are extract-space points "
      "(top-origin) — the same space as `images.figure_regions[].rect` and the "
      "`pdf2epub lines` dump. **Verify every candidate against its page render "
      "(analysis/layout/p####.png) before pasting into book.yaml; this witness "
      "flags, it never decides.**")
    w("")
    w(f"**Coverage:** scanned {len(scanned)}/{n} pages ({desc}); "
      f"{n - len(scanned)} page(s) were NOT layout-checked. Tables/figures on "
      "unscanned pages are unseen here — rerun `init --layout --layout-pages all` "
      "if this book sets tables/figures in running prose.")
    w("")
    w("## Figure/table candidates -> images.figure_regions")
    if figs:
        w("Paste, then WRITE `alt` from the render (alt is required); drop any the "
          "render shows is not a real figure/table:")
        w("```yaml")
        w("images:")
        w("  figure_regions:")
        for b in figs:
            x0, y0, x1, y1 = b.rect
            w(f"    - page: {b.page}")
            w(f"      rect: [{x0:g}, {y0:g}, {x1:g}, {y1:g}]")
            w(f'      alt: ""   # FILL from p{b.page:04d} render — {b.label} conf {b.confidence:g}')
            w(f'      note: "layout-witness {b.label} p.{b.page}; verify on render"')
        w("```")
    else:
        w("_none detected on scanned pages._")
    w("")
    w("## Multi-column pages -> flow.columns")
    cols = _column_suggestions(boxes_by_page)
    if cols:
        w("Counts are a floor (2-column detection); confirm the real count on the "
          "render:")
        w("```yaml")
        w("flow:")
        w("  columns:")
        for pno, cnt in cols:
            w(f"    - {{pages: [{pno}], count: {cnt}, "
              f'note: "layout-witness: >= {cnt} column groups; verify on render"}}')
        w("```")
    else:
        w("_no multi-column pages detected on scanned pages._")
    w("")
    w("## Cross-checks (advisory)")
    _crosschecks(w, doc, a, boxes_by_page)
    w("")
    return "\n".join(L)


def _page_span_mid(boxes) -> float:
    x0 = min(b.rect[0] for b in boxes)
    x1 = max(b.rect[2] for b in boxes)
    return (x0 + x1) / 2.0


def _y_overlap(left, right) -> bool:
    for lb in left:
        for rb in right:
            if min(lb.rect[3], rb.rect[3]) - max(lb.rect[1], rb.rect[1]) > 0:
                return True
    return False


def _column_suggestions(boxes_by_page):
    """Pages with side-by-side, vertically co-occurring text bands (real
    columns, not stacked blocks). Conservative: reports 2 where a clean
    left/right split exists; higher counts are left to the render."""
    out = []
    for pno in sorted(boxes_by_page):
        boxes = [b for b in boxes_by_page[pno]
                 if _bucket(b.label) in ("text", "heading")]
        if len(boxes) < 4:
            continue
        mid = _page_span_mid(boxes)
        left = [b for b in boxes if (b.rect[0] + b.rect[2]) / 2 < mid]
        right = [b for b in boxes if (b.rect[0] + b.rect[2]) / 2 >= mid]
        if len(left) >= 2 and len(right) >= 2 and _y_overlap(left, right):
            out.append((pno, 2))
    return out


def _crosschecks(w, doc, a, boxes_by_page) -> None:
    def pages_with(bucket):
        return sorted(p for p in boxes_by_page
                      if any(_bucket(b.label) == bucket for b in boxes_by_page[p]))

    fn = pages_with("footnote")
    if fn:
        known = set(a.footnote_pages)
        agree = [p for p in fn if p in known]
        only = [p for p in fn if p not in known]
        w(f"- **Footnotes:** witness footnote regions on {fn}. Agree with "
          f"analyzer footnote_pages: {agree or 'none'}; witness-only (review): "
          f"{only or 'none'}.")
    hf = sorted(set(pages_with("header")) | set(pages_with("footer")))
    if hf:
        w(f"- **Running head/foot:** witness header/footer furniture on {hf}. "
          "Confirm your furniture strip removes these.")
    toc = pages_with("toc")
    if toc:
        w(f"- **Table of contents:** witness TOC region on {toc}; analyzer "
          f"toc_pages={a.toc_pages}. Reconcile toc.printed_pages / toc.source.")
    hd = pages_with("heading")
    if hd:
        tail = " …" if len(hd) > 20 else ""
        w(f"- **Section headers/titles:** witness heading boxes on {hd[:20]}{tail} "
          "— spot-check against your styles.pstyle_map roles.")
    if not (fn or hf or toc or hd):
        w("- _no furniture / footnote / heading / TOC signals on scanned pages._")


# --------------------------------------------------------------- benchmark

def stratified_sample(doc, a, k: int = 8) -> list[int]:
    """A complexity-spread page sample for the benchmark: table/image/footnote/
    figure pages (the slow tail) + densest + median-text + evenly spread."""
    picks: list[int] = []

    def add(p):
        if p and 1 <= p <= doc.n_pages and p not in picks:
            picks.append(p)

    add(a.column_suspect_pages[0] if a.column_suspect_pages else None)
    add(a.image_only_pages[0] if a.image_only_pages else None)
    add(a.footnote_pages[0] if a.footnote_pages else None)
    add(a.figure_pages_proposal[0] if a.figure_pages_proposal else None)
    by_chars = sorted(doc.pages, key=lambda p: p.n_chars)
    if by_chars:
        add(by_chars[-1].number)                    # densest
        add(by_chars[len(by_chars) // 2].number)    # median text
    n, i = doc.n_pages, 1
    while len(picks) < k and i <= n:
        add(i)
        i += max(1, n // k)
    return sorted(picks[:k])


def _p95(xs: list[float]) -> float:
    if not xs:
        return 0.0
    s = sorted(xs)
    return s[min(len(s) - 1, int(round(0.95 * (len(s) - 1))))]


def benchmark(pdf_path, pages, dpi: int = LAYOUT_DPI) -> dict:
    """Time the witness over `pages`; return model-load / per-page / RSS stats
    plus 100/300/500-page projections for the flagged-vs-all default call."""
    import resource
    import statistics
    timings: dict = {}
    run_layout_witness(pdf_path, pages, dpi, timings=timings)
    per = timings.get("pages", [])
    tot = [p["render_s"] + p["predict_s"] for p in per]
    stats = {
        "model": _MODEL_ID,
        "dpi": dpi,
        "n_pages": len(per),
        "model_load_s": timings.get("model_load_s"),
        "render_median_s": round(statistics.median(p["render_s"] for p in per), 3) if per else None,
        "predict_median_s": round(statistics.median(p["predict_s"] for p in per), 3) if per else None,
        "page_median_s": round(statistics.median(tot), 3) if tot else None,
        "page_p95_s": round(_p95(tot), 3) if tot else None,
        "page_max_s": round(max(tot), 3) if tot else None,
        "peak_rss_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0, 1),
    }
    if stats["page_median_s"]:
        for bk in (100, 300, 500):
            stats[f"proj_{bk}p_min"] = round(bk * stats["page_median_s"] / 60.0, 1)
    return stats
