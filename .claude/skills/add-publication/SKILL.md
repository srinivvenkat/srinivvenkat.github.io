---
name: add-publication
description: Add a new publication to the LaTeX CV (SV_CV/srini_resume.tex), rebuild SV_CV.pdf, and propagate it through the whole site pipeline (abstracts.json → publications.html → authors/wordcloud/copub/coauthors). Use when the user says they have a new paper, preprint, book chapter, or conference paper accepted/published, or asks to add a publication / update the CV with a paper / sync the site to a new paper.
---

# Add a publication and resync the site

One new paper touches **eight** files across **two** git repos. Do the steps in order,
never skip the regeneration, and commit each repo separately.

## Inputs

Ask only for what is missing. Minimum viable input is a **DOI** (or arXiv/medRxiv id) —
everything else can be fetched. If the user pastes a citation with no identifier, use it
verbatim and set `url` to whatever link they give.

Confirm before writing:
- **Section** — one of `book-chapters`, `journal-articles`, `conference-papers`, `tech-reports`.
- **Year** — the year the site should group it under (publication year, not acceptance year).
- **Author list** — abbreviated initials style, with Srini as `SV`.

Fetch metadata from the DOI when you have one:

```bash
curl -sL "https://api.crossref.org/works/<DOI>" | python3 -m json.tool | head -80
# fallback: https://api.openalex.org/works/doi:<DOI>
# arXiv:    https://api.crossref.org/works fails → use https://export.arxiv.org/api/query?id_list=<ID>
```

## Step 1 — LaTeX CV (`SV_CV/srini_resume.tex`)

The relevant sections and their exact `\section{...}` headings:

| site section        | CV heading                              |
|---------------------|-----------------------------------------|
| `book-chapters`     | `\section{Book Chapters}`                |
| `journal-articles`  | `\section{Journal articles}`             |
| `conference-papers` | `\section{Conference and Workshop papers}` |
| `tech-reports`      | `\section{Technical Reports and Preprints}` |

Each list is an `etaremune` (reverse-numbered) environment, so **newest goes first** —
insert the new `\item` immediately after `\begin{etaremune}`, ahead of the current top entry.

House style, matched exactly:

```latex
\item A. Author, B. Author, $\ldots$, \textbf{SV}, $\ldots$, Z. Author, \emph{``Title of the paper''}, Venue Name, Vol(Issue), pages, Year.
```

- Srini is always `\textbf{SV}` (never spelled out).
- Truncation is `$\ldots$` (math ellipsis) — a few older lines use `\ldots`; use `$\ldots$` for new ones.
- Title goes in `\emph{`` ''}` with LaTeX curly quotes, no trailing period inside the quotes.
- Escape `&`, `%`, `_`, `#` as `\&`, `\%`, `\_`, `\#`. Use `---` for em-dashes in titles and
  wrap hyphenated all-caps names in `\mbox{}` (see the `\mbox{EPIHIPER}` line).
- Not-yet-published work: `accepted to be presented at <Venue> <Year>` or `arXiv preprint arXiv:XXXX.XXXXX`.

Build the PDF (see `latex-cv-build-workflow` — twice, for cross-references) and copy it up:

```bash
cd SV_CV && pdflatex -interaction=nonstopmode srini_resume.tex && pdflatex -interaction=nonstopmode srini_resume.tex
cp SV_CV/srini_resume.pdf SV_CV.pdf   # from repo root — the site links this copy
```

Check the log for errors (`grep -n "^!" SV_CV/srini_resume.log`) before moving on.

## Step 2 — `abstracts.json` (single source of truth)

Add one entry to `entries`, keyed `"<section-id>|<number>"` where `<number>` is
**max existing number in that section + 1** (numbering ascends oldest→newest, so
existing keys never shift). Current maxima: book-chapters 3, journal-articles 44,
conference-papers 42, tech-reports 14 — re-derive them, don't trust these.

```json
"journal-articles|45": {
  "section": "journal-articles",
  "section_label": "Journal Articles",
  "number": 45,
  "year": "2026",
  "title": "Title without quotes",
  "citation": "A. Author, ..., SV, ..., Z. Author, \"Title\", Venue (2026)",
  "url": "https://doi.org/10.xxxx/yyyy",
  "abstract": "Verbatim publisher abstract, or null.",
  "abstract_source": "Crossref",
  "abstract_unavailable_reason": null
}
```

- The abstract must be **verbatim from the publisher record** — never paraphrase, never generate.
  If none is deposited, set `abstract` and `abstract_source` to `null` and give a short
  `abstract_unavailable_reason`. `abstract_source` is one of the keys in the file's
  `abstract_sources` map (OpenAlex, Crossref, medRxiv, Semantic Scholar, arXiv).
- Blank lines (`\n\n`) separate paragraphs; `**bold**` marks structured-abstract labels.
- Do **not** hand-write `author_count` / `consortium_paper` — `build_authors.py` fills those in.
- Update the `counts` block (`entries`, `with_abstract` / `without_abstract`) and bump the
  matching `abstract_sources` tally.

## Step 3 — `publications.html`

Two edits, both by hand:

1. The TOC count at the top: `<a href="#journal-articles">Journal Articles (45)</a>`.
2. The entry itself, inside the right `<section id="...">`. Entries are grouped under
   `<h3 class="pub-year">YYYY</h3>` headings, each with its own `<ol class="pub-list">`,
   newest year first. If the year already has a group, add the `<li>` at the top of it;
   if not, create a new `<h3>` + `<ol>` pair above the current newest group.

```html
<li value="45">A. Author, ..., SV, ..., Z. Author, "<a href="https://doi.org/10.xxxx/yyyy" target="_blank" rel="noopener noreferrer">Title</a>", <em>Venue Name</em>, 123(4), e2521031123, 2026</li>
```

The `value` must equal the `number` in `abstracts.json` — that pairing is what
`js/abstracts.js` and the click-through filters key on. Use HTML entities for dashes
(`&ndash;`, `&mdash;`) and `&amp;`. Keep the site's no-em-dash rule for surrounding prose.

## Step 4 — regenerate derived data (order is load-bearing)

```bash
python3 tools/build_authors.py --refresh   # needs network; also writes author_count/consortium_paper back into abstracts.json
python3 tools/build_wordcloud.py           # reads abstracts.json
python3 tools/build_copub.py               # reads authors.json; needs network
python3 tools/build_coauthors.py           # reads authors.json + copub.json — must run last
```

`build_copub.py` is the slow one (per-author OpenAlex works fetch, cached in
`tools/.openalex_works_cache.json`). Run it in the background if it takes more than a
minute. Eyeball each script's printed summary — `build_authors.py` lists
`unresolved_papers`, and a brand-new DOI often isn't in OpenAlex yet, which is expected
(the entry still renders; just note it to the user).

## Step 5 — commit both repos

They are separate repos; `SV_CV/` is gitignored by the site repo.

```bash
git -C SV_CV add -A && git -C SV_CV commit -m "add <short paper handle>"
git add SV_CV.pdf abstracts.json publications.html authors.json wordcloud-data.json copub.json coauthors-data.json
git commit -m "add <short paper handle>"
```

Commit messages: short, lowercase, no body (see `terse-commit-messages`). Push both only
when the user says so — "C&P" is standing authorization to commit and push.

## Checklist

- [ ] `\item` added at the top of the right `etaremune` in `srini_resume.tex`
- [ ] `pdflatex` run twice, log clean, `SV_CV.pdf` copied to repo root
- [ ] `abstracts.json` entry added, `counts` and `abstract_sources` updated
- [ ] `publications.html` TOC count bumped and `<li value=N>` added under the right year
- [ ] all four `tools/build_*.py` re-run **in order**
- [ ] both repos committed
