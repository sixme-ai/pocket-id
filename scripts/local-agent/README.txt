Pocket ID Local Agent Test Installer (.run, Linux x86_64 only)

1. Obtain pocket-id-local-agent-linux-amd64.run from the CI artifact.
   GitHub Actions may wrap the .run in a download ZIP; extract the .run once.
2. Run: chmod +x pocket-id-local-agent-linux-amd64.run
        ./pocket-id-local-agent-linux-amd64.run
   The .run installs to ~/.local/share/pocket-id-local-agent and starts Pocket ID.
   For a different private directory, set POCKET_ID_INSTALL_DIR=/absolute/path.
3. The installer embeds Pocket ID, its frontend, and the frozen OAuth bootstrap.
   No Go, Node, pnpm, Python, Docker or Maven installation is required.
4. On first start, a local human test admin (agent-tester), public PKCE client,
   M2M client, API resource and mcp:access grants are created by the real API.
   A unique RSA workload assertion key is generated locally outside the IdP
   installation, and its PUBLIC JWK is registered on the SAME public client.
   No assertion key, reusable token or secret is shipped inside the .run.
5. A unique local static admin API key is generated in private .env (0600).
   This key is not a human password. Pocket ID human login is passkey-only.
6. The one-time human login URL is printed and stored in .login-link.txt (0600).
   Human PKCE, M2M and backend-only workload key path/claims are stored in
   .local-oauth.json (0600), but the private workload key never enters this file.
7. HTTP binds 127.0.0.1:1411 and the peer actor transport binds 127.0.0.1:1414.
   Private SQLite is local; NEVER expose this test instance to the internet.
8. Re-running the same .run reuses the existing installation and its state.
   A different .run build refuses to overwrite the existing installation.
9. Stop with ~/.local/share/pocket-id-local-agent/stop.sh (or the custom path).
   Uninstall manually only after stopping and preserving any needed local data.

Default MCP resource: http://localhost:18080/mcp
Default human OAuth callback: http://localhost:3000/callback
Override only with loopback URLs via LOCAL_MCP_RESOURCE and LOCAL_OAUTH_CALLBACK.

This package is a real local OIDC test service, not remote ChatGPT/Claude
OAuth E2E and not permission to invoke a real GitHub MCP.
