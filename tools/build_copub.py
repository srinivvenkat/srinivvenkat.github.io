#!/usr/bin/env python3
"""Fetch full pairwise co-publication counts for the co-author network's nodes.

Reads ../authors.json, selects the same co-authors that build_coauthors.py turns
into nodes, and asks OpenAlex for EVERY work each of them has authored -- not just
the ones shared with the site owner. From those it counts, for every pair of nodes,
how many papers the two have published together anywhere, and writes ../copub.json.

    python3 tools/build_copub.py            # use cache where present
    python3 tools/build_copub.py --refresh  # ignore cache, refetch everything

Why: edges built only from the owner's own bibliography make two close colleagues
look unconnected unless the owner is on their joint papers too, which fragments the
graph into satellites. Full pairwise counts restore those real ties; the network
stays an ego network only in its NODES (who appears, and their size/shade).

Consortium-scale papers are excluded AT THE API level with an authors_count filter
(<= MAX_AUTHORS authors): a 400-author hub roster is co-membership, not a pairwise
tie, and OpenAlex truncates the author list on very large works anyway, so keeping
them would both hairball the graph and undercount silently.

The works cache (.openalex_works_cache.json, gitignored) stores one entry per
author id: {work_id: [author_ids]} -- ids only, so it stays small and a re-run
only fetches authors it hasn't seen. build_coauthors.py never touches the network;
it reads the committed copub.json this script writes (see tools/README.md).
"""
import json
import os
import re
import subprocess
import sys
import time
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = os.path.join(ROOT, "authors.json")
OUT = os.path.join(ROOT, "copub.json")
CACHE = os.path.join(HERE, ".openalex_works_cache.json")
MAILTO = "srini@virginia.edu"
REFRESH = "--refresh" in sys.argv

# Mirror build_coauthors.select_nodes so we fetch exactly the graph's node set.
MIN_PAPERS = 2
# Mirror build_authors.CONSORTIUM_AUTHOR_THRESHOLD: works with more authors than
# this are excluded server-side (filter authors_count:<MAX_AUTHORS+1).
MAX_AUTHORS = 30
# Keep a pair in copub.json only at this weight or above (floor for any edge).
W_MIN = 2


def slugify(s):
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")


def get(url):
    full = url + ("&" if "?" in url else "?") + "mailto=" + MAILTO
    out = subprocess.run(["curl", "-sS", "--fail", "--max-time", "30", full],
                         capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError("curl rc=%d %s" % (out.returncode, out.stderr.strip()[:200]))
    return json.loads(out.stdout)


def select_nodes(authors):
    cand = [a for a in authors
            if not a.get("is_self") and not a.get("consortium_only")
            and a.get("paper_count", 0) >= MIN_PAPERS]
    cand.sort(key=lambda a: (-a["paper_count"], a["name"].lower()))
    return cand


def fetch_author_works(aid, cache):
    """All works (<= MAX_AUTHORS authors) for one OpenAlex author id, as
    {work_id: [author_ids]}. Cursor-paged; cached per author id."""
    if not REFRESH and aid in cache:
        return cache[aid]
    short = aid.rsplit("/", 1)[-1]
    works = {}
    cursor = "*"
    while cursor:
        url = ("https://api.openalex.org/works?filter=author.id:%s,authors_count:%%3C%d"
               "&select=id,authorships&per-page=200&cursor=%s"
               % (short, MAX_AUTHORS + 1, cursor))
        data = get(url)
        for w in data.get("results", []):
            ids = [(a.get("author") or {}).get("id")
                   for a in w.get("authorships", [])]
            works[w["id"]] = [i for i in ids if i]
        cursor = data.get("meta", {}).get("next_cursor")
        time.sleep(0.15)
    cache[aid] = works
    json.dump(cache, open(CACHE, "w"))
    return works


def main():
    doc = json.load(open(SRC, encoding="utf-8"))
    nodes = select_nodes(doc["authors"])
    print("Fetching works for %d node authors..." % len(nodes))

    # Any of a node's (merged) OpenAlex ids resolves to its index.
    id2idx = {}
    for i, a in enumerate(nodes):
        for aid in a.get("openalex_ids") or []:
            id2idx[aid] = i

    cache = {} if REFRESH else \
        (json.load(open(CACHE)) if os.path.exists(CACHE) else {})

    # Union of every node author's works, deduped by work id.
    all_works = {}
    for n, a in enumerate(nodes):
        for aid in a.get("openalex_ids") or []:
            try:
                all_works.update(fetch_author_works(aid, cache))
            except Exception as ex:
                print("ERR %s (%s): %s" % (a["name"], aid, ex), file=sys.stderr)
        if (n + 1) % 20 == 0:
            print("  ...%d/%d authors" % (n + 1, len(nodes)))

    # Count co-publications for every pair of nodes appearing on the same work.
    pair = {}
    for ids in all_works.values():
        present = sorted({id2idx[i] for i in ids if i in id2idx})
        for x in range(len(present)):
            for y in range(x + 1, len(present)):
                k = (present[x], present[y])
                pair[k] = pair.get(k, 0) + 1

    pairs_out = [{"a": slugify(nodes[i]["name"]), "b": slugify(nodes[j]["name"]), "w": w}
                 for (i, j), w in sorted(pair.items(), key=lambda kv: -kv[1])
                 if w >= W_MIN]

    out = {
        "_readme": (
            "Generated by tools/build_copub.py from authors.json + OpenAlex. Do not "
            "edit by hand. Pairwise co-publication counts between the co-author "
            "network's nodes across ALL their works (not just papers with the site "
            "owner), excluding works with more than %d authors (consortium-scale hub "
            "papers). Pairs below w=%d are omitted. 'a'/'b' are node ids (slugified "
            "names) matching coauthors-data.json; 'w' is the number of shared works. "
            "build_coauthors.py reads this file to weight edges." % (MAX_AUTHORS, W_MIN)),
        "generated": date.today().isoformat(),
        "source": "OpenAlex (https://openalex.org)",
        "max_authors": MAX_AUTHORS,
        "pairs": pairs_out,
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
        f.write("\n")

    ws = sorted((p["w"] for p in pairs_out), reverse=True)
    print("Wrote %s (%.1f KB): %d works scanned, %d pairs (w>=%d)."
          % (os.path.relpath(OUT, ROOT), os.path.getsize(OUT) / 1024,
             len(all_works), len(pairs_out), W_MIN))
    if ws:
        print("Weights: max %d, median %d; >=10: %d, >=5: %d"
              % (ws[0], ws[len(ws) // 2],
                 sum(1 for w in ws if w >= 10), sum(1 for w in ws if w >= 5)))
    name = {slugify(a["name"]): a["name"] for a in nodes}
    print("Top pairs:")
    for p in pairs_out[:10]:
        print("  %3d  %s -- %s" % (p["w"], name[p["a"]], name[p["b"]]))


if __name__ == "__main__":
    main()
