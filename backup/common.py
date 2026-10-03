"""Shared plumbing: where backups go, how a run is named, how problems are announced."""
import datetime
import gzip
import hashlib
import json
import os
import urllib.request

from . import crypto
from .s3lite import S3

WIB = datetime.timezone(datetime.timedelta(hours=7))
ACCOUNT = "27593381eccc0aa1accde8a714399c2e"          # work Cloudflare account (not a secret)
BUCKET = "p1945-backups"


def now_wib():
    return datetime.datetime.now(WIB)


def bucket_client(env=os.environ):
    return S3(f"https://{env.get('CF_ACCOUNT_ID', ACCOUNT)}.r2.cloudflarestorage.com",
              env.get("R2_BUCKET", BUCKET), env["R2_ACCESS_KEY_ID"], env["R2_SECRET_ACCESS_KEY"])


def set_prefix(day):
    return f"sets/{day.isoformat()}/"


class Run:
    """One source's backup into today's set: encrypt each artifact, upload, then a manifest."""

    def __init__(self, s3, source, day=None):
        self.s3, self.source = s3, source
        self.day = day or now_wib().date()
        self.items = []
        self.started = now_wib()

    def add(self, relpath, plaintext, note=None, compress=True):
        if compress:                                  # text compresses ~10x; stored name gains .gz
            plaintext, relpath = gzip.compress(plaintext, 6, mtime=0), relpath + ".gz"
        enc = crypto.encrypt(plaintext)
        key = f"{set_prefix(self.day)}{relpath}.cms"
        self.s3.put(key, enc)
        self.items.append({"key": key, "plain_bytes": len(plaintext),
                           "plain_sha256": hashlib.sha256(plaintext).hexdigest(),
                           "enc_bytes": len(enc), **({"note": note} if note else {})})

    def finish(self, extra=None):
        manifest = {"source": self.source, "set": self.day.isoformat(),
                    "started_wib": self.started.isoformat(timespec="seconds"),
                    "finished_wib": now_wib().isoformat(timespec="seconds"),
                    "items": self.items, **(extra or {})}
        self.s3.put(f"{set_prefix(self.day)}manifest-{self.source}.json",
                    json.dumps(manifest, indent=1).encode())
        return manifest


def alert(text, level="bad", env=os.environ):
    """Post to Slack #p1945-alerts if a webhook is configured; always print."""
    print(("🔴 " if level == "bad" else "🟢 ") + text)
    url = env.get("SLACK_ALERT_WEBHOOK")
    if not url:
        return
    body = {"attachments": [{"color": "#d9534f" if level == "bad" else "#2eb886",
                             "title": "Backups", "text": text}]}
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=30).read()
    except Exception as e:                           # an alert failing must never hide the cause
        print("(Slack post failed:", e, ")")


class LocalStore:
    """Same put/get/delete/list as S3, backed by a folder — for dry runs and tests."""

    def __init__(self, root):
        self.root = root

    def _p(self, key):
        return os.path.join(self.root, *key.split("/"))

    def put(self, key, data):
        os.makedirs(os.path.dirname(self._p(key)), exist_ok=True)
        with open(self._p(key), "wb") as f:
            f.write(data)

    def get(self, key):
        with open(self._p(key), "rb") as f:
            return f.read()

    def delete(self, key):
        os.remove(self._p(key))

    def list(self, prefix=""):
        for d, _, fs in os.walk(self.root):
            for f in fs:
                full = os.path.join(d, f)
                key = os.path.relpath(full, self.root).replace(os.sep, "/")
                if key.startswith(prefix):
                    st = os.stat(full)
                    yield key, st.st_size, datetime.datetime.fromtimestamp(st.st_mtime, datetime.timezone.utc)
