# Forked from idml2epub src/idml2epub/mapping/styles.py @ 7eb7eac (pure parts only;
# the IDML style-catalog heuristics were dropped — pdf2epub derives roles from font
# clusters in analyze.py instead of named InDesign styles)
"""Apply semantic roles to paragraphs from a pstyle -> rule map (JP-P1).

The per-book config's pstyle_map always wins; unmapped pstyles get
``unmapped_role`` and are reported (an error once ``fail_on_unmapped`` is set).

Roles: h1 h2 h3 p li blockquote footnote toc-entry title-page half-title
caption drop index

``index`` marks a single-column back-of-book index entry so the index-locator
pass links its page numbers (the columned-index case uses the
``flow.columns[].index`` flag instead; see src/pdf2epub/index_locators.py).
Emission treats ``index`` like a plain ``<p>`` (generic fall-through).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .model import Paragraph


@dataclass(slots=True)
class StyleRule:
    role: str
    class_: str | None = None


@dataclass(slots=True)
class RoleGuess:
    role: str
    confidence: str  # high | medium | low
    reason: str


def apply_roles(blocks, style_map: dict[str, StyleRule], unmapped_role: str) -> list[str]:
    """Set role/classes on every Paragraph. Returns styles that had no rule."""
    unmapped: set[str] = set()
    for b in blocks:
        if not isinstance(b, Paragraph):
            continue
        rule = style_map.get(b.style)
        if rule is None:
            unmapped.add(b.style)
            b.role = unmapped_role
        else:
            b.role = rule.role
        css = re.sub(r"[^A-Za-z0-9_-]+", "-", b.style).strip("-")
        b.classes = [css] + ([rule.class_] if rule and rule.class_ else [])
    return sorted(unmapped)
