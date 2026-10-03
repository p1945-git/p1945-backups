import json
import sqlite3
import unittest

from backup import cfdump
from tests.helpers import FakeD1CF


def sample_db():
    db = sqlite3.connect(":memory:")
    db.executescript("""
      CREATE TABLE kols (id INTEGER PRIMARY KEY, name TEXT, note TEXT, score REAL, blobby BLOB);
      CREATE TABLE "odd name" (a, b);
      CREATE INDEX ix_kols_name ON kols(name);
      CREATE TABLE empty_t (x);
    """)
    rows = [(i, f"KOL {i}", "it's \"quoted\"\nnewline" if i % 7 == 0 else None, i / 3, b"\x00\xff") for i in range(1, 1203)]
    db.executemany("INSERT INTO kols VALUES (?,?,?,?,?)", rows)
    db.execute('INSERT INTO "odd name" VALUES (1, NULL)')
    db.commit()
    return db


class D1Dump(unittest.TestCase):
    def test_dump_restores_to_identical_data(self):
        src = sample_db()
        cf = FakeD1CF({"u1": ("db1", src)}, {})
        sql, dumped, counted = cfdump.d1_dump(cf, "u1")
        self.assertEqual(dumped, counted)
        self.assertEqual(dumped["kols"], 1202)              # 3 pages of 500 -> paging works
        dst = sqlite3.connect(":memory:")
        dst.executescript(sql)
        for t in ("kols", '"odd name"', "empty_t"):
            a = src.execute(f"SELECT * FROM {t} ORDER BY 1").fetchall()
            b = dst.execute(f"SELECT * FROM {t} ORDER BY 1").fetchall()
            self.assertEqual(a, b, t)
        self.assertEqual(dst.execute("SELECT name FROM sqlite_master WHERE type='index'").fetchone()[0], "ix_kols_name")

    def test_only_select_statements_are_sent(self):
        sent = []
        cf = FakeD1CF({"u1": ("db1", sample_db())}, {})
        orig = cf.call
        cf.call = lambda path, body=None, raw=False: (sent.append((body or {}).get("sql", "")), orig(path, body, raw))[1]
        cfdump.d1_dump(cf, "u1")
        self.assertTrue(sent and all(s.lstrip().upper().startswith("SELECT") for s in sent), sent[:3])

    def test_lists_everything_by_discovery(self):
        cf = FakeD1CF({"u1": ("a", sample_db()), "u2": ("b", sample_db())}, {"ns1": {}, "ns2": {}})
        self.assertEqual([n for n, _ in cfdump.d1_databases(cf)], ["a", "b"])
        self.assertEqual([n for n, _ in cfdump.kv_namespaces(cf)], ["ns1", "ns2"])


class KVDump(unittest.TestCase):
    def test_binary_and_unicode_values_survive(self):
        import base64
        vals = {"plain": "héllo ✓".encode(), "bin": b"\x00\x01\xfe\xff", "a/b:c": b"{}"}
        cf = FakeD1CF({}, {"ns": vals})
        text, n = cfdump.kv_dump(cf, "ns")
        self.assertEqual(n, 3)
        got = {k["name"]: base64.b64decode(k["value_b64"]) for k in json.loads(text)["keys"]}
        self.assertEqual(got, vals)


if __name__ == "__main__":
    unittest.main()
