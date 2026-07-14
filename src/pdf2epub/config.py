"""Per-book configuration (book.yaml): metadata + all per-book judgment points.

The schema records the JP-P1..P8 judgments the conversion agent makes; a build
is a pure function of (source PDF, this file). Unknown keys are ERRORS — a
typo'd judgment silently ignored is worse than a failed build.

Duck-type contract: the forked core/ modules read these attributes off cfg:
title, subtitle, creators, publisher, language, additional_languages,
isbn_epub, isbn_print, date, cover, accessibility_summary, slug, include_ncx,
split_at_roles, warn_over_files, toc_handling, strip_toc_page_numbers,
fonts_subset, body_style (alias of styles.body_pstyle), build_dir,
resolve_workspace().
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from .core.roles import StyleRule

if TYPE_CHECKING:
    from .imprints import ImprintSpec


class ConfigError(Exception):
    pass


@dataclass(slots=True)
class PageRange:
    first: int
    last: int

    def __contains__(self, page: int) -> bool:
        return self.first <= page <= self.last


@dataclass(slots=True)
class RoleOverride:
    page: int
    role: str
    class_: str | None = None


@dataclass(slots=True)
class FlowOverride:
    page: int
    line: int  # RAW extraction line index within the page (see ir/extract.json)
    action: str  # join | break | drop | keep | role:<role>
    note: str = ""


@dataclass(slots=True)
class ColumnSpec:
    """Pages set in N print columns (tabular back matter: indexes, verse
    tables). The flow re-splits baseline-fused lines at the column gutters
    and reads column-by-column; every column-left line starts its own entry
    paragraph, indented lines are hanging-indent turnovers that join.
    Columned PROSE is still out of scope (escalate per the skill).

    ``index: true`` marks this columned block as a back-of-book index whose
    page-number locators the index-locator pass links to ``#pg-<label>``
    anchors (opt-in; see src/pdf2epub/index_locators.py)."""
    pages: list[int]
    count: int
    note: str = ""
    index: bool = False


@dataclass(slots=True)
class VerseSpec:
    """Semantic block judgment: pages carrying verse set at known indent
    levels. ``base``/``turns`` are pt offsets of verse-line starts from the
    page's SHIFT-CORRECTED column left (recto/verso binding shift removed).
    Two print conventions exist on this corpus: M&R-style TWO-LEVEL verse
    (turns = the deeper level(s) a couplet's second line drops to — an
    alternation prose never produces) and I&B-style SINGLE-LEVEL verse
    (every line at one inset, ragged right; turns empty/omitted — the
    ragged-right requirement then carries the discrimination).
    The deterministic classifier does the per-block work inside these pages;
    ``note`` records the render evidence and is REQUIRED. A spec that
    classifies ZERO groups is stale and fails the build (flow.overrides
    doctrine). Per-line corrections: flow.overrides ``class:verse`` /
    ``class:prose``."""
    pages: list[int]
    base: list[float]
    turns: list[float] = field(default_factory=list)
    tol: float = 2.0
    stanza_gap: float = 1.4  # × median leading opens a new stanza
    note: str = ""


@dataclass(slots=True)
class QuoteSpec:
    """Semantic block judgment: pages carrying print block quotes — JUSTIFIED
    inset blocks (the opposite signal of ragged verse). ``left_inset`` /
    ``right_inset`` are pt offsets of the quote block's edges from the page's
    OWN body-block edges (blockshapes.body_anchors — NOT the modal column:
    on quote-heavy pages the shift detector keys off the quote inset itself).
    I&B: 18/18 both sides; BoK: 36 left only (right_inset 0 = the body
    margin). Classification stamps block_class only; JOIN DECISIONS ARE
    UNTOUCHED — the flow's paragraphs are identical with or without the spec,
    they just emit inside a real <blockquote>. ``note`` records the render
    evidence and is REQUIRED; a spec that classifies ZERO runs is stale and
    fails the build. Per-line corrections: flow.overrides ``class:quote`` /
    ``class:prose``."""
    pages: list[int]
    left_inset: float = 0.0
    right_inset: float = 0.0
    tol: float = 3.0
    note: str = ""


@dataclass(slots=True)
class ListSpec:
    """Semantic block judgment: pages carrying print lists — marker lines
    (``decimal`` "1." / "43.Necessary" / "10.·…"; ``bullet`` "• …") at one
    shared entry x0, with hanging-indent turnovers ``hang`` pt deeper (0 =
    flat, I&B-style). Entry lines always BREAK (healing note-fusions) and
    hang-column turnovers always JOIN their item (healing the first-line
    splits M&R's notes apparatus shipped with); lines at other insets —
    sub-lemma paragraphs with their own first-line indent — keep the
    geometric rules and stay separate paragraphs INSIDE the item. Items
    ship as real <ol>/<ul> + <li>, printed markers KEPT in the text
    (never-rewrite; exact coverage) with list-style:none. Entry stops are
    derived PER SPEC by clustering the marker lines' x0 across the spec's
    pages (the flow.columns precedent) — recto/verso binding shifts yield
    two stops, and stray marker look-alikes (a wrapped line opening with a
    year) fall below the cluster threshold. ``note``
    records the render evidence and is REQUIRED; a spec that classifies
    ZERO items is stale and fails the build. Per-line corrections:
    flow.overrides ``class:list`` / ``class:prose``."""
    pages: list[int]
    marker: str = "decimal"   # decimal | bullet
    hang: float = 0.0
    tol: float = 3.0
    note: str = ""


@dataclass(slots=True)
class HeadingAllow:
    """A render-verified real heading that gate 16 reads as a promotion suspect.

    The gate accepts a heading's typography as evidence only when it is set in
    DISPLAY size, in a non-body family, or in a small-caps face. PWC falsifies
    that: this book marks a selection's sub-sections with CENTERED FULL CAPS at
    the body face and size ('1. THE FORM OF THE PRAYER', p.145) — real headings
    carrying none of the three. Centeredness alone cannot stand in as evidence:
    it is what the pstyle_map keys the h3 off in the first place, and the same
    gate correctly caught this book's centered '*  *  *' section-break
    ornaments. So each such heading is allowed BY TEXT, one render at a time.

    Exact snippet; note is the render evidence and is REQUIRED. Per-book, like
    qa_duplicate_allow (an agent judgment); a stale entry fails the gate, so a
    heading that later stops printing cannot silently license a real promotion.
    """
    snippet: str
    note: str


@dataclass(slots=True)
class SignatureAllow:
    """A render-verified page whose gate-17 typographic signature cannot match.

    Gate 17 compares a per-page run of size buckets. PWC p.4 sets ONE printed
    sentence in two sizes — a 10pt italic book title followed by 9.747pt roman
    prose ('…World Religions appears as one of our selections…') — so the flow's
    paragraph takes its style from the first line (10pt = 'body') while the
    gate's PDF side takes the char-weighted size (9.747, which the extractor's
    0.5pt pstyle quantizer stores as 9.5 — exactly the 'small' boundary). The
    two sides bucket the same paragraph differently, and the gate would only
    agree if the paragraph were left SPLIT mid-phrase — the very defect it
    exists to catch. Page-scoped; note is the render evidence and is REQUIRED.
    A stale entry (a page that no longer mismatches) fails the gate.
    """
    page: int
    note: str


@dataclass(slots=True)
class CharStyleFlags:
    smallcaps: bool = False
    symbol: bool = False


@dataclass(slots=True)
class PuaRule:
    action: str  # char | drop
    char: str | None = None
    lang: str | None = None
    note: str = ""


@dataclass(slots=True)
class FffdRepair:
    """U+FFFD is the extractor's unmapped-glyph placeholder: every broken
    glyph collapses to the SAME codepoint, so only a page-scoped,
    render-verified replacement is deterministic. ``replace`` may be ""
    (render shows no content at the run) but must be explicit; ``note``
    records the render evidence and is REQUIRED."""
    pages: list[int]
    replace: str
    note: str


@dataclass(slots=True)
class FontEmbed:
    family: str
    file: str
    style: str = "normal"  # normal | italic
    script: str = "latin"  # latin | cjk (cjk drives the :lang() CSS stack)
    lang: str | None = None


@dataclass(slots=True)
class FigurePages:
    pages: list[int]
    alt_template: str = "Image of page {label}"
    lang: str | None = None
    # keep_text: the page's extracted text ALSO flows after the figure —
    # for plates whose typeset heading/caption must stay live (I&B p.8:
    # the Dalai Lama's facsimile foreword letter under a typeset h1)
    keep_text: bool = False


@dataclass(slots=True)
class FigureRegion:
    """A rect on a page that ships as a cropped raster figure: the safe path
    for TRUE TABLES and diagrams embedded in prose (row/column relationships
    are content the line-based flow cannot represent). The region's text
    lines leave the flow and the coverage ground truth; alt text is
    REQUIRED — the agent writes it from the render."""
    page: int
    rect: tuple[float, float, float, float]  # extract-space pt (top-origin)
    alt: str
    note: str = ""


@dataclass(slots=True)
class CoverRender:
    page: int
    box: str = "trim"  # trim | media
    dpi: int = 300


@dataclass(slots=True)
class LostSpaceAllow:
    """A render-verified as-printed match of gate 11's fused-word patterns
    ('etc.Cambridge' genuinely printed that way). Exact snippet; note is the
    render evidence and is REQUIRED."""
    snippet: str
    note: str


@dataclass(slots=True)
class DuplicateAllow:
    """A render-verified as-printed match of gate 25's duplicated-span witness:
    a long verbatim repeat the PRINT really carries. The witness assumes a
    >=400-char repeat is pipeline damage (a duplicated page/chapter), which a
    scholarly book falsifies by quoting one passage twice — Keys quotes the
    same Schuon paragraph in ch.4 n.24 and ch.10 n.19 (pp.141/334). The
    snippet must occur INSIDE the flagged span; note is the render evidence
    and is REQUIRED. Per-book, like qa_lost_space_allow (an agent judgment);
    a stale entry fails the gate, so a repeat that later stops printing twice
    cannot silently license real duplication."""
    snippet: str
    note: str


@dataclass(slots=True)
class Adjudication:
    """Records the decision on a content-risk build warning that config
    cannot resolve structurally (warnqueue codes). Without pages the entry
    covers every open warning of the code. A stale entry — matching nothing
    open — is a config bug (flow.overrides doctrine)."""
    warning: str
    pages: list[int]
    note: str


@dataclass(slots=True)
class PdfBookConfig:
    path: Path  # config file location; relative paths resolve against its parent
    schema_version: int = 1  # book.yaml grammar version (top-level key)
    config_sha256: str = ""  # sha256 of the exact bytes load_config parsed

    # source
    source_folder: Path = Path()
    pdf: str = ""
    sha256: str = ""  # pinned by init; build refuses a different file

    # metadata (JP-P5) — publisher has NO default: generic tool
    title: str = ""
    subtitle: str | None = None
    creators: list[dict] = field(default_factory=list)
    publisher: str = ""
    language: str = "en"
    additional_languages: list[str] = field(default_factory=list)
    isbn_epub: str | None = None
    isbn_print: str | None = None
    identifier: str | None = None       # persistent EPUB id (UUID/urn); NOT slug-derived
    released: str | None = None         # YYYY-MM-DD; feeds dcterms:modified (EPUB revision)
    date: str | None = None
    cover: str | None = None            # packaged image path (workspace-relative)
    cover_render: CoverRender | None = None
    cover_synthesize: bool = False      # deterministic typographic cover fallback
    accessibility_summary: str = ""

    # pages (JP-P2)
    pages_cover: list[int] = field(default_factory=list)
    pages_front: PageRange | None = None
    pages_body: PageRange | None = None
    pages_back: PageRange | None = None
    pages_exclude: list[int] = field(default_factory=list)
    label_source: str = "pdf-page-labels"  # pdf-page-labels | printed-folios | synthetic
    label_overrides: dict[int, str] = field(default_factory=dict)
    role_overrides: list[RoleOverride] = field(default_factory=list)

    # furniture (JP-P2)
    top_band: float = 0.0      # PDF points from trim top; 0 = analyzer default
    repeat_min_pages: int = 3
    furniture_extra: list[str] = field(default_factory=list)
    furniture_keep: list[str] = field(default_factory=list)

    # styles (JP-P1)
    body_pstyle: str = ""
    pstyle_map: dict[str, StyleRule] = field(default_factory=dict)
    charstyles: dict[str, CharStyleFlags] = field(default_factory=dict)
    unmapped_role: str = "p"
    fail_on_unmapped: bool = False

    # flow joining knobs
    indent_threshold: float = 9.0   # pt of first-line indent that starts a paragraph
    gap_factor: float = 1.6         # vgap >= factor x median leading = block break
    dehyphenate: str = "lower-only"  # lower-only | off
    # render-verified compounds whose hyphen must survive a line-break split
    # ('religion-quintessence') — lower-only would otherwise strip it; matched
    # case-insensitively on the reconstructed 'word-word'. Per-book, like
    # qa_lost_space_allow (an agent judgment, NOT a global lexicon).
    keep_hyphens: frozenset = frozenset()
    restore_spaces: bool = False
    join_center_lines: bool = True
    reattach_dropcaps: bool = True
    flow_overrides: list[FlowOverride] = field(default_factory=list)
    flow_columns: list[ColumnSpec] = field(default_factory=list)

    # semantic block grammar (JP-P9): per-class judgment specs
    blocks_verse: list[VerseSpec] = field(default_factory=list)
    blocks_quotes: list[QuoteSpec] = field(default_factory=list)
    blocks_lists: list[ListSpec] = field(default_factory=list)

    # footnotes (JP-P4)
    footnote_policy: str = "none"   # none | markers
    footnote_marker: str = "digits"  # digits | asterisk
    footnote_region_max_size: float = 0.0  # pt; 0 = body size - 1.5

    # toc (JP-P3)
    toc_source: str = "outline"     # outline | printed | links
    toc_printed_pages: list[int] = field(default_factory=list)
    toc_handling: str = "rebuild"   # rebuild | drop (the in-body contents page)
    strip_toc_page_numbers: bool = True
    nav_depth: int = 2
    # printed-TOC lines that carry NO folio but are their own entry (a part
    # divider like "Appendix"), not a wrapped-title continuation of the line
    # above; matched on stripped text. Render-verified per book.
    toc_standalone_lines: list[str] = field(default_factory=list)

    # glyphs (JP-P6)
    pua_map: dict[str, PuaRule] = field(default_factory=dict)
    fail_on_unmapped_pua: bool = False
    # poppler ToUnicode 'readings' of symbol glyphs ('May God be pleased with
    # her') — stripped from QA ground truth because the EPUB legitimately
    # renders the glyph char instead; agent-verified, itemized in the QA report
    gt_strip_phrases: list[str] = field(default_factory=list)
    # repair a -0x1D-shifted subset ToUnicode CMap (Islam and Buddhism 2010):
    # runs carrying control-range marker chars get chr(c+0x1D) for c<0x60 and
    # the agent-verified highmap for non-ASCII garbage
    shifted_cmap_repair: bool = False
    shifted_cmap_highmap: dict[str, str] = field(default_factory=dict)
    fffd_repairs: list[FffdRepair] = field(default_factory=list)

    # fonts (JP-P7)
    fonts_embed: list[FontEmbed] = field(default_factory=list)
    fonts_subset: bool = True

    # languages (JP-P8)
    cjk_han_only: str = "zh"
    lang_overrides: list[dict] = field(default_factory=list)

    # split
    split_at_roles: list[str] = field(default_factory=lambda: ["h1"])
    warn_over_files: int = 90

    # images (JP-P4b)
    raster_dpi: int = 300
    max_pixels: int = 1600
    figure_pages: list[FigurePages] = field(default_factory=list)
    figure_regions: list[FigureRegion] = field(default_factory=list)

    # qa
    qa_lost_space_allow: list[LostSpaceAllow] = field(default_factory=list)
    qa_duplicate_allow: list[DuplicateAllow] = field(default_factory=list)
    qa_heading_allow: list[HeadingAllow] = field(default_factory=list)
    qa_signature_allow: list[SignatureAllow] = field(default_factory=list)
    qa_garble_chars: str = ""  # per-book gate-20 residue chars (e.g. "³´«")

    # adjudications (gate 22)
    adjudications: list[Adjudication] = field(default_factory=list)

    # imprint (publisher-specific structural transforms; None = generic tool).
    # Parsed and owned by pdf2epub.imprints; the core only routes the block.
    imprint: "ImprintSpec | None" = None

    # output
    slug: str = "book"
    include_ncx: bool = True

    # ------------------------------------------------------------------

    @property
    def body_style(self) -> str:
        """Alias for the forked emit_css, which reads cfg.body_style."""
        return self.body_pstyle

    @property
    def workspace(self) -> Path:
        return self.path.parent

    @property
    def build_dir(self) -> Path:
        return self.workspace / "build"

    @property
    def analysis_dir(self) -> Path:
        return self.workspace / "analysis"

    def pdf_path(self) -> Path:
        p = Path(self.pdf)
        return p if p.is_absolute() else self.source_folder / p

    def resolve_workspace(self, name: str) -> Path:
        p = Path(name)
        return p if p.is_absolute() else self.workspace / p

    def in_flow_pages(self, n_pages: int) -> list[int]:
        skip = set(self.pages_cover) | set(self.pages_exclude)
        return [p for p in range(1, n_pages + 1) if p not in skip]


def _check_keys(section: str, data: dict, allowed: set[str]) -> None:
    unknown = set(data) - allowed
    if unknown:
        raise ConfigError(f"unknown key(s) in {section}: {', '.join(sorted(unknown))}")


def _page_range(section: str, data) -> PageRange | None:
    if data is None:
        return None
    _check_keys(section, data, {"first", "last"})
    return PageRange(first=int(data["first"]), last=int(data["last"]))


def _page_list(items) -> list[int]:
    """Expand a YAML page list that may mix ints and 'a-b' range strings."""
    pages: list[int] = []
    for item in items:
        if isinstance(item, str) and "-" in item:
            a, b = item.split("-", 1)
            pages.extend(range(int(a), int(b) + 1))
        else:
            pages.append(int(item))
    return pages


SCHEMA_VERSION = 1

_PLACEHOLDER = "FILL-ME-IN"


def _reject_placeholders(value, path: str = "") -> None:
    """Recursively refuse any surviving FILL-ME-IN marker — the init draft's
    unresolved-judgment placeholder. initcmd promises this fails the build
    loudly; this is the enforcement."""
    if isinstance(value, str):
        if _PLACEHOLDER in value:
            raise ConfigError(
                f"unresolved {_PLACEHOLDER} placeholder at "
                f"{path or 'book.yaml'} — finalize book.yaml before building")
    elif isinstance(value, dict):
        for k, v in value.items():
            _reject_placeholders(v, f"{path}.{k}" if path else str(k))
    elif isinstance(value, (list, tuple)):
        for i, v in enumerate(value):
            _reject_placeholders(v, f"{path}[{i}]")


def _check_schema_version(data: dict, require: bool) -> None:
    """schema_version must be a plain int equal to the supported version. Type
    is always enforced (YAML `true` coerces to 1 via bool-is-int — reject it);
    PRESENCE is required only for a complete config (build/validate), so partial
    parser fixtures need not carry it."""
    if "schema_version" not in data:
        if require:
            raise ConfigError(
                f"schema_version is required — add `schema_version: {SCHEMA_VERSION}`")
        return
    sv = data["schema_version"]
    if isinstance(sv, bool) or not isinstance(sv, int):
        raise ConfigError(f"schema_version must be an integer, got {sv!r}")
    if sv != SCHEMA_VERSION:
        raise ConfigError(
            f"schema_version {sv} unsupported (this build expects {SCHEMA_VERSION})")


def _check_required_metadata(data: dict) -> None:
    """title/creators/language must be PRESENT (checked on the raw dict —
    cfg.language defaults to 'en', so a post-parse cfg check can't prove the
    key was authored)."""
    md = data.get("metadata") or {}
    for key in ("title", "creators", "language"):
        if not md.get(key):
            raise ConfigError(f"metadata.{key} is required and must be non-empty")


def _validate_page_ranges(cfg: PdfBookConfig) -> None:
    """Structural invariants on the front/body/back partition: each range
    positive with first <= last, and the declared ranges strictly ordered and
    non-overlapping. (These annotate the folio-inferred partition; the printed-
    folio cross-check is a separate, noisy advisory kept off by default.)"""
    present = [(name, r) for name, r in
               (("front", cfg.pages_front), ("body", cfg.pages_body),
                ("back", cfg.pages_back)) if r is not None]
    for name, r in present:
        if r.first < 1 or r.last < r.first:
            raise ConfigError(
                f"pages.{name} must be a positive range with first <= last, "
                f"got {r.first}..{r.last}")
    for (n1, r1), (n2, r2) in zip(present, present[1:]):
        if r2.first <= r1.last:
            raise ConfigError(
                f"pages.{n1} ({r1.first}..{r1.last}) and pages.{n2} "
                f"({r2.first}..{r2.last}) must be ordered and non-overlapping")


def load_config(path: Path, require_complete: bool = False) -> PdfBookConfig:
    """Parse book.yaml. Structural checks (unknown keys, page-range order) and
    placeholder rejection always run; `require_complete` additionally demands a
    finalized config (schema_version present, required metadata) — `build` and
    `validate` set it, low-level parser tests do not."""
    path = path.expanduser().resolve()
    # hash the EXACT bytes we parse, so the provenance manifest records the
    # config content the build actually used — not a re-read that could differ
    # if book.yaml changes between parse and hash.
    raw = path.read_bytes()
    data = yaml.safe_load(raw.decode("utf-8")) or {}
    _check_keys("book.yaml", data, {
        "schema_version",
        "source", "metadata", "pages", "furniture", "styles", "flow",
        "footnotes", "toc", "glyphs", "fonts", "languages", "split",
        "images", "output", "qa", "adjudications", "blocks", "imprint",
    })
    _reject_placeholders(data)
    _check_schema_version(data, require_complete)
    if require_complete:
        _check_required_metadata(data)
    cfg = PdfBookConfig(path=path)
    cfg.config_sha256 = hashlib.sha256(raw).hexdigest()
    cfg.schema_version = int(data.get("schema_version", SCHEMA_VERSION))

    src = data.get("source", {})
    _check_keys("source", src, {"folder", "pdf", "sha256"})
    folder = src.get("folder")
    if not folder:
        raise ConfigError("source.folder is required")
    cfg.source_folder = Path(folder).expanduser()
    if not cfg.source_folder.is_absolute():
        # relative to the config file, so in-repo packages travel with a clone
        cfg.source_folder = (path.parent / cfg.source_folder).resolve()
    cfg.pdf = src.get("pdf") or ""
    if not cfg.pdf:
        raise ConfigError("source.pdf is required")
    cfg.sha256 = src.get("sha256", "")

    md = data.get("metadata", {})
    _check_keys("metadata", md, {
        "title", "subtitle", "creators", "publisher", "language",
        "additional_languages", "isbn_epub", "isbn_print", "identifier",
        "released", "date", "cover",
        "cover_render", "cover_synthesize", "accessibility_summary",
    })
    cfg.title = md.get("title", "")
    cfg.subtitle = md.get("subtitle")
    cfg.creators = md.get("creators", []) or []
    cfg.publisher = md.get("publisher", "") or ""
    cfg.language = md.get("language", cfg.language)
    cfg.additional_languages = md.get("additional_languages", []) or []
    cfg.isbn_epub = md.get("isbn_epub") or None
    cfg.isbn_print = md.get("isbn_print") or None
    cfg.identifier = md.get("identifier") or None
    if cfg.identifier and not cfg.identifier.startswith("urn:"):
        try:
            uuid.UUID(cfg.identifier)
        except (ValueError, AttributeError, TypeError):
            raise ConfigError("metadata.identifier must be a UUID or urn: value, "
                              f"got {cfg.identifier!r}")
    cfg.released = str(md.get("released")) if md.get("released") is not None else None
    if cfg.released:
        try:
            datetime.strptime(cfg.released, "%Y-%m-%d")
        except ValueError:
            raise ConfigError("metadata.released must be YYYY-MM-DD, "
                              f"got {cfg.released!r}")
    cfg.date = str(md.get("date")) if md.get("date") is not None else None
    cfg.cover = md.get("cover")
    cr = md.get("cover_render")
    if cr:
        _check_keys("metadata.cover_render", cr, {"page", "box", "dpi"})
        cfg.cover_render = CoverRender(page=int(cr["page"]),
                                       box=cr.get("box", "trim"),
                                       dpi=int(cr.get("dpi", 300)))
    cfg.cover_synthesize = bool(md.get("cover_synthesize", False))
    cfg.accessibility_summary = md.get("accessibility_summary", "")

    pg = data.get("pages", {})
    _check_keys("pages", pg, {
        "cover", "front", "body", "back", "exclude", "label_source",
        "label_overrides", "role_overrides",
    })
    cfg.pages_cover = list(pg.get("cover", []) or [])
    cfg.pages_front = _page_range("pages.front", pg.get("front"))
    cfg.pages_body = _page_range("pages.body", pg.get("body"))
    cfg.pages_back = _page_range("pages.back", pg.get("back"))
    cfg.pages_exclude = list(pg.get("exclude", []) or [])
    cfg.label_source = pg.get("label_source", cfg.label_source)
    if cfg.label_source not in ("pdf-page-labels", "printed-folios", "synthetic"):
        raise ConfigError(f"pages.label_source invalid: {cfg.label_source}")
    cfg.label_overrides = {int(k): str(v) for k, v in (pg.get("label_overrides") or {}).items()}
    for ro in pg.get("role_overrides", []) or []:
        _check_keys("pages.role_overrides[]", ro, {"page", "role", "class"})
        cfg.role_overrides.append(RoleOverride(page=int(ro["page"]), role=ro["role"],
                                               class_=ro.get("class")))
    _validate_page_ranges(cfg)

    fu = data.get("furniture", {})
    _check_keys("furniture", fu, {"top_band", "repeat_min_pages",
                                  "extra", "keep"})
    cfg.top_band = float(fu.get("top_band", 0.0))
    cfg.repeat_min_pages = int(fu.get("repeat_min_pages", cfg.repeat_min_pages))
    cfg.furniture_extra = list(fu.get("extra", []) or [])
    cfg.furniture_keep = list(fu.get("keep", []) or [])

    st = data.get("styles", {})
    _check_keys("styles", st, {"body_pstyle", "pstyle_map", "charstyles",
                               "unmapped_role", "fail_on_unmapped"})
    cfg.body_pstyle = st.get("body_pstyle", "")
    for name, rule in (st.get("pstyle_map") or {}).items():
        if isinstance(rule, str):
            cfg.pstyle_map[name] = StyleRule(role=rule)
        else:
            _check_keys(f"styles.pstyle_map[{name}]", rule, {"role", "class"})
            cfg.pstyle_map[name] = StyleRule(role=rule["role"], class_=rule.get("class"))
    for fam, flags in (st.get("charstyles") or {}).items():
        _check_keys(f"styles.charstyles[{fam}]", flags, {"smallcaps", "symbol"})
        cfg.charstyles[fam] = CharStyleFlags(smallcaps=bool(flags.get("smallcaps", False)),
                                             symbol=bool(flags.get("symbol", False)))
    cfg.unmapped_role = st.get("unmapped_role", cfg.unmapped_role)
    cfg.fail_on_unmapped = bool(st.get("fail_on_unmapped", False))

    fl = data.get("flow", {})
    _check_keys("flow", fl, {"indent_threshold", "gap_factor", "dehyphenate",
                             "restore_spaces", "join_center_lines",
                             "reattach_dropcaps", "overrides", "columns",
                             "keep_hyphens"})
    cfg.indent_threshold = float(fl.get("indent_threshold", cfg.indent_threshold))
    cfg.gap_factor = float(fl.get("gap_factor", cfg.gap_factor))
    cfg.dehyphenate = fl.get("dehyphenate", cfg.dehyphenate)
    if cfg.dehyphenate not in ("lower-only", "off"):
        raise ConfigError(f"flow.dehyphenate invalid: {cfg.dehyphenate}")
    cfg.keep_hyphens = frozenset(
        str(h).lower() for h in (fl.get("keep_hyphens", []) or []))
    cfg.restore_spaces = bool(fl.get("restore_spaces", False))
    cfg.join_center_lines = bool(fl.get("join_center_lines", True))
    cfg.reattach_dropcaps = bool(fl.get("reattach_dropcaps", True))
    for ov in fl.get("overrides", []) or []:
        _check_keys("flow.overrides[]", ov, {"page", "line", "action", "note"})
        action = ov["action"]
        if action not in ("join", "break", "drop", "keep", "class:verse",
                          "class:quote", "class:list", "class:prose") \
                and not action.startswith("role:"):
            raise ConfigError(f"flow.overrides action invalid: {action}")
        cfg.flow_overrides.append(FlowOverride(page=int(ov["page"]), line=int(ov["line"]),
                                               action=action, note=ov.get("note", "")))
    for cs in fl.get("columns", []) or []:
        _check_keys("flow.columns[]", cs, {"pages", "count", "note", "index"})
        pages = _page_list(cs["pages"])
        count = int(cs["count"])
        if count < 2:
            raise ConfigError("flow.columns count must be >= 2")
        if not pages:
            raise ConfigError("flow.columns needs at least one page")
        cfg.flow_columns.append(ColumnSpec(pages=pages, count=count,
                                           note=cs.get("note", ""),
                                           index=bool(cs.get("index", False))))

    fn = data.get("footnotes", {})
    _check_keys("footnotes", fn, {"policy", "marker", "region_max_size"})
    cfg.footnote_policy = fn.get("policy", cfg.footnote_policy)
    if cfg.footnote_policy not in ("none", "markers"):
        raise ConfigError(f"footnotes.policy invalid: {cfg.footnote_policy}")
    cfg.footnote_marker = fn.get("marker", cfg.footnote_marker)
    if cfg.footnote_marker not in ("digits", "asterisk"):
        raise ConfigError(f"footnotes.marker invalid: {cfg.footnote_marker}")
    cfg.footnote_region_max_size = float(fn.get("region_max_size", 0.0))

    tc = data.get("toc", {})
    _check_keys("toc", tc, {"source", "printed_pages", "handling",
                            "strip_page_numbers", "nav_depth",
                            "standalone_lines"})
    cfg.toc_source = tc.get("source", cfg.toc_source)
    if cfg.toc_source not in ("outline", "printed", "links"):
        raise ConfigError(f"toc.source invalid: {cfg.toc_source}")
    cfg.toc_printed_pages = list(tc.get("printed_pages", []) or [])
    cfg.toc_handling = tc.get("handling", cfg.toc_handling)
    cfg.strip_toc_page_numbers = bool(tc.get("strip_page_numbers", True))
    cfg.nav_depth = int(tc.get("nav_depth", cfg.nav_depth))
    cfg.toc_standalone_lines = list(tc.get("standalone_lines", []) or [])

    gl = data.get("glyphs", {})
    _check_keys("glyphs", gl, {"pua_map", "fail_on_unmapped_pua", "gt_strip_phrases",
                               "shifted_cmap_repair", "shifted_cmap_highmap",
                               "fffd_repairs"})
    cfg.gt_strip_phrases = list(gl.get("gt_strip_phrases", []) or [])
    cfg.shifted_cmap_repair = bool(gl.get("shifted_cmap_repair", False))
    cfg.shifted_cmap_highmap = dict(gl.get("shifted_cmap_highmap", {}) or {})
    for fd in gl.get("fffd_repairs", []) or []:
        _check_keys("glyphs.fffd_repairs[]", fd, {"pages", "replace", "note"})
        if "replace" not in fd:
            raise ConfigError('glyphs.fffd_repairs requires "replace" '
                              '(may be "" when the render shows no content)')
        if not fd.get("note"):
            raise ConfigError("glyphs.fffd_repairs requires a note "
                              "(render-verified evidence)")
        pages = _page_list(fd["pages"])
        if not pages:
            raise ConfigError("glyphs.fffd_repairs needs at least one page")
        cfg.fffd_repairs.append(FffdRepair(pages=pages, replace=str(fd["replace"]),
                                           note=fd["note"]))
    for cp, rule in (gl.get("pua_map") or {}).items():
        _check_keys(f"glyphs.pua_map[{cp!r}]", rule, {"action", "char", "lang", "note"})
        action = rule["action"]
        if action not in ("char", "drop"):
            raise ConfigError(f"glyphs.pua_map action invalid: {action}")
        if action == "char" and not rule.get("char"):
            raise ConfigError(f"glyphs.pua_map[{cp!r}]: action char requires 'char'")
        cfg.pua_map[cp] = PuaRule(action=action, char=rule.get("char"),
                                  lang=rule.get("lang"), note=rule.get("note", ""))
    cfg.fail_on_unmapped_pua = bool(gl.get("fail_on_unmapped_pua", False))

    fo = data.get("fonts", {})
    _check_keys("fonts", fo, {"embed", "subset"})
    for fe in fo.get("embed", []) or []:
        _check_keys("fonts.embed[]", fe, {"family", "file", "style", "script", "lang"})
        cfg.fonts_embed.append(FontEmbed(family=fe["family"], file=fe["file"],
                                         style=fe.get("style", "normal"),
                                         script=fe.get("script", "latin"),
                                         lang=fe.get("lang")))
    cfg.fonts_subset = bool(fo.get("subset", True))

    lg = data.get("languages", {})
    _check_keys("languages", lg, {"cjk_han_only", "overrides"})
    cfg.cjk_han_only = lg.get("cjk_han_only", cfg.cjk_han_only)
    cfg.lang_overrides = lg.get("overrides", []) or []

    sp = data.get("split", {})
    _check_keys("split", sp, {"at_roles", "warn_over_files"})
    cfg.split_at_roles = sp.get("at_roles", cfg.split_at_roles)
    cfg.warn_over_files = int(sp.get("warn_over_files", cfg.warn_over_files))

    im = data.get("images", {})
    _check_keys("images", im, {"raster_dpi", "max_pixels",
                               "figure_pages", "figure_regions"})
    cfg.raster_dpi = int(im.get("raster_dpi", cfg.raster_dpi))
    cfg.max_pixels = int(im.get("max_pixels", cfg.max_pixels))
    for fp in im.get("figure_pages", []) or []:
        _check_keys("images.figure_pages[]", fp,
                    {"pages", "alt_template", "lang", "keep_text"})
        pages = _page_list(fp["pages"])
        cfg.figure_pages.append(FigurePages(pages=pages,
                                            alt_template=fp.get("alt_template",
                                                                "Image of page {label}"),
                                            lang=fp.get("lang"),
                                            keep_text=bool(fp.get("keep_text",
                                                                  False))))
    for fr in im.get("figure_regions", []) or []:
        _check_keys("images.figure_regions[]", fr, {"page", "rect", "alt", "note"})
        rect = tuple(float(v) for v in fr["rect"])
        if len(rect) != 4 or rect[0] >= rect[2] or rect[1] >= rect[3]:
            raise ConfigError("images.figure_regions rect must be [x0, y0, x1, y1]")
        if not fr.get("alt"):
            raise ConfigError("images.figure_regions requires alt text "
                              "(write it from the page render)")
        cfg.figure_regions.append(FigureRegion(page=int(fr["page"]), rect=rect,
                                               alt=fr["alt"],
                                               note=fr.get("note", "")))

    bl = data.get("blocks", {})
    _check_keys("blocks", bl, {"verse", "quotes", "lists"})
    for vs in bl.get("verse", []) or []:
        _check_keys("blocks.verse[]", vs,
                    {"pages", "base", "turns", "tol", "stanza_gap", "note"})
        if not vs.get("note"):
            raise ConfigError("blocks.verse requires a note "
                              "(render-verified evidence)")
        pages = _page_list(vs.get("pages", []) or [])
        if not pages:
            raise ConfigError("blocks.verse needs at least one page")
        base = [float(v) for v in (vs.get("base", []) or [])]
        turns = [float(v) for v in (vs.get("turns", []) or [])]
        if not base:
            raise ConfigError("blocks.verse requires base indent level(s) "
                              "(pt offsets from the shift-corrected column "
                              "left); turns may be omitted for single-level "
                              "verse")
        col_pages = {p for cs in cfg.flow_columns for p in cs.pages}
        fig_pages = {p for fp in cfg.figure_pages for p in fp.pages}
        clash = set(pages) & (col_pages | fig_pages)
        if clash:
            raise ConfigError("blocks.verse pages overlap flow.columns/"
                              f"figure_pages: {sorted(clash)[:8]}")
        cfg.blocks_verse.append(VerseSpec(
            pages=pages, base=base, turns=turns,
            tol=float(vs.get("tol", 2.0)),
            stanza_gap=float(vs.get("stanza_gap", 1.4)),
            note=vs["note"]))
    for qs in bl.get("quotes", []) or []:
        _check_keys("blocks.quotes[]", qs,
                    {"pages", "left_inset", "right_inset", "tol", "note"})
        if not qs.get("note"):
            raise ConfigError("blocks.quotes requires a note "
                              "(render-verified evidence)")
        pages = _page_list(qs.get("pages", []) or [])
        if not pages:
            raise ConfigError("blocks.quotes needs at least one page")
        left_inset = float(qs.get("left_inset", 0.0))
        if left_inset < 6.0:
            raise ConfigError("blocks.quotes left_inset must be >= 6pt (a "
                              "quote at the body left edge has no detectable "
                              "shape; right_inset alone cannot carry it)")
        col_pages = {p for cs in cfg.flow_columns for p in cs.pages}
        fig_pages = {p for fp in cfg.figure_pages for p in fp.pages}
        clash = set(pages) & (col_pages | fig_pages)
        if clash:
            raise ConfigError("blocks.quotes pages overlap flow.columns/"
                              f"figure_pages: {sorted(clash)[:8]}")
        cfg.blocks_quotes.append(QuoteSpec(
            pages=pages, left_inset=left_inset,
            right_inset=float(qs.get("right_inset", 0.0)),
            tol=float(qs.get("tol", 3.0)),
            note=qs["note"]))
    for ls in bl.get("lists", []) or []:
        _check_keys("blocks.lists[]",
                    ls, {"pages", "marker", "hang", "tol", "note"})
        if not ls.get("note"):
            raise ConfigError("blocks.lists requires a note "
                              "(render-verified evidence)")
        pages = _page_list(ls.get("pages", []) or [])
        if not pages:
            raise ConfigError("blocks.lists needs at least one page")
        marker = ls.get("marker", "decimal")
        if marker not in ("decimal", "bullet", "hang"):
            raise ConfigError(f"blocks.lists marker invalid: {marker}")
        if marker == "hang" and float(ls.get("hang", 0.0)) <= 0:
            raise ConfigError("blocks.lists marker 'hang' (marker-less "
                              "hanging apparatus) requires hang > 0")
        col_pages = {p for cs in cfg.flow_columns for p in cs.pages}
        fig_pages = {p for fp in cfg.figure_pages for p in fp.pages}
        clash = set(pages) & (col_pages | fig_pages)
        if clash:
            raise ConfigError("blocks.lists pages overlap flow.columns/"
                              f"figure_pages: {sorted(clash)[:8]}")
        cfg.blocks_lists.append(ListSpec(
            pages=pages, marker=marker,
            hang=float(ls.get("hang", 0.0)),
            tol=float(ls.get("tol", 3.0)),
            note=ls["note"]))

    qa = data.get("qa", {})
    _check_keys("qa", qa, {"lost_space_allow", "garble_chars",
                           "duplicate_allow", "heading_allow",
                           "signature_allow"})
    for al in qa.get("heading_allow", []) or []:
        _check_keys("qa.heading_allow[]", al, {"snippet", "note"})
        if not al.get("snippet"):
            raise ConfigError("qa.heading_allow requires the exact snippet")
        if not al.get("note"):
            raise ConfigError("qa.heading_allow requires a note "
                              "(render-verified heading evidence)")
        cfg.qa_heading_allow.append(
            HeadingAllow(snippet=al["snippet"], note=al["note"]))
    for al in qa.get("signature_allow", []) or []:
        _check_keys("qa.signature_allow[]", al, {"page", "note"})
        if not al.get("page"):
            raise ConfigError("qa.signature_allow requires the page")
        if not al.get("note"):
            raise ConfigError("qa.signature_allow requires a note "
                              "(render-verified evidence)")
        cfg.qa_signature_allow.append(
            SignatureAllow(page=int(al["page"]), note=al["note"]))
    for al in qa.get("duplicate_allow", []) or []:
        _check_keys("qa.duplicate_allow[]", al, {"snippet", "note"})
        if not al.get("snippet"):
            raise ConfigError("qa.duplicate_allow requires the exact snippet")
        if not al.get("note"):
            raise ConfigError("qa.duplicate_allow requires a note "
                              "(render-verified as-printed evidence)")
        cfg.qa_duplicate_allow.append(
            DuplicateAllow(snippet=al["snippet"], note=al["note"]))
    for al in qa.get("lost_space_allow", []) or []:
        _check_keys("qa.lost_space_allow[]", al, {"snippet", "note"})
        if not al.get("snippet"):
            raise ConfigError("qa.lost_space_allow requires the exact snippet")
        if not al.get("note"):
            raise ConfigError("qa.lost_space_allow requires a note "
                              "(render-verified as-printed evidence)")
        cfg.qa_lost_space_allow.append(
            LostSpaceAllow(snippet=al["snippet"], note=al["note"]))
    cfg.qa_garble_chars = str(qa.get("garble_chars", "") or "")

    for ad in data.get("adjudications", []) or []:
        _check_keys("adjudications[]", ad, {"warning", "pages", "note"})
        from .warnqueue import CODES
        code = ad.get("warning") or ""
        if code not in CODES:
            raise ConfigError(f"adjudications warning code unknown: {code!r} "
                              f"(known: {', '.join(sorted(CODES))})")
        if not ad.get("note"):
            raise ConfigError("adjudications requires a note "
                              "(the render-verified reason)")
        cfg.adjudications.append(Adjudication(
            warning=code, pages=_page_list(ad.get("pages", []) or []),
            note=ad["note"]))

    out = data.get("output", {})
    _check_keys("output", out, {"slug", "include_ncx"})
    cfg.slug = out.get("slug", cfg.slug)
    cfg.include_ncx = bool(out.get("include_ncx", True))

    imp = data.get("imprint")
    if imp is not None:
        # the imprint package owns its sub-schema; the core only routes it
        from .imprints import parse_imprint
        cfg.imprint = parse_imprint(imp)

    return cfg
