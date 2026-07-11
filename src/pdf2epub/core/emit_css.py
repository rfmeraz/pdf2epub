# Forked from idml2epub src/idml2epub/emit/css.py @ 7eb7eac (catalog is passed in
# as a dict of SynthStyle instead of being loaded from an IDML file)
"""Generate the stylesheet from applied styles only.

Sizes, alignment, spacing, and indents come from the synthetic style catalog
built out of the PDF font clusters (styles_synth.py), expressed in em relative
to the body point size. Language-specific font stacks use :lang() selectors
plus class fallbacks (.zh/.ar/...) for readers with weak :lang() support.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(slots=True)
class SynthStyle:
    """Pre-resolved style properties for one pstyle cluster.

    Mirrors the surface of idml2epub's ParaStyleDef that the CSS loop reads,
    but values are already effective — there is no BasedOn chain in a PDF.
    """

    point_size: float | None = None
    justification: str | None = None   # CenterAlign | RightAlign | LeftAlign | ...
    space_before: float | None = None
    space_after: float | None = None
    first_line_indent: float | None = None
    font_style: str | None = None      # "Italic"
    capitalization: str | None = None  # "SmallCaps"

    def effective(self, catalog, key):
        return getattr(self, key)


def _css_class(style_name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "-", style_name).strip("-")


_JUSTIFY = {
    "LeftJustified": "justify",
    "FullyJustified": "justify",
    "RightJustified": "justify",
    "CenterJustified": "justify",
    "CenterAlign": "center",
    "RightAlign": "right",
    "LeftAlign": "left",
}

_BASE = """\
html, body { margin: 0; padding: 0; }
body {
  font-family: {latin_stack};
  line-height: 1.4;
  -epub-hyphens: auto;
}
p { margin: 0; text-indent: 1.2em; text-align: justify; }
p.first, p.first-dropcap { text-indent: 0; }
p.first-dropcap::first-letter {
  float: left; font-size: 2.6em; line-height: 1;
  margin: 0 0.06em 0 0; padding-top: 0.05em;
}
h1, h2, h3 { font-weight: normal; text-align: center; page-break-after: avoid; }
blockquote { margin: 0.7em 2em; }
blockquote p { text-indent: 0; }
blockquote.verse { margin: 1em 2.5em; }
blockquote.quote { margin: 0.7em 1.6em; }
blockquote.epigraph { margin: 1.2em 2.2em; }
p.bq { text-indent: 0; margin: 0.4em 0; }
ol.plist, ul.plist { list-style: none; margin: 0.7em 0; padding: 0 0 0 1.4em; }
li.li1 { margin: 0.25em 0; }
p.lp { text-indent: 0; margin: 0; }
p.lpc { text-indent: 0.8em; margin: 0.15em 0 0 0; }
p.vs { text-indent: 0; text-align: left; margin: 0.8em 0; }
p.vs span.vl { display: block; padding-left: 1.5em; text-indent: -1.5em; }
p.vs span.vt { padding-left: 3em; }
p.vs br { display: none; }
p.listpara { text-indent: 0; margin-left: 1.5em; }
p.caption { text-indent: 0; text-align: center; font-size: 0.9em; margin: 0.5em 0; }
p.titletext { text-indent: 0; text-align: center; }
p.toc-entry { text-indent: 0; margin: 0.3em 0; }
p.toc-entry a { text-decoration: none; color: inherit; }
h1.contents-head { margin-bottom: 1em; }
div.pagebreak { height: 0; margin: 0; padding: 0; }
figure.figure { margin: 1em auto; text-align: center; page-break-inside: avoid; }
figure.figure img { max-width: 100%; height: auto; }
div.figure { text-align: center; margin: 0.8em auto; }
div.figure img { max-width: 30%; height: auto; }
div.chinese-page { text-align: center; margin: 0; page-break-inside: avoid; }
div.chinese-page img { max-width: 100%; max-height: 95vh; height: auto; }
ol.notes { margin: 1em 0 1em 1.5em; padding: 0; }
ol.notes li { margin-bottom: 0.6em; }
ol.notes p { text-indent: 0; text-align: left; }
a.noteref { text-decoration: none; }
a.backlink { text-decoration: none; }
a.xref { text-decoration: none; color: inherit; }
span.smallcaps { font-variant: small-caps; }
"""


def generate_css(cfg, catalog: dict[str, SynthStyle], used_styles: set[str],
                 fontfaces: list[dict]) -> str:
    body = catalog.get(cfg.body_style)
    body_size = (body.effective(catalog, "point_size") if body else None) or 11.0

    latin_families = [ff["family"] for ff in fontfaces if ff.get("script") == "latin"]
    cjk_families = {ff.get("lang"): ff["family"] for ff in fontfaces if ff.get("script") == "cjk"}
    latin_stack = ", ".join(f'"{f}"' for f in dict.fromkeys(latin_families)) or "serif"

    out = []
    for ff in fontfaces:
        out.append(
            "@font-face {\n"
            f'  font-family: "{ff["family"]}";\n'
            f"  font-style: {ff.get('style', 'normal')};\n"
            f"  font-weight: normal;\n"
            f'  src: url("../font/{ff["file"]}");\n'
            "}"
        )
    out.append(_BASE.replace("{latin_stack}", f"{latin_stack}, serif"))

    # per-style rules from the catalog
    for name in sorted(used_styles):
        st = catalog.get(name)
        if st is None:
            continue
        props: list[str] = []
        size = st.effective(catalog, "point_size")
        if size and abs(size - body_size) > 0.2:
            props.append(f"font-size: {size / body_size:.3f}em")
        just = st.effective(catalog, "justification")
        if just and just in _JUSTIFY and _JUSTIFY[just] != "justify":
            props.append(f"text-align: {_JUSTIFY[just]}")
        sb = st.effective(catalog, "space_before")
        sa = st.effective(catalog, "space_after")
        if sb:
            props.append(f"margin-top: {sb / body_size:.2f}em")
        if sa:
            props.append(f"margin-bottom: {sa / body_size:.2f}em")
        fli = st.effective(catalog, "first_line_indent")
        if fli is not None and fli == 0:
            props.append("text-indent: 0")
        if st.effective(catalog, "font_style") == "Italic":
            props.append("font-style: italic")
        if st.effective(catalog, "capitalization") in ("SmallCaps", "CapToSmallCap"):
            props.append("font-variant: small-caps")
        if props:
            out.append(f".{_css_class(name)} {{ {'; '.join(props)}; }}")

    # language font stacks (+ class fallback)
    for lang, family in sorted(cjk_families.items()):
        if not lang:
            continue
        out.append(
            f':lang({lang}), span.{lang} {{ font-family: "{family}", '
            f"{latin_stack}, serif; }}"
        )
    return "\n".join(out) + "\n"
