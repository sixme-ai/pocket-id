"""Exercise the bootstrap's read-only preflight without an IdP or substitute services."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from oauth_profile import verify_delegated_grant, verify_public_registration
from oauth_profile import verify_resource, verify_web_registration


class ProfilePreflight(unittest.TestCase):
    origin = "https://localhost:18443"
    resource = origin + "/mcp"
    callback = "https://localhost:3000/callback"
    web_callback = origin + "/login/oauth2/code/pocket-id"
    aquifer = ("--https", "--profile", "aquifer")

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        for name in ("bootstrap.py", "local_tls.py", "oauth_profile.py"):
            shutil.copy(Path(__file__).with_name(name), self.root)

    def check(self, args, error=None, **settings):
        env = {k: v for k, v in os.environ.items() if not k.startswith("LOCAL_")}
        env.update(settings, PYTHONDONTWRITEBYTECODE="1")
        command = [sys.executable, str(self.root / "bootstrap.py"), "--check-profile", *args]
        before = {p.name: p.read_bytes() for p in self.root.iterdir()}
        result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=10)
        if error is None:
            self.assertEqual(result.returncode, 0, result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(error, result.stderr)
        self.assertFalse(result.stdout)
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.root.iterdir()})

    def save(self, **values):
        (self.root / ".local-oauth.json").write_text(json.dumps(values))

    def test_fresh_https_aquifer_and_both_existing_defaults(self):
        for args in (self.aquifer, ("--https",), ()):
            with self.subTest(args=args):
                self.check(args)

    def test_fixed_resource_and_distinct_mcp_callback(self):
        for resource in (self.origin, "http://localhost:18443/mcp"):
            self.check(self.aquifer, "Aquifer resource", LOCAL_MCP_RESOURCE=resource)
        for callback in (self.web_callback, self.resource, "http://localhost:3000/callback"):
            self.check(self.aquifer, "Aquifer MCP callback", LOCAL_OAUTH_CALLBACK=callback)

    def test_rejects_aquifer_on_http(self):
        self.check(("--profile", "aquifer"), "requires the HTTPS installer")

    def test_legacy_registration_cannot_be_repurposed(self):
        self.save(resource="http://localhost:18080/mcp", callback="http://localhost:3000/callback")
        self.check(("--https",))
        self.check(self.aquifer, "different OAuth profile")

    def test_registered_profile_restarts_without_changes(self):
        self.save(profile="aquifer", resource=self.resource, callback=self.callback,
                  scope="aquifer:mcp", web_origin=self.origin, web_callback=self.web_callback)
        self.check(self.aquifer)
        self.check(("--https",), "different OAuth profile")
        self.check(self.aquifer, "Aquifer MCP callback", LOCAL_OAUTH_CALLBACK=self.web_callback)

    def test_refuses_drift_in_registered_web_callback(self):
        self.save(profile="aquifer", resource=self.resource, callback=self.callback,
                  scope="aquifer:mcp", web_origin=self.origin, web_callback=self.callback)
        self.check(self.aquifer, "Saved Aquifer settings")


class LocalCatalogContract(unittest.TestCase):
    def test_public_and_web_registrations_are_distinct(self):
        ids = {"human_client_id": "human", "web_client_id": "web"}
        web = {"isPublic": False, "pkceEnabled": True,
               "callbackURLs": ["https://localhost:18443/login/oauth2/code/pocket-id"]}
        mcp = {"isPublic": True, "pkceEnabled": True,
               "callbackURLs": ["https://localhost:3000/callback"]}
        verify_web_registration(web)
        verify_public_registration(mcp, ids)
        changesets = ({"isPublic": True}, {"pkceEnabled": False},
                      {"callbackURLs": mcp["callbackURLs"]})
        for changes in changesets:
            with self.subTest(changes=changes), self.assertRaises(RuntimeError):
                verify_web_registration({**web, **changes})
        with self.assertRaises(RuntimeError):
            verify_public_registration(mcp, {**ids, "web_client_id": "human"})
        with self.assertRaises(RuntimeError):
            verify_public_registration({**mcp, "callbackURLs": web["callbackURLs"]}, ids)

    def test_scope_only_on_the_registered_audience(self):
        api = {"resource": "https://localhost:18443/mcp", "allowCimdClients": False,
               "permissions": [{"id": "permission", "key": "aquifer:mcp"}]}
        verify_resource(api, "permission")
        for changes in ({"allowCimdClients": True}, {"resource": "http://localhost:18080/mcp"},
                        {"permissions": [{"id": "permission", "key": "mcp:access"}]}):
            with self.subTest(changes=changes), self.assertRaises(RuntimeError):
                verify_resource({**api, **changes}, "permission")

    def test_only_the_mcp_user_has_delegated_access(self):
        grant = {"client": {"id": "human"}, "clientAccess": False, "clientPermissionIds": [],
                 "userDelegatedAccess": True, "userDelegatedPermissionIds": ["permission"]}
        page = {"data": [grant], "pagination": {"totalItems": 1}}
        verify_delegated_grant(page, "human", "permission")
        with self.assertRaises(RuntimeError):
            verify_delegated_grant({**page, "pagination": {"totalItems": 2}}, "human", "permission")
        alternate_rows = ([], [grant, grant], [{**grant, "client": {"id": "web"}}],
                          [{**grant, "clientAccess": True}],
                          [{**grant, "clientPermissionIds": ["permission"]}],
                          [{**grant, "userDelegatedAccess": False}],
                          [{**grant, "userDelegatedPermissionIds": []}])
        for rows in alternate_rows:
            with self.subTest(rows=rows), self.assertRaises(RuntimeError):
                verify_delegated_grant({**page, "data": rows}, "human", "permission")


if __name__ == "__main__":
    unittest.main()
