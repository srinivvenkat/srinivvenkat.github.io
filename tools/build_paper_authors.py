#!/usr/bin/env python3
"""Build paper-authors.json — the full, ordered author list per publication.

publications.html condenses long author lists with an ellipsis ("..."). To let the
page reveal the full list on hover, this script emits the complete ordered author
names for every publication that resolves in OpenAlex, keyed by "<section-id>|<number>"
(matching the <section id> / <li value> in the page, same scheme as abstracts.json).

Names come verbatim from the OpenAlex records already cached by build_authors.py
(tools/.openalex_cache.json) — nothing is fetched or generated here. A paper OpenAlex
does not index falls back to tools/paper-authors-overrides.json if it has an entry
there; otherwise it is omitted and the page leaves its ellipsis as plain text. The
override is only consulted when OpenAlex has nothing, so it retires itself once the
paper is indexed.

    python3 tools/build_paper_authors.py

Input:  ./.openalex_cache.json          (populated by build_authors.py)
        ./paper-authors-overrides.json  (hand-written fallbacks)
Output: ../paper-authors.json           (committed; fetched by js/pub-authors.js)
Requires: Python 3 stdlib only.
"""
import json, os
from collections import OrderedDict

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
CACHE = os.path.join(HERE, ".openalex_cache.json")
OVERRIDES = os.path.join(HERE, "paper-authors-overrides.json")
OUT = os.path.join(REPO, "paper-authors.json")

README = (
    "Full, ordered author list per publication, keyed by '<section-id>|<entry-number>' "
    "to match the <section id> and <li value> in publications.html. js/pub-authors.js "
    "fetches this at load time and turns each condensing ellipsis ('...') in a citation "
    "into a hoverable button that reveals the complete list. Names are taken verbatim "
    "from OpenAlex (via tools/.openalex_cache.json), or, for papers OpenAlex does not "
    "index yet, from tools/paper-authors-overrides.json; anything in neither is omitted "
    "(its ellipsis stays plain text). Regenerate with tools/build_paper_authors.py."
)


def main():
    with open(CACHE) as f:
        cache = json.load(f)

    entries = OrderedDict()
    for key, blob in cache.items():
        record = (blob or {}).get("record") or {}
        authorships = record.get("authorships") or []
        names = []
        for a in authorships:
            name = ((a or {}).get("author") or {}).get("display_name")
            if name:
                names.append(name)
        if names:
            entries[key] = names

    # Fall back to hand-written lists, but only where OpenAlex gave us nothing, so an
    # override stops being consulted the moment the real record shows up.
    overrides = {}
    used_overrides = []
    if os.path.exists(OVERRIDES):
        with open(OVERRIDES) as f:
            overrides = (json.load(f) or {}).get("entries") or {}
        for key, names in overrides.items():
            if key in entries:
                continue
            if names:
                entries[key] = list(names)
                used_overrides.append(key)

    out = OrderedDict()
    out["_readme"] = README
    out["count"] = len(entries)
    out["source"] = "OpenAlex (https://openalex.org)"
    out["entries"] = entries

    with open(OUT, "w") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print("Wrote %s (%d papers with author lists)" % (OUT, len(entries)))
    if used_overrides:
        print("  from overrides: %s" % ", ".join(sorted(used_overrides)))
    stale = sorted(k for k in overrides if k not in used_overrides)
    if stale:
        print("  OVERRIDE NO LONGER NEEDED (OpenAlex now has it): %s" % ", ".join(stale))


if __name__ == "__main__":
    main()
