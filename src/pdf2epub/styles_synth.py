"""Synthetic style catalog: pstyle cluster names -> SynthStyle for the CSS
generator. A pstyle is 'Family@size[/center]'; values are already effective
(no BasedOn chains in a PDF)."""

from __future__ import annotations

from .core.emit_css import SynthStyle


def build_catalog(ctx) -> dict[str, SynthStyle]:
    cfg = ctx.cfg
    catalog: dict[str, SynthStyle] = {}
    for pstyle in set(ctx.flow.style_usage) | {cfg.body_pstyle}:
        if pstyle.startswith("__"):
            continue
        st = SynthStyle()
        base = pstyle
        if "/" in base:
            base, layout = base.split("/", 1)
            if layout == "center":
                st.justification = "CenterAlign"
                st.first_line_indent = 0.0
        try:
            family, size = base.rsplit("@", 1)
            st.point_size = float(size)
        except ValueError:
            family = base
        # NO font-style from the family name: run-level italics already carry
        # <i> (MuPDF italic flags cover 100% of italic-family chars on the
        # test corpus), and a class-level italic wrongly sweeps the roman
        # runs of MIXED paragraphs along (BoK p.xx: roman narration around an
        # italic Qurʾān quote rendered all-italic). QA gate 15 (emphasis
        # conservation) guards the inverse failure — an italic font whose
        # runs are NOT flagged would show up as lost italics.
        flags = cfg.charstyles.get(family)
        if flags and flags.smallcaps:
            st.capitalization = "SmallCaps"
        catalog[pstyle] = st
    return catalog
