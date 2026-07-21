#!/usr/bin/env python3
"""Build authors.json — the co-author roster — from abstracts.json.

For every publication with a resolvable DOI / arXiv / medRxiv id, the full author
list, full author names, and institutional affiliations are fetched from OpenAlex
(api.openalex.org, keyed by DOI). Names, affiliations, and author identities come
verbatim from OpenAlex; nothing is generated. Raw responses are cached next to this
script so reruns don't re-hit the API.

    python3 tools/build_authors.py            # use cache where present
    python3 tools/build_authors.py --refresh  # ignore cache, refetch everything

Input:  ../abstracts.json      (single source of truth for publications)
Output: ../authors.json        (committed; the file an author visualization fetches)
Requires: Python 3 stdlib + `curl` on PATH. No packages, no build step.
"""
import json, os, re, sys, time, subprocess, html
from collections import OrderedDict, Counter
from urllib.parse import urlparse, quote

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
ABSTRACTS = os.path.join(REPO, "abstracts.json")
OUT = os.path.join(REPO, "authors.json")
CACHE = os.path.join(HERE, ".openalex_cache.json")   # gitignored
MAILTO = "srini@virginia.edu"
REFRESH = "--refresh" in sys.argv


# --------------------------------------------------------------------------- fetch
def get(url):
    full = url + ("&" if "?" in url else "?") + "mailto=" + MAILTO
    out = subprocess.run(["curl", "-sS", "--fail", "--max-time", "30", full],
                         capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError("curl rc=%d %s" % (out.returncode, out.stderr.strip()[:200]))
    return json.loads(out.stdout)


def norm_title(t):
    return re.sub(r"[^a-z0-9]+", " ", (t or "").lower()).strip()


def extract_doi(url):
    """Best-effort DOI (or DOI-shaped id) from an entry url; None if not derivable."""
    u = urlparse(url)
    if u.netloc == "doi.org":
        return u.path.lstrip("/")
    if u.netloc == "dl.acm.org" and u.path.startswith("/doi/"):
        return u.path[len("/doi/"):]
    if u.netloc == "www.medrxiv.org":
        m = re.search(r"/content/(10\.[^/]+/[^/v]+)", u.path)
        if m:
            return m.group(1)
    if u.netloc == "arxiv.org":
        m = re.search(r"/abs/([^/]+)", u.path)
        if m:
            return "10.48550/arXiv." + m.group(1)
    return None


def fetch_records(entries):
    cache = {} if REFRESH else (json.load(open(CACHE)) if os.path.exists(CACHE) else {})
    for key, v in entries.items():
        if key in cache and cache[key].get("record") is not None:
            continue
        url = v.get("url") or ""
        doi = extract_doi(url)
        rec = method = None
        try:
            if doi:
                try:
                    rec = get("https://api.openalex.org/works/https://doi.org/" + quote(doi))
                    method = "doi"
                except Exception:
                    rec = None
            if rec is None:  # title-search fallback, verified by author/title match
                q = get("https://api.openalex.org/works?per_page=3&search=" + quote(v["title"]))
                for cand in q.get("results", []):
                    names = " ".join(a["author"].get("display_name", "")
                                     for a in cand.get("authorships", []))
                    if "venkatramanan" in names.lower() or \
                       norm_title(cand.get("display_name")) == norm_title(v["title"]):
                        rec, method = cand, "search"
                        break
        except Exception as ex:
            print("ERR", key, ex, file=sys.stderr)
        cache[key] = {"doi": doi, "url": url, "method": method, "record": rec}
        json.dump(cache, open(CACHE, "w"))
        time.sleep(0.15)
    return cache


# ----------------------------------------------------------------------- aggregate
# Affiliation normalization ---------------------------------------------------
# OpenAlex affiliation strings need three kinds of cleanup: (1) known bad
# institution links, (2) raw affiliation strings that carry department prefixes and
# postal addresses, and (3) HTML entities. Keys below are matched AFTER html.unescape
# and whitespace/trailing-';' trimming. This map is intentionally explicit (not a
# regex) so every rewrite is auditable; add new messy strings here as papers are added.
AFFIL_REMAP = {
    # systematic OpenAlex mislink: "Biocom" == UVA Biocomplexity Institute
    "Biocom": "University of Virginia",
    # raw-string fallbacks -> core organization
    "Metaculus, Santa Cruz, CA, USA": "Metaculus",
    "Amplitude, San Francisco, CA, USA": "Amplitude",
    "Meta AI, Paris, France": "Meta AI",
    "Meta AI, New York, NY, USA": "Meta AI",
    "Auquan, Bengaluru, KA, India": "Auquan",
    "Auquan, London, EC2A 4DP, UK": "Auquan",
    "River Hill High School, Clarksville, MD, USA": "River Hill High School",
    "Ehrlich & Fenster of the Ehrlich Group, Ramat-Gan, Israel": "Ehrlich & Fenster (Ehrlich Group)",
    "Department of Biostatistics & Center for Infectious Disease Modeling and Analysis, "
        "Yale School of Public Health, New Haven, CT 06510": "Yale University",
    "Guidehouse Advisory and Consulting Services, McClean VA, 22102": "Guidehouse",
    "Wadhwani Institute of Artificial Intelligence, Mumbai, Maharashtra, 400093, India":
        "Wadhwani Institute of Artificial Intelligence",
    "Oliver Wyman Digital, Oliver Wyman, New York, NY, 10036, USA": "Oliver Wyman",
    "Oliver Wyman Digital, Oliver Wyman, Sao Paolo, 04711-904, Brazil": "Oliver Wyman",
    "Financial Services, Oliver Wyman, New York, NY, 10036, USA": "Oliver Wyman",
    "Financial Services, Oliver Wyman, Toronto, ON, M5J 0A1, Canada": "Oliver Wyman",
    "Health & Life Sciences, Oliver Wyman, New York, NY, 10036, USA": "Oliver Wyman",
    "Health & Life Sciences, Oliver Wyman, Boston, MA, 2110, USA": "Oliver Wyman",
    "Core Consultant Group, Oliver Wyman, New York, NY, 10036, USA": "Oliver Wyman",
    "Life Sciences, JMP, LLC, Cary, NC, 27513, USA": "JMP",
    "IEM, Baton Rouge, LA, 70809": "IEM, Inc",
    "IEM, Inc, Bel Air, United States": "IEM, Inc",
    "Emerging Technologies, IEM, Inc, Bel Air, MD, 21015, USA": "IEM, Inc",
    "Emerging Technologies, IEM, Inc, Baton Rouge, LA, 70809, USA": "IEM, Inc",
    "Inverence, Madrid, Spain": "Inverence",
    # user-confirmed mislink corrections
    "University of America": "Catholic University of America",
    "Harvard University Press": "Harvard University",
    "Institute for Environmental Management": "IEM, Inc",
    "The Institute for Advanced Physics": "IEM, Inc",
    "Center for Global Health": "Case Western Reserve University",
}


def clean_affiliation(s):
    if not s:
        return None
    s = html.unescape(s).strip().rstrip(";").strip()
    if s in AFFIL_REMAP:
        return AFFIL_REMAP[s]
    # non-institution placeholders (independent / unaffiliated contributors)
    if s.lower().startswith("unaffiliated") or s.lower() == "independent researcher":
        return "Independent"
    return s


def akey(a):
    aid = (a.get("author") or {}).get("id")
    if aid:
        return aid
    nm = (a.get("author") or {}).get("display_name", "")
    return "name::" + re.sub(r"[^a-z]", "", nm.lower())


def letters(s):
    return re.sub(r"[^a-z]", "", (s or "").lower())


# Human-confirmed same-person name variants that OpenAlex splits across author ids
# (different display names and/or different ORCIDs). Maps a canonical display name to
# the other spellings seen. Merging these OVERRIDES the ORCID-conflict guard, so only
# add pairs a human has confirmed. Extend after a duplicate scan (see tools/dupscan
# workflow). Listing the canonical name among the variants is unnecessary but harmless.
NAME_ALIASES = {
    "Christopher L. Barrett": ["Chris L Barrett", "Chris Barrett"],
    "Bryan Lewis": ["Bryan R. Lewis"],
    "Jiangzhuo Chen": ["J. D.Z. Chen"],
    "Henning Mortveit": ["Henning S. Mortveit"],
    "Clifton McKee": ["Clif D. McKee"],
    "Kaitlin Rainwater-Lovett": ["Kaitlin Rainwater‐Lovett", "Kaitlin Lovett"],
    "Rita R. Colwell": ["Rita Colwell"],
    "Young Yun Baek": ["Youngyun Chung Baek"],
    "Bradley T. Suchoski": ["Brad Suchoski", "Brad T. Suchoski", "Bradley Suchoski"],
    "Alessandro Vespignani": ["Alessandro Vespigiani"],
    "Joseph C. Lemaitre": ["Joseph C Lemairtre"],
    "Nutcha Wattanachit": ["Nutcha Wattanchit"],
    "Erica C. Carcelén": ["Erica Carcelen"],
    "Steven A. Stage": ["Steve A. Stage", "Steve Stage", "Steven Stage"],
    # confirmed despite conflicting ORCIDs
    "Amanda Wilson": [],
    "Richard G. Posner": ["Richard A. Posner"],
    "Graham Gibson": ["Graham Casey Gibson"],
}
_ALIAS_LOOKUP = {}
for _canon, _variants in NAME_ALIASES.items():
    for _form in [_canon] + _variants:
        _ALIAS_LOOKUP[letters(_form)] = _canon


def is_owner(name):
    """True for the site owner under any of his OpenAlex name spellings, including
    'Srini Venkat', 'S. Venkatramanan', and OpenAlex typos ('Venaktramanan',
    'Venkataramanan'). A 'Srini' first name plus a 'Ven...' surname is unique to him."""
    letters = re.sub(r"[^a-z]", "", name.lower())
    if "venkatramanan" in letters:  # main spelling + 'S. Venkatramanan'
        return True
    toks = re.findall(r"[a-z]+", name.lower())
    return any(t.startswith("srini") for t in toks) and any(t.startswith("ven") for t in toks)


def norm_name(n):
    # collapse the site owner's name variants into one group
    if is_owner(n):
        return "__owner__"
    ltr = letters(n)
    if ltr in _ALIAS_LOOKUP:                 # confirmed same-person aliases
        return "alias::" + _ALIAS_LOOKUP[ltr]
    return ltr


def merge_nodes(nodes):
    base = nodes[0]
    ids = []
    for n in nodes:
        if n["openalex_id"]:
            ids.append(n["openalex_id"])
        if n is not base:
            base["_affil_counter"].update(n["_affil_counter"])
            base["paper_count"] += n["paper_count"]
            base["papers"].extend(n["papers"])
            for y in (n["first_year"], n["last_year"]):
                if y is not None:
                    base["first_year"] = y if base["first_year"] is None else min(base["first_year"], y)
                    base["last_year"] = y if base["last_year"] is None else max(base["last_year"], y)
            base["orcid"] = base["orcid"] or n["orcid"]
    base["openalex_ids"] = ids
    base.pop("openalex_id", None)
    return base


def build(entries, cache):
    authors = OrderedDict()
    unresolved = []
    for entry_key, meta in entries.items():
        rec = cache.get(entry_key, {}).get("record")
        if not rec:
            unresolved.append(entry_key)
            continue
        year = rec.get("publication_year") or \
            (int(meta["year"]) if str(meta.get("year", "")).isdigit() else None)
        for a in rec.get("authorships", []):
            au = a.get("author") or {}
            name = au.get("display_name")
            if not name:
                continue
            k = akey(a)
            insts = [i.get("display_name") for i in a.get("institutions", []) if i.get("display_name")] \
                or (a.get("raw_affiliation_strings") or [])
            node = authors.get(k)
            if node is None:
                node = authors[k] = {
                    "name": name, "openalex_id": au.get("id"), "orcid": au.get("orcid"),
                    "primary_affiliation": None, "affiliations": [], "_affil_counter": Counter(),
                    "paper_count": 0, "last_year": None, "first_year": None, "papers": [],
                }
            for ins in insts:
                ins = clean_affiliation(ins)
                if ins:
                    node["_affil_counter"][ins] += 1
            node["paper_count"] += 1
            if year is not None:
                node["last_year"] = year if node["last_year"] is None else max(node["last_year"], year)
                node["first_year"] = year if node["first_year"] is None else min(node["first_year"], year)
            node["papers"].append({"key": entry_key, "title": meta["title"],
                                   "year": year, "section": meta["section_label"]})

    # merge duplicate OpenAlex profiles for one person (guarded by ORCID)
    by_name = OrderedDict()
    for node in authors.values():
        by_name.setdefault(norm_name(node["name"]), []).append(node)
    merged = []
    for gkey, grp in by_name.items():
        forced = gkey == "__owner__" or gkey.startswith("alias::")  # human-confirmed
        orcids = {n["orcid"] for n in grp if n["orcid"]}
        if forced or len(orcids) <= 1:
            merged.append(merge_nodes(grp))
        else:  # conflicting ORCIDs on an organic name group -> keep people apart
            buckets = OrderedDict()
            for n in grp:
                buckets.setdefault(n["orcid"] or id(n), []).append(n)
            for b in buckets.values():
                merged.append(merge_nodes(b))

    for a in merged:
        ranked = [ins for ins, _ in a["_affil_counter"].most_common()]
        a["affiliations"] = ranked
        a["primary_affiliation"] = ranked[0] if ranked else None
        del a["_affil_counter"]
        seen, uniq = set(), []
        for p in sorted(a["papers"], key=lambda p: (-(p["year"] or 0), p["key"])):
            if p["key"] not in seen:
                seen.add(p["key"]); uniq.append(p)
        a["papers"] = uniq
        a["paper_count"] = len(uniq)
        a["is_self"] = is_owner(a["name"])
        if a["is_self"]:
            a["name"] = "Srinivasan Venkatramanan"  # canonical display name
        else:
            canon = _ALIAS_LOOKUP.get(letters(a["name"]))
            if canon:
                a["name"] = canon

    ordered = sorted(merged, key=lambda a: (-a["paper_count"], a["name"].lower()))
    return ordered, unresolved


# ---------------------------------------------------------------------------- main
def main():
    entries = json.load(open(ABSTRACTS))["entries"]
    cache = fetch_records(entries)
    authors, unresolved = build(entries, cache)

    out = OrderedDict()
    out["_readme"] = (
        "Co-author roster derived from abstracts.json. For every paper with a resolvable "
        "DOI/arXiv/medRxiv id, the full author list, full names, and institutional affiliations "
        "were retrieved from OpenAlex (api.openalex.org, keyed by DOI). paper_count and "
        "first_year/last_year are computed over the resolved papers only. Duplicate OpenAlex "
        "author profiles for the same person are merged by name unless their ORCIDs conflict; the "
        "site owner's spelling variants (incl. 'Srini Venkat' and OpenAlex typos) are unified, "
        "and a curated list of human-confirmed same-person aliases is merged even across "
        "conflicting ORCIDs. Affiliation strings are normalized (known mislinks remapped, "
        "addresses/departments/HTML-entities stripped; 'Unaffiliated' -> 'Independent'). "
        "affiliations are ranked by how often they appear (primary_affiliation = most frequent); "
        "strings occasionally reflect OpenAlex mis-linkage (e.g. 'Biocom' for the Biocomplexity "
        "Institute). Regenerate with tools/build_authors.py.")
    out["counts"] = {"authors": len(authors),
                     "papers_resolved": len(entries) - len(unresolved),
                     "papers_total": len(entries)}
    out["source"] = "OpenAlex (https://openalex.org)"
    out["unresolved_papers"] = [
        {"key": k, "title": entries[k]["title"], "url": entries[k]["url"],
         "reason": "not indexed in OpenAlex; no full author names/affiliations available"}
        for k in unresolved]
    out["authors"] = authors

    json.dump(out, open(OUT, "w"), indent=2, ensure_ascii=False)
    print("Wrote %s" % os.path.relpath(OUT, REPO))
    print("  authors:          %d" % len(authors))
    print("  papers resolved:  %d / %d" % (len(entries) - len(unresolved), len(entries)))
    if unresolved:
        print("  unresolved:       %s" % ", ".join(unresolved))


if __name__ == "__main__":
    main()
