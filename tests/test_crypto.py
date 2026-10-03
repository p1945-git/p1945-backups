import os
import subprocess
import tempfile
import unittest

from backup import crypto


class Crypto(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d = tempfile.mkdtemp()
        cls.priv, cls.cert = os.path.join(cls.d, "k.pem"), os.path.join(cls.d, "c.pem")
        cls.other = os.path.join(cls.d, "other.pem")
        subprocess.run(["openssl", "genpkey", "-algorithm", "RSA", "-pkeyopt", "rsa_keygen_bits:2048",
                        "-out", cls.priv], check=True, capture_output=True)
        subprocess.run(["openssl", "genpkey", "-algorithm", "RSA", "-pkeyopt", "rsa_keygen_bits:2048",
                        "-out", cls.other], check=True, capture_output=True)
        subprocess.run(["openssl", "req", "-new", "-x509", "-key", cls.priv, "-days", "30",
                        "-subj", "/CN=t", "-out", cls.cert], check=True, capture_output=True)

    def test_roundtrip_and_no_plaintext_leak(self):
        data = b"secret kol deal terms " * 5000
        enc = crypto.encrypt(data, self.cert)
        self.assertNotIn(b"secret kol", enc)
        self.assertEqual(crypto.decrypt(enc, self.priv, self.cert), data)

    def test_wrong_key_cannot_read(self):
        enc = crypto.encrypt(b"x" * 100, self.cert)
        with self.assertRaises(RuntimeError):
            crypto.decrypt(enc, self.other, self.cert)

    def test_repo_cert_is_public_only(self):
        self.assertNotIn("PRIVATE KEY", open(crypto.CERT).read())


if __name__ == "__main__":
    unittest.main()
