import json
import os
import tempfile
import unittest
from unittest import mock

from backup import common, crypto, restore, vault_files
from tests.helpers import make_keys

PRIV, CERT = make_keys()


class VaultFiles(unittest.TestCase):
    def setUp(self):
        mock.patch.object(crypto, "CERT", CERT).start()
        mock.patch.object(vault_files, "load_keychain", lambda: None).start()
        self.addCleanup(mock.patch.stopall)
        self.vault, self.store, self.cache = tempfile.mkdtemp(), tempfile.mkdtemp(), tempfile.mktemp()
        self.write("Fin/rec.xlsx", b"\x50\x4b binary sheet")
        self.write("Hub/page.html", b"<html>hello</html>" * 50)
        self.write("Hub/copy.html", b"<html>hello</html>" * 50)        # same content -> one blob
        self.write("notes.md", b"# a note")                            # notes are the other job's
        self.write("Studio/box.zip", b"zip")                           # studio zips excluded
        self.write("Hub/page.html.bak-20261004", b"old")               # leftovers excluded

    def write(self, rel, data):
        p = os.path.join(self.vault, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as f:
            f.write(data)

    def run_job(self):
        return vault_files.main(["--local", self.store, "--vault", self.vault, "--cache", self.cache])

    def manifest(self):
        st = common.LocalStore(self.store)
        k = [k for k, _, _ in st.list("sets/") if k.endswith("manifest-files.json")][-1]
        return json.loads(st.get(k))

    def test_scope_dedupe_and_restore(self):
        self.assertEqual(self.run_job(), 0)
        m = self.manifest()
        self.assertEqual(sorted(i["path"] for i in m["items"]), ["Fin/rec.xlsx", "Hub/copy.html", "Hub/page.html"])
        self.assertEqual(m["uploaded_files"], 2)                       # duplicate stored once
        self.assertTrue(all(i["blob"].endswith(".gz.cms") for i in m["items"] if i["path"].endswith(".html")))
        out = tempfile.mkdtemp()
        self.assertEqual(restore.fetch(common.LocalStore(self.store), __import__("datetime").date.fromisoformat(m["set"]), PRIV, out), 0)
        with open(os.path.join(out, "files", "Hub", "page.html"), "rb") as f:
            self.assertEqual(f.read(), b"<html>hello</html>" * 50)

    def test_second_night_uploads_only_changes(self):
        self.run_job()
        self.write("Fin/rec.xlsx", b"\x50\x4b changed sheet")
        self.run_job()
        self.assertEqual(self.manifest()["uploaded_files"], 1)

    def test_wipe_is_flagged(self):
        self.run_job()
        for f in ("Hub/page.html", "Hub/copy.html"):
            os.remove(os.path.join(self.vault, f))
        self.assertEqual(self.run_job(), 1)
        self.assertTrue(any("shrank" in p for p in self.manifest()["problems"]))


if __name__ == "__main__":
    unittest.main()
