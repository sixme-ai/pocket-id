"""Read the selected installation's real TLS discovery, registrations and API access."""
import http.client
import json
from pathlib import Path
import ssl
import sys


root = Path(sys.argv[1])
issuer = "https://localhost:14411"
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
env = dict(line.split("=", 1) for line in (root / ".env").read_text().splitlines() if "=" in line)
trust = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
trust.load_verify_locations(cafile=str(root / "tls" / "ca.pem"))


def read(path, admin=False):
    connection = http.client.HTTPSConnection("localhost", 14411, context=trust, timeout=8)
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
print("PASS: HTTPS discovery, two distinct PKCE registrations and delegated-only Aquifer scope")
