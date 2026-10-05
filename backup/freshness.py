"""Daily freshness check: alert if the newest backup of any source is older than 36 hours.
Run on GitHub Actions at 12:00 WIB, well after the 02:00 and 02:30 jobs have had their chance.
"""
import datetime
import sys

from . import common

MAX_AGE = datetime.timedelta(hours=36)
SOURCES = ("cloud", "vault", "files")


def check(store, now=None):
    now = now or datetime.datetime.now(datetime.timezone.utc)
    newest = {}
    for key, _, when in store.list("sets/"):
        for s in SOURCES:
            if key.endswith(f"/manifest-{s}.json") and (s not in newest or when > newest[s]):
                newest[s] = when
    problems = []
    for s in SOURCES:
        if s not in newest:
            problems.append(f"no '{s}' backup exists at all")
        elif now - newest[s] > MAX_AGE:
            hrs = (now - newest[s]).total_seconds() / 3600
            problems.append(f"'{s}' backup is {hrs:.0f} h old (limit 36 h)")
    return problems, newest


def main():
    problems, newest = check(common.bucket_client())
    if problems:
        common.alert("Backups are STALE:\n• " + "\n• ".join(problems))
        return 1
    print("fresh:", {s: t.isoformat(timespec="minutes") for s, t in newest.items()})
    return 0


if __name__ == "__main__":
    sys.exit(main())
