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
        if "italic" in family.lower():
            st.font_style = "Italic"
        flags = cfg.charstyles.get(family)
        if flags and flags.smallcaps:
            st.capitalization = "SmallCaps"
        catalog[pstyle] = st
    return catalog
