"""Read the selected installation's real TLS discovery, registrations and API access."""
import base64
import hashlib
import http.client
import json
from pathlib import Path
import secrets
import socket
import ssl
import sys
from urllib.parse import parse_qs, urlencode, urlsplit


root = Path(sys.argv[1])
env = dict(line.split("=", 1) for line in (root / ".env").read_text().splitlines() if "=" in line)
port = int(env["PORT"])
issuer = f"https://localhost:{port}"
assert env["APP_URL"] == env["INTERNAL_APP_URL"] == issuer
public_callback = "https://localhost:3000/callback"
web_callback = "https://localhost:18443/login/oauth2/code/pocket-id"
state_path = root / ".local-oauth.json"
assert state_path.is_file() and state_path.stat().st_mode & 0o077 == 0
state = json.loads(state_path.read_bytes())
assert state["profile"] == "aquifer" and state["callback"] == public_callback
assert state["resource"] == "https://localhost:18443/mcp" and state["scope"] == "aquifer:mcp"
assert state["web_callback"] == web_callback and state["web_origin"] == "https://localhost:18443"
assert state["web_client_secret"] and state["web_client_id"] != state["human_client_id"]
assert "m2m_client_id" not in state and "m2m_client_secret" not in state
assert state["workload_audience"] == issuer and state["federated_granted"]
assert Path(state["workload_key_path"]).stat().st_mode & 0o077 == 0
trust = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
trust.load_verify_locations(cafile=str(root / "tls" / "ca.pem"))

for hostname, context in (("127.0.0.1", trust),
                          ("localhost", ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT))):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=5) as raw:
            with context.wrap_socket(raw, server_hostname=hostname):
                raise AssertionError("Unexpected TLS identity acceptance")
    except ssl.SSLCertVerificationError:
        pass


def read(path, admin=False):
    connection = http.client.HTTPSConnection("localhost", port, context=trust, timeout=8)
    try:
        headers = {"X-API-KEY": env["STATIC_API_KEY"]} if admin else {}
        connection.request("GET", path, headers=headers)
        reply = connection.getresponse()
        if reply.status != 200:
            raise ValueError(f"Read of local provider returned HTTP {reply.status}")
        return json.load(reply)
    finally:
        connection.close()


discovery = read("/.well-known/openid-configuration")
assert discovery["issuer"] == issuer
assert discovery["introspection_endpoint"] == issuer + "/api/oidc/introspect"
for key, public, callback in (("human_client_id", True, public_callback),
                              ("web_client_id", False, web_callback)):
    client = read("/api/oidc/clients/" + state[key], admin=True)
    assert client["isPublic"] is public and client["pkceEnabled"] is True
    assert client["callbackURLs"] == [callback]
page = read("/api/apis/" + state["api_id"] + "/clients", admin=True)
assert page["pagination"]["totalItems"] == 1
grants = page["data"]
assert len(grants) == 1 and grants[0]["client"]["id"] == state["human_client_id"]
assert grants[0]["clientAccess"] is False and not grants[0]["clientPermissionIds"]
assert grants[0]["userDelegatedAccess"] is True
assert grants[0]["userDelegatedPermissionIds"] == [state["permission_id"]]
api = read("/api/apis/" + state["api_id"], admin=True)
assert api["resource"] == state["resource"] and api["allowCimdClients"] is False
assert [(p["id"], p["key"]) for p in api["permissions"]] == [
    (state["permission_id"], "aquifer:mcp")]


def oauth_request(method, endpoint, parameters):
    address = urlsplit(endpoint)
    assert address.scheme == "https" and address.netloc == f"localhost:{port}"
    connection = http.client.HTTPSConnection("localhost", port, context=trust, timeout=8)
    try:
        encoded = urlencode(parameters)
        if method == "GET":
            connection.request(method, address.path + "?" + encoded)
        else:
            connection.request(method, address.path, encoded,
                               {"Content-Type": "application/x-www-form-urlencoded"})
        reply = connection.getresponse()
        raw = reply.read()
        location = urlsplit(reply.getheader("Location", ""))
        body = json.loads(raw) if reply.getheader("Content-Type", "").startswith("application/json") else {}
        return reply.status, location, body
    finally:
        connection.close()


def check_authorize(client_id, callback, wrong_callback, scope, resource=None):
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    form = {"response_type": "code", "client_id": client_id, "scope": scope,
            "state": secrets.token_urlsafe(24), "nonce": secrets.token_urlsafe(24),
            "code_challenge": challenge, "code_challenge_method": "S256"}
    if resource:
        form["resource"] = resource
    endpoint = discovery["authorization_endpoint"]
    status, location, _ = oauth_request("GET", endpoint, {**form, "redirect_uri": callback})
    assert status == 302 and location.path == "/interaction"
    assert set(parse_qs(location.query)) == {"interaction"}
    status, location, _ = oauth_request("GET", endpoint, {**form, "redirect_uri": wrong_callback})
    assert status == 302 and location.path == "/interaction/error"
    errors = parse_qs(location.query).get("error", [])
    assert len(errors) == 1 and "not registered for this client" in errors[0]
    assert wrong_callback in errors[0] and "code" not in parse_qs(location.query)


check_authorize(state["human_client_id"], public_callback, web_callback,
                "openid aquifer:mcp", state["resource"])
check_authorize(state["web_client_id"], web_callback, public_callback, "openid")

for key, expected_error in (("human_client_id", "invalid_grant"),
                            ("web_client_id", "invalid_scope")):
    form = {"grant_type": "client_credentials", "client_id": state[key],
            "resource": state["resource"], "scope": state["scope"]}
    if key == "web_client_id":
        form["client_secret"] = state["web_client_secret"]
    status, _, body = oauth_request("POST", discovery["token_endpoint"], form)
    assert status == 400 and body.get("error") == expected_error
    assert "access_token" not in body

print("PASS: HTTPS trust, distinct PKCE registrations, delegated-only scope and cross-client rejection")
