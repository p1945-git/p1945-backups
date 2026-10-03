"""Mac job: back up the work vault's notes (.md only) to R2, encrypted, and keep a weekly copy on disk.

  python -m backup.vault_backup [--local DIR] [--vault PATH]
R2 keys come from the macOS Keychain (set once with mac/store-keys.sh) — never from a file.
"""
import argparse
import datetime
import io
import json
import os
import subprocess
import sys
import tarfile

from . import common, retention

DEFAULT_VAULT = os.path.expanduser(
    "~/Library/Mobile Documents/iCloud~md~obsidian/Documents/P1945-HUB")
SKIP_DIRS = {".git", ".obsidian", ".trash", ".Trash", "node_modules", "__pycache__"}
LOCAL_COPY = os.path.expanduser("~/Backups/p1945")
KEYCHAIN = {"R2_ACCESS_KEY_ID": "p1945-backup-r2-access-key-id",
            "R2_SECRET_ACCESS_KEY": "p1945-backup-r2-secret-access-key",
            "SLACK_ALERT_WEBHOOK": "p1945-backup-slack-webhook"}


def load_keychain(env=os.environ):
    for var, service in KEYCHAIN.items():
        if not env.get(var):
            p = subprocess.run(["security", "find-generic-password", "-s", service, "-w"],
                               capture_output=True, text=True)
            if p.returncode == 0:
                env[var] = p.stdout.strip()


def pack(vault):
    """Return (tar.gz bytes, files_packed, icloud_placeholders_skipped)."""
    buf, n, skipped = io.BytesIO(), 0, 0
    with tarfile.open(fileobj=buf, mode="w:gz", compresslevel=6) as tar:
        for d, dirs, files in os.walk(vault):
            dirs[:] = sorted(x for x in dirs if x not in SKIP_DIRS)
            for f in sorted(files):
                if f.endswith(".icloud"):               # not downloaded to this Mac — can't be read
                    skipped += f.startswith(".") and f.endswith(".md.icloud")
                    continue
                if f.endswith(".md"):
                    full = os.path.join(d, f)
                    tar.add(full, arcname=os.path.relpath(full, vault), recursive=False)
                    n += 1
    return buf.getvalue(), n, skipped


def previous_count(store):
    ms = sorted(k for k, _, _ in store.list("sets/") if k.endswith("manifest-vault.json"))
    if not ms:
        return None
    try:
        return json.loads(store.get(ms[-1])).get("files")
    except Exception:
        return None


def pull_weekly(store, day):
    """Sunday: copy today's whole (still-encrypted) set to this Mac, keep the newest 4."""
    prefix = common.set_prefix(day)
    for key, _, _ in store.list(prefix):
        dest = os.path.join(LOCAL_COPY, *key.split("/"))
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "wb") as f:
            f.write(store.get(key))
    sets = sorted(os.listdir(os.path.join(LOCAL_COPY, "sets"))) if os.path.isdir(LOCAL_COPY + "/sets") else []
    for old in sets[:-4]:
        for d, _, fs in os.walk(os.path.join(LOCAL_COPY, "sets", old), topdown=False):
            for f in fs:
                os.remove(os.path.join(d, f))
            os.rmdir(d)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--local", help="write to this folder instead of R2 (dry run)")
    ap.add_argument("--vault", default=DEFAULT_VAULT)
    args = ap.parse_args(argv)
    load_keychain()
    store = common.LocalStore(args.local) if args.local else common.bucket_client()

    data, n, skipped = pack(args.vault)
    problems = []
    prev = previous_count(store)
    if n == 0:
        problems.append("vault produced 0 notes — wrong path or iCloud offline")
    elif prev and n < 0.8 * prev:
        problems.append(f"vault shrank: {n} notes vs {prev} last time (a wipe looks like this)")
    if skipped:
        problems.append(f"{skipped} notes are iCloud placeholders not downloaded to this Mac, so NOT in the backup")

    run = common.Run(store, "vault")
    run.add("vault/p1945-hub-notes.tar.gz", data, compress=False)
    manifest = run.finish({"files": n, "icloud_placeholders_skipped": skipped, "problems": problems})
    print(f"vault set {manifest['set']}: {n} notes, {len(data):,} bytes packed, "
          f"{manifest['items'][0]['enc_bytes']:,} encrypted")

    if not args.local and run.day.weekday() == 6:       # Sunday
        pull_weekly(store, run.day)
        print("weekly copy pulled to", LOCAL_COPY)
    if problems:
        common.alert("Vault backup had problems:\n• " + "\n• ".join(problems))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
