# Forked from idml2epub src/idml2epub/qa/imagecheck.py @ 7eb7eac
"""Image inventory + alt-text audit."""

from __future__ import annotations

from dataclasses import dataclass, field

from .qa_epubload import LoadedEpub

_XHTML = "{http://www.w3.org/1999/xhtml}"


@dataclass
class ImageResult:
    manifest_images: int = 0
    referenced: int = 0
    unresolved_srcs: list[str] = field(default_factory=list)
    orphans: list[str] = field(default_factory=list)
    empty_alt_content: list[str] = field(default_factory=list)  # non-decorative w/o alt
    total_bytes: int = 0

    @property
    def ok(self) -> bool:
        return not self.unresolved_srcs and not self.empty_alt_content


def check_images(ep: LoadedEpub) -> ImageResult:
    res = ImageResult()
    manifest_hrefs = {
        it["href"]: it for it in ep.manifest.values()
        if it["media_type"].startswith("image/")
    }
    res.manifest_images = len(manifest_hrefs)
    for href, it in manifest_hrefs.items():
        try:
            res.total_bytes += len(ep.read(href))
        except KeyError:
            res.unresolved_srcs.append(f"manifest item missing from zip: {href}")

    used: set[str] = set()
    nav = ep.nav_doc()
    docs = ep.spine_docs() + ([nav] if nav is not None else [])
    seen = set()
    for doc in docs:
        if doc.href in seen:
            continue
        seen.add(doc.href)
        base = doc.href.rsplit("/", 1)[0] + "/" if "/" in doc.href else ""
        for img in doc.root.iter(f"{_XHTML}img"):
            src = img.get("src") or ""
            norm = src if not base else base + src
            # normalize ../
            parts: list[str] = []
            for seg in norm.split("/"):
                if seg == "..":
                    if parts:
                        parts.pop()
                elif seg != ".":
                    parts.append(seg)
            norm = "/".join(parts)
            if norm not in manifest_hrefs:
                res.unresolved_srcs.append(f"{doc.href}: img src not in manifest: {src}")
            else:
                used.add(norm)
            alt = img.get("alt")
            decorative = (img.get("role") == "presentation") or alt == ""
            if alt is None or (not decorative and not alt.strip()):
                res.empty_alt_content.append(f"{doc.href}: {src}")
    res.referenced = len(used)
    cover_hrefs = {
        it["href"] for it in ep.manifest.values() if "cover-image" in it["properties"]
    }
    res.orphans = sorted(set(manifest_hrefs) - used - cover_hrefs)
    return res
