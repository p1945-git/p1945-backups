#!/bin/bash
# Run ONCE by Denny, in Terminal. Stores the backup keys in the macOS Keychain. Each value is typed or
# pasted at a hidden prompt — it never appears on screen, in shell history, or in any file.
# Press Return on the Slack line to skip it.
set -e
store() {  # service, label
  echo "Paste $2, then press Return (hidden):"
  security add-generic-password -U -a p1945 -s "$1" -w
}
store p1945-backup-r2-access-key-id "the R2 Access Key ID"
store p1945-backup-r2-secret-access-key "the R2 Secret Access Key"
store p1945-backup-slack-webhook "the Slack alert webhook (optional)"
echo "Done."
