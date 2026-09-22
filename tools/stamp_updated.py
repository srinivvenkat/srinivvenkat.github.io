#!/usr/bin/env python3
"""Stamp the "Last updated" date into every page's footer and into sitemap.xml.

Rewrites the <time> element inside the footer of each ../*.html page so the date
visitors see matches the day the site was actually published, and the matching
<lastmod> in ../sitemap.xml so the date crawlers read says the same thing:

    python3 tools/stamp_updated.py                # today
    python3 tools/stamp_updated.py --from-git     # date of the last content commit
    python3 tools/stamp_updated.py --date 2026-08-04
    python3 tools/stamp_updated.py --check        # verify only, change nothing

Why: the footer date is the only thing on the site telling a reviewer, a program
officer, or a prospective student whether they are looking at current work. Hand
-maintained, it silently rots, which is worse than showing nothing -- a stale date
actively misinforms. sitemap.xml rots the same way, unseen: a <lastmod> older than
the page tells crawlers not to bother re-reading it. Run this immediately before
committing a content change.

--from-git reads the date of the last commit that touched site content (see
CONTENT_PATHS), so it is the right choice when re-stamping a repository whose
pages have not changed since they were committed. It deliberately ignores commits
that touch only tools/, CI config or docs, because those do not change what a
visitor sees and must not drag the published date forward. For the normal case
(you edited pages and are about to commit) the default of today is correct,
because the commit you are about to make will carry today's date.

--check exits non-zero if any page is missing a stamp, any page or sitemap entry
disagrees with the target date, or the sitemap and the set of pages have drifted
apart, which makes it usable as a pre-commit hook or CI step.

In the footer, the machine-readable datetime attribute and the human-readable text
are written together, so they can never drift apart. In the sitemap, HTML entries
follow the same target date as the footers; a non-HTML entry (the CV) keeps the
date of the commit that last changed that file, so editing prose does not claim
the PDF was revised.
"""
import argparse
import datetime as dt
import glob
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Matches the footer stamp written by this script, capturing nothing we need to
# keep: the whole element is rewritten. Kept deliberately narrow (it requires the
# "Last updated " prefix) so it can never touch another <time> added later.
STAMP_RE = re.compile(
    r'(Last updated <time datetime=")(\d{4}-\d{2}-\d{2})(">)([^<]*)(</time>)'
)

SITEMAP = os.path.join(ROOT, "sitemap.xml")
BASE_URL = "https://srinivvenkat.github.io/"

# One <url> block of the sitemap, as this repo writes them: <loc> then <lastmod>.
# Only the date is rewritten; changefreq, priority and the ordering are left alone.
URL_RE = re.compile(
    r"(<loc>)([^<]+)(</loc>\s*<lastmod>)(\d{4}-\d{2}-\d{2})(</lastmod>)"
)

# What counts as "content" for --from-git: the things a visitor actually sees.
# Same set the pre-commit hook tests, minus sitemap.xml itself, which is derived
# from the pages and so must never be what decides their date.
CONTENT_PATHS = ["*.html", "css/*.css", "js/*.js", "*.json", "SV_CV.pdf"]

# Pages that exist but are deliberately absent from the sitemap.
UNLISTED_PAGES = {"404.html"}


def human(d):
    """2026-08-04 -> '4 August 2026'. No leading zero, matching the site's prose."""
    return f"{d.day} {d:%B} {d.year}"


def git_date(paths=None):
    """Commit date of the last commit touching `paths` (default: any), or None.

    Returns None outside a git checkout, and also when no commit has touched those
    paths -- callers fall back rather than guessing a date.
    """
    cmd = ["git", "-C", ROOT, "log", "-1", "--format=%cs"]
    if paths:
        cmd += ["--"] + list(paths)
    try:
        out = subprocess.run(
            cmd, capture_output=True, text=True, check=True,
        ).stdout.strip()
        return dt.date.fromisoformat(out)
    except (subprocess.CalledProcessError, FileNotFoundError, ValueError):
        return None


def git_is_dirty(path):
    """True if `path` differs from HEAD (staged or not), i.e. it is changing now."""
    rel = os.path.relpath(path, ROOT)
    try:
        out = subprocess.run(
            ["git", "-C", ROOT, "status", "--porcelain", "--", rel],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        return bool(out)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def pages():
    return sorted(glob.glob(os.path.join(ROOT, "*.html")))


def loc_to_page(loc):
    """Map a sitemap <loc> onto the repo file it serves, or None if off-site.

    The bare site root serves index.html; every other URL is a path in the repo.
    """
    if not loc.startswith(BASE_URL):
        return None
    path = loc[len(BASE_URL):]
    return path or "index.html"


def sitemap_date(name, target):
    """The date a sitemap entry should carry.

    HTML pages move with the footer stamp, so they take the target date outright.
    Anything else (the CV) keeps the date of the commit that last changed it, so a
    prose edit does not go on record as a revision of the PDF; if it is changing in
    this very commit, it takes the target date like everything else.
    """
    if name.endswith(".html"):
        return target
    if git_is_dirty(os.path.join(ROOT, name)):
        return target
    return git_date([name]) or target


def stamp_sitemap(target, check):
    """Bring sitemap.xml's <lastmod> dates in line. Returns (changed, problems)."""
    if not os.path.exists(SITEMAP):
        print("  NO SITEMAP sitemap.xml: not found")
        return 0, 1

    s = open(SITEMAP, encoding="utf-8").read()
    changed = problems = 0
    listed = set()

    def fix(m):
        nonlocal changed, problems
        loc, was = m.group(2), m.group(4)
        name = loc_to_page(loc)
        if name is None:
            print(f"  OFF-SITE sitemap.xml: <loc>{loc}</loc> is not on {BASE_URL}")
            problems += 1
            return m.group(0)
        listed.add(name)
        if not os.path.exists(os.path.join(ROOT, name)):
            print(f"  DANGLING sitemap.xml: {name} is listed but not in the repo")
            problems += 1
            return m.group(0)
        want = sitemap_date(name, target).isoformat()
        if was == want:
            return m.group(0)
        if check:
            problems += 1
            print(f"  stale  sitemap.xml: {name}: {was}, should be {want}")
            return m.group(0)
        changed += 1
        print(f"  stamped sitemap.xml: {name}: {was} -> {want}")
        return f"{m.group(1)}{loc}{m.group(3)}{want}{m.group(5)}"

    out = URL_RE.sub(fix, s)

    # A page added to the site but never added to the sitemap is invisible to
    # crawlers, which is the failure this file exists to prevent.
    for path in pages():
        name = os.path.basename(path)
        if name not in UNLISTED_PAGES and name not in listed:
            print(f"  UNLISTED sitemap.xml: {name} exists but is not in the sitemap")
            problems += 1

    if changed and not check:
        open(SITEMAP, "w", encoding="utf-8").write(out)
    return changed, problems


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--from-git", action="store_true",
                     help="use the date of the last commit that changed site "
                          "content, instead of today")
    src.add_argument("--date", metavar="YYYY-MM-DD",
                     help="use an explicit date")
    ap.add_argument("--check", action="store_true",
                    help="report drift and exit non-zero; write nothing")
    args = ap.parse_args()

    if args.date:
        try:
            target = dt.date.fromisoformat(args.date)
        except ValueError:
            sys.exit(f"error: --date must be YYYY-MM-DD, got {args.date!r}")
    elif args.from_git:
        target = git_date(CONTENT_PATHS)
        if target is None:
            sys.exit("error: --from-git needs a git checkout with at least one "
                     "commit touching site content")
    else:
        target = dt.date.today()

    iso, text = target.isoformat(), human(target)
    found = changed = stale = 0
    missing = []

    for path in pages():
        name = os.path.basename(path)
        s = open(path, encoding="utf-8").read()
        m = STAMP_RE.search(s)
        if not m:
            missing.append(name)
            continue
        found += 1
        if m.group(2) == iso and m.group(4) == text:
            continue
        if args.check:
            stale += 1
            print(f"  stale  {name}: {m.group(2)} ({m.group(4)})")
            continue
        s = STAMP_RE.sub(rf"\g<1>{iso}\g<3>{text}\g<5>", s, count=1)
        open(path, "w", encoding="utf-8").write(s)
        changed += 1
        print(f"  stamped {name}: {m.group(2)} -> {iso}")

    for name in missing:
        print(f"  NO STAMP {name}: footer has no 'Last updated <time ...>' element")

    map_changed, map_problems = stamp_sitemap(target, args.check)

    if args.check:
        problems = stale + len(missing) + map_problems
        print(f"{found} page(s) stamped, {stale} stale, {len(missing)} missing, "
              f"{map_problems} sitemap problem(s) (target {iso})")
        sys.exit(1 if problems else 0)

    print(f"{changed} page(s) updated, {found - changed} already at {iso}, "
          f"{map_changed} sitemap entr{'y' if map_changed == 1 else 'ies'} updated"
          + (f", {len(missing)} missing a stamp" if missing else "")
          + (f", {map_problems} sitemap problem(s)" if map_problems else ""))
    if map_problems:
        sys.exit(1)


if __name__ == "__main__":
    main()
