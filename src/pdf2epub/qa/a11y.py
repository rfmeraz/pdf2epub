"""Gate 26 — accessibility readiness (automated portion only).

Automated readiness ≠ a WCAG conformance CLAIM: Ace explicitly cannot verify
alt-text *appropriateness*, reading-order sense, or table semantics, and
DAISY/W3C require a MANUAL inspection of the complete publication before
asserting conformance. So this gate checks the machine-checkable floor — alt
coverage, the accessibility metadata block, and Ace critical/serious — and does
NOT emit `dcterms:conformsTo` (deferred to the recorded manual-certification
workflow). See specs/semantic-polish.md #2.

Alt rule is STRICTER than qa_imagecheck's (which treats any alt="" as
decorative): a readiness claim requires each image to carry role="presentation"
(or epub:type decorative) OR non-empty alt.
"""

from __future__ import annotations

from ..core.qa_epubload import opf_metadata
from .ace import run_ace

_X = "{http://www.w3.org/1999/xhtml}"
_OPS = "{http://www.idpf.org/2007/ops}"

_NEEDED_META = ["schema:accessMode", "schema:accessModeSufficient",
                "schema:accessibilityFeature", "schema:accessibilityHazard"]


def _images_missing_alt(ep) -> list[str]:
    bad: list[str] = []
    for d in ep.spine_docs():
        for img in d.root.iter(f"{_X}img"):
            role = img.get("role") or ""
            etype = img.get(f"{_OPS}type") or ""
            decorative = role == "presentation" or "decorative" in etype
            alt = img.get("alt")
            if not decorative and not (alt and alt.strip()):
                bad.append(f"{d.href}: {img.get('src', '?')}")
    return bad


def check_a11y(ep, cfg) -> tuple[bool, list[str]]:
    root = opf_metadata(ep)
    props = {m.get("property") for m in root.iter("{*}meta") if m.get("property")}
    missing_meta = [p for p in _NEEDED_META if p not in props]
    has_summary = "schema:accessibilitySummary" in props
    has_source = any(e.tag.endswith("}source") for e in root.iter())

    bad_alt = _images_missing_alt(ep)
    ace_ok, ace_lines = run_ace(ep.path)

    ok = not bad_alt and not missing_meta and ace_ok is not False
    lines = [f"alt {'OK' if not bad_alt else f'FAIL({len(bad_alt)})'}; "
             f"metadata {'OK' if not missing_meta else 'FAIL'}; "
             f"ace {'skipped' if ace_ok is None else ('pass' if ace_ok else 'FAIL')}"]
    if bad_alt:
        lines.append(f"images missing alt/role=presentation: {bad_alt[:6]}")
    if missing_meta:
        lines.append(f"missing accessibility metadata: {missing_meta}")
    if cfg.isbn_print and not has_source:
        lines.append("advisory: dc:source (print-ISBN pagination source) absent")
    if not has_summary:
        lines.append("advisory: schema:accessibilitySummary absent "
                     "(agent-authored per book; not gating)")
    lines += ace_lines
    return ok, lines
