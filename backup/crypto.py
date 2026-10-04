"""Envelope encryption with the openssl that is already on the Mac and on the GitHub runner.

Encrypt needs only the PUBLIC certificate (keys/backup-cert.pem, safe to keep in the repo).
Decrypt needs the private key, which lives offline with Denny and is never on a server.
So a stolen backup bucket — or a stolen GitHub secret — cannot read a single backup.
"""
import os
import re
import subprocess
import tempfile

CERT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "keys", "backup-cert.pem")
_OAEP = ["-keyopt", "rsa_padding_mode:oaep", "-keyopt", "rsa_oaep_md:sha256"]


def _run(args, data):
    with tempfile.TemporaryDirectory() as d:
        src, dst = os.path.join(d, "in"), os.path.join(d, "out")
        with open(src, "wb") as f:
            f.write(data)
        p = subprocess.run(["openssl", "cms"] + args + ["-in", src, "-out", dst],
                           capture_output=True)
        if p.returncode != 0:
            raise RuntimeError("openssl cms failed: " + p.stderr.decode()[:300])
        with open(dst, "rb") as f:
            return f.read()


def encrypt(data, cert=None):
    cert = cert or CERT
    return _run(["-encrypt", "-binary", "-aes-256-cbc", "-outform", "DER", "-recip", cert] + _OAEP, data)


def _normalise_pem(path, tmpdir):
    """Password managers often flatten a PEM key onto ONE line. Re-wrap it so openssl accepts it."""
    text = open(path, encoding="utf-8").read()
    m = re.match(r"\s*(-----BEGIN [A-Z ]+-----)(.*?)(-----END [A-Z ]+-----)\s*$", text, re.S)
    if not m:
        return path
    body = "".join(m.group(2).split())
    out = os.path.join(tmpdir, "key.pem")
    with open(out, "w") as f:
        f.write(m.group(1) + "\n" + "\n".join(body[i:i + 64] for i in range(0, len(body), 64))
                + "\n" + m.group(3) + "\n")
    os.chmod(out, 0o600)
    return out


def decrypt(data, private_key, cert=None):
    cert = cert or CERT
    with tempfile.TemporaryDirectory() as d:
        key = _normalise_pem(private_key, d)
        return _run(["-decrypt", "-binary", "-inform", "DER", "-inkey", key,
                     "-recip", cert] + _OAEP, data)
