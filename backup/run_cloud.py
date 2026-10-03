"""Nightly cloud backup: every D1 database + every KV namespace -> encrypted -> R2, then prune.

  python -m backup.run_cloud              # real run (needs the R2 + Cloudflare secrets)
  python -m backup.run_cloud --local DIR  # same work, written to a folder instead of R2
Exit code 1 + a Slack card on any failure. Nothing is pruned unless every upload succeeded.
"""
import argparse
import os
import sys

from . import cfdump, common, retention


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--local", help="write to this folder instead of R2 (dry run / tests)")
    ap.add_argument("--no-prune", action="store_true")
    args = ap.parse_args(argv)

    store = common.LocalStore(args.local) if args.local else common.bucket_client()
    cf = cfdump.CF(os.environ["CF_BACKUP_RO_TOKEN"], os.environ.get("CF_ACCOUNT_ID", common.ACCOUNT))
    run = common.Run(store, "cloud")
    problems, summary = [], {"d1": {}, "kv": {}}

    for name, uuid in cfdump.d1_databases(cf):
        try:
            sql, dumped, counted = cfdump.d1_dump(cf, uuid)
            run.add(f"d1/{name}.sql", sql.encode())
            summary["d1"][name] = {"tables": len(dumped), "rows": sum(dumped.values())}
            short = {t: (dumped[t], counted[t]) for t in dumped if dumped[t] < counted[t]}
            if short:                                   # rows can only be MORE if people wrote mid-dump
                problems.append(f"D1 {name}: fewer rows dumped than counted: {short}")
        except Exception as e:
            problems.append(f"D1 {name}: {e}")

    for title, ns in cfdump.kv_namespaces(cf):
        try:
            text, n = cfdump.kv_dump(cf, ns)
            run.add(f"kv/{title}.json", text.encode())
            summary["kv"][title] = {"keys": n}
        except Exception as e:
            problems.append(f"KV {title}: {e}")

    if not summary["d1"] and not summary["kv"]:
        problems.append("found no databases or namespaces — refusing to call that a backup")

    manifest = run.finish({"summary": summary, "problems": problems})
    print(f"set {manifest['set']}: {len(run.items)} files, {sum(i['enc_bytes'] for i in run.items):,} bytes encrypted")
    print("summary:", summary)

    if problems:
        common.alert("Nightly cloud backup had problems:\n• " + "\n• ".join(problems))
        return 1
    if not args.no_prune:
        today = common.now_wib().date()
        doomed = retention.keys_to_delete([k for k, _, _ in store.list("sets/")], today)
        for k in doomed:
            store.delete(k)
        print(f"pruned {len(doomed)} old objects")
    return 0


if __name__ == "__main__":
    sys.exit(main())
