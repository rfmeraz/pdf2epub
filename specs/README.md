# specs/ — deferred-enhancement hand-off documents

Each spec is a self-contained hand-off for a future implementation session: the problem,
the evidence behind it (researched 2026-07-09; sources cited inline), a design sketch
grounded in the current architecture, integration points by file, acceptance criteria,
and explicit non-goals. Specs record *judgment already exercised* — read one before
re-litigating its decisions.

| Spec | What | Status | Trigger |
|---|---|---|---|
| [commercial-parity.md](commercial-parity.md) | Landscape: what commercial ebook-production ships that we don't (tables, math, RTL layout, output breadth, cross-refs) + priority map tying the specs below together | landscape | positioning / roadmap review |
| [ocr-witness.md](ocr-witness.md) | OCR as a third text witness for legacy/scanned PDFs | spec'd | first Distiller-era or scanned book |
| [semantic-polish.md](semantic-polish.md) | Linked index locators (#1 SHIPPED 2026-07-11); EAA/a11y conformance + Ace gate; typogrify-lite | #1 done; #2–3 spec'd | next conversion wave / EU distribution |
| [arabic-fonts.md](arabic-fonts.md) | Arabic-variant font upgrade (verified coverage matrix) | spec'd | first FD40–4F honorific, or next arabic-variant build |
| [qa-methodology.md](qa-methodology.md) | Per-page assertion gates; poppler `-remove-hyphens` second witness | spec'd | opportunistic |

The **semantic block grammar** (verse/blockquote/list/epigraph) is NOT spec'd here — it
was implemented directly (see NOTES.md and the `blocks:` section of book.yaml configs);
these four are the runners-up from the same research pass.
