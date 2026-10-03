import os
import subprocess
import tempfile


def make_keys():
    d = tempfile.mkdtemp()
    priv, cert = os.path.join(d, "k.pem"), os.path.join(d, "c.pem")
    subprocess.run(["openssl", "genpkey", "-algorithm", "RSA", "-pkeyopt", "rsa_keygen_bits:2048",
                    "-out", priv], check=True, capture_output=True)
    subprocess.run(["openssl", "req", "-new", "-x509", "-key", priv, "-days", "30", "-subj", "/CN=t",
                    "-out", cert], check=True, capture_output=True)
    return priv, cert


class FakeD1CF:
    """Stands in for the Cloudflare API: answers D1 /query with a real SQLite database,
    and KV list/value calls from a dict. So the dump logic is tested against genuine SQL."""

    def __init__(self, sqlite_dbs, kv):
        self.dbs, self.kv = sqlite_dbs, kv         # {uuid: sqlite3.Connection}, {ns: {key: bytes}}
        self.calls = 0

    def paged(self, path, params=None):
        if path == "/d1/database":
            for u, (name, _) in self.dbs.items():
                yield {"name": name, "uuid": u}
        elif path == "/storage/kv/namespaces":
            for ns in self.kv:
                yield {"title": ns, "id": ns}
        elif path.endswith("/keys"):
            ns = path.split("/")[-2]
            for k in self.kv[ns]:
                yield {"name": k, "expiration": None, "metadata": None}

    def call(self, path, body=None, raw=False):
        self.calls += 1
        if "/query" in path:
            uuid = path.split("/")[-2]
            db = self.dbs[uuid][1]
            cur = db.execute(body["sql"], body["params"])
            names = [c[0] for c in cur.description]
            # real D1 hands BLOBs back as a list of byte values
            rows = [{n: (list(v) if isinstance(v, bytes) else v) for n, v in zip(names, r)}
                    for r in cur.fetchall()]
            return {"result": [{"results": rows}]}
        if "/values/" in path:
            from urllib.parse import unquote
            ns, key = path.split("/")[-3], unquote(path.split("/")[-1])
            return self.kv[ns][key]
        raise AssertionError(path)
