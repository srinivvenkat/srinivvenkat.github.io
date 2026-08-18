#!/usr/bin/env python3
"""Build ../bibtex.json: one BibTeX record per publication, for the copy buttons.

Reads ../publications.html, pulls the identifier out of each entry's link, and
fetches a BibTeX record for it -- from doi.org content negotiation for anything
with a DOI, from the arXiv Atom API for arXiv-only preprints. Writes a single
JSON file keyed "<section-id>|<entry-number>", the same scheme abstracts.json and
paper-authors.json use, so js/pub-bibtex.js can attach each record to its <li>
without re-parsing anything.

Alongside the JSON it writes ../SV_publications.bib: the same records concatenated
into one file, in page order under a comment header per section, which
publications.html offers as a single download for anyone who wants the whole list
rather than one citation at a time.

    python3 tools/build_bibtex.py            # use cache where present
    python3 tools/build_bibtex.py --refresh  # ignore cache, refetch everything
    python3 tools/build_bibtex.py --report   # list what has no identifier

Why a build step rather than fetching in the browser: doi.org sends no CORS
headers, so a page script cannot read the response at all. Baking the records in
also keeps the page fast and works offline.

Cite keys are regenerated rather than kept as the publisher sent them. Crossref
hands back keys like "Venkatramanan_2021", which collide as soon as one author
has two papers in a year; this script builds "<surname><year><first-title-word>"
and disambiguates with a/b/c suffixes, so keys are stable and legible.

Entries whose link is a Google Scholar search (a handful of older technical
reports with no DOI) have no identifier to resolve and are skipped -- pub-bibtex.js
simply renders no button for them. --report lists those.

bibtex-overrides.json (committed, next to this script) supplies hand-written
records for entries no service can resolve, keyed the same way. An override wins
over the network, so it also serves as an escape hatch when a publisher's record
is wrong. The current case is the ANNSIM paper: its DOI was never deposited with
the handle system (doi.org, Crossref, OpenAlex and Semantic Scholar all return
not-found) even though the ACM page it links to is live, so there is nothing to
fetch and the record is transcribed from the CV citation.

Because those keys are entry numbers, renumbering a section silently re-points
every override in it at whatever paper now holds that number -- which is how the
ANNSIM and epiDAMIK records ended up attached to two unrelated papers. Each
override's title is therefore checked against the entry it lands on, and a
mismatch is reported as MISAIMED and exits non-zero rather than being applied.

The cache (.bibtex_cache.json, gitignored) is keyed by identifier, so a re-run
after adding one paper makes exactly one network call.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from html import unescape

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HTML = os.path.join(ROOT, "publications.html")
OUT = os.path.join(ROOT, "bibtex.json")
BIB = os.path.join(ROOT, "SV_publications.bib")
CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".bibtex_cache.json")
OVERRIDES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bibtex-overrides.json")

UA = "srinivvenkat.github.io bibtex builder (mailto:srini@virginia.edu)"
PAUSE = 0.4  # be polite to doi.org / arXiv

# Words that never carry meaning in a cite key.
STOP = {"a", "an", "the", "on", "of", "in", "for", "to", "and", "with", "using",
        "towards", "toward", "from", "at", "by", "into", "via"}


def fetch(url, accept=None):
    """GET via curl, matching build_authors.py / build_copub.py: stdlib + curl on
    PATH, no packages. curl also uses the system trust store, which several
    python.org builds on macOS do not have."""
    cmd = ["curl", "-sS", "--fail", "--location", "--max-time", "45",
           "-A", UA]
    if accept:
        cmd += ["-H", "Accept: " + accept]
    out = subprocess.run(cmd + [url], capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError("curl rc=%d %s" % (out.returncode, out.stderr.strip()[:200]))
    return out.stdout


def identifier(href):
    """(kind, id) for a citation link, or (None, None) if it carries no identifier."""
    m = re.search(r"doi\.org/(10\.[^\s\"?#]+)", href)
    if m:
        return "doi", m.group(1).rstrip("/")
    # Publisher pages that embed the DOI in the path (ACM, medRxiv, bioRxiv).
    m = re.search(r"/(?:doi|content)/(10\.\d{4,9}/[^\s\"?#]+?)(?:v\d+)?/?$", href)
    if m:
        return "doi", m.group(1)
    m = re.search(r"arxiv\.org/abs/([0-9.]+(?:v\d+)?)", href)
    if m:
        return "arxiv", m.group(1).split("v")[0]
    return None, None


def entries_from_html():
    """[(key, href, text)] for every <li value=N> under a <section id=...>.

    text is the citation with markup stripped, kept only so an override can be
    checked against the entry it claims to describe (see match_check)."""
    html = open(HTML, encoding="utf-8").read()
    out = []
    for sec in re.finditer(r'<section id="([^"]+)">(.*?)</section>', html, re.S):
        sid, body = sec.group(1), sec.group(2)
        for li in re.finditer(r'<li value="(\d+)">(.*?)</li>', body, re.S):
            href = re.search(r'href="([^"]+)"', li.group(2))
            text = re.sub(r"<[^>]+>", "", li.group(2))
            out.append((f"{sid}|{li.group(1)}", href.group(1) if href else "", text))
    return out


def section_titles():
    """{section-id: heading} for the four category sections, for the .bib headers."""
    html = open(HTML, encoding="utf-8").read()
    out = {}
    for m in re.finditer(r'<section id="([^"]+)">\s*<h2>(.*?)</h2>', html, re.S):
        out[m.group(1)] = unescape(re.sub(r"<[^>]+>", "", m.group(2))).strip()
    return out


def write_bib(records, items):
    """Write ../SV_publications.bib: every record concatenated, in page order.

    Same records as the JSON, just in a form BibTeX itself can read, so the page
    can offer the whole list as one download instead of 100 copy buttons. Order
    follows publications.html -- section by section, newest first within each --
    with a comment header per section, since a reader opening the file wants the
    same shape they saw on the page."""
    titles = section_titles()
    lines = [
        "% Publications of Srinivasan (Srini) Venkatramanan",
        "% https://srinivvenkat.github.io/publications.html",
        "%",
        f"% {len(records)} entries, generated {time.strftime('%Y-%m-%d')} by "
        "tools/build_bibtex.py.",
        "% Records come from doi.org and arXiv; cite keys are regenerated as",
        "% <surname><year><first-title-word>. Entries with no resolvable DOI or",
        "% arXiv id are absent.",
    ]
    section = None
    for key, _, _ in items:
        if key not in records:
            continue
        sid = key.split("|")[0]
        if sid != section:
            section = sid
            heading = titles.get(sid, sid)
            lines += ["", "% " + "-" * 68, f"% {heading}", "% " + "-" * 68]
        lines += ["", records[key]]
    open(BIB, "w", encoding="utf-8").write("\n".join(lines) + "\n")


def norm(s):
    """Comparison form: letters and digits only, lowercased. Absorbs the
    &ndash;/-- and quoting differences between a BibTeX field and the page."""
    return re.sub(r"[^a-z0-9]", "", unescape(s).lower())


def match_check(bib, text):
    """True if this record's title appears in the entry text it is keyed to.

    Override keys are entry numbers, and numbers move when a section is
    renumbered. A stale key does not miss harmlessly -- it lands on whichever
    paper now holds that number and attaches the wrong citation to it, which
    nothing else here would notice. Comparing titles turns that into an error."""
    title = field(bib, "title")
    return bool(title) and norm(title) in norm(text)


def field(bib, name):
    """Value of a BibTeX field, brace- or quote-delimited."""
    m = re.search(rf"{name}\s*=\s*\{{(.*?)\}}\s*,", bib, re.S | re.I)
    if not m:
        m = re.search(rf'{name}\s*=\s*"(.*?)"\s*,', bib, re.S | re.I)
    return re.sub(r"\s+", " ", m.group(1)).strip() if m else ""


def make_key(bib, used):
    """<surname><year><first-title-word>, disambiguated with a/b/c."""
    author = field(bib, "author")
    surname = "anon"
    if author:
        first = re.split(r"\s+and\s+", author)[0].strip()
        surname = first.split(",")[0].strip() if "," in first else first.split()[-1]
    surname = re.sub(r"[^a-z]", "", surname.lower()) or "anon"

    year = re.search(r"\b(19|20)\d{2}\b", field(bib, "year") or bib)
    year = year.group(0) if year else "nd"

    word = ""
    for tok in re.sub(r"[^a-zA-Z\s]", " ", field(bib, "title")).lower().split():
        if tok not in STOP and len(tok) > 2:
            word = tok
            break

    base = f"{surname}{year}{word}"
    key, n = base, 0
    while key in used:
        n += 1
        key = base + chr(ord("a") + n - 1)
    used.add(key)
    return key


def rekey(bib, key):
    return re.sub(r"^(\s*@\w+\s*\{)[^,]*,", rf"\g<1>{key},", bib.strip(), count=1)


def tidy(bib):
    """One field per line, two-space indent. Publishers vary wildly; this doesn't."""
    bib = re.sub(r"\s+", " ", bib.strip())
    m = re.match(r"@(\w+)\s*\{\s*([^,]+),\s*(.*)\}\s*$", bib, re.S)
    if not m:
        return bib
    typ, key, body = m.group(1).lower(), m.group(2).strip(), m.group(3)

    fields, depth, buf = [], 0, ""
    for ch in body:
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        if ch == "," and depth == 0:
            fields.append(buf.strip())
            buf = ""
        else:
            buf += ch
    if buf.strip():
        fields.append(buf.strip())

    lines = [f"@{typ}{{{key},"]
    lines += [f"  {f}," for f in fields if f]
    lines[-1] = lines[-1].rstrip(",")
    lines.append("}")
    return "\n".join(lines)


def from_arxiv(arxiv_id):
    """Build a record from the arXiv Atom API; arXiv serves no BibTeX directly."""
    xml = fetch(f"http://export.arxiv.org/api/query?id_list={arxiv_id}")
    ns = {"a": "http://www.w3.org/2005/Atom"}
    e = ET.fromstring(xml).find("a:entry", ns)
    if e is None:
        return None
    title = re.sub(r"\s+", " ", (e.findtext("a:title", "", ns) or "").strip())
    authors = [a.findtext("a:name", "", ns).strip() for a in e.findall("a:author", ns)]
    year = (e.findtext("a:published", "", ns) or "")[:4]
    names = " and ".join(
        f"{n.split()[-1]}, {' '.join(n.split()[:-1])}" if len(n.split()) > 1 else n
        for n in authors
    )
    return (
        f"@misc{{arxiv{arxiv_id},\n"
        f"  title={{{title}}},\n"
        f"  author={{{names}}},\n"
        f"  year={{{year}}},\n"
        f"  eprint={{{arxiv_id}}},\n"
        f"  archivePrefix={{arXiv}},\n"
        f"  url={{https://arxiv.org/abs/{arxiv_id}}}\n"
        f"}}"
    )


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--refresh", action="store_true", help="ignore the cache")
    ap.add_argument("--report", action="store_true",
                    help="list entries with no resolvable identifier and exit")
    args = ap.parse_args()

    cache = {}
    if os.path.exists(CACHE) and not args.refresh:
        try:
            cache = json.load(open(CACHE, encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            cache = {}

    overrides = {}
    if os.path.exists(OVERRIDES):
        overrides = json.load(open(OVERRIDES, encoding="utf-8")).get("entries", {})

    items = entries_from_html()
    skipped = [(k, h) for k, h, _ in items
               if identifier(h)[0] is None and k not in overrides]

    if args.report:
        print(f"{len(items)} entries, {len(skipped)} with neither an identifier "
              f"nor an override:")
        for k, h in skipped:
            print(f"  {k:26s} {h[:78] or '(no link)'}")
        return

    out, used, fetched, failed, overridden = {}, set(), 0, [], 0
    misaimed = [k for k in overrides if k not in {i[0] for i in items}]
    for key, href, text in items:
        # A hand-written record wins: it exists precisely because the network
        # cannot supply one, or supplied a wrong one. It only wins where it
        # belongs, though -- an override on the wrong entry is worse than none.
        if key in overrides:
            bib = overrides[key]
            if not match_check(bib, text):
                misaimed.append(key)
                continue
            out[key] = tidy(rekey(bib, make_key(bib, used)))
            overridden += 1
            continue

        kind, ident = identifier(href)
        if not kind:
            continue

        cache_key = f"{kind}:{ident}"
        bib = cache.get(cache_key)
        if bib is None:
            try:
                if kind == "doi":
                    bib = fetch(f"https://doi.org/{ident}", "application/x-bibtex")
                else:
                    bib = from_arxiv(ident)
                time.sleep(PAUSE)
                fetched += 1
            except (RuntimeError, ET.ParseError) as e:
                failed.append((key, cache_key, str(e)))
                continue
            if not bib or "@" not in bib:
                failed.append((key, cache_key, "empty response"))
                continue
            cache[cache_key] = bib

        out[key] = tidy(rekey(bib, make_key(bib, used)))

    json.dump(cache, open(CACHE, "w", encoding="utf-8"), indent=1)
    json.dump({"entries": out}, open(OUT, "w", encoding="utf-8"),
              indent=1, ensure_ascii=False)
    write_bib(out, items)

    print(f"{len(out)} records written to {os.path.relpath(OUT, ROOT)} "
          f"and {os.path.relpath(BIB, ROOT)} "
          f"({fetched} fetched, {len(out) - fetched - overridden} from cache, "
          f"{overridden} hand-written)")
    print(f"{len(skipped)} entries have no identifier "
          f"(run --report to list them)")
    for key, ident, err in failed:
        print(f"  FAILED {key} [{ident}]: {err}", file=sys.stderr)
    for key in misaimed:
        print(f"  MISAIMED OVERRIDE {key}: title does not match the entry at that "
              f"number in publications.html -- rekey it", file=sys.stderr)
    if failed or misaimed:
        sys.exit(1)


if __name__ == "__main__":
    main()
