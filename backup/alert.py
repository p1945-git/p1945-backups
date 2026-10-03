"""Used by workflows: python -m backup.alert "message"  -> Slack card (if webhook set) + stdout."""
import sys

from . import common

common.alert(" ".join(sys.argv[1:]) or "backup job failed")
