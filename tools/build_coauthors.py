#!/usr/bin/env python3
"""Precompute the homepage co-author network from authors.json.

Reads ../authors.json (the co-author roster; itself derived from abstracts.json)
and writes ../coauthors-data.json, a small file the homepage fetches to render an
interactive force-directed "collaboration network".

    python3 tools/build_coauthors.py

Python 3 standard library only -- no third-party packages, no build step. This
matches the site's zero-dependency ethos (see tools/build_wordcloud.py).

What the graph shows
--------------------
It is an EGO network with the ego removed. The site owner co-authors with every
node, so drawing him would just be a hairball hub; instead the whole graph *is*
his collaboration circle:

  * nodes   = the owner's most frequent co-authors (>= MIN_PAPERS shared papers,
              capped at TOP_N), SIZED by how many papers they share with him.
  * color   = LENGTH OF COLLABORATION: a single-hue sequential ramp shading each
              node from light (a short-lived collaboration) to dark (a years-long
              one), by the span from our first shared paper to our latest. Tenure
              is a magnitude, so it takes a ramp, not categorical hues -- and
              unlike institution (which splits the graph into one big UVA cluster
              plus a scattered rim) it varies *within* both, so the gradient reads
              across the whole graph instead of lopsiding it.
  * edges   = papers two co-authors share WITH EACH OTHER (i.e. both appear on the
              same paper). This is what pulls real sub-communities together: the
              UVA epi group, the Northeastern crowd, the scenario-hub collaborators.

Layout is precomputed here (Fruchterman-Reingold with weighted edges, gravity, and
hard collision so bubbles pack without overlapping) so the browser only renders and
handles interaction -- the same division of labor as the word cloud.

Regenerate after authors.json changes (which itself follows an abstracts.json edit;
see tools/README.md).
"""
import json
import math
import os
import random
import re
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = os.path.join(ROOT, "authors.json")
OUT = os.path.join(ROOT, "coauthors-data.json")

# --- node selection --------------------------------------------------------
MIN_PAPERS = 2     # a co-author needs at least this many shared papers to appear
TOP_N = 50         # ...and we keep at most this many (largest first)

# --- edge selection --------------------------------------------------------
EDGE_MIN = 2           # draw an edge only when two co-authors share >= this many papers
MAX_EDGES_PER_NODE = 5 # keep only each node's few strongest ties, so the graph reads
                       # as clusters rather than a hairball. Genuine hubs (co-authors
                       # on nearly everything) still accrue high degree -- that is the
                       # true story -- but nobody contributes more than a few weak ties.

# --- node sizing (logical units; the viewBox is derived from final extents) --
R_MIN = 15.0
R_MAX = 46.0
SIZE_EXP = 0.5     # radius ~ paper_count**SIZE_EXP (0.5 => area ~ paper_count)

# --- layout ----------------------------------------------------------------
CANVAS_W = 1040.0
CANVAS_H = 600.0
ITERS = 900
SEED = 20240607    # fixed so the committed layout is reproducible
COLLIDE_PAD = 9.0  # min gap between bubble edges (breathing room for labels)
# Anisotropic gravity (vertical > horizontal) spreads the graph into a landscape
# blob so it fills the wide homepage container instead of a tall central column.
# It is firm enough to keep edge-less outliers (early-career co-authors with no
# strong tie to the epi cluster) tucked in as satellites rather than flung wide.
GRAVITY_X = 0.020
GRAVITY_Y = 0.048
ISOLATE_GRAVITY = 7.0   # extra centre-pull for edge-less nodes (tuck them in)
# The collision step pushes overlapping bubbles apart isotropically, which rounds
# the settled pack toward a near-square blob -- and a square graph, dropped into the
# wide homepage panel, gets shrunk by the CSS max-height and stranded between big
# side margins. So after the sim we FIT the layout to a landscape aspect by spreading
# it horizontally about its centre (see fit_aspect). Scaling x *apart* only ever
# increases gaps, so it can't reintroduce overlaps, and being the last step nothing
# re-rounds it. The word cloud fills its panel the same way (a landscape canvas).
TARGET_ASPECT = 2.15  # width:height for the node centres; lands the final viewBox
                      # (which adds equal margins, and whose radii aren't scaled)
                      # near ~2.0, so the graph fills the ~900px panel under max-height

# --- tenure ramp (sequential) ----------------------------------------------
# Nodes are shaded by LENGTH OF COLLABORATION -- the span in years from our first
# shared paper to our latest. That is a magnitude, so it takes a single-hue
# sequential ramp (light = short, dark = long), never categorical hues. Institution
# coloring is inherently lopsided here (half the graph is one UVA cluster), whereas
# tenure varies within both the core and the rim, so the gradient reads across the
# whole graph. There is no legend by design -- shade reads as ambient depth-of-tie.
#
# The ramp is the site blue, floored at a mid-light step: anything paler vanishes
# against the white page and can't back a label. It deepens toward navy for the
# longest ties. Labels sit INSIDE the bubbles, so the lighter half of the ramp
# can't carry white text -- each node emits `pale` when its fill is too light, and
# the renderer flips that label to dark ink (see coauthors.js / .cn-label-dark).
RAMP = [  # site blue, light -> dark (validated sequential steps, monotone lightness)
    "#86b6ef", "#6da7ec", "#5598e7", "#3987e5", "#2a78d6",
    "#256abf", "#1c5cab", "#184f95", "#104281", "#0d366b",
]
SPAN_MIN = 2       # spans clamp to [SPAN_MIN, SPAN_MAX] before mapping onto the ramp
SPAN_MAX = 10      # (the observed range; keeps the common 3-5 band spread over steps)
MISSING_SPAN = 4   # fallback shade for a node with no usable year data (~ the median)
PALE_CONTRAST = 3.0  # white-on-fill WCAG contrast below this => dark label instead


def slugify(s):
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")


def short_name(name):
    """Last token of the name, for labelling small bubbles that can't fit the
    full name. Handles hyphenated surnames ('Rainwater-Lovett')."""
    toks = [t for t in re.split(r"\s+", name.strip()) if t]
    return toks[-1] if toks else name


def select_nodes(authors):
    cand = [a for a in authors
            if not a.get("is_self") and not a.get("consortium_only")
            and a.get("paper_count", 0) >= MIN_PAPERS]
    cand.sort(key=lambda a: (-a["paper_count"], a["name"].lower()))
    return cand[:TOP_N]


def collab_span(a):
    """Length of the collaboration in years: last shared paper minus first. None
    when the year data is missing or inconsistent."""
    fy, ly = a.get("first_year"), a.get("last_year")
    if not fy or not ly or ly < fy:
        return None
    return ly - fy


def tenure_color(span):
    """Map a collaboration span onto the sequential ramp (clamped to [MIN,MAX])."""
    s = MISSING_SPAN if span is None else max(SPAN_MIN, min(SPAN_MAX, span))
    frac = (s - SPAN_MIN) / (SPAN_MAX - SPAN_MIN)
    return RAMP[int(round(frac * (len(RAMP) - 1)))]


def _rel_lum(hexcolor):
    ch = [int(hexcolor[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in ch]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def is_pale(hexcolor):
    """True when white text on this fill falls below PALE_CONTRAST -- i.e. the
    bubble is light enough that its label must flip to dark ink."""
    return (1.05 / (_rel_lum(hexcolor) + 0.05)) < PALE_CONTRAST


def build_edges(nodes):
    """Weight between two co-authors = number of papers they share. Kept when the
    weight clears EDGE_MIN and the edge is among the strongest for BOTH endpoints."""
    keysets = [set(p["key"] for p in n["papers"]) for n in nodes]
    raw = []  # (i, j, weight)
    for i in range(len(nodes)):
        for j in range(i + 1, len(nodes)):
            w = len(keysets[i] & keysets[j])
            if w >= EDGE_MIN:
                raw.append((i, j, w))

    # Rank each node's incident edges; keep an edge only if it is within the top
    # MAX_EDGES_PER_NODE for at least one endpoint (a strong tie one side cares
    # about survives even if the other side is a busy hub).
    incident = {i: [] for i in range(len(nodes))}
    for idx, (i, j, w) in enumerate(raw):
        incident[i].append((w, idx))
        incident[j].append((w, idx))
    keep_idx = set()
    for i, lst in incident.items():
        lst.sort(reverse=True)
        for _w, idx in lst[:MAX_EDGES_PER_NODE]:
            keep_idx.add(idx)
    return [raw[idx] for idx in sorted(keep_idx)]


def layout(nodes, edges, radii):
    """Fruchterman-Reingold with weighted edge attraction, mild gravity toward the
    centre, and per-step collision resolution so bubbles pack without overlapping."""
    rng = random.Random(SEED)
    n = len(nodes)

    # Nodes with no kept edge (early-career co-authors with no strong tie to the
    # rest of the set) feel only repulsion + gravity, so they drift to a far
    # equilibrium and waste canvas. Give them a much firmer pull to the centre so
    # collision seats them as satellites on the cluster rim instead.
    degree = [0] * n
    for i, j, _w in edges:
        degree[i] += 1
        degree[j] += 1
    grav_mult = [ISOLATE_GRAVITY if degree[i] == 0 else 1.0 for i in range(n)]
    area = CANVAS_W * CANVAS_H
    k = 0.75 * math.sqrt(area / max(n, 1))   # natural spring length

    # Seed on a small centred circle (deterministic).
    px = [0.0] * n
    py = [0.0] * n
    for i in range(n):
        ang = 2 * math.pi * i / n + rng.uniform(-0.15, 0.15)
        r = rng.uniform(0.05, 0.35) * min(CANVAS_W, CANVAS_H)
        px[i] = math.cos(ang) * r
        py[i] = math.sin(ang) * r

    # Edge attraction is amplified for heavier ties so tight collaborators sit closer.
    ew = [1.0 + math.log(w) for (_i, _j, w) in edges]

    t = 0.12 * CANVAS_W   # temperature (max displacement per step), cooled linearly
    for step in range(ITERS):
        dx = [0.0] * n
        dy = [0.0] * n

        # Repulsion between every pair (k^2 / d), damped at very small distances.
        for i in range(n):
            for j in range(i + 1, n):
                ox = px[i] - px[j]
                oy = py[i] - py[j]
                d2 = ox * ox + oy * oy
                if d2 < 1e-6:
                    ox, oy = rng.uniform(-1, 1), rng.uniform(-1, 1)
                    d2 = ox * ox + oy * oy
                d = math.sqrt(d2)
                f = (k * k) / d
                ux, uy = ox / d, oy / d
                dx[i] += ux * f; dy[i] += uy * f
                dx[j] -= ux * f; dy[j] -= uy * f

        # Attraction along edges (d^2 / k), scaled by tie strength.
        for e, (i, j, _w) in enumerate(edges):
            ox = px[i] - px[j]
            oy = py[i] - py[j]
            d = math.hypot(ox, oy) or 1e-6
            f = (d * d) / k * ew[e]
            ux, uy = ox / d, oy / d
            dx[i] -= ux * f; dy[i] -= uy * f
            dx[j] += ux * f; dy[j] += uy * f

        # Gravity: pull everything gently toward the centre so loosely-tied nodes
        # don't drift off. It is anisotropic -- vertical pull is stronger than
        # horizontal -- so the cluster settles into a LANDSCAPE blob that fills the
        # wide homepage container (the word cloud stretches the same way).
        for i in range(n):
            dx[i] -= px[i] * GRAVITY_X * grav_mult[i] * k
            dy[i] -= py[i] * GRAVITY_Y * grav_mult[i] * k

        # Apply, capped by the current temperature.
        for i in range(n):
            d = math.hypot(dx[i], dy[i]) or 1e-6
            m = min(d, t)
            px[i] += (dx[i] / d) * m
            py[i] += (dy[i] / d) * m

        # Collision: a few relaxation passes pushing overlapping bubbles apart.
        for _ in range(2):
            for i in range(n):
                for j in range(i + 1, n):
                    ox = px[i] - px[j]
                    oy = py[i] - py[j]
                    d = math.hypot(ox, oy) or 1e-6
                    mind = radii[i] + radii[j] + COLLIDE_PAD
                    if d < mind:
                        push = (mind - d) / 2.0
                        ux, uy = ox / d, oy / d
                        px[i] += ux * push; py[i] += uy * push
                        px[j] -= ux * push; py[j] -= uy * push

        t = max(t * 0.985, 1.0)   # cool down

    return px, py


def fit_aspect(px, py, radii, target=TARGET_ASPECT):
    """Spread the settled layout horizontally so its bounding box reaches `target`
    width:height, letting it fill the wide panel. Only ever stretches x outward
    (never compresses), so bubbles keep their size and no overlaps are introduced.
    A near-square blob (aspect ~1) becomes landscape; an already-wide one is left be."""
    n = len(px)
    minx = min(px[i] - radii[i] for i in range(n))
    maxx = max(px[i] + radii[i] for i in range(n))
    miny = min(py[i] - radii[i] for i in range(n))
    maxy = max(py[i] + radii[i] for i in range(n))
    w, h = maxx - minx, maxy - miny
    if h <= 0 or w / h >= target:
        return px
    f = target * h / w
    cx = (minx + maxx) / 2.0
    return [cx + (x - cx) * f for x in px]


def main():
    doc = json.load(open(SRC, encoding="utf-8"))
    authors = doc["authors"]

    nodes = select_nodes(authors)
    if not nodes:
        raise SystemExit("No co-authors selected -- check authors.json / MIN_PAPERS")

    edges = build_edges(nodes)

    counts = [a["paper_count"] for a in nodes]
    cmin, cmax = min(counts), max(counts)
    pspan = (cmax - cmin) or 1

    def radius(c):
        norm = (c - cmin) / pspan
        return R_MIN + (R_MAX - R_MIN) * (norm ** SIZE_EXP)

    radii = [radius(a["paper_count"]) for a in nodes]

    px, py = layout(nodes, edges, radii)
    px = fit_aspect(px, py, radii)   # stretch to landscape so it fills the panel

    # Recentre to the origin, then emit rounded coordinates. The renderer derives
    # its own viewBox from node extents, so absolute placement doesn't matter.
    cx = sum(px) / len(px)
    cy = sum(py) / len(py)

    nodes_out = []
    for i, a in enumerate(nodes):
        inst = a.get("primary_affiliation") or "Unknown"
        cspan = collab_span(a)
        color = tenure_color(cspan)
        node = {
            "id": slugify(a["name"]),
            "name": a["name"],
            "short": short_name(a["name"]),
            "papers": a["paper_count"],
            "inst": inst,
            "color": color,
            "span": cspan,             # years first->last shared paper (drives shade)
            "firstYear": a.get("first_year"),
            "lastYear": a.get("last_year"),
            "x": round(px[i] - cx, 2),
            "y": round(py[i] - cy, 2),
            "r": round(radii[i], 2),
            "keys": sorted(p["key"] for p in a["papers"]),
        }
        if is_pale(color):
            node["pale"] = True        # fill too light for white text -> dark label
        nodes_out.append(node)

    edges_out = [{"a": nodes_out[i]["id"], "b": nodes_out[j]["id"], "w": w}
                 for (i, j, w) in edges]

    out = {
        "_readme": (
            "Generated by tools/build_coauthors.py from authors.json. Do not edit by "
            "hand -- rerun the script after authors.json changes. An ego network with "
            "the site owner removed: nodes are his most frequent co-authors, sized by "
            "shared-paper count ('papers'), shaded by length of collaboration -- the "
            "'span' in years from first to latest shared paper -- on a light->dark ramp "
            "('color'); 'pale' marks a fill light enough that its label flips to dark ink. "
            "edges weight how many papers two co-authors share with each other. 'x','y','r' "
            "are precomputed layout coordinates (arbitrary units; the page derives its "
            "viewBox from them). 'keys' are '<section-id>|<number>' matching "
            "publications.html so a node can filter the publication list."),
        "generatedFrom": "authors.json",
        "nodes": nodes_out,
        "edges": edges_out,
    }

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
        f.write("\n")

    size_kb = os.path.getsize(OUT) / 1024
    print("Wrote %s (%.1f KB): %d nodes, %d edges."
          % (os.path.relpath(OUT, ROOT), size_kb, len(nodes_out), len(edges_out)))
    deg = Counter()
    for i, j, _w in edges:
        deg[i] += 1; deg[j] += 1
    isolated = [nodes_out[i]["name"] for i in range(len(nodes)) if deg[i] == 0]
    print("Top nodes (papers | span yrs | institution):")
    for a in nodes_out[:12]:
        print("  %-26s %3d  %4s  %s"
              % (a["name"], a["papers"], a.get("span"), a["inst"]))
    spans = [a["span"] for a in nodes_out if a.get("span") is not None]
    if spans:
        print("Collaboration span: %d-%d yrs (median %d)"
              % (min(spans), max(spans), sorted(spans)[len(spans) // 2]))
    npale = sum(1 for a in nodes_out if a.get("pale"))
    print("Shade ramp: %d steps; %d pale nodes (dark label)" % (len(RAMP), npale))
    if isolated:
        print("Isolated (no kept edge): %s" % ", ".join(isolated))


if __name__ == "__main__":
    main()
