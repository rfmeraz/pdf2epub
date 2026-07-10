"""Slice EPUB spine content by source page via the pagebreak anchors.

Anchor pairing is ORDINAL: the k-th `div epub:type="pagebreak"` in spine
document order is the k-th in-flow source page (labels collide across
roman/arabic folio sequences, so ids are never looked up). aria-labels are
only cross-checked; a count mismatch or repeated label drift returns
ok=False so every dependent typography check degrades to one info line
instead of false-firing on a slicing failure.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .qa_epubload import block_text

_X = "{http://www.w3.org/1999/xhtml}"
_E = "{http://www.idpf.org/2007/ops}"
_XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"

_BLOCK_TAGS = {"p", "h1", "h2", "h3", "h4", "li", "figcaption"}


@dataclass(slots=True)
class EpubBlock:
    tag: str
    classes: tuple[str, ...]
    in_blockquote: bool
    text: str
    letters: int = 0             # alpha chars, minus sup/sub and lang spans
    italic_letters: int = 0      # alpha chars inside <i>/<em>
    bold_letters: int = 0        # alpha chars inside <b>/<strong>
    sc_letters: int = 0          # alpha chars inside span.smallcaps
    lang_span_letters: int = 0   # alpha chars inside span[lang] (PUA readings)
    href: str = ""


@dataclass(slots=True)
class SliceResult:
    ok: bool
    detail: str = ""
    slices: dict[int, list[EpubBlock]] = field(default_factory=dict)
    preamble: list[EpubBlock] = field(default_factory=list)  # before 1st anchor


def _census(el, blk: EpubBlock, in_i=False, in_b=False, in_sup=False,
            in_sc=False, in_lang=False) -> None:
    tag = el.tag
    local = tag[len(_X):] if isinstance(tag, str) and tag.startswith(_X) else ""
    if local in ("i", "em"):
        in_i = True
    elif local in ("b", "strong"):
        in_b = True
    elif local in ("sup", "sub"):
        in_sup = True
    elif local == "span":
        if "smallcaps" in (el.get("class") or "").split():
            in_sc = True
        if el.get("lang") or el.get(_XML_LANG):
            in_lang = True

    def count(text: str | None) -> None:
        if not text:
            return
        # Latin-side alpha only (CJK is lang-span-wrapped when tagged; the
        # PDF side applies the same bound so fractions stay comparable)
        n = sum(1 for c in text if c.isalpha() and ord(c) < 0x2E80)
        if not n or in_sup:
            return
        if in_lang:
            blk.lang_span_letters += n
            return
        blk.letters += n
        if in_i:
            blk.italic_letters += n
        if in_b:
            blk.bold_letters += n
        if in_sc:
            blk.sc_letters += n

    count(el.text)
    for child in el:
        _census(child, blk, in_i, in_b, in_sup, in_sc, in_lang)
        count(child.tail)  # tails live in THIS element's context


def _make_block(el, href: str) -> EpubBlock:
    classes = tuple((el.get("class") or "").split())
    in_bq = False
    p = el.getparent()
    while p is not None:
        if p.tag == f"{_X}blockquote":
            in_bq = True
            break
        p = p.getparent()
    blk = EpubBlock(tag=el.tag[len(_X):], classes=classes, in_blockquote=in_bq,
                    text=block_text(el), href=href)
    _census(el, blk)
    return blk


def slice_pages(body_docs, in_flow: list[int],
                labels: dict[int, str]) -> SliceResult:
    res = SliceResult(ok=True)
    for pno in in_flow:
        res.slices[pno] = []
    k = -1                     # index into in_flow of the current page cursor
    extra_anchors = 0
    label_misses: list[str] = []
    for doc in body_docs:
        body = doc.root.find(f"{_X}body")
        if body is None:
            continue
        for el in body.iter():
            tag = el.tag
            if not isinstance(tag, str) or not tag.startswith(_X):
                continue
            local = tag[len(_X):]
            if (el.get(f"{_E}type") or "") == "pagebreak":
                k += 1
                if k >= len(in_flow):
                    extra_anchors += 1
                    continue
                want = labels.get(in_flow[k], str(in_flow[k]))
                got = el.get("aria-label") or ""
                if got != want:
                    label_misses.append(f"anchor {k}: label {got!r} != {want!r}")
            elif local in _BLOCK_TAGS:
                if local == "li" and any(
                        isinstance(c.tag, str) and c.tag == f"{_X}p"
                        for c in el):
                    # a blocks.lists item is a CONTAINER (li > p.lp…): its
                    # child paragraphs are the blocks; slicing the li too
                    # would double every item's text
                    continue
                blk = _make_block(el, doc.href)
                if k < 0:
                    res.preamble.append(blk)
                elif k < len(in_flow):
                    res.slices[in_flow[k]].append(blk)
    n_anchors = k + 1 + extra_anchors
    if n_anchors != len(in_flow) or len(label_misses) >= 3:
        res.ok = False
        res.detail = (f"{n_anchors} pagebreak anchors vs {len(in_flow)} in-flow "
                      f"pages; label mismatches: {len(label_misses)}"
                      + ("".join("; " + m for m in label_misses[:3])))
    return res
