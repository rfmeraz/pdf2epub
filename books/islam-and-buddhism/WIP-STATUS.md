# islam-and-buddhism: NEARLY DONE (gates 2,3 remain)

PASS: 1 epubcheck, 4 nav, 5 images, 6 reading order (±1 source-discrepancy
tolerated), 7 toc agreement 41/41, 8 furniture, 9 hyphen (15 vs source 16),
10 pua. FAIL: gate 2 at 98.44% (gate 99) and gate 3 (1 placement failure).

Remaining ~0.56% coverage deficit: residual note-excision misses (13, mostly
pp.28-32 al-Ghazali footnote pages — diacritic/seam mismatches in
_find_fuzzyish) + small essay-section seams (p.138 'ternoon=napK' — poppler
decodes some shifted runs differently from MuPDF; per-page agreement stays
>=90 so the disputed-page exclusion doesn't trigger; consider a lower
threshold or per-SEGMENT dispute detection). Gate 3's single failure: run
qa, read qa_report gate 3 lines for the note id.

Machinery all committed: shifted-CMap repair + highmap, cross-run/in-run
dehyphenation, italic-twin pstyle fold (_ps_root), role-override implies
break, generated join overrides (51) + subsection-head overrides (36),
marker-line gt excision fallback, ±1 TOC tolerance, engine-disputed page
exclusion (QA now extracts WITH agreement scores).
