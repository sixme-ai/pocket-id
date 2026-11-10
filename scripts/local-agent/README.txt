Pocket ID Local Agent Test Bundle (Linux x86_64 only)

1. Extract the ZIP and run ./start.sh. No Go, Node, pnpm, Docker or Maven needed.
2. Python 3 is required for the automatic bootstrap (present on the agent Linux environment).
3. The first start creates a real local human test admin (username agent-tester),
   a public OAuth PKCE client, an M2M OAuth client and mcp:access resource grants.
4. ./start.sh prints a real single-use login link for the human test admin,
   fresh on each start. The same link is also in .login-link.txt (mode 0600).
5. Pocket ID is PASSKEY-ONLY: the shared test admin API key in shared-admin-key.txt
   is not a human password. For human login, use the printed one-time login code.
6. The identical shared test API key is bundled for all agents that download
   the same GitHub Actions artifact; NEVER expose this local instance to the internet.
7. For M2M OAuth client ID, secret and resource, inspect .local-oauth.json
   (mode 0600). The human PKCE client ID is there as well.
8. The service listens only on 127.0.0.1:1411 and uses private local SQLite.
9. Run ./stop.sh when done. Re-running ./start.sh is idempotent.

Default MCP resource: http://localhost:8080/mcp
Default human OAuth callback: http://localhost:3000/callback
Override only with loopback URLs using LOCAL_MCP_RESOURCE and LOCAL_OAUTH_CALLBACK.

This bundle provides a real local OIDC test server, NOT ChatGPT/Claude remote
OAuth E2E, nor automatic permission to invoke the real GitHub MCP.
