"""PHASE 2 — e-commerce Postgres (Render) backup. NOT YET ENABLED, NOT YET TESTED AGAINST THE REAL DATABASE.

Waits on three things that are Denny's: the `backup_ro` login (sql/backup_ro.sql), a decision on
how the job reaches the database (see README → Phase 2), and the secrets that follow from it.
  PG_DSN=postgresql://backup_ro:...@127.0.0.1:5433/p1945_ecomm python -m backup.pg_backup
The DSN is read from the environment and never printed.
"""
import os
import subprocess
import sys
import tempfile

from . import common


def main():
    dsn = os.environ["PG_DSN"]
    store = common.bucket_client()
    run = common.Run(store, "pg")
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "p1945_ecomm.dump")
        p = subprocess.run(["pg_dump", "--format=custom", "--no-owner", "--no-privileges",
                            "--file", out, dsn], capture_output=True, text=True)
        if p.returncode != 0:
            common.alert("Postgres backup failed: " + p.stderr.strip().splitlines()[-1][:200])
            return 1
        toc = subprocess.run(["pg_restore", "--list", out], capture_output=True, text=True)
        entries = sum(1 for ln in toc.stdout.splitlines() if ln and not ln.startswith(";"))
        with open(out, "rb") as f:
            run.add("pg/p1945_ecomm.dump", f.read(), note=f"{entries} objects in pg_restore --list")
    run.finish({"toc_entries": entries})
    print("postgres dump uploaded,", entries, "objects")
    return 0


if __name__ == "__main__":
    sys.exit(main())
