"""Get a backup back. Everything here runs on YOUR machine with the offline private key.

  python -m backup.restore list
  python -m backup.restore fetch --set 2026-10-04 --key /path/private.pem --out ./restored [--from DIR]
  python -m backup.restore inspect restored/d1/p1945-kol.sql      # rows per table in a D1 dump
Each file is decrypted and checked against the SHA-256 in the set's manifest before it is trusted.
--from DIR reads the weekly copy on the Mac's disk instead of R2.
"""
import argparse
import collections
import gzip
import hashlib
import json
import os
import re
import sys

from . import common, crypto


def fetch(store, day, key_path, out):
    prefix = common.set_prefix(day)
    manifests = [k for k, _, _ in store.list(prefix) if "/manifest-" in k]
    if not manifests:
        raise SystemExit(f"no backup set for {day.isoformat()}")
    bad = 0
    for mk in manifests:
        m = json.loads(store.get(mk))
        if m.get("source") == "files":               # work files: path -> shared blob
            for it in m["items"]:
                plain = crypto.decrypt(store.get(it["blob"]), key_path)
                if it["blob"].endswith(".gz.cms"):
                    plain = gzip.decompress(plain)
                ok = hashlib.sha256(plain).hexdigest() == it["sha256"]
                dest = os.path.join(out, "files", *it["path"].split("/"))
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                with open(dest, "wb") as f:
                    f.write(plain)
                print(("OK   " if ok else "BAD  ") + "files/" + it["path"], f"{len(plain):,} bytes")
                bad += not ok
            continue
        for it in m["items"]:
            plain = crypto.decrypt(store.get(it["key"]), key_path)
            ok = hashlib.sha256(plain).hexdigest() == it["plain_sha256"]
            rel = it["key"][len(prefix):-len(".cms")]
            if ok and rel.endswith(".gz") and not rel.endswith(".tar.gz"):
                plain, rel = gzip.decompress(plain), rel[:-3]
            dest = os.path.join(out, *rel.split("/"))
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with open(dest, "wb") as f:
                f.write(plain)
            print(("OK   " if ok else "BAD  ") + rel, f"{len(plain):,} bytes")
            bad += not ok
    return bad


def inspect_sql(path):
    counts = collections.Counter(re.findall(r'^INSERT INTO "((?:[^"]|"")+)"', open(path, encoding="utf-8").read(), re.M))
    for t, n in sorted(counts.items()):
        print(f"{t}: {n} rows")


def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    f = sub.add_parser("fetch")
    f.add_argument("--set", required=True)
    f.add_argument("--key", required=True)
    f.add_argument("--out", required=True)
    f.add_argument("--from", dest="src")
    i = sub.add_parser("inspect")
    i.add_argument("file")
    a = ap.parse_args(argv)
    if a.cmd == "inspect":
        return inspect_sql(a.file)
    store = common.LocalStore(a.src) if getattr(a, "src", None) else common.bucket_client()
    if a.cmd == "list":
        for d in sorted({k.split("/")[1] for k, _, _ in store.list("sets/") if k.count("/") >= 2}):
            print(d)
        return 0
    import datetime
    return 1 if fetch(store, datetime.date.fromisoformat(a.set), a.key, a.out) else 0


if __name__ == "__main__":
    sys.exit(main())
