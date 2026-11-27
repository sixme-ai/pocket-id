"""Check the issued identity and real introspection on the isolated devkit profile."""
import base64
import http.client
import json
from pathlib import Path
import socket
import ssl
import sys
from urllib.parse import urlencode

root = Path(sys.argv[1])
issuer = "https://localhost:14411"
token_path = "/api/oidc/token"
introspection_path = "/api/oidc/introspect"
tls = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
tls.load_verify_locations(cafile=str(root / "tls" / "ca.pem"))
for hostname, trust in [("127.0.0.1", tls), ("localhost", ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT))]:
    try:
        with socket.create_connection(("127.0.0.1", 14411), timeout=5) as raw:
            with trust.wrap_socket(raw, server_hostname=hostname):
                raise ValueError("Expected TLS identity rejection")
    except ssl.SSLCertVerificationError:
        pass


def request(method, path, form=None, auth=None):
    connection = http.client.HTTPSConnection("localhost", 14411, timeout=8, context=tls)
    headers = {"Content-Type": "application/x-www-form-urlencoded"} if form else {}
    if auth:
        headers["Authorization"] = "Basic " + base64.b64encode(auth.encode()).decode()
    try:
        connection.request(method, path, urlencode(form) if form else None, headers)
        reply = connection.getresponse()
        if reply.status != 200:
            raise ValueError(f"{method} {path}: {reply.status}")
        return json.load(reply)
    finally:
        connection.close()


meta = request("GET", "/.well-known/openid-configuration")
assert meta["issuer"] == issuer
assert meta["introspection_endpoint"] == issuer + introspection_path
assert meta["token_endpoint"] == issuer + token_path
state = json.loads((root / ".local-oauth.json").read_text())
form = {"grant_type": "client_credentials", "client_id": state["m2m_client_id"],
        "client_secret": state["m2m_client_secret"], "resource": state["resource"], "scope": "mcp:access"}
token = request("POST", token_path, form)["access_token"]
credential = state["m2m_client_id"] + ":" + state["m2m_client_secret"]
result = request("POST", introspection_path, {"token": token}, credential)
assert result["active"] is True and result["client_id"] == state["m2m_client_id"]
assert request("POST", introspection_path, {"token": "not-an-issued-token"}, credential)["active"] is False
print("PASS: verified issuer, advertised HTTPS introspection, active/inactive, wrong hostname, absent CA")
