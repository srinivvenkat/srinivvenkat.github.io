#!/usr/bin/env python3
"""
Precompute the homepage research word cloud from abstracts.json.

Reads ../abstracts.json (the single source of truth for publication abstracts)
and writes ../wordcloud-data.json, a small file the homepage fetches to render an
interactive, TF-IDF-weighted, theme-colored word cloud.

Run manually after editing abstracts.json:

    python3 tools/build_wordcloud.py

Python 3 standard library only -- no third-party packages, no build step. This
matches the site's zero-dependency ethos.

Design notes
------------
* IDF is computed corpus-internally: document frequency across the abstracts we
  actually have. That is the honest signal available here, and it naturally damps
  generic academic filler (terms that show up in most abstracts get a low IDF).
* Stemming is deliberately shallow (plural/-ing/-ed folding only) -- no external
  stemmer. Bigrams are detected by a light PMI-style score plus a curated
  allowlist so multi-word themes ("genomic surveillance") survive as one term.
* Weights are pre-normalized to 0..1 so the browser does no TF-IDF math at load.
"""

import json
import math
import os
import re
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = os.path.join(ROOT, "abstracts.json")
OUT = os.path.join(ROOT, "wordcloud-data.json")

# How many terms to keep in the cloud, and how many to also show on mobile.
TOP_N = 60
MOBILE_N = 40

# ---------------------------------------------------------------------------
# Career eras. Per-era weights are still emitted for possible future use, but the
# home page currently renders only the combined all-time cloud. Ranges are
# inclusive and must cover every year present in the data.
# ---------------------------------------------------------------------------
ERAS = [
    {"id": "2010-2016", "label": "2010–2016", "sub": "Early work", "lo": 0, "hi": 2016},
    {"id": "2017-2019", "label": "2017–2019", "sub": "Mobility & forecasting", "lo": 2017, "hi": 2019},
    {"id": "2020-2021", "label": "2020–2021", "sub": "COVID response", "lo": 2020, "hi": 2021},
    {"id": "2022-2023", "label": "2022–2023", "sub": "Scenario modeling & HPC", "lo": 2022, "hi": 2023},
    {"id": "2024-2026", "label": "2024–2026", "sub": "Genomics & agentic AI", "lo": 2024, "hi": 9999},
]

# ---------------------------------------------------------------------------
# Theme buckets. Curated seed keywords map a term to a research cluster; the
# first bucket (in priority order epi > networks > ml > methods) whose seeds the
# term matches wins, otherwise the term is "neutral". Colors are dark-on-white
# and WCAG-validated (see plan / tools/README.md).
# ---------------------------------------------------------------------------
# Legend / output display order. Only the five research DOMAINS plus the merged
# methods bucket appear; the domains carry distinct colors (they show the breadth
# of the work) and "methods" is a single recessive gray. "neutral" is defined for
# fallback only — it is not shown (PER_THEME_CAP is 0) and not in the legend.
THEME_ORDER = ["epi", "genomics", "migration", "social", "agri", "methods"]

# Assignment priority (see theme_for). Distinct, smaller areas are matched BEFORE
# the broad "epi"/"methods" buckets so their defining terms keep their own color
# instead of being absorbed — e.g. "genomic surveillance" -> genomics, not epi.
THEME_PRIORITY = ["genomics", "migration", "agri", "social", "methods", "epi"]

THEMES = {
    "epi": {"label": "Epidemiology", "color": "#c1121f"},
    "genomics": {"label": "Genomics & evolution", "color": "#7b2cbf"},
    "migration": {"label": "Migration & mobility", "color": "#0e7c86"},
    "social": {"label": "Social & information networks", "color": "#1a5fb4"},
    "agri": {"label": "Agriculture & ecology", "color": "#2e7d32"},
    # ML and computing methods are merged into one recessive gray: they describe
    # HOW the work is done, so they should not compete with the domain colors.
    "methods": {"label": "Methods & ML", "color": "#5b6473"},
    "neutral": {"label": "General", "color": "#9aa0ab"},
}
# Seeds are single tokens only — theme_for splits multi-word terms into words and
# matches each word, so a term like "genomic surveillance" is caught by "genomic".
# Keep the sets disjoint; priority order (above) resolves any genuine overlap.
THEME_SEEDS = {
    "epi": {
        "epidemic", "epidemics", "epidemiological", "epidemiology", "outbreak",
        "outbreaks", "influenza", "flu", "covid", "sars", "pandemic", "pandemics",
        "forecast", "forecasting", "forecasts", "surveillance", "disease",
        "diseases", "transmission", "transmissibility", "infection", "infections",
        "infectious", "vaccine", "vaccines", "vaccination", "seir", "sir",
        "hospitalization", "hospitalizations", "wastewater", "incidence",
        "prevalence", "immunity", "antibody", "seroprevalence", "mpox",
        "intervention", "interventions", "nonpharmaceutical", "quarantine",
        "projection", "projections", "spread", "resurgence", "burden",
        "health", "healthcare",
    },
    "genomics": {
        "genomic", "genomics", "genome", "genomes", "variant", "variants",
        "multivariant", "multivariants", "sequencing", "sequence", "sequences",
        "phylogenetic", "phylogenetics", "phylogeny", "lineage", "lineages",
        "mutation", "mutations", "sweep", "strain", "strains", "evolutionary",
    },
    "migration": {
        "migration", "migrant", "migrants", "displacement", "displaced",
        "refugee", "refugees", "mobility", "commute", "commuting", "commuter",
        "commuters", "travel", "movement", "movements", "ukraine",
    },
    "social": {
        "network", "networks", "node", "nodes", "influence", "diffusion",
        "dissemination", "osn", "osns", "citation", "citations", "opinion",
        "posting", "twitter", "content", "collaboration", "threshold",
        "popularity",
    },
    "agri": {
        "pest", "pests", "invasive", "invasion", "invasions", "species", "crop",
        "crops", "agriculture", "agricultural", "armyworm", "frugiperda", "weed",
        "weeds", "ecological", "ecology", "locust", "food", "commodity",
        "absoluta", "tuta", "ageratina", "adenophora", "phytosanitary",
    },
    # Methods & ML combined: computational methods and machine-learning terms
    # share a single (recessive) theme.
    "methods": {
        "simulation", "simulations", "stochastic", "computational", "hpc",
        "scalable", "pipeline", "optimization", "parallel", "performance",
        "framework", "algorithmic", "compartmental", "mechanistic", "numerical",
        "supercomputing", "benchmark", "scenario", "scenarios", "digital",
        "sensitivity", "uncertainty", "metapopulation",
        "machine", "learning", "neural", "agentic", "agent", "agents",
        "ensemble", "ensembles", "bayesian", "calibration", "deep", "algorithm",
        "algorithms", "ai", "llm", "llms", "regression", "gaussian", "inference",
        "generative", "predictive", "classifier", "reinforcement", "gnn",
    },
}

# Per-theme cap on how many terms enter the cloud. This is the core of the
# "balanced" selection: instead of the global top-N (which the largest topic
# dominates), take the strongest few terms from EACH area so the cloud reads as
# a map of the whole portfolio. Sum is ~TOP_N; small areas simply contribute
# fewer if they have fewer distinctive terms.
PER_THEME_CAP = {
    "epi": 9, "genomics": 8, "migration": 8, "social": 9,
    "agri": 8, "methods": 10, "neutral": 0,
}

# Bigrams to always keep as a single term when they occur (subject to df guard),
# even if the PMI score is modest.
BIGRAM_ALLOWLIST = {
    "contact network", "disease surveillance", "agent based", "machine learning",
    "genomic surveillance", "human mobility", "scenario modeling", "time series",
    "public health", "infectious disease", "data driven", "nonpharmaceutical intervention",
    "high performance", "deep learning", "situational awareness", "seasonal influenza",
    "social distancing", "digital surveillance", "vaccine allocation",
    "forced migration", "human movement", "invasive species", "food flow",
    "commodity flow", "food trade", "social network", "social media",
    "information dissemination", "content spread", "selective sweep",
    "linear threshold", "neural network",
}

# General + academic stopwords. Intentionally broad: filler that would otherwise
# dominate a raw-frequency cloud. Edit freely; order does not matter.
STOPWORDS = set("""
a an the and or but if then else for while of to in on at by with without within into onto from up down over under again further this that these those here there all any both each few more most other some such no nor not only own same so than too very can will just should now
we our us i you your they them their he she it its his her who whom which what when where why how
is are was were be been being have has had do does did doing would could may might must shall can
paper papers study studies work works result results show shows showed shown using use used uses based approach approaches method methods methodology model models modeling modelling propose proposed proposes present presents presented presenting provide provides provided introduce introduces develop developed developing consider considered given give gives given
also however thus therefore hence moreover furthermore additionally although though whether either neither
one two three four five first second third new novel recent current existing different various several many multiple single common general specific particular important significant significantly high low large small key main major minor overall total number numbers set sets case cases example examples due including include includes included well able across between among against
data datasets dataset value values level levels rate rates time times year years day days week weeks month months period periods scale scales range ranges order orders type types kind form forms part parts point points area areas region regions
find found finding findings observe observed observation observations demonstrate demonstrated evaluate evaluated evaluation analysis analyses analyze analyzed compare compared comparison estimate estimated estimation measure measured obtain obtained achieve achieved report reported apply applied application applications
effect effects impact impacts change changes increase increases increased decrease decreases reduce reduced reducing improve improved improving perform performance
system systems process processes function functions structure structures problem problems solution solutions
et al fig figure table section eg ie vs per via non pre post
paper's study's abstract chapter covers starts details describes
january february march april may june july august september october november december
monday tuesday wednesday thursday friday saturday sunday
google scholar crossref pubmed scopus doi org www http https com html media url link links
copyright preprint preprints license licensed licence perpetuity certified peer review reviewed
published publish publisher publishing accessed access posted posting available display
grant grants granted grantee funded funder funders funding award awards acknowledge acknowledgment acknowledgements
university institute department college school foundation center centre supported
date dated cdc who nih fig et al eg ie
during individual individuals state states united unit projection projections death deaths
dynamic quantity quantities aim aimed goal goals context settings setting
support strategy strategies predict design designed limit limited challenge challenges
research effective effectively realistic interest interested interesting better best
million millions national content influence influences influenced
even through suggest suggests suggested understand understanding understood depend depends
author authors information insight insights toward towards regarding
allow allows allowing team teams group groups future decision decisions
""".split())

WORD_RE = re.compile(r"[a-z][a-z\-]*[a-z]|[a-z]")

# Reference / license / boilerplate scrubbing applied before tokenizing. Some
# abstracts (especially preprints and one citation-laden record) carry embedded
# bibliographies, DOIs, "Google Scholar / Date accessed" runs, and license
# footers that would otherwise flood the cloud with non-research terms.
BOILERPLATE_RES = [
    re.compile(r"https?://\S+", re.I),                       # bare URLs
    re.compile(r"www\.\S+", re.I),
    re.compile(r"10\.\d{4,9}/\S+"),                          # DOI strings
    re.compile(r"google scholar", re.I),
    re.compile(r"date accessed[:\s].*?(?=[A-Z]|$)", re.I),   # "Date accessed: May 19, 2022"
    re.compile(r"date:\s*\d{4}", re.I),
    re.compile(r"view in article|crossref|pubmed|scopus", re.I),
    re.compile(r"the copyright holder for this preprint.*?license\.?", re.I | re.S),
    re.compile(r"(is|was) made available under a[^.]*license\.?", re.I),
    re.compile(r"who (has )?granted medrxiv[^.]*\.", re.I),
]


def clean_text(text):
    for rx in BOILERPLATE_RES:
        text = rx.sub(" ", text)
    return text


def tokenize(text):
    """Lowercase, split on non-letters, keep internal hyphens, drop short/numeric."""
    text = clean_text(text).lower()
    # Normalize unicode dashes to spaces so word boundaries are clean, but keep
    # ASCII hyphens inside words (agent-based).
    text = text.replace("–", " ").replace("—", " ").replace("/", " ")
    raw = WORD_RE.findall(text)
    toks = []
    for w in raw:
        w = w.strip("-")
        if len(w) < 3:
            continue
        if w in STOPWORDS:
            continue
        toks.append(w)
    return toks


def fold(word, vocab):
    """Shallow suffix folding: map a plural/gerund/past form onto its stem when
    the stem (>=4 chars) also appears in the corpus vocabulary. Returns the
    canonical stem or the word unchanged."""
    for suf in ("ies", "es", "s", "ing", "ed"):
        if word.endswith(suf) and len(word) - len(suf) >= 4:
            stem = word[: -len(suf)]
            if suf == "ies":
                stem = stem + "y"
            if stem in vocab:
                return stem
    return word


def theme_for(term):
    # Split on spaces and hyphens so "agent-based" matches the "agent" seed and
    # "genomic surveillance" matches "genomic". Themes are tried in priority order
    # (distinct areas before the broad epi/methods buckets).
    parts = re.split(r"[\s\-]+", term)
    for theme in THEME_PRIORITY:
        seeds = THEME_SEEDS[theme]
        for p in parts:
            if p in seeds:
                return theme
    return "neutral"


def era_index(year):
    for i, era in enumerate(ERAS):
        if era["lo"] <= year <= era["hi"]:
            return i
    return None


def main():
    with open(SRC, encoding="utf-8") as f:
        data = json.load(f)

    entries = data["entries"]

    # Per-document token lists (unigrams), keyed by the publication key.
    docs = {}
    doc_year = {}
    for key, e in entries.items():
        abstract = e.get("abstract")
        if not abstract:
            continue
        # Include the title too -- it is authored, on-topic, and boosts signal
        # for the ~12 papers whose abstracts are missing elsewhere.
        text = (e.get("title", "") + ". ") + abstract
        toks = tokenize(text)
        docs[key] = toks
        try:
            doc_year[key] = int(str(e.get("year", "")).strip()[:4])
        except (ValueError, TypeError):
            doc_year[key] = 0

    n_docs = len(docs)

    # Build a vocabulary for suffix folding (a token can fold only onto a stem
    # that itself occurs). Then re-map every doc's tokens through the folder.
    vocab = set()
    for toks in docs.values():
        vocab.update(toks)
    for key in docs:
        docs[key] = [fold(w, vocab) for w in docs[key]]

    # ------------------------------------------------------------------
    # Bigram detection. Count adjacent token pairs; keep a pair as a phrase
    # when it is in the allowlist, or its document frequency >= 3 and its
    # PMI-style score clears a threshold. Then rewrite docs so a kept phrase
    # replaces its two constituent unigrams (avoids double counting).
    # ------------------------------------------------------------------
    uni_count = Counter()
    for toks in docs.values():
        uni_count.update(toks)

    pair_count = Counter()
    pair_docs = defaultdict(set)
    for key, toks in docs.items():
        for a, b in zip(toks, toks[1:]):
            pair = (a, b)
            pair_count[pair] += 1
            pair_docs[pair].add(key)

    total_uni = sum(uni_count.values()) or 1
    keep_phrases = {}
    for pair, c in pair_count.items():
        a, b = pair
        phrase = a + " " + b
        df = len(pair_docs[pair])
        allow = phrase in BIGRAM_ALLOWLIST or (a + " " + b) in BIGRAM_ALLOWLIST
        if allow and df >= 2:
            keep_phrases[pair] = phrase
            continue
        if df >= 3 and c >= 3:
            # PMI-ish: co-occurrence lift over independent expectation.
            pa = uni_count[a] / total_uni
            pb = uni_count[b] / total_uni
            pab = c / total_uni
            if pa > 0 and pb > 0:
                score = pab / (pa * pb)
                if score >= 30:  # empirically separates phrases from chance adjacency
                    keep_phrases[pair] = phrase

    def rewrite(toks):
        out = []
        i = 0
        while i < len(toks):
            if i + 1 < len(toks) and (toks[i], toks[i + 1]) in keep_phrases:
                out.append(keep_phrases[(toks[i], toks[i + 1])])
                i += 2
            else:
                out.append(toks[i])
                i += 1
        return out

    for key in docs:
        docs[key] = rewrite(docs[key])

    # ------------------------------------------------------------------
    # TF-IDF over the rewritten corpus.
    # ------------------------------------------------------------------
    # Corpus frequency is aggregated with per-document sublinear damping:
    # each document contributes (1 + log(count)) for a term, not its raw count.
    # This keeps one very long, citation-heavy abstract from dominating the cloud
    # with terms that are really specific to that single paper.
    corpus_freq = defaultdict(float)
    df_count = Counter()
    term_keys = defaultdict(list)
    for key, toks in docs.items():
        counts = Counter(toks)
        for t, c in counts.items():
            corpus_freq[t] += 1.0 + math.log(c)
            df_count[t] += 1
            term_keys[t].append(key)

    # Gentle IDF (capped rarity reward) so recurring, cross-paper themes rank
    # above single-paper jargon while universal filler is still damped.
    def idf(t):
        return math.log(1.0 + n_docs / (df_count[t] + 1.0))

    def is_phrase(t):
        return " " in t

    scored = []
    for t, cf in corpus_freq.items():
        df = df_count[t]
        if is_phrase(t):
            if df < 3:  # multi-word phrases need firmer support
                continue
        else:
            if df < 2:  # a term must recur across >= 2 papers, not a one-off
                continue
            if len(t) < 4:
                continue
        weight = cf * idf(t)
        scored.append((t, weight))

    scored.sort(key=lambda x: x[1], reverse=True)
    if not scored:
        raise SystemExit("No terms survived filtering -- check abstracts.json")

    # ------------------------------------------------------------------
    # Balanced selection: bucket every surviving term by theme, then take the
    # strongest few per theme (PER_THEME_CAP). This is what surfaces smaller
    # areas — migration, genomics, agriculture — that a global top-N would bury
    # under the much larger COVID/forecasting corpus.
    # ------------------------------------------------------------------
    themed = defaultdict(list)
    for t, w in scored:  # scored is already sorted, so each bucket stays ranked
        th = theme_for(t)
        themed[th].append((t, w, th))
    selected = []
    for theme, cap in PER_THEME_CAP.items():
        selected.extend(themed.get(theme, [])[:cap])
    if not selected:
        raise SystemExit("No terms selected -- check theme seeds / caps")

    # Per-theme size normalization: divide each term's weight by the top weight
    # in its own theme, so every area gets a comparably-sized flagship word and
    # no single topic visually dominates. Within-theme proportions are preserved.
    # "neutral" (General) is damped so generic filler stays background, never a
    # headline-sized word competing with a real research theme.
    NEUTRAL_SCALE = 0.7
    theme_max = defaultdict(float)
    for t, w, th in selected:
        if w > theme_max[th]:
            theme_max[th] = w
    disp = [
        (t, (w / (theme_max[th] or 1.0)) * (NEUTRAL_SCALE if th == "neutral" else 1.0), th)
        for t, w, th in selected
    ]
    # Order by display weight so the biggest words place first and the mobile
    # subset keeps each theme's flagship.
    disp.sort(key=lambda x: x[1], reverse=True)
    disp = disp[:TOP_N]

    # ------------------------------------------------------------------
    # Per-era term frequency, with the GLOBAL idf held fixed so a term's
    # distinctiveness is stable. Retained in the data for possible future use;
    # the page currently renders only the combined all-time cloud.
    # ------------------------------------------------------------------
    era_cf = [defaultdict(float) for _ in ERAS]
    for key, toks in docs.items():
        idx = era_index(doc_year.get(key, 0))
        if idx is None:
            continue
        counts = Counter(toks)
        for t, c in counts.items():
            era_cf[idx][t] += 1.0 + math.log(c)

    era_weight_raw = []  # per era: {term: weight}
    for i, _ in enumerate(ERAS):
        col = {}
        for t, _dw, _th in disp:
            cf = era_cf[i].get(t, 0.0)
            col[t] = cf * idf(t) if cf > 0 else 0.0
        era_weight_raw.append(col)
    era_max = [max(col.values()) if any(col.values()) else 1.0 for col in era_weight_raw]

    terms_out = []
    for rank, (t, dw, th) in enumerate(disp):
        era_weights = []
        for i, _ in enumerate(ERAS):
            raw = era_weight_raw[i].get(t, 0.0)
            era_weights.append(round(raw / era_max[i], 4) if era_max[i] else 0.0)
        terms_out.append({
            "term": t,
            "weight": round(dw, 4),
            "theme": th,
            "eraWeights": era_weights,
            "keys": sorted(term_keys[t]),
            "mobile": rank < MOBILE_N,
        })

    out = {
        "_readme": (
            "Generated by tools/build_wordcloud.py from abstracts.json. Do not edit "
            "by hand -- rerun the script after changing abstracts.json. Terms are "
            "selected per-theme (balanced across research areas) and 'weight' is "
            "normalized within each theme (0..1) so every area has a comparably "
            "sized flagship word. 'keys' are '<section-id>|<number>' matching "
            "publications.html."
        ),
        "generatedFrom": "abstracts.json",
        "docCount": n_docs,
        "eras": [{"id": e["id"], "label": e["label"], "sub": e["sub"]} for e in ERAS],
        "themes": THEMES,
        "themeOrder": THEME_ORDER,
        "terms": terms_out,
    }

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
        f.write("\n")

    size_kb = os.path.getsize(OUT) / 1024
    print("Wrote %s (%.1f KB) from %d abstracts." % (os.path.relpath(OUT, ROOT), size_kb, n_docs))
    print("Top 25 terms (term | theme | weight):")
    for row in terms_out[:25]:
        print("  %-26s %-9s %.3f" % (row["term"], row["theme"], row["weight"]))
    # Theme distribution for a quick sanity check, with how many candidate terms
    # each theme had available before the per-theme cap was applied.
    dist = Counter(r["theme"] for r in terms_out)
    print("Theme distribution (shown / available):")
    for th in THEME_ORDER:
        avail = len(themed.get(th, []))
        print("  %-10s %2d / %2d" % (th, dist.get(th, 0), avail))


if __name__ == "__main__":
    main()
