"""Mac job: back up the vault's WORK FILES (everything except notes) to R2, encrypted, changed files only.

  python -m backup.vault_files [--local DIR] [--vault PATH]
CEO 2026-10-04 19:41 WIB chose "work files, skip the studio zips": spreadsheets, PDFs, Word files,
hub pages, data files and images (~6.3 GB). Notes (.md) stay in vault_backup's nightly tarball.

Each distinct file content is stored ONCE, named by its SHA-256: blobs/<sha>[.gz].cms. A night's
manifest (sets/<day>/manifest-files.json) maps every path to its blob, so after the first night only
changed files are uploaded, and any kept night can be restored whole. Blobs live outside sets/, so
the retention pruner never touches them.
"""
import argparse
import gzip
import hashlib
import json
import os
import sys

from . import common, crypto
from .vault_backup import DEFAULT_VAULT, LOCAL_COPY, SKIP_DIRS, load_keychain

SKIP_EXT = {".md", ".zip", ".mp4", ".mov", ".m4v", ".icloud"}
SKIP_NAMES = {".DS_Store", "Icon\r"}
TEXT_EXT = {".json", ".jsonl", ".csv", ".tsv", ".html", ".htm", ".txt", ".xml", ".sql", ".svg",
            ".js", ".css", ".py", ".sh", ".yaml", ".yml", ".toml", ".log"}
CACHE = os.path.join(LOCAL_COPY, "files-hash-cache.json")


def wanted(name):
    ext = os.path.splitext(name)[1].lower()
    return not (name in SKIP_NAMES or ext in SKIP_EXT or ".bak" in name or name.startswith("~$"))


def scan(vault):
    """Yield (relpath, fullpath) for every file in scope, plus a count of iCloud placeholders."""
    found, placeholders = [], 0
    for d, dirs, files in os.walk(vault):
        dirs[:] = sorted(x for x in dirs if x not in SKIP_DIRS and not x.startswith(".tmp.drive"))  # Drive's in-flight copies
        for f in sorted(files):
            if f.endswith(".icloud"):
                placeholders += not f.endswith(".md.icloud")
                continue
            full = os.path.join(d, f)
            if wanted(f) and not os.path.islink(full):   # links point elsewhere (e.g. a tool folder's python) and may dangle
                found.append((os.path.relpath(full, vault), full))
    return found, placeholders


def blob_key(sha, gz):
    return f"blobs/{sha}{'.gz' if gz else ''}.cms"


def load_cache(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def previous_count(store):
    ms = sorted(k for k, _, _ in store.list("sets/") if k.endswith("manifest-files.json"))
    if not ms:
        return None
    try:
        return json.loads(store.get(ms[-1])).get("files")
    except Exception:
        return None


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--local", help="write to this folder instead of R2 (dry run)")
    ap.add_argument("--vault", default=DEFAULT_VAULT)
    ap.add_argument("--cache", default=CACHE)
    args = ap.parse_args(argv)
    load_keychain()
    store = common.LocalStore(args.local) if args.local else common.bucket_client()

    started = common.now_wib()
    files, placeholders = scan(args.vault)
    have = {k for k, _, _ in store.list("blobs/")}
    cache, new_cache = load_cache(args.cache), {}
    items, problems = [], []
    uploaded = up_bytes = total_bytes = 0

    for rel, full in files:
        try:
            st = os.stat(full)
            c = cache.get(rel)
            data = None
            if c and c[0] == st.st_size and c[1] == st.st_mtime_ns:
                sha = c[2]
            else:
                with open(full, "rb") as f:
                    data = f.read()
                sha = hashlib.sha256(data).hexdigest()
            gz = os.path.splitext(rel)[1].lower() in TEXT_EXT
            key = blob_key(sha, gz)
            if key not in have:
                if data is None:
                    with open(full, "rb") as f:
                        data = f.read()
                    if hashlib.sha256(data).hexdigest() != sha:      # cache lied: file changed in place
                        sha = hashlib.sha256(data).hexdigest()
                        key = blob_key(sha, gz)
                if key not in have:
                    body = gzip.compress(data, 6, mtime=0) if gz else data
                    store.put(key, crypto.encrypt(body))
                    have.add(key)
                    uploaded += 1
                    up_bytes += len(data)
            new_cache[rel] = [st.st_size, st.st_mtime_ns, sha]
            total_bytes += st.st_size
            items.append({"path": rel, "blob": key, "sha256": sha, "bytes": st.st_size})
        except Exception as e:                       # one unreadable file must not lose the night
            problems.append(f"{rel}: {type(e).__name__}: {str(e)[:120]}")

    prev = previous_count(store)
    if not items:
        problems.append("0 work files found — wrong path or iCloud offline")
    elif prev and len(items) < 0.8 * prev:
        problems.append(f"work files shrank: {len(items)} vs {prev} last time (a wipe looks like this)")
    if placeholders:
        problems.append(f"{placeholders} files are iCloud placeholders not downloaded to this Mac, so NOT in the backup")

    day = started.date()
    manifest = {"source": "files", "set": day.isoformat(),
                "started_wib": started.isoformat(timespec="seconds"),
                "finished_wib": common.now_wib().isoformat(timespec="seconds"),
                "files": len(items), "bytes": total_bytes,
                "uploaded_files": uploaded, "uploaded_bytes": up_bytes,
                "items": items, "problems": problems}
    store.put(f"{common.set_prefix(day)}manifest-files.json", json.dumps(manifest, indent=1).encode())
    if not args.local:
        os.makedirs(os.path.dirname(args.cache), exist_ok=True)
        with open(args.cache, "w") as f:
            json.dump(new_cache, f)
    print(f"files set {day}: {len(items)} files ({total_bytes/1e9:.2f} GB), "
          f"uploaded {uploaded} new ({up_bytes/1e6:.1f} MB), {len(problems)} problems")
    if problems:
        common.alert("Work-files backup had problems:\n• " + "\n• ".join(problems[:20]))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
