# Forked from idml2epub src/idml2epub/qa/epubload.py @ 7eb7eac
"""Minimal EPUB loader for QA checks (zip + OPF + parsed spine docs)."""

from __future__ import annotations

import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from lxml import etree

_OPF_NS = "{http://www.idpf.org/2007/opf}"
_CNT_NS = "{urn:oasis:names:tc:opendocument:xmlns:container}"
_XHTML = "{http://www.w3.org/1999/xhtml}"
_OPS_NS = "{http://www.idpf.org/2007/ops}"


@dataclass
class EpubDoc:
    href: str  # OPF-relative
    root: etree._Element

    def ids(self) -> set[str]:
        return {el.get("id") for el in self.root.iter() if el.get("id")}

    def is_endnotes(self) -> bool:
        """True only for the generated endnotes file, which carries
        ``<section epub:type="endnotes">``. Keyed on that structural marker,
        NOT a filename substring: back-matter *sections* whose title merely
        contains 'Notes' (e.g. 'Editor's Notes', 'Biographical Notes') are
        body content and must stay in the coverage/typography scope."""
        for el in self.root.iter():
            if isinstance(el.tag, str) and el.get(f"{_OPS_NS}type") == "endnotes":
                return True
        return False

    def text(self) -> str:
        body = self.root.find(f"{_XHTML}body")
        if body is None:
            return ""
        for nav in body.iter(f"{_XHTML}nav"):
            nav.getparent().remove(nav)
        return " ".join(body.itertext())


@dataclass
class LoadedEpub:
    path: Path
    zf: zipfile.ZipFile
    opf_dir: PurePosixPath
    manifest: dict[str, dict]  # id -> {href, media_type, properties}
    spine: list[str]  # manifest ids in order
    docs: dict[str, EpubDoc] = field(default_factory=dict)  # href -> doc

    def resolve(self, href: str) -> str:
        return str((self.opf_dir / href))

    def read(self, href: str) -> bytes:
        return self.zf.read(self.resolve(href))

    def doc(self, href: str) -> EpubDoc | None:
        href = href.split("#")[0]
        if href in self.docs:
            return self.docs[href]
        try:
            root = etree.fromstring(self.read(href))
        except (KeyError, etree.XMLSyntaxError):
            return None
        d = EpubDoc(href, root)
        self.docs[href] = d
        return d

    def spine_docs(self) -> list[EpubDoc]:
        out = []
        for sid in self.spine:
            item = self.manifest.get(sid)
            if item and item["media_type"] == "application/xhtml+xml":
                d = self.doc(item["href"])
                if d is not None:
                    out.append(d)
        return out

    def nav_doc(self) -> EpubDoc | None:
        for item in self.manifest.values():
            if "nav" in item["properties"]:
                return self.doc(item["href"])
        return None


def load_epub(path: Path) -> LoadedEpub:
    zf = zipfile.ZipFile(path)
    container = etree.fromstring(zf.read("META-INF/container.xml"))
    opf_path = container.find(f".//{_CNT_NS}rootfile").get("full-path")
    opf_dir = PurePosixPath(opf_path).parent
    opf = etree.fromstring(zf.read(opf_path))
    manifest: dict[str, dict] = {}
    for item in opf.iter(f"{_OPF_NS}item"):
        manifest[item.get("id")] = {
            "href": item.get("href"),
            "media_type": item.get("media-type"),
            "properties": (item.get("properties") or "").split(),
        }
    spine = [ref.get("idref") for ref in opf.iter(f"{_OPF_NS}itemref")]
    return LoadedEpub(path=path, zf=zf, opf_dir=opf_dir, manifest=manifest,
                      spine=spine, docs={})


def opf_metadata(ep: LoadedEpub) -> etree._Element:
    container = etree.fromstring(ep.zf.read("META-INF/container.xml"))
    opf_path = container.find(f".//{_CNT_NS}rootfile").get("full-path")
    return etree.fromstring(ep.zf.read(opf_path))
