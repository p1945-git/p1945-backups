import http.server
import threading
import unittest
import urllib.parse
from xml.sax.saxutils import escape

from backup.s3lite import S3, sign


class SigningVector(unittest.TestCase):
    def test_aws_published_example(self):
        """GET Object example from AWS's own Signature V4 documentation."""
        h = {"host": "examplebucket.s3.amazonaws.com", "range": "bytes=0-9",
             "x-amz-content-sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
             "x-amz-date": "20130524T000000Z"}
        auth, sig = sign("GET", h["host"], "/test.txt", {}, h, h["x-amz-content-sha256"],
                         "AKIAIOSFODNN7EXAMPLE", "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
                         "us-east-1", "s3", "20130524T000000Z")
        self.assertEqual(sig, "f0e8bdb87c964420e857bd35b5d6ed310bd44f0170aba48dd91039c6036bdb41")
        self.assertIn("SignedHeaders=host;range;x-amz-content-sha256;x-amz-date", auth)


class FakeS3(http.server.BaseHTTPRequestHandler):
    store = {}
    page = 2

    def log_message(self, *a):
        pass

    def _key(self):
        u = urllib.parse.urlparse(self.path)
        return urllib.parse.unquote(u.path).split("/", 2)[2] if u.path.count("/") >= 2 else "", \
            dict(urllib.parse.parse_qsl(u.query))

    def _ok(self):
        return self.headers.get("Authorization", "").startswith("AWS4-HMAC-SHA256 Credential=AK/")

    def do_PUT(self):
        if not self._ok():
            return self.send_error(403)
        n = int(self.headers["Content-Length"])
        self.store[self._key()[0]] = self.rfile.read(n)
        self.send_response(200); self.end_headers()

    def do_GET(self):
        if not self._ok():
            return self.send_error(403)
        key, q = self._key()
        if key == "":
            keys = sorted(k for k in self.store if k.startswith(q.get("prefix", "")))
            start = keys.index(q["continuation-token"]) if "continuation-token" in q else 0
            chunk, more = keys[start:start + self.page], start + self.page < len(keys)
            body = ('<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">'
                    f'<IsTruncated>{str(more).lower()}</IsTruncated>'
                    + (f"<NextContinuationToken>{escape(keys[start + self.page])}</NextContinuationToken>" if more else "")
                    + "".join(f"<Contents><Key>{escape(k)}</Key><LastModified>2026-10-04T01:02:03.000Z</LastModified>"
                              f"<Size>{len(self.store[k])}</Size></Contents>" for k in chunk)
                    + "</ListBucketResult>").encode()
        elif key in self.store:
            body = self.store[key]
        else:
            return self.send_error(404)
        self.send_response(200); self.send_header("Content-Length", str(len(body))); self.end_headers()
        self.wfile.write(body)

    def do_DELETE(self):
        if not self._ok():
            return self.send_error(403)
        self.store.pop(self._key()[0], None)
        self.send_response(204); self.end_headers()


class Roundtrip(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = http.server.HTTPServer(("127.0.0.1", 0), FakeS3)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.s3 = S3(f"http://127.0.0.1:{cls.srv.server_port}", "bkt", "AK", "SK", retries=1)

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def test_put_get_list_delete_with_paging_and_odd_names(self):
        for k in ["sets/2026-10-01/a b.sql.cms", "sets/2026-10-02/d1/x.cms", "sets/2026-10-03/m.json",
                  "sets/2026-10-04/é&=.cms", "other/z"]:
            self.s3.put(k, k.encode())
        self.assertEqual(self.s3.get("sets/2026-10-01/a b.sql.cms"), b"sets/2026-10-01/a b.sql.cms")
        got = sorted(k for k, _, _ in self.s3.list("sets/"))
        self.assertEqual(len(got), 4)                       # 4 keys over pages of 2 -> paging works
        self.assertNotIn("other/z", got)
        self.s3.delete("sets/2026-10-02/d1/x.cms")
        self.assertEqual(len(list(self.s3.list("sets/"))), 3)


if __name__ == "__main__":
    unittest.main()
