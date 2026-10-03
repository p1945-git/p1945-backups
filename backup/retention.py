"""Which backup sets to keep: 14 daily · 8 weekly · 12 monthly. Pure logic, no network.

A set is one date folder (sets/YYYY-MM-DD/). Weekly keeps the OLDEST set in each of the last 8
ISO weeks and monthly the OLDEST in each of the last 12 calendar months, so a missed Sunday or
missed 1st never leaves a hole. Two guards stop a bug from emptying the bucket.
"""
import datetime
import re

SET_RE = re.compile(r"^sets/(\d{4}-\d{2}-\d{2})/")
DAILY, WEEKLY, MONTHLY, NEVER_PRUNE_NEWEST = 14, 8, 12, 3


def set_date(key):
    m = SET_RE.match(key)
    if not m:
        return None
    try:
        return datetime.date.fromisoformat(m.group(1))
    except ValueError:
        return None


def keep_dates(dates, today):
    dates = sorted(set(dates))
    keep = {d for d in dates if (today - d).days < DAILY}
    keep.update(dates[-NEVER_PRUNE_NEWEST:])
    weeks = {}
    for d in dates:
        weeks.setdefault(d.isocalendar()[:2], []).append(d)
    for wk in sorted(weeks)[-WEEKLY:]:
        keep.add(min(weeks[wk]))
    months = {}
    for d in dates:
        months.setdefault((d.year, d.month), []).append(d)
    for mo in sorted(months)[-MONTHLY:]:
        keep.add(min(months[mo]))
    return keep


def keys_to_delete(keys, today):
    """Return the object keys to delete. Anything not under a dated set is never touched."""
    by_date = {}
    for k in keys:
        d = set_date(k)
        if d:
            by_date.setdefault(d, []).append(k)
    if not by_date:
        return []
    keep = keep_dates(by_date, today)
    assert keep, "refusing to prune: keep-set is empty"
    return [k for d, ks in by_date.items() if d not in keep for k in ks]
