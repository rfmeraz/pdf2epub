# specs/ — deferred-enhancement hand-off documents

Each spec is a self-contained hand-off for a future implementation session: the problem,
the evidence behind it (researched 2026-07-09; sources cited inline), a design sketch
grounded in the current architecture, integration points by file, acceptance criteria,
and explicit non-goals. Specs record *judgment already exercised* — read one before
re-litigating its decisions.

| Spec | What | Status | Trigger |
|---|---|---|---|
| [commercial-parity.md](commercial-parity.md) | Landscape: what commercial ebook-production ships that we don't (tables, math, RTL layout, output breadth, cross-refs) + the **single re-ranked priority list** tying every spec below together (reliability items now interleaved ahead of most features) | landscape | positioning / roadmap review |
| [reliability-hardening.md](reliability-hardening.md) | The trust substrate: config integrity (FILL-ME-IN enforcement, dead-field removal, `validate`), transactional builds + provenance manifest, package identity/revision metadata, hermetic tests + CI, scoped process limits, maintainability | **§1–§4 SHIPPED 2026-07-12**; §5 (process limits) + §6 (maintainability) deferred | §5: untrusted intake; §6: characterization tests |
| [ocr-witness.md](ocr-witness.md) | OCR as a third text witness for legacy/scanned PDFs (+ era/pathology census as the cheap always-on step 1; guarded `verified-ocr` source mode) | spec'd | census: anytime (cheap); witness: first Distiller-era or scanned book |
| [semantic-polish.md](semantic-polish.md) | Linked index locators (#1 SHIPPED 2026-07-11); EAA/a11y — automated readiness gate 26 (#2 SHIPPED 2026-07-12) vs recorded manual certification (deferred); typogrify-lite (#3) | #1–2 done; manual cert + #3 spec'd | manual cert / EU distribution; #3: next wave |
| [arabic-fonts.md](arabic-fonts.md) | Arabic-variant font upgrade (verified coverage matrix) | spec'd | first FD40–4F honorific, or next arabic-variant build |
| [qa-methodology.md](qa-methodology.md) | Per-page assertion gates (#1 SHIPPED 2026-07-11 as gate 24); poppler `-remove-hyphens` witness (#2 blocked on poppler ≥ 26.05); **page-aligned fidelity — recall+precision+order+duplication (#3 SHIPPED 2026-07-12 as gate 25, gating)** | #1, #3 done; #2 blocked | #2: poppler bump |

The **semantic block grammar** (verse/blockquote/list/epigraph) is NOT spec'd here — it
was implemented directly (see NOTES.md and the `blocks:` section of book.yaml configs).

Two axes live here now: **feature/parity** specs (ocr, semantic-polish, arabic-fonts) and
**reliability/QA** specs (reliability-hardening, qa-methodology §3), the latter added after
the 2026-07-12 implementation review argued — correctly — that several QA-integrity and
build-trust items belong *ahead* of most remaining features. commercial-parity.md's priority
ranking is the single merged order.
