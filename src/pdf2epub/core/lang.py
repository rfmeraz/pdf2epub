# Forked from idml2epub src/idml2epub/mapping/lang.py @ 7eb7eac
"""CJK language tagging (JP-3).

The IDML mis-tags everything as Japanese, so language is derived from the
script itself: each maximal CJK cluster inside a paragraph is tagged ``ja`` if
it contains any kana, otherwise the configured Han-only language (default
``zh``). TextRuns are split so each cluster carries its own ``lang``.
"""

from __future__ import annotations

import re
from collections import Counter

from .model import FlowDoc, Paragraph, TextRun

_KANA = r"぀-ヿㇰ-ㇿ"
_HAN = r"㐀-䶿一-鿿豈-﫿"
_CJK_PUNCT = r"　-〿＀-￯・"
_CJK_CLUSTER = re.compile(f"[{_KANA}{_HAN}][{_KANA}{_HAN}{_CJK_PUNCT}]*")
_HAS_KANA = re.compile(f"[{_KANA}]")


# right-to-left scripts (Hebrew, Arabic + supplements/presentation forms,
# Syriac). Live RTL text is not converted yet — only detected, so the build
# warns instead of silently emitting text with the wrong layout direction.
_RTL = re.compile(
    "["
    "֐-׿"  # Hebrew
    "؀-ۿݐ-ݿࢠ-ࣿ"  # Arabic + supplements
    "܀-ݏ"  # Syriac
    "יִ-ﭏﭐ-﷿ﹰ-﻿"  # presentation forms
    "]"
)


def count_rtl_chars(doc: FlowDoc) -> int:
    """Number of right-to-left-script characters in the flow (incl. notes)."""
    n = 0
    for b in doc.blocks:
        if isinstance(b, Paragraph):
            n += sum(len(_RTL.findall(it.text)) for it in b.items if isinstance(it, TextRun))
    for note in doc.notes.values():
        for p in note.paragraphs:
            n += sum(len(_RTL.findall(it.text)) for it in p.items if isinstance(it, TextRun))
    return n


def _split_run(run: TextRun, han_lang: str) -> list[TextRun]:
    text = run.text
    out: list[TextRun] = []
    pos = 0
    for m in _CJK_CLUSTER.finditer(text):
        if m.start() > pos:
            out.append(TextRun(text=text[pos : m.start()], fmt=run.fmt))
        cluster = m.group(0)
        lang = "ja" if _HAS_KANA.search(cluster) else han_lang
        fmt = type(run.fmt)(**{f: getattr(run.fmt, f) for f in run.fmt.__dataclass_fields__})
        fmt.lang = lang
        out.append(TextRun(text=cluster, fmt=fmt))
        pos = m.end()
    if pos < len(text):
        out.append(TextRun(text=text[pos:], fmt=run.fmt))
    return out if out else [run]


def _tag_paragraph(p: Paragraph, han_lang: str, census: Counter) -> None:
    new_items = []
    for item in p.items:
        if isinstance(item, TextRun) and _CJK_CLUSTER.search(item.text):
            parts = _split_run(item, han_lang)
            for part in parts:
                if part.fmt.lang:
                    census[part.fmt.lang] += 1
            new_items.extend(parts)
        else:
            new_items.append(item)
    p.items = new_items


def tag_languages(doc: FlowDoc, han_lang: str, overrides: list[dict]) -> dict[str, int]:
    """Tag CJK clusters in all paragraphs and notes. Returns cluster census."""
    census: Counter = Counter()
    for b in doc.blocks:
        if isinstance(b, Paragraph):
            _tag_paragraph(b, han_lang, census)
    for note in doc.notes.values():
        for p in note.paragraphs:
            _tag_paragraph(p, han_lang, census)

    # explicit per-paragraph overrides: {story: uXXX, para: N, lang: ja}
    if overrides:
        by_story: dict[tuple[str, int], str] = {
            (o["story"], int(o["para"])): o["lang"] for o in overrides
        }
        for b in doc.blocks:
            if not isinstance(b, Paragraph):
                continue
            want = by_story.get((b.src.story_id, b.src.psr_index))
            if want:
                for item in b.items:
                    if isinstance(item, TextRun) and item.fmt.lang:
                        item.fmt.lang = want
    return dict(census)
