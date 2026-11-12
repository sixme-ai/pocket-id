#!/usr/bin/env python3
"""Provision a loopback-only Pocket ID test instance through its real HTTP API."""
import base64
import json
import os
import secrets
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
import sys
from pathlib import Path
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve().parent
BASE = "http://localhost:1411"
STATE = ROOT / ".local-oauth.json"
RESOURCE = os.environ.get("LOCAL_MCP_RESOURCE", "http://localhost:18080/mcp")
CALLBACK = os.environ.get("LOCAL_OAUTH_CALLBACK", "http://localhost:3000/callback")
for item in (RESOURCE, CALLBACK):
    parsed = urllib.parse.urlparse(item)
    if parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise SystemExit("Local test resource and callback must use loopback HTTP")

config = dict(line.split("=", 1) for line in (ROOT / ".env").read_text().splitlines() if "=" in line)
API_KEY = config.get("STATIC_API_KEY", "")
if len(API_KEY) < 16:
    raise SystemExit("STATIC_API_KEY missing from local .env")
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def request(method, path, data=None, *, admin=False, form=False):
    headers = {"X-API-KEY": API_KEY} if admin else {}
    payload = None
    if data is not None:
        if form:
            headers["Content-Type"] = "application/x-www-form-urlencoded"
            payload = urllib.parse.urlencode(data).encode()
        else:
            headers["Content-Type"] = "application/json"
            payload = json.dumps(data).encode()
    req = urllib.request.Request(BASE + path, data=payload, headers=headers, method=method)
    try:
        with OPENER.open(req, timeout=8) as res:
            raw = res.read(262144)
            return res.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as err:
        return err.code, {}


def expect(status, payload, wanted, stage):
    if status != wanted or not isinstance(payload, dict):
        raise RuntimeError(f"{stage}: HTTP {status}, expected {wanted}")
    return payload


# Require actual OIDC discovery and JWKS on the expected loopback address.
for attempt in range(90):
    try:
        status, meta = request("GET", "/.well-known/openid-configuration")
        if status == 200 and meta.get("issuer") == BASE:
            status, jwks = request("GET", "/.well-known/jwks.json")
            if status == 200 and isinstance(jwks.get("keys"), list) and jwks["keys"]:
                break
    except (OSError, ValueError):
        pass
    time.sleep(1)
else:
    raise SystemExit("Pocket ID discovery/JWKS did not become ready in 90 seconds")

# The real first administrator completes /setup; the static API user does not.
status, _ = request("GET", "/api/signup/setup")
if status == 204:
    status, _ = request("POST", "/api/signup/setup", {
        "username": "agent-tester", "email": "agent-tester@localhost.invalid",
        "firstName": "Local", "lastName": "Tester"})
    expect(status, _, 200, "Create local human test administrator")
    print("Local human test administrator created")
elif status == 404:
    print("Initial human administrator already exists")
else:
    raise RuntimeError(f"Unexpected initial setup status: HTTP {status}")


def save(state):
    target = STATE.with_suffix(".json.tmp")
    fd = os.open(target, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as output:
        json.dump(state, output, indent=2)
        output.write("\n")
    os.replace(target, STATE)
    os.chmod(STATE, 0o600)


if STATE.is_symlink():
    raise RuntimeError("Credentials file must not be a symlink")
state = json.loads(STATE.read_text()) if STATE.exists() else {}
if state and (state.get("resource") != RESOURCE or state.get("callback") != CALLBACK):
    raise RuntimeError("Local OAuth resource/callback changed; refusing to reuse old grants")
state.update(resource=RESOURCE, callback=CALLBACK)

if "api_id" not in state:
    status, obj = request("POST", "/api/apis", {"name": "Local GitHub MCP", "resource": RESOURCE}, admin=True)
    state["api_id"] = expect(status, obj, 201, "Create MCP API")["id"]
    save(state)

if "permission_id" not in state:
    status, obj = request("PUT", "/api/apis/" + state["api_id"] + "/permissions",
                          {"permissions": [{"key": "mcp:access", "name": "MCP access"}]}, admin=True)
    obj = expect(status, obj, 200, "Configure MCP scope")
    state["permission_id"] = next(p["id"] for p in obj["permissions"] if p["key"] == "mcp:access")
    save(state)

if "m2m_client_id" not in state:
    status, obj = request("POST", "/api/oidc/clients", {
        "name": "Local Agent M2M", "isPublic": False, "pkceEnabled": True,
        "callbackURLs": [CALLBACK]}, admin=True)
    obj = expect(status, obj, 201, "Create confidential test client")
    state["m2m_client_id"] = obj["id"]
    state["m2m_client_secret"] = (obj.get("createdSecret") or {}).get("secret", "")
    save(state)

if not state.get("m2m_client_secret"):
    status, obj = request("POST", "/api/oidc/clients/" + state["m2m_client_id"] + "/secrets", {}, admin=True)
    state["m2m_client_secret"] = expect(status, obj, 201, "Create M2M secret")["secret"]
    save(state)

if not state.get("m2m_granted"):
    status, obj = request("PUT", "/api/apis/" + state["api_id"] + "/clients/" + state["m2m_client_id"], {
        "clientAccess": True, "clientPermissionIds": [state["permission_id"]],
        "userDelegatedAccess": False, "userDelegatedPermissionIds": []}, admin=True)
    expect(status, obj, 200, "Grant test M2M access")
    state["m2m_granted"] = True
    save(state)

if "human_client_id" not in state:
    status, obj = request("POST", "/api/oidc/clients", {
        "name": "Local Human PKCE", "isPublic": True, "pkceEnabled": True,
        "callbackURLs": [CALLBACK]}, admin=True)
    state["human_client_id"] = expect(status, obj, 201, "Create public human test client")["id"]
    save(state)

if not state.get("human_granted"):
    status, obj = request("PUT", "/api/apis/" + state["api_id"] + "/clients/" + state["human_client_id"], {
        "clientAccess": False, "clientPermissionIds": [],
        "userDelegatedAccess": True, "userDelegatedPermissionIds": [state["permission_id"]]}, admin=True)
    expect(status, obj, 200, "Grant human PKCE access")
    state["human_granted"] = True
    save(state)

# Provision one unique test-only RSA workload for federated introspection on the SAME
# public human client. Never bundle private key bytes, a reusable assertion, or a client secret.
# The backend-only identity lives next to (not inside) the Pocket ID installation.
WORKLOAD_DIR = ROOT.parent / (ROOT.name + "-mcp-workload")
if WORKLOAD_DIR.is_symlink():
    raise RuntimeError("MCP workload directory must not be a symlink")
WORKLOAD_DIR.mkdir(mode=0o700, exist_ok=True)
os.chmod(WORKLOAD_DIR, 0o700)
KEY_FILE = WORKLOAD_DIR / "assertion-private.pem"
if KEY_FILE.is_symlink():
    raise RuntimeError("MCP backend assertion key must not be a symlink")
if not KEY_FILE.exists():
    if state.get("federated_granted"):
        raise RuntimeError("Existing federated workload key is missing; refuse silent rotation")
    backend_key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    private_bytes = backend_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption())
    fd = os.open(KEY_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(fd, "wb") as output:
        output.write(private_bytes)
if (not KEY_FILE.is_file() or KEY_FILE.stat().st_mode & 0o077):
    raise RuntimeError("Private MCP assertion key has unsafe permissions")
private_key = serialization.load_pem_private_key(KEY_FILE.read_bytes(), password=None)
if not isinstance(private_key, rsa.RSAPrivateKey) or private_key.key_size < 3072:
    raise RuntimeError("MCP backend assertion key has unsafe algorithm or size")
numbers = private_key.public_key().public_numbers()
def jwk_integer(value):
    raw = value.to_bytes((value.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")
key_id = state.get("workload_kid") or secrets.token_hex(12)
workload_issuer = BASE + "/local-mcp-workload"
workload_subject = "local-github-mcp"
jwk = {"kty": "RSA", "use": "sig", "alg": "RS256", "kid": key_id,
       "n": jwk_integer(numbers.n), "e": jwk_integer(numbers.e)}
identity = {"issuer": workload_issuer, "subject": workload_subject,
            "audience": BASE, "publicKeys": [jwk], "replayProtection": True}
if not state.get("federated_granted"):
    status, obj = request("PUT", "/api/oidc/clients/" + state["human_client_id"], {
        "name": "Local Human PKCE", "isPublic": True, "pkceEnabled": True,
        "callbackURLs": [CALLBACK],
        "credentials": {"federatedIdentities": [identity]}}, admin=True)
    expect(status, obj, 200, "Configure federated workload on same public PKCE client")
    state.update(federated_granted=True, workload_kid=key_id,
                 workload_key_path=str(KEY_FILE), workload_issuer=workload_issuer,
                 workload_subject=workload_subject, workload_audience=BASE)
    save(state)
elif state.get("workload_kid") != key_id or state.get("workload_key_path") != str(KEY_FILE):
    raise RuntimeError("Existing workload identity does not match retained private key")
# Recheck on EVERY start, not only initial provisioning, to reject stale JWK or key drift.
status, client = request("GET", "/api/oidc/clients/" + state["human_client_id"], admin=True)
expect(status, client, 200, "Read back federated public client")
identities = (client.get("credentials") or {}).get("federatedIdentities") or []
if not any(x.get("issuer") == workload_issuer
           and x.get("subject") == workload_subject
           and x.get("audience") == BASE
           and x.get("replayProtection") is True
           and jwk in (x.get("publicKeys") or []) for x in identities):
    raise RuntimeError("Public client federated JWK differs from retained backend key")
print("Same-client federated workload identity with backend-only RSA and replay prevention: PASS")


# Authenticate against the real token endpoint and reject a wrong client secret.
form = {"grant_type": "client_credentials", "client_id": state["m2m_client_id"],
        "client_secret": state["m2m_client_secret"], "resource": RESOURCE, "scope": "mcp:access"}
status, token = request("POST", "/api/oidc/token", form, form=True)
token = expect(status, token, 200, "Issue M2M access token")
access_token = token.get("access_token", "")
if access_token.count(".") != 2 or token.get("token_type", "").lower() != "bearer":
    raise RuntimeError("Expected JWT bearer token")
encoded = access_token.split(".")[1]
claims = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
aud = claims.get("aud", [])
if isinstance(aud, str):
    aud = [aud]
scopes = claims.get("scope", "")
if claims.get("iss") != BASE or RESOURCE not in aud or "mcp:access" not in scopes.split():
    raise RuntimeError("M2M JWT issuer, audience or scope mismatch")
if not isinstance(claims.get("exp"), int) or claims["exp"] <= time.time():
    raise RuntimeError("M2M JWT expired or has no expiry")
status, _ = request("POST", "/api/oidc/token", {**form, "client_secret": "invalid-secret"}, form=True)
if status not in (400, 401, 403):
    raise RuntimeError("Invalid secret was not rejected: HTTP " + str(status))
print("OIDC/JWKS, local human setup, M2M OAuth and wrong-secret denial: PASS")
print("Public PKCE client_id:", state["human_client_id"])
print("MCP resource:", RESOURCE)
print("Local OAuth credentials:", STATE.name)
