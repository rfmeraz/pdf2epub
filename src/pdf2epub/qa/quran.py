"""Qurʾānic citation validation — gate 19.

A 'Qurʾānic verses cited' index is the one back-matter apparatus with a
fully checkable external structure: 114 suras with fixed verse counts
(Ḥafṣ/Kufan numbering — the numbering of virtually every modern printed
muṣḥaf and of scholarly indexes), entries sorted by (sura, verse), page
references drawn from the book's own page labels. Column interleaving —
the exact failure that shipped BoK's index garbled while both text-coverage
witnesses were blind (the columned pages are engine-disputed, so gate 2
excludes them) — produces impossible citations ('9318:67') and non-monotone
entry order, both of which this gate catches deterministically. Expect this
apparatus on most books in the corpus.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_X = "{http://www.w3.org/1999/xhtml}"
_HEADINGS = {f"{_X}h{i}" for i in range(1, 5)}

# Verse count per sura, Ḥafṣ/Kufan numbering (index 0 = sura 1).
# Total = 6236, the canonical count; pinned by a unit test.
SURA_VERSES = (
    7, 286, 200, 176, 120, 165, 206, 75, 129, 109,      # 1-10
    123, 111, 43, 52, 99, 128, 111, 110, 98, 135,       # 11-20
    112, 78, 118, 64, 77, 227, 93, 88, 69, 60,          # 21-30
    34, 30, 73, 54, 45, 83, 182, 88, 75, 85,            # 31-40
    54, 53, 89, 59, 37, 35, 38, 29, 18, 45,             # 41-50
    60, 49, 62, 55, 78, 96, 29, 22, 24, 13,             # 51-60
    14, 11, 11, 18, 12, 12, 30, 52, 52, 44,             # 61-70
    28, 28, 20, 56, 40, 31, 50, 40, 46, 42,             # 71-80
    29, 19, 36, 25, 22, 17, 19, 26, 30, 20,             # 81-90
    15, 21, 11, 8, 8, 19, 5, 8, 8, 11,                  # 91-100
    11, 8, 3, 9, 5, 4, 7, 3, 6, 3,                      # 101-110
    5, 4, 5, 6,                                         # 111-114
)

# 'Qurʾānic Verses Cited', 'Index of Qurʾanic Citations', 'Verses of the
# Qurʾān' … (ʾ/ʼ/’ and ā vary per book's transliteration scheme). The
# heading must name the Qurʾān — a plain 'Verses Cited' could index another
# scripture, whose refs this table can't judge.
HEADING_RE = re.compile(
    r"(qur.{0,4}n(ic)?\s+(verses|citations|passages|quotations))"
    r"|(verses\s+(cited|quoted)\s+from\s+the\s+qur)|(index\s+of\s+qur)", re.I)

# entry: 'S:V, pages' / 'S:V–V, pages' — pages are arabic or roman folios
_ENTRY_RE = re.compile(
    r"^(\d{1,4})\s*:\s*(\d{1,4})(?:\s*[–—-]\s*(\d{1,4}))?\s*[,.]?\s+(.+?)\.?$")
_PAGE_TOKEN_RE = re.compile(r"^(\d{1,4}|[ivxlcdm]{1,8})$")


@dataclass(slots=True)
class QuranIndexResult:
    found: bool = False
    n_entries: int = 0
    defects: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.defects

    @property
    def lines(self) -> list[str]:
        if not self.found:
            return ["no Qurʾānic verses index in the EPUB (heading scan)"]
        head = (f"{self.n_entries} entries under the Qurʾānic index heading; "
                f"{len(self.defects)} defects")
        return [head] + self.defects[:10] + (
            [f"… and {len(self.defects) - 10} more"]
            if len(self.defects) > 10 else [])


def _entry_texts(body_docs) -> tuple[bool, list[str]]:
    """Paragraph texts between the Qurʾānic-index heading and the next
    heading, in spine order."""
    collecting = False
    entries: list[str] = []
    for d in body_docs:
        for el in d.root.iter():
            if el.tag in _HEADINGS:
                text = "".join(el.itertext())
                if collecting:
                    return True, entries
                collecting = bool(HEADING_RE.search(text))
            elif collecting and el.tag == f"{_X}p":
                entries.append("".join(el.itertext()))
        if collecting:  # heading was the doc's last section
            return True, entries
    return collecting, entries


def check_quran_index(body_docs, page_labels: set[str]) -> QuranIndexResult:
    found, texts = _entry_texts(body_docs)
    res = QuranIndexResult(found=found)
    if not found:
        return res
    res.n_entries = len(texts)
    prev_key: tuple[int, int] | None = None
    for raw in texts:
        text = re.sub(r"\s+", " ", raw).strip()
        show = text[:60]
        m = _ENTRY_RE.match(text)
        if not m:
            res.defects.append(f"unparsable entry: {show!r}")
            continue
        sura, v0 = int(m.group(1)), int(m.group(2))
        v1 = int(m.group(3)) if m.group(3) else v0
        if not 1 <= sura <= 114:
            res.defects.append(f"no sura {sura}: {show!r}")
            continue
        if not 1 <= v0 <= v1 <= SURA_VERSES[sura - 1]:
            res.defects.append(
                f"sura {sura} has {SURA_VERSES[sura - 1]} verses, entry cites "
                f"{v0}" + (f"–{v1}" if v1 != v0 else "") + f": {show!r}")
            continue
        key = (sura, v0)
        if prev_key is not None and key < prev_key:
            res.defects.append(
                f"order violation: {sura}:{v0} after {prev_key[0]}:"
                f"{prev_key[1]} (column interleaving?): {show!r}")
        prev_key = key
        for tok in re.split(r",\s*", m.group(4).strip()):
            tok = tok.strip()
            if not _PAGE_TOKEN_RE.match(tok):
                res.defects.append(f"bad page ref {tok!r}: {show!r}")
            elif page_labels and tok not in page_labels:
                res.defects.append(f"cited page {tok!r} not in the "
                                   f"EPUB page-list: {show!r}")
    return res
