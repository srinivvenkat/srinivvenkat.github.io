# tools/

Developer utilities for this site. Nothing here is served to visitors.

## build_wordcloud.py

Precomputes the home-page "Research Themes" word cloud from `abstracts.json`.

```bash
python3 tools/build_wordcloud.py
```

- **Input:** `../abstracts.json` (the single source of truth for publication abstracts).
- **Output:** `../wordcloud-data.json` (~37 KB) — the small file the home page fetches.
- **Requirements:** Python 3 standard library only. No packages, no build step.

**Rerun this whenever you edit `abstracts.json`** (add a paper, fix an abstract),
then commit the regenerated `wordcloud-data.json` alongside your change. The file is
committed, not generated at deploy time, so GitHub Pages needs no build.

### What it does

For each of the ~90 abstracts (title + abstract text), it tokenizes, strips
reference/license/funding boilerplate, folds simple plurals/verb endings, detects a
few multi-word phrases (e.g. *genomic surveillance*), and scores terms by a TF-IDF-style
weight. Corpus frequency is aggregated with per-document damping so one long,
citation-heavy abstract can't dominate, and a gentle IDF keeps recurring cross-paper
themes above single-paper jargon. Each surviving term is assigned a research theme
from curated seed keywords, and selection is **balanced across themes** (`PER_THEME_CAP`):
rather than a global top-N — which the large COVID/forecasting corpus would dominate —
the script takes the strongest few terms from each area so smaller areas (migration,
genomics, agriculture) stay visible. Word size is then normalized **within** each theme
so every area gets a comparably sized flagship word (General is damped so filler stays
background). It also records the publication keys each term appears in (for the
click-through filter on `publications.html`) and per-era weights (unused by the page
now, kept for possible future use).

### Tuning

All knobs are near the top of the script and commented:

- `STOPWORDS` — words to exclude. Add filler that slips through.
- `THEME_SEEDS` / `THEMES` / `THEME_PRIORITY` — keyword→theme mapping, the labels and
  (WCAG-validated) hues, and the order themes are matched in (distinct areas before the
  broad epi/methods buckets). Seeds are single tokens; keep the sets disjoint.
- `PER_THEME_CAP` — how many terms each theme may contribute (the balance knob).
- `BIGRAM_ALLOWLIST` — multi-word phrases to always keep together.
- `ERAS` — career year-ranges used for the per-era weights (currently unused by the page).
- `TOP_N` / `MOBILE_N` — overall/mobile term ceilings.

After changing anything, rerun the script and eyeball the printed per-theme
distribution (shown / available): every area should surface its defining terms, and no
single topic should crowd out the rest.

### Theme colors

Only the five research **domains** carry distinct colors (they show the breadth of the
work); the merged **Methods & ML** bucket is a single recessive gray so methodology
doesn't compete with the domains, and General is dropped from the cloud entirely
(`PER_THEME_CAP["neutral"] = 0`). The hues are dark-on-white and chosen for WCAG text
contrast against a white background. If you change a hue, verify its contrast ratio is at
least 3:1 (aim 4.5:1) before committing. The same hex values live in `css/style.css` as
`--theme-*` tokens — keep the two in sync.
