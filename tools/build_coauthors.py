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
  * edges   = how many papers two co-authors have published together ACROSS ALL
              THEIR WORK (from copub.json, built by tools/build_copub.py against
              OpenAlex) -- not just the papers the owner is on. This is what pulls
              real sub-communities together: the UVA epi group, the Northeastern
              crowd, the scenario-hub collaborators. Counting only owner-shared
              papers fragmented the graph -- close colleagues looked unconnected
              unless the owner happened to be on their joint work. Consortium-scale
              papers (> ~30 authors) are already excluded from those counts:
              co-membership on a 400-author hub roster is not a pairwise tie.

Layout is precomputed here (Fruchterman-Reingold with weighted edges, gravity, and
hard collision so bubbles pack without overlapping) so the browser only renders and
handles interaction -- the same division of labor as the word cloud.

Regenerate after authors.json changes (which itself follows an abstracts.json edit)
and after refreshing copub.json via tools/build_copub.py; see tools/README.md.
"""
import json
import math
import os
import random
import re
from collections import deque

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = os.path.join(ROOT, "authors.json")
COPUB = os.path.join(ROOT, "copub.json")   # pairwise co-pub counts (build_copub.py)
OUT = os.path.join(ROOT, "coauthors-data.json")

# --- node selection --------------------------------------------------------
MIN_PAPERS = 2     # a co-author needs at least this many shared papers to appear
TOP_N = 1000       # ...and we keep at most this many (largest first)

# --- edge selection --------------------------------------------------------
EDGE_MIN = 2           # draw an edge only when two co-authors share >= this many papers
                       # (full-career counts from copub.json, not just owner-shared)
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
# Gravity is deliberately firm and the spring length K_FACTOR short so the pack
# compresses until COLLISION is the binding constraint -- a dense bubble chart
# with cluster structure, not a sparse repulsion equilibrium full of whitespace.
GRAVITY_X = 0.040
GRAVITY_Y = 0.095
K_FACTOR = 0.45    # fraction of the uniform-area spring length sqrt(area/n)
# After the sim, compact() nudges nodes toward the centroid with collision
# resolution -- but only until circle-area fill reaches a NOMINAL density, not a
# wall-to-wall contact pack (running it to convergence proved far too dense). The
# pull is steered each iteration: whichever axis the blob is too long on gets the
# stronger pull, so it densifies TOWARD the landscape TARGET_ASPECT and the final
# fit_aspect stretch (which would re-dilute the fill) has nothing left to do.
COMPACT_ITERS = 400
COMPACT_PULL = 0.03
COMPACT_TARGET_FILL = 0.18  # stop once sum(circle areas) / bbox area reaches this
# Centrality-weighted gravity: the graph's most central co-authors -- many shared
# papers (weight), many kept ties (degree), and high betweenness (bridges between
# clusters) -- belong in the MIDDLE of the picture. Each node's centre-pull is
# scaled by its centrality score (mean of the three, each min-max normalized), and
# the seed ring places high scorers innermost, so the sim sorts hubs inward and
# collision displaces low-centrality nodes to the rim.
GRAV_MIN_MULT = 0.5   # gravity multiplier at centrality 0 (rim dwellers)
GRAV_MAX_MULT = 2.5   # ...and at centrality 1 (the core)
# Gravity alone loses to edge attraction (heavy ties pull ~6x harder), so a hub
# still drifts to wherever its cluster sits. The RADIAL CAP is the enforcer: each
# node's distance from the layout centre -- measured elliptically, in units of the
# blob's own x/y spread -- may not exceed CAP_BASE + CAP_SPAN * (1 - centrality).
# The most central nodes are confined to the innermost ~0.6 std of the blob; rim
# dwellers get ~2.5 std (rarely binding). Applied softly every iteration of both
# the sim and the compaction, so FR keeps angles/clusters while the cap decides
# how far OUT anyone may live.
CAP_BASE = 0.6
CAP_SPAN = 1.9
CAP_STRENGTH = 0.5    # fraction of the excess radius removed per application
# Even capped-and-biased forces only sort the extremes -- edge attraction still
# scrambles the mid-centrality band. radial_sort() settles it decisively after
# the sim: each node KEEPS ITS ANGLE (clusters remain angular neighborhoods) but
# its radius is blended toward a sqrt-spaced centrality-rank target, innermost
# rank = most central. The blend leaves some of the sim's radial signal so tightly
# tied nodes don't get torn apart.
# --- communities ------------------------------------------------------------
# Communities are detected by weighted label propagation on the kept-edge graph
# (deterministic via SEED) and are the layout's FIRST-CLASS unit: a node's pull
# toward its community centroid (COMM_GRAVITY) is deliberately STRONGER than any
# centrality-based centre pull, so research groups travel as coherent blobs.
# Centrality then decides where each COMMUNITY sits -- community_sort() rigidly
# translates whole communities so the high-centrality ones (area-weighted mean of
# member scores) are innermost -- and only nudges individuals within that.
COMM_GRAVITY = 0.30        # community-centroid pull in the sim (vs centrality
                           # gravity's max of GRAVITY_Y * GRAV_MAX_MULT ~= 0.24)
COMM_COMPACT_PULL = 0.05   # cohesion pull re-applied during each compaction step
# The community rank targets are AREA-AWARE: radius is allocated by cumulative
# member bubble area, so big core communities claim proportional room and the
# middle packs without gaping voids.
# Bigger communities BREATHE: both the collision pad between two members and the
# radial room a community claims scale with its member count, so the 59-member
# UVA blob spreads out instead of crowding while small groups keep tight spacing.
COMM_BREATHE = 0.6         # max fractional pad/area bonus (at the largest community)

# --- micro-communities (hierarchical, only if natural) -----------------------
# Big communities are probed for INTERNAL structure: remove their top-k internal
# hubs (super-connectors obscure substructure -- plain LP sees one dense block),
# re-run label propagation on the remainder, and accept the split only if it
# yields at least two sub-groups of MICRO_MIN_SUB members (nothing is forced;
# hubs re-attach to the sub-group they share the most edge weight with). Members
# then feel a SECONDARY cohesion pull toward their sub-group's centroid --
# deliberately weaker than COMM_GRAVITY, so parent blobs stay intact and
# community gravity remains the dominant force.
MICRO_MIN_SIZE = 15        # only communities at least this big are probed
MICRO_MIN_SUB = 4          # a valid split needs >= 2 sub-groups of this size
MICRO_HUB_TRIES = (2, 3)   # how many hubs to set aside, tried in order
SUB_GRAVITY = 0.12         # sub-group cohesion in the sim (< COMM_GRAVITY)
SUB_COMPACT_PULL = 0.02    # ...and during compaction (< COMM_COMPACT_PULL)

# --- affiliation misfits -----------------------------------------------------
# In a large community, members whose primary affiliation differs from the
# community's dominant one (e.g. Georgia Tech / Google folks inside the UVA
# blob) belong at its EDGE, not its core: after community placement they are
# rescaled onto a rim band (angle kept), and their community-cohesion pull is
# damped so packing doesn't reel them back in. Members with no known
# affiliation are left alone.
MISFIT_MIN_COMM = 12       # only communities at least this big get the treatment
MISFIT_COHESION = 0.6      # cohesion multiplier for misfit members
MISFIT_FLOOR = 0.95        # min misfit offset, x the community's non-misfit p90
ISOLATE_GRAVITY = 12.0  # extra centre-pull for nodes in a small component (tuck them in)
MINOR_COMPONENT_MAX = 6 # a connected component this small is an off-topic mini-cluster
                        # (or a lone isolate); every node in it gets ISOLATE_GRAVITY so it
                        # seats against the core's rim instead of being flung to a corner
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
    """Last token of the name, for the resting in-bubble label. Handles hyphenated
    surnames ('Rainwater-Lovett'). Ambiguous on its own -- 'Wen You' renders as a
    bubble labeled 'You' -- so every node also gets a full-name hover popup in the
    renderer (coauthors.js)."""
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


def build_edges(nodes, copub):
    """Weight between two co-authors = number of papers they have published together
    across ALL their work (copub.json; consortium-scale papers already excluded there).
    Kept when the weight clears EDGE_MIN and the edge is among the top
    MAX_EDGES_PER_NODE strongest for AT LEAST ONE endpoint (a strong tie one side
    cares about survives even if the other side is a busy hub -- so a hub's degree
    far exceeds MAX_EDGES_PER_NODE).

    Each kept edge is returned as (i, j, w, na, nb): na/nb record whether endpoint i/j
    was one of the two endpoints that nominated it (put it in its own top-N). This lets
    the renderer tell a node's OWN picks apart from ties it merely accrued because
    others nominated it."""
    idx = {slugify(n["name"]): i for i, n in enumerate(nodes)}
    raw = []  # (i, j, weight)
    for p in copub["pairs"]:
        i, j = idx.get(p["a"]), idx.get(p["b"])
        if i is None or j is None:   # pair member not a node (e.g. roster changed)
            continue
        if i > j:
            i, j = j, i
        if p["w"] >= EDGE_MIN:
            raw.append((i, j, p["w"]))

    # Rank each node's incident edges and let it nominate its top MAX_EDGES_PER_NODE.
    # An edge is kept if either endpoint nominated it; we remember which did.
    incident = {i: [] for i in range(len(nodes))}
    for idx, (i, j, w) in enumerate(raw):
        incident[i].append((w, idx))
        incident[j].append((w, idx))
    nominators = {}  # kept edge idx -> set of endpoint node-indices that nominated it
    for i, lst in incident.items():
        lst.sort(reverse=True)
        for _w, idx in lst[:MAX_EDGES_PER_NODE]:
            nominators.setdefault(idx, set()).add(i)
    out = []
    for idx in sorted(nominators):
        i, j, w = raw[idx]
        out.append((i, j, w, i in nominators[idx], j in nominators[idx]))
    return out


def centrality(nodes, edges):
    """Per-node centrality score in [0, 1]: the mean of min-max-normalized shared-
    paper count (weight), kept-edge degree, and betweenness (Brandes, unweighted).
    Drives the seed ring and per-node gravity so the layout's middle belongs to
    the co-authors who anchor the network."""
    n = len(nodes)
    deg = [0] * n
    adj = [[] for _ in range(n)]
    for i, j, _w, _na, _nb in edges:
        adj[i].append(j)
        adj[j].append(i)
        deg[i] += 1
        deg[j] += 1

    # Brandes betweenness on the unweighted kept-edge graph (n=125 -> instant).
    bet = [0.0] * n
    for s in range(n):
        stack = []
        pred = [[] for _ in range(n)]
        sigma = [0] * n
        sigma[s] = 1
        dist = [-1] * n
        dist[s] = 0
        q = deque([s])
        while q:
            v = q.popleft()
            stack.append(v)
            for u in adj[v]:
                if dist[u] < 0:
                    dist[u] = dist[v] + 1
                    q.append(u)
                if dist[u] == dist[v] + 1:
                    sigma[u] += sigma[v]
                    pred[u].append(v)
        delta = [0.0] * n
        while stack:
            v = stack.pop()
            for u in pred[v]:
                delta[u] += sigma[u] / sigma[v] * (1 + delta[v])
            if v != s:
                bet[v] += delta[v]

    def norm(xs):
        lo, hi = min(xs), max(xs)
        return [(x - lo) / (hi - lo) if hi > lo else 0.5 for x in xs]

    papers = norm([a["paper_count"] for a in nodes])
    degree = norm(deg)
    between = norm(bet)
    return [(papers[i] + degree[i] + between[i]) / 3 for i in range(n)]


def collide_pair(px, py, radii, cent, padf, i, j):
    """Resolve one overlapping pair, splitting the push by centrality: the LESS
    central node absorbs most of the displacement (a +0.2 floor keeps low-low
    pairs symmetric). Over many relaxation passes this systematically migrates
    rim dwellers outward while the core barely budges. The pad scales with the
    pair's community-size factors (padf), so members of big communities keep
    more air between them (see COMM_BREATHE)."""
    ox = px[i] - px[j]
    oy = py[i] - py[j]
    d = math.hypot(ox, oy) or 1e-6
    mind = radii[i] + radii[j] + COLLIDE_PAD * (padf[i] + padf[j]) / 2.0
    if d >= mind:
        return
    push = mind - d
    ci, cj = cent[i] + 0.2, cent[j] + 0.2
    share_i = cj / (ci + cj)          # i moves in proportion to j's centrality
    ux, uy = ox / d, oy / d
    px[i] += ux * push * share_i
    py[i] += uy * push * share_i
    px[j] -= ux * push * (1 - share_i)
    py[j] -= uy * push * (1 - share_i)


def communities(nodes, edges):
    """Weighted label propagation on the kept-edge graph: each node repeatedly
    adopts the label carrying the most edge weight among its neighbors, until
    stable. Deterministic (seeded visit order, sorted tie-breaks). Returns a
    community id per node, ids renumbered 0..k-1 by descending community size."""
    n = len(nodes)
    wadj = [dict() for _ in range(n)]
    for i, j, w, _na, _nb in edges:
        wadj[i][j] = wadj[i].get(j, 0) + w
        wadj[j][i] = wadj[j].get(i, 0) + w
    labels = list(range(n))
    rng = random.Random(SEED + 2)
    order = list(range(n))
    for _ in range(60):
        rng.shuffle(order)
        changed = False
        for i in order:
            if not wadj[i]:
                continue
            tally = {}
            for j, w in wadj[i].items():
                tally[labels[j]] = tally.get(labels[j], 0) + w
            best = max(sorted(tally), key=lambda lb: tally[lb])
            if best != labels[i]:
                labels[i] = best
                changed = True
        if not changed:
            break
    sizes = {}
    for lb in labels:
        sizes[lb] = sizes.get(lb, 0) + 1
    renum = {lb: k for k, lb in
             enumerate(sorted(sizes, key=lambda lb: (-sizes[lb], lb)))}
    return [renum[lb] for lb in labels]


def community_scores(comm, cent, radii):
    """Per-community centrality: the bubble-area-weighted mean of member node
    scores. Decides which communities sit innermost (see community_sort)."""
    tot = {}
    wsum = {}
    for i, c in enumerate(comm):
        a = math.pi * radii[i] * radii[i]
        tot[c] = tot.get(c, 0.0) + a
        wsum[c] = wsum.get(c, 0.0) + a * cent[i]
    raw = {c: wsum[c] / tot[c] for c in tot}
    lo, hi = min(raw.values()), max(raw.values())
    if hi <= lo:
        return {c: 0.5 for c in raw}
    return {c: (v - lo) / (hi - lo) for c, v in raw.items()}  # min-max to [0,1]


def sub_communities(nodes, edges, comm):
    """Hierarchical pass: probe each community of >= MICRO_MIN_SIZE members for
    internal micro-communities. Plain LP sees one dense block (the community's
    super-connectors touch everyone), so the top-k internal-degree hubs are set
    aside first (k from MICRO_HUB_TRIES, in order); a split is accepted only if
    the remainder yields >= 2 sub-groups of MICRO_MIN_SUB -- otherwise the
    community stays whole. Set-aside hubs re-attach to the sub-group they share
    the most edge weight with. Returns sub[i] = (community, sub-label) for nodes
    in a split community, None elsewhere."""
    n = len(nodes)
    sizes = {}
    for c in comm:
        sizes[c] = sizes.get(c, 0) + 1
    sub = [None] * n
    for c in sorted(sizes):
        if sizes[c] < MICRO_MIN_SIZE:
            continue
        mem = [i for i in range(n) if comm[i] == c]
        lidx = {o: l for l, o in enumerate(mem)}
        led = [(lidx[i], lidx[j], w, na, nb) for (i, j, w, na, nb) in edges
               if i in lidx and j in lidx]
        deg = {l: 0 for l in range(len(mem))}
        for i, j, _w, _na, _nb in led:
            deg[i] += 1
            deg[j] += 1
        for k in MICRO_HUB_TRIES:
            hubs = set(sorted(deg, key=lambda l: (-deg[l], l))[:k])
            rest = [l for l in range(len(mem)) if l not in hubs]
            rmap = {o: r for r, o in enumerate(rest)}
            redges = [(rmap[i], rmap[j], w, na, nb) for (i, j, w, na, nb) in led
                      if i in rmap and j in rmap]
            labels = communities([nodes[mem[l]] for l in rest], redges)
            lsz = {}
            for lb in labels:
                lsz[lb] = lsz.get(lb, 0) + 1
            if sum(1 for s in lsz.values() if s >= MICRO_MIN_SUB) < 2:
                continue   # no natural split at this k; try setting aside more hubs
            for r, l in enumerate(rest):
                sub[mem[l]] = (c, labels[r])
            for h in sorted(hubs):   # hubs join their strongest sub-group
                tally = {}
                for i, j, w, _na, _nb in led:
                    o = j if i == h else (i if j == h else None)
                    if o is not None and sub[mem[o]] is not None:
                        lb = sub[mem[o]][1]
                        tally[lb] = tally.get(lb, 0) + w
                if tally:
                    sub[mem[h]] = (c, max(sorted(tally), key=lambda lb: tally[lb]))
            break
    return sub


def find_misfits(nodes, comm):
    """Mark members of large communities whose primary affiliation differs from
    the community's dominant one (mode; deterministic tie-break). Unknown
    affiliations never count as misfit."""
    n = len(nodes)
    sizes = {}
    for c in comm:
        sizes[c] = sizes.get(c, 0) + 1
    mis = [False] * n
    for c in sorted(sizes):
        if sizes[c] < MISFIT_MIN_COMM:
            continue
        tally = {}
        for i in range(n):
            if comm[i] == c:
                inst = nodes[i].get("primary_affiliation")
                if inst:
                    tally[inst] = tally.get(inst, 0) + 1
        if not tally:
            continue
        dominant = max(sorted(tally), key=lambda t: tally[t])
        for i in range(n):
            if comm[i] == c:
                inst = nodes[i].get("primary_affiliation")
                if inst and inst != dominant:
                    mis[i] = True
    return mis


def radial_cap(px, py, cent, strength=CAP_STRENGTH):
    """Softly confine each node within its centrality-derived elliptical radius
    (see CAP_BASE/CAP_SPAN). Distances are measured in units of the blob's own
    x/y standard deviation, so the cap tracks whatever size and aspect the layout
    currently has instead of assuming a fixed canvas."""
    n = len(px)
    sx = math.sqrt(sum(x * x for x in px) / n) or 1.0
    sy = math.sqrt(sum(y * y for y in py) / n) or 1.0
    for i in range(n):
        cap = CAP_BASE + CAP_SPAN * (1 - cent[i])
        e = math.hypot(px[i] / sx, py[i] / sy)
        if e > cap:
            f = 1 - strength * (1 - cap / e)
            px[i] *= f
            py[i] *= f


def layout(nodes, edges, radii, cent, comm, cscore, sub, padf, cohf):
    """Fruchterman-Reingold with weighted edge attraction, a dominant community-
    cohesion pull (COMM_GRAVITY, stronger by design than any centrality gravity,
    damped by cohf for affiliation misfits), a subordinate micro-community pull
    (SUB_GRAVITY), centrality-weighted gravity toward the centre (see
    GRAV_MIN/MAX_MULT), and per-step collision resolution (community-size-scaled
    pads, padf) so bubbles pack without overlapping."""
    rng = random.Random(SEED)
    n = len(nodes)

    # Nodes in a small connected component (a lone isolate, or an off-topic
    # mini-cluster with no strong tie to the main epi cluster) feel only repulsion
    # + gravity, so they drift to a far equilibrium and waste canvas -- or worse, a
    # tight mini-cluster gets flung to a corner where it visually stands out. Give
    # every node in a small component a much firmer pull to the centre so collision
    # seats it as a satellite on the core's rim instead.
    adj = [[] for _ in range(n)]
    for i, j, _w, _na, _nb in edges:
        adj[i].append(j)
        adj[j].append(i)
    comp_id = [-1] * n
    comp_size = []
    for s in range(n):
        if comp_id[s] != -1:
            continue
        cid = len(comp_size)
        stack, size = [s], 0
        while stack:
            x = stack.pop()
            if comp_id[x] != -1:
                continue
            comp_id[x] = cid
            size += 1
            stack.extend(adj[x])
        comp_size.append(size)
    # Gravity per node: small components get the firm isolate pull; everyone else
    # is pulled in proportion to centrality, so the core sorts to the middle.
    grav_mult = [ISOLATE_GRAVITY if comp_size[comp_id[i]] <= MINOR_COMPONENT_MAX
                 else GRAV_MIN_MULT + (GRAV_MAX_MULT - GRAV_MIN_MULT) * cent[i]
                 for i in range(n)]
    area = CANVAS_W * CANVAS_H
    k = K_FACTOR * math.sqrt(area / max(n, 1))   # natural spring length

    # Seed communities as pre-formed clumps (deterministic): community centroids
    # on a golden-angle spiral -- highest-scoring community innermost -- with
    # members jittered tightly around their centroid. The sim then refines blobs
    # it already agrees with instead of having to assemble them.
    px = [0.0] * n
    py = [0.0] * n
    golden = math.pi * (3 - math.sqrt(5))
    corder = sorted(set(comm), key=lambda c: -cscore[c])
    nc = len(corder)
    span = min(CANVAS_W, CANVAS_H)
    for rank, c in enumerate(corder):
        frac = (rank + 0.5) / nc
        cr = (0.06 + 0.42 * math.sqrt(frac)) * span
        ang = golden * rank
        bx, by = math.cos(ang) * cr, math.sin(ang) * cr
        # Members of a split community seed clumped by SUB-GROUP: each sub-group
        # gets its own small offset patch inside the community's patch, so the
        # sim starts from -- and keeps -- the micro-structure.
        subs = sorted(set(sub[i][1] for i in range(n)
                          if comm[i] == c and sub[i] is not None))
        soff = {s: (math.cos(golden * k) * 0.045 * span,
                    math.sin(golden * k) * 0.045 * span)
                for k, s in enumerate(subs)}
        for i in range(n):
            if comm[i] != c:
                continue
            if sub[i] is not None:
                ox, oy = soff[sub[i][1]]
                px[i] = bx + ox + rng.uniform(-0.03, 0.03) * span
                py[i] = by + oy + rng.uniform(-0.03, 0.03) * span
            else:
                px[i] = bx + rng.uniform(-0.06, 0.06) * span
                py[i] = by + rng.uniform(-0.06, 0.06) * span

    # Edge attraction is amplified for heavier ties so tight collaborators sit closer.
    ew = [1.0 + math.log(w) for (_i, _j, w, _na, _nb) in edges]

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
        for e, (i, j, _w, _na, _nb) in enumerate(edges):
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

        # Community cohesion: pull each node toward its community's current
        # centroid. Deliberately STRONGER than the centrality gravity above, so
        # membership beats individual prominence and groups travel as blobs.
        # Misfits feel it damped (cohf), so they hover at the blob's edge; a
        # subordinate pull toward the micro-community centroid (SUB_GRAVITY)
        # keeps sub-groups legible inside their parent.
        csx = {}
        csy = {}
        ccount = {}
        ssx = {}
        ssy = {}
        scount = {}
        for i in range(n):
            c = comm[i]
            csx[c] = csx.get(c, 0.0) + px[i]
            csy[c] = csy.get(c, 0.0) + py[i]
            ccount[c] = ccount.get(c, 0) + 1
            if sub[i] is not None:
                s = sub[i]
                ssx[s] = ssx.get(s, 0.0) + px[i]
                ssy[s] = ssy.get(s, 0.0) + py[i]
                scount[s] = scount.get(s, 0) + 1
        for i in range(n):
            c = comm[i]
            dx[i] -= (px[i] - csx[c] / ccount[c]) * COMM_GRAVITY * cohf[i] * k
            dy[i] -= (py[i] - csy[c] / ccount[c]) * COMM_GRAVITY * cohf[i] * k
            if sub[i] is not None:
                s = sub[i]
                dx[i] -= (px[i] - ssx[s] / scount[s]) * SUB_GRAVITY * cohf[i] * k
                dy[i] -= (py[i] - ssy[s] / scount[s]) * SUB_GRAVITY * cohf[i] * k

        # Apply, capped by the current temperature.
        for i in range(n):
            d = math.hypot(dx[i], dy[i]) or 1e-6
            m = min(d, t)
            px[i] += (dx[i] / d) * m
            py[i] += (dy[i] / d) * m

        # Keep central nodes central: enforce the centrality radial cap before
        # collision, so overlaps resolve around a correctly-sorted core.
        radial_cap(px, py, cent)

        # Collision: a few relaxation passes pushing overlapping bubbles apart.
        # The push is split by centrality -- the LESS central node absorbs most of
        # it -- so every resolved overlap nudges rim dwellers outward and leaves
        # the core in place (see collide_pair).
        for _ in range(2):
            for i in range(n):
                for j in range(i + 1, n):
                    collide_pair(px, py, radii, cent, padf, i, j)

        t = max(t * 0.985, 1.0)   # cool down

    return px, py


def misfit_band(px, py, comm, mis, strength=0.5):
    """Keep affiliation misfits at their community's rim. One-sided, like
    radial_cap: a misfit sitting INSIDE the floor (closer to the community
    centroid than MISFIT_FLOOR x the non-misfit p90 offset) is pushed outward
    by `strength` of the shortfall, angle preserved; one already at or beyond
    the floor is left alone. The p90 reference deliberately excludes the misfits
    themselves -- otherwise pushing them out inflates (or collapsing pulls
    shrink) the very reference they're placed by. Re-asserted every compaction
    iteration: a one-shot placement erodes under the repeated cohesion pulls."""
    members = {}
    for i, c in enumerate(comm):
        members.setdefault(c, []).append(i)
    for c, ms in members.items():
        mfs = sorted(i for i in ms if mis[i])
        core = [i for i in ms if not mis[i]]
        if not mfs or len(core) < 3:
            continue
        mx = sum(px[i] for i in ms) / len(ms)
        my = sum(py[i] for i in ms) / len(ms)
        offs = sorted(math.hypot(px[i] - mx, py[i] - my) for i in core)
        p90 = offs[min(len(offs) - 1, int(0.9 * len(offs)))] or 1.0
        floor = p90 * MISFIT_FLOOR
        for k, i in enumerate(mfs):
            d = math.hypot(px[i] - mx, py[i] - my)
            if d < 1e-9:    # on the centroid: send it out at a deterministic angle
                ang = 2 * math.pi * (k + 0.5) / len(mfs)
                px[i] = mx + math.cos(ang) * floor * strength
                py[i] = my + math.sin(ang) * floor * strength
            elif d < floor:
                f = 1 + strength * (floor / d - 1)
                px[i] = mx + (px[i] - mx) * f
                py[i] = my + (py[i] - my) * f


def community_sort(px, py, comm, cscore, radii, mis):
    """Place whole COMMUNITIES radially by their centrality score: each community
    is rigidly translated (internal structure untouched) so its centroid sits at
    an area-aware rank radius -- highest-scoring community innermost, radius
    allocated by cumulative member bubble area so big communities claim
    proportional room and the middle packs without voids. Angles are kept from
    the sim, so neighborhoods stay where FR put them. Rigid translation is the
    point: the earlier per-NODE radial sort tore communities apart radially,
    and the user wants research groups to travel together."""
    n = len(px)
    cx = sum(px) / n
    cy = sum(py) / n
    sx = math.sqrt(sum((x - cx) ** 2 for x in px) / n) or 1.0
    sy = math.sqrt(sum((y - cy) ** 2 for y in py) / n) or 1.0

    members = {}
    for i, c in enumerate(comm):
        members.setdefault(c, []).append(i)
    ccx = {c: sum((px[i] - cx) / sx for i in ms) / len(ms)
           for c, ms in members.items()}
    ccy = {c: sum((py[i] - cy) / sy for i in ms) / len(ms)
           for c, ms in members.items()}
    # Effective area gets the same size-scaled bonus as the collision pads, so a
    # big community claims proportionally more radial room to breathe in.
    maxsz = max(len(ms) for ms in members.values())
    area = {c: sum(math.pi * radii[i] ** 2 for i in ms)
            * (1 + COMM_BREATHE * len(ms) / maxsz)
            for c, ms in members.items()}

    rmax = max(math.hypot(ccx[c], ccy[c]) for c in members) or 1.0
    order = sorted(members, key=lambda c: -cscore[c])
    total = sum(area.values()) or 1.0
    cum = 0.0
    for c in order:
        target = rmax * math.sqrt((cum + area[c] / 2) / total)
        cum += area[c]
        d = math.hypot(ccx[c], ccy[c])
        if d > 1e-9:
            f = target / d
            tx, ty = ccx[c] * f, ccy[c] * f
        else:               # centroid already at the origin: leave it there
            tx, ty = ccx[c], ccy[c]
        dx, dy = tx - ccx[c], ty - ccy[c]
        for i in members[c]:
            px[i] += dx * sx
            py[i] += dy * sy

    misfit_band(px, py, comm, mis, strength=1.0)   # initial placement: full push
    return px, py


def compact(px, py, radii, cent, comm, cscore, sub, padf, cohf, mis):
    """Nudge the settled layout toward a NOMINAL density: repeatedly pull every
    node a small fraction toward the centroid and resolve collisions, stopping
    once circle-area fill reaches COMPACT_TARGET_FILL. The pull is anisotropic
    and STEERED: the axis the blob is too long on (vs TARGET_ASPECT) pulls
    harder, so the pack densifies into a landscape shape directly and the later
    fit_aspect stretch -- which would re-dilute the fill -- has nothing to do.
    The FR sim settles at a sparse repulsion equilibrium (fine for STRUCTURE,
    wasteful on whitespace); full contact packing proved far too dense, so the
    fill target caps this partway. Preserves the relative arrangement."""
    n = len(px)
    carea = sum(math.pi * r * r for r in radii)
    for _ in range(COMPACT_ITERS):
        w = (max(px[i] + radii[i] for i in range(n))
             - min(px[i] - radii[i] for i in range(n)))
        h = (max(py[i] + radii[i] for i in range(n))
             - min(py[i] - radii[i] for i in range(n)))
        if carea / (w * h) >= COMPACT_TARGET_FILL:
            break   # nominal density reached; keep the remaining air
        wide = (w / h) > TARGET_ASPECT   # too wide -> squeeze x; else squeeze y
        pull_x = COMPACT_PULL * (1.5 if wide else 0.25)
        pull_y = COMPACT_PULL * (0.25 if wide else 1.5)
        cx = sum(px) / n
        cy = sum(py) / n
        # Central nodes densify inward first (pull scaled up with centrality);
        # rim dwellers lag behind and stay outside.
        for i in range(n):
            cm = 0.6 + 0.8 * cent[i]
            px[i] += (cx - px[i]) * pull_x * cm
            py[i] += (cy - py[i]) * pull_y * cm
        # Community cohesion during packing too: pull members toward their
        # community's current centroid so densification can't smear blobs apart
        # (damped for misfits, plus the subordinate micro-community pull).
        csx = {}
        csy = {}
        cnum = {}
        ssx = {}
        ssy = {}
        snum = {}
        for i in range(n):
            c = comm[i]
            csx[c] = csx.get(c, 0.0) + px[i]
            csy[c] = csy.get(c, 0.0) + py[i]
            cnum[c] = cnum.get(c, 0) + 1
            if sub[i] is not None:
                s = sub[i]
                ssx[s] = ssx.get(s, 0.0) + px[i]
                ssy[s] = ssy.get(s, 0.0) + py[i]
                snum[s] = snum.get(s, 0) + 1
        for i in range(n):
            c = comm[i]
            px[i] += (csx[c] / cnum[c] - px[i]) * COMM_COMPACT_PULL * cohf[i]
            py[i] += (csy[c] / cnum[c] - py[i]) * COMM_COMPACT_PULL * cohf[i]
            if sub[i] is not None:
                s = sub[i]
                px[i] += (ssx[s] / snum[s] - px[i]) * SUB_COMPACT_PULL * cohf[i]
                py[i] += (ssy[s] / snum[s] - py[i]) * SUB_COMPACT_PULL * cohf[i]
        # Keep the radial sorting while the pack densifies. The cap is keyed to
        # the COMMUNITY score, not the node's own centrality, so it confines
        # whole blobs rather than tearing individual members out of them. The
        # misfit band is re-asserted every iteration for the same reason.
        misfit_band(px, py, comm, mis)
        capscore = [cscore[comm[i]] for i in range(n)]
        radial_cap(px, py, capscore)
        for _p in range(3):
            for i in range(n):
                for j in range(i + 1, n):
                    collide_pair(px, py, radii, cent, padf, i, j)

    # Fix the aspect WITHOUT changing density: exiting on fill alone can strand
    # the blob overstretched, and further compaction pulls would over-densify it.
    # An area-preserving anisotropic rescale (squeeze one axis, stretch the other
    # by the same factor) hits TARGET_ASPECT at constant fill.
    w = (max(px[i] + radii[i] for i in range(n))
         - min(px[i] - radii[i] for i in range(n)))
    h = (max(py[i] + radii[i] for i in range(n))
         - min(py[i] - radii[i] for i in range(n)))
    if abs(w / h - TARGET_ASPECT) / TARGET_ASPECT > 0.05:
        s = math.sqrt(TARGET_ASPECT / (w / h))
        cx = sum(px) / n
        cy = sum(py) / n
        for i in range(n):
            px[i] = cx + (px[i] - cx) * s
            py[i] = cy + (py[i] - cy) / s

    # UNCONDITIONAL settle: the main loop's fill check fires at the top of an
    # iteration, so it can exit before a single collision pass has run (the
    # community placement + misfit band routinely arrive already at target
    # fill, full of overlaps). Interleave the band with collision passes, then
    # finish with pure collision passes so no overlap survives.
    for _ in range(20):
        misfit_band(px, py, comm, mis)
        for _p in range(3):
            for i in range(n):
                for j in range(i + 1, n):
                    collide_pair(px, py, radii, cent, padf, i, j)
    for _ in range(10):
        for i in range(n):
            for j in range(i + 1, n):
                collide_pair(px, py, radii, cent, padf, i, j)
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
    if not os.path.exists(COPUB):
        raise SystemExit("copub.json missing -- run tools/build_copub.py first "
                         "(needs network; see tools/README.md)")
    copub = json.load(open(COPUB, encoding="utf-8"))

    nodes = select_nodes(authors)
    if not nodes:
        raise SystemExit("No co-authors selected -- check authors.json / MIN_PAPERS")

    edges = build_edges(nodes, copub)

    # Prune nodes with no kept edge: a lone bubble floating off the pack reads as
    # clutter, not information (the roster page still lists everyone).
    connected = set()
    for i, j, _w, _na, _nb in edges:
        connected.add(i); connected.add(j)
    if len(connected) < len(nodes):
        dropped = [nodes[i]["name"] for i in range(len(nodes)) if i not in connected]
        keep = sorted(connected)
        remap = {old: new for new, old in enumerate(keep)}
        nodes = [nodes[i] for i in keep]
        edges = [(remap[i], remap[j], w, na, nb) for (i, j, w, na, nb) in edges]
        print("Dropped %d edge-less node(s): %s" % (len(dropped), ", ".join(dropped)))

    counts = [a["paper_count"] for a in nodes]
    cmin, cmax = min(counts), max(counts)
    pspan = (cmax - cmin) or 1

    def radius(c):
        norm = (c - cmin) / pspan
        return R_MIN + (R_MAX - R_MIN) * (norm ** SIZE_EXP)

    radii = [radius(a["paper_count"]) for a in nodes]

    cent = centrality(nodes, edges)
    comm = communities(nodes, edges)
    cscore = community_scores(comm, cent, radii)
    sub = sub_communities(nodes, edges, comm)   # micro-structure, if it's natural
    mis = find_misfits(nodes, comm)             # affiliation misfits -> blob rims
    csizes = {}
    for c in comm:
        csizes[c] = csizes.get(c, 0) + 1
    maxsz = max(csizes.values())
    padf = [1 + COMM_BREATHE * csizes[comm[i]] / maxsz for i in range(len(nodes))]
    cohf = [MISFIT_COHESION if mis[i] else 1.0 for i in range(len(nodes))]

    px, py = layout(nodes, edges, radii, cent, comm, cscore, sub, padf, cohf)
    px, py = community_sort(px, py, comm, cscore, radii, mis)  # placed whole
    # Order matters: stretch to landscape FIRST, then densify. The FR blob is
    # square-ish and often already at nominal fill, so compacting first would
    # no-op and the stretch would then re-dilute the fill it was meant to fix.
    # compact() steers its pulls to hold TARGET_ASPECT while it densifies, and
    # the trailing fit_aspect is only a guard (no-op unless still too square).
    px = fit_aspect(px, py, radii)
    px, py = compact(px, py, radii, cent, comm, cscore, sub, padf, cohf, mis)
    px = fit_aspect(px, py, radii)

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
            "short": short_name(a["name"]),  # resting in-bubble label; full name on hover
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

    # na/nb: whether endpoint a/b nominated this tie (one of its own top-N) vs merely
    # accrued it because the other endpoint did -- the renderer colors hover edges by it.
    edges_out = [{"a": nodes_out[i]["id"], "b": nodes_out[j]["id"], "w": w,
                  "na": na, "nb": nb}
                 for (i, j, w, na, nb) in edges]

    out = {
        "_readme": (
            "Generated by tools/build_coauthors.py from authors.json. Do not edit by "
            "hand -- rerun the script after authors.json changes. An ego network with "
            "the site owner removed: nodes are his most frequent co-authors, sized by "
            "shared-paper count ('papers'), shaded by length of collaboration -- the "
            "'span' in years from first to latest shared paper -- on a light->dark ramp "
            "('color'); 'pale' marks a fill light enough that its label flips to dark ink. "
            "edges weight how many papers two co-authors have published together across "
            "all their work (copub.json; consortium-scale papers excluded). 'x','y','r' "
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
    sizes = {}
    for c in comm:
        sizes[c] = sizes.get(c, 0) + 1
    print("Communities: %d (sizes %s)"
          % (len(sizes), sorted(sizes.values(), reverse=True)))
    split = {}
    for i, s in enumerate(sub):
        if s is not None:
            split.setdefault(s[0], {}).setdefault(s[1], []).append(i)
    for c, groups in sorted(split.items()):
        print("Micro-communities in community %d:" % c)
        for lb, ms in sorted(groups.items(), key=lambda g: -len(g[1])):
            names = [nodes_out[i]["name"] for i in ms]
            print("  [%2d] %s%s" % (len(ms), ", ".join(names[:6]),
                                    " ..." if len(names) > 6 else ""))
    mnames = [nodes_out[i]["name"] + " (" + (nodes[i].get("primary_affiliation") or "?") + ")"
              for i in range(len(nodes)) if mis[i]]
    if mnames:
        print("Affiliation misfits on their blob's rim (%d): %s"
              % (len(mnames), "; ".join(mnames)))
    # Cohesion: mean member distance to own community centroid, relative to the
    # mean distance to the overall centroid. Small = groups travel together.
    mem = {}
    for i, c in enumerate(comm):
        mem.setdefault(c, []).append(i)
    dsum = 0.0
    for c, ms in mem.items():
        mx = sum(nodes_out[i]["x"] for i in ms) / len(ms)
        my = sum(nodes_out[i]["y"] for i in ms) / len(ms)
        dsum += sum(math.hypot(nodes_out[i]["x"] - mx, nodes_out[i]["y"] - my)
                    for i in ms)
    gd = sum(math.hypot(n["x"], n["y"]) for n in nodes_out) or 1.0
    print("Community cohesion: mean dist to own centroid = %.2f x mean dist to centre"
          % (dsum / gd))
    minx = min(n["x"] - n["r"] for n in nodes_out)
    maxx = max(n["x"] + n["r"] for n in nodes_out)
    miny = min(n["y"] - n["r"] for n in nodes_out)
    maxy = max(n["y"] + n["r"] for n in nodes_out)
    w, h = maxx - minx, maxy - miny
    fill = sum(math.pi * n["r"] ** 2 for n in nodes_out) / (w * h)
    print("Layout: %.0f x %.0f (aspect %.2f), circle-area fill %.0f%%"
          % (w, h, w / h, 100 * fill))
    # Did centrality-weighted gravity work? Rank-correlate centrality against
    # distance from the centroid (x normalized by the landscape stretch so a
    # wide layout doesn't overweight horizontal distance). Want strongly negative.
    dist = [math.hypot(n["x"] / (w / h), n["y"]) for n in nodes_out]
    def ranks(xs):
        order = sorted(range(len(xs)), key=lambda i: xs[i])
        rk = [0] * len(xs)
        for r, i in enumerate(order):
            rk[i] = r
        return rk
    rc, rd = ranks(cent), ranks(dist)
    m = len(rc)
    mc, md = sum(rc) / m, sum(rd) / m
    cov = sum((rc[i] - mc) * (rd[i] - md) for i in range(m))
    var = math.sqrt(sum((r - mc) ** 2 for r in rc) * sum((r - md) ** 2 for r in rd))
    print("Centrality vs centre-distance rank corr: %.2f (negative = core centred)"
          % (cov / var if var else 0.0))
    top = sorted(range(m), key=lambda i: -cent[i])[:8]
    dr = ranks(dist)
    print("Most central (score | dist rank of %d):" % m)
    for i in top:
        print("  %-26s %.2f  #%d" % (nodes_out[i]["name"], cent[i], dr[i] + 1))


if __name__ == "__main__":
    main()
