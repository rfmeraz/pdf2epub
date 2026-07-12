# Forked from idml2epub src/idml2epub/qa/textdiff.py @ 7eb7eac
"""PDF-vs-flow (or EPUB) text coverage: both sides share textnorm.normalize.

Coverage = fraction of the PDF's normalized text that appears in the candidate
text, computed with difflib matching blocks. Reports every missing segment
longer than a threshold so a human can see *what* dropped, not just a number.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from difflib import SequenceMatcher


@dataclass(slots=True)
class CoverageResult:
    pdf_chars: int
    matched_chars: int
    missing_segments: list[str] = field(default_factory=list)
    # per-page diagnostics for the fidelity gate (25): one tuple per non-blank
    # source page, in reading order — (pno, matched_chars, page_len,
    # candidate_start). candidate_start is the actual best-match offset in the
    # candidate, so gate 25 can test start-monotonicity (reorder witness).
    per_page: list[tuple[int, int, int, int]] = field(default_factory=list)

    @property
    def coverage(self) -> float:
        return self.matched_chars / self.pdf_chars if self.pdf_chars else 1.0


def coverage(pdf_text: str, candidate_text: str, min_segment: int = 20) -> CoverageResult:
    """How much of pdf_text is present (in order) in candidate_text."""
    sm = SequenceMatcher(None, pdf_text, candidate_text, autojunk=False)
    matched = 0
    missing: list[str] = []
    prev_end = 0
    for block in sm.get_matching_blocks():
        gap = pdf_text[prev_end : block.a]
        if len(gap.strip()) >= min_segment:
            missing.append(gap.strip())
        matched += block.size
        prev_end = block.a + block.size
    return CoverageResult(
        pdf_chars=len(pdf_text), matched_chars=matched, missing_segments=missing
    )
