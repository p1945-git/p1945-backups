#!/bin/bash
# Called by launchd at 02:30 WIB. Keys come from the Keychain inside the Python code.
export PATH=/opt/homebrew/bin:/usr/bin:/bin
cd "$(dirname "$0")/.." || exit 1
mkdir -p "$HOME/Library/Logs"
{ echo "=== $(date '+%F %T %Z') ==="; python3 -m backup.vault_backup; echo "exit=$?"; } >> "$HOME/Library/Logs/p1945-vault-backup.log" 2>&1
