# Mattermost MCP

MCP server for interacting with Mattermost over the Web API. The implementation is written in Python. `Playwright` is used for SSO authorization through a browser flow.

## Features

- `mattermost_get_me` - get the current user for the active session.
- `mattermost_list_teams` - get the current user's teams.
- `mattermost_list_channels` - get the user's channels inside a team.
- `mattermost_get_channel_by_name` - find a channel by `team_id` and `channel_name`.
- `mattermost_get_channel_posts` - get channel posts with pagination.
- `mattermost_create_post` - send a message to a channel.
- `mattermost_search_posts` - search posts inside a team.

## Environment Variables

- `MATTERMOST_BASE_URL` - base Mattermost URL, for example `https://mattermost.example.com`
- `MATTERMOST_AUTH_MODE` - authorization mode: `auto`, `token`, `browser`, `login`, `playwright`. Default: `auto`
- `MATTERMOST_TOKEN` - personal access token or bot token for Bearer auth
- `MATTERMOST_MMAUTHTOKEN` - `MMAUTHTOKEN` cookie value for browser-session auth
- `MATTERMOST_MMCSRF` - `MMCSRF` cookie value for browser-session auth
- `MATTERMOST_MMUSERID` - `MMUSERID` cookie value, optional but recommended
- `MATTERMOST_LOGIN_ID` - email or username for auto-login through `POST /api/v4/users/login`
- `MATTERMOST_PASSWORD` - password for auto-login
- `MATTERMOST_MFA_TOKEN` - one-time MFA code if the server requires MFA
- `MATTERMOST_SSO_AUTH_URL` - direct OIDC/SSO URL for browser login through `Playwright`
- `MATTERMOST_PLAYWRIGHT_HEADLESS` - run browser headless, default: `true`
- `MATTERMOST_PLAYWRIGHT_INTERACTIVE` - if `true`, Playwright does not auto-fill or auto-submit the form and waits for you to complete login manually
- `MATTERMOST_PLAYWRIGHT_BROWSER` - browser name: `chromium`, `firefox`, or `webkit`, default: `chromium`
- `MATTERMOST_PLAYWRIGHT_TIMEOUT_MS` - browser step timeout, default: `300000`
- `MATTERMOST_PLAYWRIGHT_USERNAME_SELECTOR` - CSS selector for the username field, default: `input[name="username"]`
- `MATTERMOST_PLAYWRIGHT_PASSWORD_SELECTOR` - CSS selector for the password field, default: `input[name="password"]`
- `MATTERMOST_PLAYWRIGHT_SUBMIT_SELECTOR` - CSS selector for the login button, default: `input[name="login"], button[type="submit"], #kc-login`
- `MATTERMOST_PLAYWRIGHT_POST_LOGIN_URL_PREFIX` - URL prefix considered a successful return to Mattermost. Default: `MATTERMOST_BASE_URL` without `/api/v4`
- `MATTERMOST_PLAYWRIGHT_SUCCESS_SELECTOR` - optional CSS selector that must appear after successful login
- `MATTERMOST_AUTH_TEST_ONLY` - if `true`, the process only verifies authentication using `GET /api/v4/users/me`, prints the result, and exits without starting the MCP stdio loop
- `MATTERMOST_TIMEOUT_SECONDS` - HTTP request timeout, default: `15`
- `MATTERMOST_VERIFY_SSL` - verify TLS certificates, default: `true`

If `MATTERMOST_BASE_URL` already ends with `/api/v4`, the server does not append the prefix again.

## Authorization

Four modes are supported:

- Bearer token: the server sends `Authorization: Bearer <MATTERMOST_TOKEN>`
- Browser session: the server sends `MMAUTHTOKEN`, `MMCSRF`, `MMUSERID` cookies and the `X-CSRF-Token` header
- Login session: on startup the server calls `POST /api/v4/users/login`, keeps the returned tokens in memory, and reauthenticates on `401/403`
- Playwright SSO session: on startup the server opens a browser, goes through the SSO flow, extracts Mattermost cookies, and reauthenticates through a repeated browser login on `401/403`

In `auto` mode the priority order is:

1. If `MATTERMOST_TOKEN` is set, Bearer auth is used.
2. Otherwise, if `MATTERMOST_MMAUTHTOKEN` and `MATTERMOST_MMCSRF` are set, browser-session auth is used.
3. Otherwise, if `MATTERMOST_LOGIN_ID` and `MATTERMOST_PASSWORD` are set, login auth is used.
4. Otherwise, if `MATTERMOST_SSO_AUTH_URL`, `MATTERMOST_LOGIN_ID`, and `MATTERMOST_PASSWORD` are set, playwright auth is used.

Example of the Playwright SSO mode:

```bash
export MATTERMOST_BASE_URL=https://mattermost.example.com
export MATTERMOST_AUTH_MODE=playwright
export MATTERMOST_SSO_AUTH_URL='https://sso.example.com/auth/realms/mattermost/protocol/openid-connect/auth?...'
export MATTERMOST_LOGIN_ID='bot@example.com'
export MATTERMOST_PASSWORD='super-secret-password'
export MATTERMOST_PLAYWRIGHT_HEADLESS='false'
export MATTERMOST_PLAYWRIGHT_INTERACTIVE='true'
export MATTERMOST_PLAYWRIGHT_TIMEOUT_MS='600000'
export MATTERMOST_AUTH_TEST_ONLY='true'
uv run python -m mattermost_mcp
```

If your Keycloak setup uses a standard login form, the default selectors should work without changes. If the form is customized, override the selectors through environment variables.

For manually completing SSO, copying prompts, and taking screenshots, it is best to run with:

- `MATTERMOST_PLAYWRIGHT_HEADLESS=false`
- `MATTERMOST_PLAYWRIGHT_INTERACTIVE=true`
- `MATTERMOST_PLAYWRIGHT_TIMEOUT_MS=600000`
- `MATTERMOST_AUTH_TEST_ONLY=true`

In this mode the browser opens, the process waits for SSO to complete, verifies `GET /api/v4/users/me`, prints the result, and exits. The MCP server itself is not started, so you do not get JSON-RPC noise in the terminal.

Important: `login`, `browser-session`, and `playwright` auth are more fragile than a Bearer token. The session can expire or be invalidated on logout or password change. Playwright cookies are written to `MATTERMOST_SESSION_FILE` (default `.mm-session`, gitignored) after a successful SSO. Later MCP and CLI starts reuse that file and open a browser only on `401/403` or when the file is missing. The MCP stdio server does not log in during `initialize` or `tools/list`.

## Setup

```bash
uv sync
uv run playwright install chromium
cp .env.example .env
export $(grep -v '^#' .env | xargs)
uv run python -m mattermost_mcp
```

If you run `python -m mattermost_mcp` directly in a normal terminal without `MATTERMOST_AUTH_TEST_ONLY=true`, the process will refuse to start as an MCP server. That is expected: an MCP stdio server should be started only by an MCP client, not manually from a shell.

To manually read a channel by ID without an MCP client:

```bash
uv run python -m mattermost_mcp read-channel --channel-id CHANNEL_ID
```

Useful flags:

- `--per-page 200` - page size
- `--max-pages 20` - maximum number of pages to fetch
- `--json` - output raw posts as JSON instead of human-readable text

To manually send a message to a channel without an MCP client:

```bash
uv run python -m mattermost_mcp send-message --channel-id CHANNEL_ID --message "test from cli"
```

Useful flags:

- `--root-id POST_ID` - send a thread reply
- `--json` - output raw created post JSON

Example MCP client configuration:

```json
{
  "mcpServers": {
    "mattermost": {
      "command": "uv",
      "args": [
        "run",
        "--directory",
        "/absolute/path/to/mattermost-mcp",
        "python",
        "-m",
        "mattermost_mcp"
      ],
      "env": {
        "MATTERMOST_BASE_URL": "https://mattermost.example.com",
        "MATTERMOST_AUTH_MODE": "playwright",
        "MATTERMOST_SSO_AUTH_URL": "https://sso.example.com/auth/realms/mattermost/protocol/openid-connect/auth?...",
        "MATTERMOST_LOGIN_ID": "bot@example.com",
        "MATTERMOST_PASSWORD": "super-secret-password",
        "MATTERMOST_PLAYWRIGHT_HEADLESS": "false",
        "MATTERMOST_PLAYWRIGHT_INTERACTIVE": "true",
        "MATTERMOST_PLAYWRIGHT_TIMEOUT_MS": "600000",
        "MATTERMOST_PLAYWRIGHT_BROWSER": "chromium",
        "MATTERMOST_TIMEOUT_SECONDS": "15",
        "MATTERMOST_VERIFY_SSL": "true"
      }
    }
  }
}
```

## Session Rotation

For `login` and `playwright` auth, a separate manual rotation process is usually not needed. Mattermost returns a session token or browser session cookies whose lifetime is controlled by the server configuration. When the session expires and the API responds with `401` or `403`, the server performs login again and retries the request with a new session.

If you need a stricter rotation policy, it is better to build it around:

- a dedicated technical user
- storing login/password in MCP client secrets
- automatic re-login on session expiry
- revoking access by changing the password or using logout/revoke sessions on the Mattermost side

## Playwright Notes

- The `playwright` mode is meant for instances where `POST /api/v4/users/login` does not work because of SSO/OIDC.
- The implementation is designed to start from a ready-made `MATTERMOST_SSO_AUTH_URL`.
- By default it uses Keycloak selectors:
  - `input[name="username"]`
  - `input[name="password"]`
  - `input[name="login"], button[type="submit"], #kc-login`
- If you need an additional check that the Mattermost UI has loaded after login, set `MATTERMOST_PLAYWRIGHT_SUCCESS_SELECTOR`.
- For local debugging and manual SSO flows, `MATTERMOST_PLAYWRIGHT_HEADLESS=false` is convenient.
- If you need to manually read prompts, go through extra steps, and take screenshots, enable `MATTERMOST_PLAYWRIGHT_INTERACTIVE=true`.

## Verification

```bash
uv run python -m unittest discover -s tests -v
```

## Postman

The following files are included for manual smoke testing:

- `postman/Mattermost Web API Manual Testing.postman_collection.json`
- `postman/Mattermost Web API Manual Testing.local.postman_environment.json`

What the collection checks:

- login through `POST /api/v4/users/login`
- storing `Token`, `MMAUTHTOKEN`, `MMCSRF`, and `MMUSERID` from the response
- reading `users/me` through a Bearer token
- reading `users/me` through browser-session cookies
- listing teams and channels
- sending a post
- reading channel posts
- searching posts
- manually verifying session rotation through re-login after `401/403`
