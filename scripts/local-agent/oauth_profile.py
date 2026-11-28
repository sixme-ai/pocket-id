"""Local OAuth registration parameters shared by preflight and provisioning."""
from urllib.parse import urlparse


WEB_ORIGIN = "https://localhost:18443"
WEB_CALLBACK = WEB_ORIGIN + "/login/oauth2/code/pocket-id"
MCP_RESOURCE = WEB_ORIGIN + "/mcp"
MCP_CALLBACK = "https://localhost:3000/callback"
MCP_SCOPE = "aquifer:mcp"


def select_profile(args):
    if args == ["--profile", "aquifer"]:
        raise SystemExit("The Aquifer profile requires the HTTPS installer")
    if args == ["--https", "--profile", "aquifer"]:
        return True, True
    if args in ([], ["--https"]):
        return bool(args), False
    raise SystemExit("Unsupported bootstrap profile")


def aquifer_parameters(state, env):
    if env.get("LOCAL_MCP_RESOURCE", MCP_RESOURCE) != MCP_RESOURCE:
        raise SystemExit("Aquifer resource must use its registered HTTPS URI")
    if env.get("LOCAL_OAUTH_CALLBACK", MCP_CALLBACK) != MCP_CALLBACK:
        raise SystemExit("Aquifer MCP callback must use its registered HTTPS URI")
    if state and (state.get("scope"), state.get("web_origin"), state.get("web_callback")) != (
            MCP_SCOPE, WEB_ORIGIN, WEB_CALLBACK):
        raise SystemExit("Saved Aquifer settings differ from the registered profile")
    return MCP_RESOURCE, MCP_CALLBACK, MCP_SCOPE


def default_parameters(env):
    resource = env.get("LOCAL_MCP_RESOURCE", "http://localhost:18080/mcp")
    callback = env.get("LOCAL_OAUTH_CALLBACK", "http://localhost:3000/callback")
    for item in (resource, callback):
        parsed = urlparse(item)
        if parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise SystemExit("Local test resource and callback must use loopback HTTP")
    return resource, callback, "mcp:access"


def oauth_parameters(aquifer, state, env):
    profile = "aquifer" if aquifer else "default"
    if state and state.get("profile", "default") != profile:
        raise SystemExit("Installation has a different OAuth profile; use a separate directory")
    values = aquifer_parameters(state, env) if aquifer else default_parameters(env)
    resource, callback, scope = values
    if state and (state.get("resource"), state.get("callback")) != (resource, callback):
        raise SystemExit("Local OAuth resource/callback changed; refusing to reuse old grants")
    return resource, callback, scope


def verify_web_registration(client):
    if (client.get("isPublic") is not False or client.get("pkceEnabled") is not True
            or client.get("callbackURLs") != [WEB_CALLBACK]):
        raise RuntimeError("Confidential Web client or its exact callback differs")


def verify_public_registration(client, state):
    if (client.get("isPublic") is not True or client.get("pkceEnabled") is not True
            or client.get("callbackURLs") != [MCP_CALLBACK]
            or state["human_client_id"] == state["web_client_id"]):
        raise RuntimeError("Aquifer public MCP client or its separate callback differs")


def verify_resource(api, permission_id):
    permissions = [(p["id"], p["key"]) for p in api["permissions"]]
    if (api.get("resource") != MCP_RESOURCE or api.get("allowCimdClients") is not False
            or permissions != [(permission_id, MCP_SCOPE)]):
        raise RuntimeError("Aquifer resource, permission or CIMD configuration differs")


def verify_delegated_grant(page, client_id, permission_id):
    grants = page["data"]
    if page["pagination"]["totalItems"] == 1 and len(grants) == 1:
        grant = grants[0]
        if (grant["client"]["id"] == client_id and grant.get("clientAccess") is False
                and not grant["clientPermissionIds"] and grant.get("userDelegatedAccess") is True
                and grant.get("userDelegatedPermissionIds") == [permission_id]):
            return
    raise RuntimeError("Aquifer requires only the public client's delegated scope")
