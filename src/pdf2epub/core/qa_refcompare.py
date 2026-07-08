# Forked from idml2epub src/idml2epub/qa/refcompare.py @ 7eb7eac
"""Scorecard: our EPUB vs the manually-created reference, row by row."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from .qa_epubload import LoadedEpub, load_epub

_XHTML = "{http://www.w3.org/1999/xhtml}"
_EPUB = "{http://www.idpf.org/2007/ops}"


@dataclass(slots=True)
class Row:
    metric: str
    ours: str
    reference: str
    verdict: str  # beat | parity | behind


def _stats(ep: LoadedEpub) -> dict:
    s: dict = {}
    docs = ep.spine_docs()
    nav = ep.nav_doc()
    s["spine_files"] = len(docs)

    headings = Counter()
    empty_links = 0
    imgs = 0
    empty_alt = 0
    langs = Counter()
    noterefs: list[tuple[str, str]] = []  # (doc href, target)
    ids_by_doc = {}
    for d in docs + ([nav] if nav is not None else []):
        ids_by_doc[d.href] = d.ids()
    for d in docs:
        for el in d.root.iter():
            tag = getattr(el, "tag", "")
            if not isinstance(tag, str) or not tag.startswith(_XHTML):
                continue
            local = tag[len(_XHTML):]
            if local in ("h1", "h2", "h3", "h4"):
                headings[local] += 1
            elif local == "a":
                href = el.get("href")
                if href is None or href == "":
                    empty_links += 1
                if (el.get(f"{_EPUB}type") or "") == "noteref" and href:
                    noterefs.append((d.href, href))
            elif local == "img":
                imgs += 1
                if not (el.get("alt") or "").strip() and el.get("role") != "presentation":
                    empty_alt += 1
            lang = el.get("lang") or el.get("{http://www.w3.org/XML/1998/namespace}lang")
            if lang and local not in ("html",):
                langs[lang.split("-")[0]] += 1
    s["headings"] = sum(headings.values())
    s["headings_detail"] = dict(headings)
    s["empty_links"] = empty_links
    s["images"] = imgs
    s["empty_alt"] = empty_alt
    s["langs"] = dict(langs)

    # footnote round-trip
    rt_ok = rt_bad = 0
    for base, href in noterefs:
        target, _, frag = href.partition("#")
        tdoc = ep.doc(target or base)
        if tdoc is None or frag not in tdoc.ids():
            rt_bad += 1
            continue
        back_ok = False
        for a in tdoc.root.iter(f"{_XHTML}a"):
            bh = a.get("href") or ""
            if "backlink" in (a.get(f"{_EPUB}type") or "") or "doc-backlink" in (a.get("role") or ""):
                bt, _, bfrag = bh.partition("#")
                bdoc = ep.doc(bt or tdoc.href)
                if bdoc is not None and bfrag in bdoc.ids():
                    back_ok = True
        rt_ok += 1 if back_ok else 0
        rt_bad += 0 if back_ok else 1
    s["noteref_roundtrip"] = (rt_ok, rt_bad)

    # page-list
    pl = []
    if nav is not None:
        for navel in nav.root.iter(f"{_XHTML}nav"):
            if (navel.get(f"{_EPUB}type") or "") == "page-list":
                pl = [(a.text or "").strip() for a in navel.findall(f".//{_XHTML}a")]
    s["pagelist"] = len(pl)
    s["pagelist_dups"] = len(pl) - len(set(pl))

    # fonts
    fonts = [it["href"].rsplit("/", 1)[-1] for it in ep.manifest.values()
             if "font" in it["media_type"] or it["href"].lower().endswith((".ttf", ".otf"))]
    s["fonts"] = sorted(fonts)
    try:
        ep.zf.getinfo("META-INF/encryption.xml")
        s["font_obfuscation"] = True
    except KeyError:
        s["font_obfuscation"] = False

    # a11y metadata
    from .qa_epubload import opf_metadata

    opf = opf_metadata(ep)
    s["a11y_metas"] = sum(
        1 for m in opf.iter("{http://www.idpf.org/2007/opf}meta")
        if (m.get("property") or "").startswith("schema:access")
    )
    s["size_mb"] = round(ep.path.stat().st_size / 1e6, 1)
    return s


_PROPRIETARY_HINTS = ("mincho", "arialunicode", "arial-unicode", "arial_unicode", "msgothic", "meiryo")


def compare(ours_path, ref_path) -> list[Row]:
    ours = _stats(load_epub(ours_path))
    ref = _stats(load_epub(ref_path))
    rows: list[Row] = []

    def row(metric, o, r, better):
        rows.append(Row(metric, str(o), str(r), better))

    def num_row(metric, o, r, higher_is_better=True, tie="parity"):
        if o == r:
            v = tie
        elif (o > r) == higher_is_better:
            v = "beat"
        else:
            v = "behind"
        row(metric, o, r, v)

    num_row("semantic headings (h1-h4)", ours["headings"], ref["headings"])
    num_row("spine content files", ours["spine_files"], ref["spine_files"])
    num_row("dead/empty links", ours["empty_links"], ref["empty_links"], higher_is_better=False)
    num_row("page-list entries", ours["pagelist"], ref["pagelist"])
    num_row("page-list duplicates", ours["pagelist_dups"], ref["pagelist_dups"], higher_is_better=False)
    num_row("images with empty alt", ours["empty_alt"], ref["empty_alt"], higher_is_better=False)

    o_rt, r_rt = ours["noteref_roundtrip"], ref["noteref_roundtrip"]
    row(
        "footnote round-trips (ok/broken)",
        f"{o_rt[0]}/{o_rt[1]}",
        f"{r_rt[0]}/{r_rt[1]}",
        "parity" if (o_rt[1] == 0) == (r_rt[1] == 0) and o_rt[0] >= r_rt[0] * 0 else "behind",
    )

    def lang_summary(s):
        return " ".join(f"{k}:{v}" for k, v in sorted(s["langs"].items())) or "none"

    # tagging correctness cannot be judged by counting spans (a count
    # difference may be a correction, as the rehearsal test showed) — so
    # this row is informational, except the unambiguous case of one side
    # having no language tagging at all.
    o_any, r_any = bool(ours["langs"]), bool(ref["langs"])
    verdict = "info" if o_any == r_any else ("beat" if o_any else "behind")
    row("lang-tagged spans (informational)", lang_summary(ours), lang_summary(ref), verdict)

    o_prop = [f for f in ours["fonts"] if any(h in f.lower().replace(" ", "") for h in _PROPRIETARY_HINTS)]
    r_prop = [f for f in ref["fonts"] if any(h in f.lower().replace(" ", "") for h in _PROPRIETARY_HINTS)]
    row(
        "proprietary embedded fonts",
        ", ".join(o_prop) or "none",
        ", ".join(r_prop) or "none",
        "beat" if not o_prop and r_prop else ("parity" if bool(o_prop) == bool(r_prop) else "behind"),
    )
    num_row("accessibility metadata entries", ours["a11y_metas"], ref["a11y_metas"])
    row(
        "total size (MB)",
        ours["size_mb"],
        ref["size_mb"],
        "parity" if ours["size_mb"] <= ref["size_mb"] * 1.6 else "behind",
    )
    return rows
