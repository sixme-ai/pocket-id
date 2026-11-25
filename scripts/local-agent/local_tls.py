"""Create the private loopback server identity once per HTTPS installation."""
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
from tempfile import TemporaryDirectory

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID


def prepare_tls(root: Path) -> None:
    target = root / "tls"
    files = ("ca.pem", "server.pem", "server.key")
    if target.exists() or target.is_symlink():
        if target.is_symlink() or not target.is_dir():
            raise ValueError("Invalid TLS directory")
        for name in files:
            path = target / name
            if path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o077:
                raise ValueError("Incomplete or unprotected TLS identity; refusing replacement")
        return
    if (root / ".env").exists() or (root / ".local-oauth.json").exists():
        raise ValueError("Existing TLS identity missing; refusing silent rotation")
    now = datetime.now(timezone.utc)
    ca_key = ec.generate_private_key(ec.SECP256R1())
    server_key = ec.generate_private_key(ec.SECP256R1())
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Pocket ID DevKit local CA")])
    leaf_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])

    def certificate(subject, public_key, lifetime):
        return (x509.CertificateBuilder().subject_name(subject).issuer_name(ca_name)
                .public_key(public_key).serial_number(x509.random_serial_number())
                .not_valid_before(now - timedelta(minutes=5)).not_valid_after(now + lifetime))

    ca = (certificate(ca_name, ca_key.public_key(), timedelta(days=1825))
          .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
          .add_extension(x509.KeyUsage(False, False, False, False, False, True, True, False, False), True)
          .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), False)
          .sign(ca_key, hashes.SHA256()))
    leaf = (certificate(leaf_name, server_key.public_key(), timedelta(days=365))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.KeyUsage(True, False, False, False, False, False, False, False, False), True)
            .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost")]), False)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), False)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), False)
            .sign(ca_key, hashes.SHA256()))
    # Stage the identity as a unit and discard the CA signing key after issuing the leaf
    with TemporaryDirectory(dir=root) as temp:
        staged = Path(temp) / "tls"
        staged.mkdir(mode=0o700)
        (staged / "ca.pem").write_bytes(ca.public_bytes(serialization.Encoding.PEM))
        (staged / "server.pem").write_bytes(leaf.public_bytes(serialization.Encoding.PEM))
        (staged / "server.key").write_bytes(server_key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        for name in files:
            os.chmod(staged / name, 0o600)
        staged.rename(target)
