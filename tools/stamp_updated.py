#!/usr/bin/env python3
"""Stamp the "Last updated" date into every page's footer.

Rewrites the <time> element inside the footer of each ../*.html page so the date
visitors see matches the day the site was actually published:

    python3 tools/stamp_updated.py                # today
    python3 tools/stamp_updated.py --from-git     # date of the last commit
    python3 tools/stamp_updated.py --date 2026-08-04
    python3 tools/stamp_updated.py --check        # verify only, change nothing

Why: the footer date is the only thing on the site telling a reviewer, a program
officer, or a prospective student whether they are looking at current work. Hand
-maintained, it silently rots, which is worse than showing nothing -- a stale date
actively misinforms. Run this immediately before committing a content change.

--from-git reads the last COMMIT date, so it is the right choice when re-stamping
a repository whose content has not changed since it was committed. For the normal
case (you edited pages and are about to commit) the default of today is correct,
because the commit you are about to make will carry today's date.

--check exits non-zero if any page is missing a stamp or disagrees with the target
date, which makes it usable as a pre-commit hook or CI step.

Both the machine-readable datetime attribute and the human-readable text are
written together, so they can never drift apart.
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


def human(d):
    """2026-08-04 -> '4 August 2026'. No leading zero, matching the site's prose."""
    return f"{d.day} {d:%B} {d.year}"


def git_commit_date():
    """Author date of HEAD as a date object, or None outside a git checkout."""
    try:
        out = subprocess.run(
            ["git", "-C", ROOT, "log", "-1", "--format=%cs"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        return dt.date.fromisoformat(out)
    except (subprocess.CalledProcessError, FileNotFoundError, ValueError):
        return None


def pages():
    return sorted(glob.glob(os.path.join(ROOT, "*.html")))


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--from-git", action="store_true",
                     help="use the date of the last commit instead of today")
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
        target = git_commit_date()
        if target is None:
            sys.exit("error: --from-git needs a git checkout with at least one commit")
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

    if args.check:
        problems = stale + len(missing)
        print(f"{found} page(s) stamped, {stale} stale, {len(missing)} missing "
              f"(target {iso})")
        sys.exit(1 if problems else 0)

    print(f"{changed} page(s) updated, {found - changed} already at {iso}"
          + (f", {len(missing)} missing a stamp" if missing else ""))


if __name__ == "__main__":
    main()
