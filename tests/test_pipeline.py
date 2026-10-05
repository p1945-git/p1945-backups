import datetime
import gzip
import io
import json
import os
import sqlite3
import tarfile
import tempfile
import unittest
from unittest import mock

from backup import common, crypto, freshness, restore, run_cloud, vault_backup
from tests.helpers import FakeD1CF, make_keys
from tests.test_cfdump import sample_db

PRIV, CERT = make_keys()


class Pipeline(unittest.TestCase):
    def setUp(self):
        self.store_dir = tempfile.mkdtemp()
        self.enc = mock.patch.object(crypto, "CERT", CERT)
        self.enc.start()
        self.addCleanup(mock.patch.stopall)

    def run_cloud(self, cf):
        env = {"CF_BACKUP_RO_TOKEN": "t"}
        with mock.patch.dict(os.environ, env), \
             mock.patch.object(run_cloud.cfdump, "CF", lambda *a: cf):
            return run_cloud.main(["--local", self.store_dir])

    def test_cloud_backup_then_restore_matches(self):
        src = sample_db()
        cf = FakeD1CF({"u1": ("db1", src)}, {"ns": {"k": b"v"}})
        self.assertEqual(self.run_cloud(cf), 0)
        store = common.LocalStore(self.store_dir)
        keys = [k for k, _, _ in store.list("sets/")]
        self.assertTrue(any(k.endswith("d1/db1.sql.gz.cms") for k in keys))
        self.assertTrue(any(k.endswith("manifest-cloud.json") for k in keys))
        raw = b"".join(store.get(k) for k in keys if k.endswith(".cms"))
        self.assertNotIn(b"KOL 1", raw)                      # nothing readable at rest
        out = tempfile.mkdtemp()
        bad = restore.fetch(store, common.now_wib().date(), PRIV, out)
        self.assertEqual(bad, 0)
        dst = sqlite3.connect(":memory:")
        dst.executescript(open(os.path.join(out, "d1", "db1.sql")).read())
        self.assertEqual(dst.execute("SELECT COUNT(*) FROM kols").fetchone()[0], 1202)

    def test_nothing_found_is_a_failure_not_a_green_tick(self):
        self.assertEqual(self.run_cloud(FakeD1CF({}, {})), 1)

    def test_tampered_backup_is_caught_on_restore(self):
        cf = FakeD1CF({"u1": ("db1", sample_db())}, {})
        self.run_cloud(cf)
        store = common.LocalStore(self.store_dir)
        mk = next(k for k, _, _ in store.list("sets/") if k.endswith("manifest-cloud.json"))
        m = json.loads(store.get(mk))
        m["items"][0]["plain_sha256"] = "0" * 64
        store.put(mk, json.dumps(m).encode())
        self.assertEqual(restore.fetch(store, common.now_wib().date(), PRIV, tempfile.mkdtemp()), 1)

    def test_prune_runs_only_on_success_and_spares_recent(self):
        store = common.LocalStore(self.store_dir)
        for i in range(1, 60):
            d = common.now_wib().date() - datetime.timedelta(days=i)
            store.put(f"sets/{d}/manifest-cloud.json", b"{}")
        self.assertEqual(self.run_cloud(FakeD1CF({"u1": ("db1", sample_db())}, {})), 0)
        left = {k.split("/")[1] for k, _, _ in store.list("sets/")}
        self.assertLess(len(left), 40)
        self.assertIn(str(common.now_wib().date()), left)


class Vault(unittest.TestCase):
    def test_pack_takes_only_md_and_skips_hidden_and_placeholders(self):
        v = tempfile.mkdtemp()
        os.makedirs(os.path.join(v, "[FAT-MASTER] x"))
        os.makedirs(os.path.join(v, ".git"))
        for rel in ["a.md", "[FAT-MASTER] x/b [odd] & name.md", "c.xlsx", ".git/h.md", ".gone.md.icloud"]:
            open(os.path.join(v, rel), "w").write("x")
        data, n, skipped = vault_backup.pack(v)
        names = sorted(tarfile.open(fileobj=io.BytesIO(data)).getnames())
        self.assertEqual(names, ["[FAT-MASTER] x/b [odd] & name.md", "a.md"])
        self.assertEqual((n, skipped), (2, 1))

    def test_shrunken_vault_raises_an_alarm(self):
        store_dir, v = tempfile.mkdtemp(), tempfile.mkdtemp()
        store = common.LocalStore(store_dir)
        store.put("sets/2026-10-01/manifest-vault.json", json.dumps({"files": 1000}).encode())
        open(os.path.join(v, "a.md"), "w").write("x")
        with mock.patch.object(crypto, "CERT", CERT), \
             mock.patch.object(vault_backup, "load_keychain", lambda: None), \
             mock.patch.object(common, "alert") as al:
            self.assertEqual(vault_backup.main(["--local", store_dir, "--vault", v]), 1)
        self.assertIn("shrank", al.call_args[0][0])


class Freshness(unittest.TestCase):
    def test_flags_old_and_missing(self):
        d = tempfile.mkdtemp()
        store = common.LocalStore(d)
        store.put("sets/2026-10-04/manifest-cloud.json", b"{}")
        mtime = os.stat(os.path.join(d, "sets/2026-10-04/manifest-cloud.json")).st_mtime
        now = datetime.datetime.fromtimestamp(mtime, datetime.timezone.utc)
        problems, _ = freshness.check(store, now + datetime.timedelta(hours=10))
        self.assertEqual(len(problems), 2)                    # cloud fresh; vault + files never existed
        self.assertIn("vault", problems[0])
        self.assertIn("files", problems[1])
        problems, _ = freshness.check(store, now + datetime.timedelta(hours=40))
        self.assertEqual(len(problems), 3)
        self.assertIn("40 h old", " ".join(problems))


if __name__ == "__main__":
    unittest.main()
