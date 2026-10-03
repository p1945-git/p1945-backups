"""Tiny S3-compatible client (AWS Signature V4) for Cloudflare R2 — standard library only.

Why hand-rolled: the Mac has no boto3/aws-cli, and the backup must run the same way on the
GitHub runner and on the Mac with nothing to install. Covers exactly what backups need:
put, get, delete, list. Verified against AWS's published signing example (tests/test_s3lite.py).
"""
import datetime
import hashlib
import hmac
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET


def _hmac(key, msg):
    return hmac.new(key, msg.encode(), hashlib.sha256).digest()


def _quote(s, safe="-_.~"):
    return urllib.parse.quote(s, safe=safe)


def sign(method, host, path, query, headers, payload_hash, access_key, secret_key,
         region, service, amz_date):
    """Return (authorization_header_value, signature). `headers` must already hold every header
    to sign, lower-case names, including host, x-amz-date and x-amz-content-sha256."""
    date = amz_date[:8]
    canon_uri = "/".join(_quote(seg) for seg in path.split("/")) or "/"
    canon_qs = "&".join(f"{_quote(k)}={_quote(v)}" for k, v in sorted(query.items()))
    names = sorted(headers)
    canon_headers = "".join(f"{n}:{' '.join(str(headers[n]).split())}\n" for n in names)
    signed = ";".join(names)
    canon = "\n".join([method, canon_uri, canon_qs, canon_headers, signed, payload_hash])
    scope = f"{date}/{region}/{service}/aws4_request"
    to_sign = "\n".join(["AWS4-HMAC-SHA256", amz_date, scope,
                         hashlib.sha256(canon.encode()).hexdigest()])
    k = _hmac(("AWS4" + secret_key).encode(), date)
    for part in (region, service, "aws4_request"):
        k = _hmac(k, part)
    sig = hmac.new(k, to_sign.encode(), hashlib.sha256).hexdigest()
    auth = (f"AWS4-HMAC-SHA256 Credential={access_key}/{scope}, "
            f"SignedHeaders={signed}, Signature={sig}")
    return auth, sig


class S3Error(Exception):
    pass


class S3:
    def __init__(self, endpoint, bucket, access_key, secret_key, region="auto", retries=3):
        self.endpoint = endpoint.rstrip("/")
        self.host = urllib.parse.urlparse(self.endpoint).netloc
        self.bucket = bucket
        self.ak, self.sk, self.region, self.retries = access_key, secret_key, region, retries

    def _request(self, method, key="", query=None, body=b""):
        query = query or {}
        path = f"/{self.bucket}" + (f"/{key}" if key else "")
        payload_hash = hashlib.sha256(body).hexdigest()
        last = None
        for attempt in range(self.retries):
            amz_date = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            headers = {"host": self.host, "x-amz-date": amz_date,
                       "x-amz-content-sha256": payload_hash}
            auth, _ = sign(method, self.host, path, query, headers, payload_hash,
                           self.ak, self.sk, self.region, "s3", amz_date)
            qs = "&".join(f"{_quote(k)}={_quote(v)}" for k, v in sorted(query.items()))
            url = self.endpoint + "/".join(_quote(s) for s in path.split("/")) + (f"?{qs}" if qs else "")
            req = urllib.request.Request(url, data=body if method in ("PUT", "POST") else None,
                                         method=method)
            for n, v in headers.items():
                if n != "host":
                    req.add_header(n, v)
            req.add_header("Authorization", auth)
            try:
                with urllib.request.urlopen(req, timeout=120) as r:
                    return r.status, r.read()
            except urllib.error.HTTPError as e:
                data = e.read()
                if e.code in (500, 502, 503, 504) and attempt < self.retries - 1:
                    last = f"HTTP {e.code}"
                    time.sleep(2 ** attempt)
                    continue
                raise S3Error(f"{method} {key or '/'} -> HTTP {e.code}: {data[:300]!r}")
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                last = str(e)
                if attempt < self.retries - 1:
                    time.sleep(2 ** attempt)
                    continue
        raise S3Error(f"{method} {key or '/'} failed after {self.retries} tries: {last}")

    def put(self, key, data):
        self._request("PUT", key, body=data)

    def get(self, key):
        return self._request("GET", key)[1]

    def delete(self, key):
        self._request("DELETE", key)

    def list(self, prefix=""):
        """Yield (key, size, last_modified_utc_datetime) for every object under prefix."""
        token = None
        while True:
            q = {"list-type": "2", "prefix": prefix}
            if token:
                q["continuation-token"] = token
            _, body = self._request("GET", "", query=q)
            root = ET.fromstring(body)
            ns = {"s": root.tag.split("}")[0].strip("{")} if "}" in root.tag else {}
            p = "s:" if ns else ""
            for c in root.findall(f"{p}Contents", ns):
                lm = c.find(f"{p}LastModified", ns).text
                when = datetime.datetime.fromisoformat(lm.replace("Z", "+00:00"))
                yield (c.find(f"{p}Key", ns).text, int(c.find(f"{p}Size", ns).text), when)
            if (root.findtext(f"{p}IsTruncated", default="false", namespaces=ns) or "").lower() == "true":
                token = root.findtext(f"{p}NextContinuationToken", namespaces=ns)
            else:
                return
