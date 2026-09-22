#!/usr/bin/env python3
"""Check every link on the site: internal targets, fragments, and outbound URLs.

    python3 tools/check_links.py              # internal only, fast, offline
    python3 tools/check_links.py --external   # outbound URLs too (network)
    python3 tools/check_links.py --all        # both
    python3 tools/check_links.py --all --json report.json

Why: this site is a permanent record of where the work lives, and almost every
claim on it is carried by a link -- a DOI, a funder, a news story, a repository.
Those rot quietly. A 404 behind "best paper award" is worse than no link, because
a reader takes it as the evidence and finds nothing. Past cleanups here (a dead
CBS19 story, stale redirect stubs) were all found by hand, one at a time.

Two halves, deliberately separable:

* **Internal** -- relative hrefs and srcs must resolve to a file in the repo, and
  a "page.html#thing" must land on an id that page actually has. This needs no
  network, never flakes, and a failure is always a real bug, so it is the half
  that belongs on every push.
* **External** -- http(s) URLs, checked with curl. This depends on the rest of
  the internet behaving, so it is opt-in and reported in three buckets:

      DEAD          404, 410, or a host that does not resolve. Fix these.
      UNVERIFIED    403, 429, timeouts, TLS trouble. Publishers block robots
                    routinely (doi.org resolves fine in a browser and rejects
                    HEAD from a datacentre), so these are reported, never failed.
      REDIRECTED    2xx, but the final URL differs in more than trailing slash
                    or scheme. Worth updating eventually; not an error.

Only DEAD (and any internal breakage) sets a non-zero exit, so a scheduled run
stays quiet until something is genuinely broken.

Needs Python 3 stdlib plus curl on PATH, like every other script in tools/. curl
carries the system trust store, which several python.org builds do not.
"""
import argparse
import concurrent.futures
import glob
import json
import os
import re
import subprocess
import sys
import urllib.parse
from html import unescape

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

UA = ("Mozilla/5.0 (compatible; srinivvenkat.github.io link check; "
      "+https://srinivvenkat.github.io/)")

# href="..." / src="..." in the site's own hand-written markup. Attribute values
# are always double-quoted here, which keeps this honest without an HTML parser.
LINK_RE = re.compile(r'(?:href|src)="([^"]+)"')

ID_RE = re.compile(r'\bid="([^"]+)"')

# Schemes that are not ours to verify.
SKIP_SCHEMES = ("mailto:", "tel:", "javascript:", "data:", "#")

# Hosts that answer a browser but refuse automated requests often enough that a
# failure from them says nothing. Reported as UNVERIFIED rather than DEAD even on
# a hard status, so the check does not cry wolf every week.
TOUCHY_HOSTS = {
    "www.linkedin.com", "linkedin.com",
    "scholar.google.com",
    "open.spotify.com",
    "dl.acm.org",
    "www.sciencedirect.com",
    "ieeexplore.ieee.org",
}

DEAD_STATUSES = {404, 410}


def pages():
    return sorted(glob.glob(os.path.join(ROOT, "*.html")))


def links_in(path):
    """[(raw_href, line_number)] for one page, deduplicated per page."""
    seen, out = set(), []
    for n, line in enumerate(open(path, encoding="utf-8"), 1):
        for raw in LINK_RE.findall(line):
            href = unescape(raw).strip()
            if href and href not in seen:
                seen.add(href)
                out.append((href, n))
    return out


def ids_in(path):
    return set(ID_RE.findall(open(path, encoding="utf-8").read()))


def check_internal():
    """Resolve every relative link and fragment. Returns a list of problems."""
    problems = []
    id_cache = {}

    def ids_for(name):
        if name not in id_cache:
            id_cache[name] = ids_in(os.path.join(ROOT, name))
        return id_cache[name]

    for path in pages():
        page = os.path.basename(path)
        for href, line in links_in(path):
            if href.startswith(SKIP_SCHEMES) and not href.startswith("#"):
                continue
            if re.match(r"^[a-z][a-z0-9+.-]*:", href):
                continue  # absolute URL, the external half's business

            target, _, frag = href.partition("#")
            frag = urllib.parse.unquote(frag)
            # Drop the query: "?v=24" is cache-busting and "?topic=epi" is read
            # by pub-filter.js. Neither is part of the path on disk.
            target = target.partition("?")[0]

            if target in ("", "."):
                name = page  # a bare "#thing" points into this page
            else:
                # Leading "/" means site root, which is the repo root here.
                rel = target.lstrip("/") if target.startswith("/") else target
                name = os.path.normpath(rel)
                full = os.path.join(ROOT, name)
                if os.path.isdir(full):
                    name = os.path.join(name, "index.html")
                    full = os.path.join(ROOT, name)
                if not os.path.exists(full):
                    problems.append(f"{page}:{line}  MISSING FILE  {href}")
                    continue

            if frag:
                if not name.endswith(".html"):
                    continue  # a fragment on a PDF is a viewer hint, not ours
                if frag not in ids_for(name):
                    problems.append(f"{page}:{line}  MISSING ANCHOR  {href}")
    return problems


def external_urls():
    """{url: [(page, line), ...]} for every outbound http(s) link on the site."""
    urls = {}
    for path in pages():
        page = os.path.basename(path)
        for href, line in links_in(path):
            if href.startswith(("http://", "https://")):
                urls.setdefault(href, []).append((page, line))
    return urls


def probe(url, timeout):
    """(bucket, detail) for one URL. Buckets: OK, REDIRECTED, DEAD, UNVERIFIED."""
    base = ["curl", "-sS", "-o", os.devnull, "--location", "--max-time",
            str(timeout), "-A", UA,
            "-w", "%{http_code} %{url_effective}"]
    # HEAD first: cheap, and enough for most servers. A server that dislikes HEAD
    # (405, 403, or an empty status) gets a second chance with a ranged GET.
    res = subprocess.run(base + ["-I", url], capture_output=True, text=True)
    status, final = parse_probe(res)
    if status in (0, 403, 405, 406, 501) or res.returncode != 0:
        res = subprocess.run(base + ["-r", "0-2048", url],
                             capture_output=True, text=True)
        status, final = parse_probe(res)

    host = urllib.parse.urlsplit(url).netloc.lower()

    if res.returncode != 0 and status == 0:
        err = res.stderr.strip().splitlines()[-1] if res.stderr.strip() else ""
        # 6 is "could not resolve host": the domain itself is gone, which is as
        # dead as a link gets. Everything else (timeout, TLS, reset) is noise.
        if res.returncode == 6 and host not in TOUCHY_HOSTS:
            return "DEAD", f"host does not resolve ({err[:80]})"
        return "UNVERIFIED", f"curl rc={res.returncode} {err[:80]}"

    if status in DEAD_STATUSES and host not in TOUCHY_HOSTS:
        return "DEAD", f"HTTP {status}"
    if status >= 400 or status == 0:
        return "UNVERIFIED", f"HTTP {status}"
    if final and normalise(final) != normalise(url):
        return "REDIRECTED", final
    return "OK", str(status)


def parse_probe(res):
    """(status, final_url) out of curl's -w line, or (0, '') if it wrote none."""
    out = res.stdout.strip().splitlines()
    if not out:
        return 0, ""
    parts = out[-1].split(None, 1)
    try:
        status = int(parts[0])
    except (ValueError, IndexError):
        return 0, ""
    return status, parts[1] if len(parts) > 1 else ""


def normalise(url):
    """Ignore the differences nobody needs to act on: scheme, trailing slash."""
    s = urllib.parse.urlsplit(url)
    return (s.netloc.lower().removeprefix("www."), s.path.rstrip("/"), s.query)


def check_external(timeout, jobs):
    """Probe every outbound URL once. Returns {bucket: [(url, detail, wheres)]}."""
    urls = external_urls()
    buckets = {"OK": [], "REDIRECTED": [], "DEAD": [], "UNVERIFIED": []}
    with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as pool:
        futures = {pool.submit(probe, u, timeout): u for u in urls}
        for done in concurrent.futures.as_completed(futures):
            url = futures[done]
            bucket, detail = done.result()
            buckets[bucket].append((url, detail, urls[url]))
    for rows in buckets.values():
        rows.sort()
    return buckets


def where(rows, limit=3):
    """'index.html:214, talks.html:57' -- enough to find it without a grep."""
    shown = ", ".join(f"{p}:{n}" for p, n in rows[:limit])
    return shown + (f" (+{len(rows) - limit} more)" if len(rows) > limit else "")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--external", action="store_true",
                    help="probe outbound URLs over the network")
    ap.add_argument("--internal", action="store_true",
                    help="check internal links only (the default)")
    ap.add_argument("--all", action="store_true",
                    help="check both halves")
    ap.add_argument("--timeout", type=int, default=25,
                    help="seconds per URL (default 25)")
    ap.add_argument("--jobs", type=int, default=8,
                    help="URLs in flight at once (default 8)")
    ap.add_argument("--json", metavar="FILE",
                    help="also write the full result as JSON")
    args = ap.parse_args()

    do_external = args.external or args.all
    do_internal = args.internal or args.all or not do_external

    failures = 0
    report = {}

    if do_internal:
        problems = check_internal()
        report["internal"] = problems
        print(f"Internal links across {len(pages())} pages: "
              f"{len(problems) or 'no'} problem(s)")
        for p in problems:
            print(f"  {p}")
        failures += len(problems)
        if do_external:
            print()

    if do_external:
        buckets = check_external(args.timeout, args.jobs)
        total = sum(len(v) for v in buckets.values())
        report["external"] = {
            k: [{"url": u, "detail": d, "seen": [f"{p}:{n}" for p, n in w]}
                for u, d, w in v]
            for k, v in buckets.items()
        }
        print(f"Outbound URLs: {total} unique, {len(buckets['OK'])} ok, "
              f"{len(buckets['REDIRECTED'])} redirected, "
              f"{len(buckets['DEAD'])} dead, "
              f"{len(buckets['UNVERIFIED'])} unverified")
        for bucket in ("DEAD", "REDIRECTED", "UNVERIFIED"):
            if not buckets[bucket]:
                continue
            print(f"\n{bucket}")
            for url, detail, rows in buckets[bucket]:
                print(f"  {url}\n      {detail}\n      {where(rows)}")
        failures += len(buckets["DEAD"])

    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=1)
        print(f"\nwrote {args.json}")

    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
