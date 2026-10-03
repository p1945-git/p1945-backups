"""Read-only dumps of every Cloudflare D1 database and KV namespace in the work account.

Needs only a token with  Account › D1 › Read  and  Account › Workers KV Storage › Read.
It uses the SQL query route (SELECT only) rather than the D1 export route, because the export
route may need a write permission — a read-only token is the whole point.
Databases and namespaces are LISTED, never hard-coded, so a new one is backed up automatically.
"""
import base64
import json
import urllib.parse
import urllib.request

API = "https://api.cloudflare.com/client/v4"
PAGE = 500


class CF:
    def __init__(self, token, account):
        self.token, self.account = token, account

    def call(self, path, body=None, raw=False):
        req = urllib.request.Request(
            f"{API}/accounts/{self.account}{path}",
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as r:
            data = r.read()
        if raw:
            return data
        out = json.loads(data)
        if not out.get("success"):
            raise RuntimeError(f"Cloudflare {path}: {out.get('errors')}")
        return out

    def paged(self, path, params=None):
        cursor = None
        while True:
            q = dict(params or {})
            q["limit"] = 1000
            if cursor:
                q["cursor"] = cursor
            out = self.call(path + "?" + urllib.parse.urlencode(q))
            yield from out["result"]
            cursor = (out.get("result_info") or {}).get("cursor")
            if not cursor:
                return


# ---------- D1 ----------

def sql_literal(v):
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, (bytes, bytearray)):
        v = list(v)
    if isinstance(v, list):                        # D1 returns BLOBs as a list of byte values
        return "X'" + bytes(v).hex() + "'"
    return "'" + str(v).replace("'", "''") + "'"


def qid(name):
    return '"' + name.replace('"', '""') + '"'


def d1_databases(cf):
    return [(d["name"], d["uuid"]) for d in cf.paged("/d1/database")]


def d1_dump(cf, uuid):
    """Return (sql_text, {table: rows_dumped}, {table: rows_counted_before}). SELECT-only."""
    def q(sql, params=None):
        return cf.call(f"/d1/database/{uuid}/query", {"sql": sql, "params": params or []}
                       )["result"][0]["results"]

    objs = q("SELECT type,name,sql FROM sqlite_master WHERE sql IS NOT NULL "
             "AND name NOT LIKE 'sqlite\\_%' ESCAPE '\\' AND name NOT LIKE '\\_cf\\_%' ESCAPE '\\' "
             "ORDER BY name")
    tables = [o for o in objs if o["type"] == "table"]
    later = [o for o in objs if o["type"] != "table"]
    out = ["PRAGMA defer_foreign_keys = TRUE;"]
    for t in tables:
        out.append(t["sql"].rstrip(";") + ";")
    dumped, counted = {}, {}
    for t in tables:
        name = t["name"]
        counted[name] = q(f"SELECT COUNT(*) AS n FROM {qid(name)}")[0]["n"]
        n, last = 0, -1
        while True:
            try:
                rows = q(f"SELECT rowid AS __rid, * FROM {qid(name)} WHERE rowid > ? "
                         f"ORDER BY rowid LIMIT {PAGE}", [last])
            except RuntimeError:                   # WITHOUT ROWID table: one plain pass
                rows = q(f"SELECT * FROM {qid(name)}") if n == 0 else []
                for r in rows:
                    out.append(_insert(name, r))
                n += len(rows)
                break
            if not rows:
                break
            for r in rows:
                last = r.pop("__rid")
                out.append(_insert(name, r))
            n += len(rows)
            if len(rows) < PAGE:
                break
        dumped[name] = n
    for o in later:
        out.append(o["sql"].rstrip(";") + ";")
    return "\n".join(out) + "\n", dumped, counted


def _insert(table, row):
    cols = ", ".join(qid(c) for c in row)
    vals = ", ".join(sql_literal(v) for v in row.values())
    return f"INSERT INTO {qid(table)} ({cols}) VALUES ({vals});"


# ---------- KV ----------

def kv_namespaces(cf):
    return [(n["title"], n["id"]) for n in cf.paged("/storage/kv/namespaces")]


def kv_dump(cf, ns_id):
    """Return (json_text, key_count). Values are base64 so binary survives."""
    keys = []
    for k in cf.paged(f"/storage/kv/namespaces/{ns_id}/keys"):
        raw = cf.call(f"/storage/kv/namespaces/{ns_id}/values/{urllib.parse.quote(k['name'], safe='')}",
                      raw=True)
        keys.append({"name": k["name"], "expiration": k.get("expiration"),
                     "metadata": k.get("metadata"),
                     "value_b64": base64.b64encode(raw).decode()})
    return json.dumps({"namespace": ns_id, "keys": keys}, ensure_ascii=False), len(keys)
