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

For each of the ~92 abstracts (title + abstract text), it tokenizes, strips
reference/license/funding boilerplate, folds simple plurals/verb endings, detects a
few multi-word phrases (e.g. *genomic surveillance*), and scores terms by a TF-IDF-style
weight. Corpus frequency is aggregated with per-document damping so one long,
citation-heavy abstract can't dominate, and a gentle IDF keeps recurring cross-paper
themes above single-paper jargon. It keeps the top 60 terms, assigns each a research
theme from curated seed keywords, and records per-era weights (for the time-lapse
slider) plus the publication keys each term appears in (for the click-through filter
on `publications.html`).

### Tuning

All knobs are near the top of the script and commented:

- `STOPWORDS` — words to exclude. Add filler that slips through.
- `THEME_SEEDS` / `THEMES` — keyword→theme mapping and the (WCAG-validated) hues.
- `BIGRAM_ALLOWLIST` — multi-word phrases to always keep together.
- `ERAS` — the career year-ranges the time-lapse slider steps through.
- `TOP_N` / `MOBILE_N` — how many terms to show (and how many on small screens).

After changing anything, rerun the script and eyeball the printed top-25 list: the
terms should read like this researcher's work, not generic academic filler.

### Theme colors

The five theme hues are dark-on-white and checked for WCAG text contrast against a
white background (four are AA-normal; the brand orange is AA-large and reserved for
larger words). If you change a hue, verify its contrast ratio is at least 3:1 (aim
4.5:1) before committing. The same hex values live in `css/style.css` as
`--theme-*` tokens — keep the two in sync.
