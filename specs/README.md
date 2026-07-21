# specs/ — deferred-enhancement hand-off documents

Each spec is a self-contained hand-off for a future implementation session: the problem,
the evidence behind it (sources cited inline), a design sketch grounded in the current
architecture, integration points by file, acceptance criteria, and explicit non-goals.
Specs record *judgment already exercised* — read one before re-litigating its decisions.

Shipped items keep a short record here (status + where the implementation diverged from
the sketch and why); the implementation narrative lives in NOTES.md and the full original
sketches live in git history. The corpus these specs serve has grown from five books to
**ten (eleven tracked configs)** — `pdf2epub corpus` rebuilds, QAs, byte-compares, and
counter-diffs all of them, and is the regression net every spec's acceptance now assumes.

## Where to start

- **Planning what to build next?** → [commercial-parity.md](commercial-parity.md) holds
  the single merged priority ranking.
- **Picking up an open item?** → the table below; each spec's Status line says exactly
  what remains.

| Spec | What | Status | Trigger |
|---|---|---|---|
| [commercial-parity.md](commercial-parity.md) | Landscape: what commercial ebook-production ships that we don't (tables, math, RTL layout, output breadth, cross-refs) + the **single merged priority ranking** tying every spec below together | landscape; ranking current to 2026-07-21 | positioning / roadmap review |
| [reliability-hardening.md](reliability-hardening.md) | The trust substrate: config integrity, transactional builds + provenance, package identity, hermetic tests + CI | **§1–§4 SHIPPED 2026-07-12**; corpus runner + fixture-presence gate + per-rule telemetry followed 2026-07-19; **open: §5 process limits, §6 maintainability extraction** | §5: untrusted intake; §6: rides the next big content feature |
| [qa-methodology.md](qa-methodology.md) | Per-page assertion gates; poppler `-remove-hyphens` witness; page-aligned fidelity | #1 SHIPPED (gate 24), #3 SHIPPED (gate 25, gating); **open: #2 (blocked on poppler ≥ 26.05; system has 26.01), gate-25b promotion to gating** | #2: poppler bump |
| [semantic-polish.md](semantic-polish.md) | Linked index locators; EAA/a11y; typogrify-lite | #1 SHIPPED, #2 automated readiness SHIPPED (gate 26); **open: manual a11y certification + `conformsTo`, #3 typogrify-lite** | cert: EU distribution; #3: next wave |
| [ocr-witness.md](ocr-witness.md) | OCR as a third text witness for legacy/scanned PDFs (+ era/pathology census as the cheap always-on step 1; guarded `verified-ocr` source mode) | spec'd, not implemented | census: anytime (cheap); witness: first Distiller-era or scanned book |
| [arabic-fonts.md](arabic-fonts.md) | Arabic-variant font upgrade Amiri → Scheherazade New (verified coverage matrix) | spec'd, not implemented (arabic variant still ships Amiri) | first FD40–4F honorific, or next arabic-variant build |

The **semantic block grammar** (verse/blockquote/list/epigraph) is NOT spec'd here — it
was implemented directly (see NOTES.md and the `blocks:` section of book.yaml configs).

Two axes live here: **feature/parity** specs (ocr, semantic-polish, arabic-fonts) and
**reliability/QA** specs (reliability-hardening, qa-methodology), the latter added after
the 2026-07-12 implementation review argued — correctly — that several QA-integrity and
build-trust items belong *ahead* of most remaining features. commercial-parity.md's
priority ranking is the single merged order.
