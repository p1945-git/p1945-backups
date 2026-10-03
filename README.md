# p1945-backups

Nightly encrypted backups of Project 1945's Cloudflare D1 + KV, and the work vault's notes, into the
R2 bucket `p1945-backups`. Full plain-language runbook (status, Denny's checklist, restore drill):
`P1945-HUB/[SYS-MASTER] Systems & Tools/[SYS] 202610 Backups Runbook 2026-10-04 V1.md`.

- `backup/run_cloud.py` — D1 + KV → gzip → encrypt → R2 → prune (GitHub Actions, 02:00 WIB)
- `backup/vault_backup.py` — vault `.md` → tar.gz → encrypt → R2 (Mac launchd, 02:30 WIB)
- `backup/freshness.py` — alert if any backup > 36 h old (GitHub Actions, 12:00 WIB)
- `backup/restore.py` — `list` · `fetch` (decrypt + fingerprint check) · `inspect`
- `backup/pg_backup.py`, `sql/backup_ro.sql` — Phase 2, e-commerce Postgres (untested, not enabled)
- `keys/backup-cert.pem` — PUBLIC certificate only. The private key is never in this repo.

Standard library only (+ the system `openssl`). Tests: `python3 -m unittest discover -s tests -t .`

## Go-live
1. Secrets exist in GitHub (`R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `CF_BACKUP_RO_TOKEN`, `SLACK_ALERT_WEBHOOK`) and in the Mac Keychain (`mac/store-keys.sh`).
2. Uncomment the `schedule:` blocks in `.github/workflows/*.yml`, push.
3. Actions → nightly-backup → Run workflow once; check the set appears in R2.
4. Install `mac/com.project1945.vault-backup.plist` into `~/Library/LaunchAgents/`, `launchctl bootstrap gui/$(id -u) …`.
5. Practice restore (runbook §4).
