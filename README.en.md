# Databricks Token Exchange MCP Proxy

An MCP proxy server that allows Entra ID–authenticated MCP clients (ChatGPT, Claude Desktop, etc.) to access [Databricks Managed MCP](https://docs.databricks.com/aws/en/generative-ai/mcp/managed-mcp) tools.

It receives the Entra ID Bearer token presented by the client, exchanges it for a Databricks access token via [OAuth Token Exchange (RFC 8693)](https://docs.databricks.com/aws/en/dev-tools/auth/oauth-federation-exchange), and forwards the request to the backend. Exchanged Databricks tokens are cached inside the proxy and reused for subsequent requests from the same user until they expire.

```
MCP Client ──[Entra ID Token]──► MCP Proxy ──[Databricks Token]──► Databricks Managed MCP
```

## Prerequisites

- Python 3.11+ (installed via [uv](https://docs.astral.sh/uv/))
- Access to an Azure tenant (permission to create App Registrations)
- Databricks workspace with Managed MCP enabled
- Access to Databricks Account Console (for federation policy configuration)

---

## Setup

### 1. Entra ID — Create an App Registration for the proxy server

Azure Portal → **Microsoft Entra ID** → **App registrations** → **New registration**

| Field | Value |
|---|---|
| Name | Any (e.g. `mcp-proxy-server`) |
| Supported account types | This organization directory only |
| Redirect URI | Not required (leave blank) |

#### 1-1. Expose an API (define scopes)

**"Expose an API"** tab → **"Add a scope"**

| Field | Value |
|---|---|
| Application ID URI | `api://<Application (client) ID>` (auto-generated) or any custom URI |
| Scope name | `access` (must match the short-form name set in `REQUIRED_SCOPES`) |
| Who can consent | Admins and users |

> **About App ID URI:** When MCP Inspector or other clients run the OAuth flow, Entra ID requires that the `resource` parameter and the scopes point to the same App ID URI. Since `BASE_URL/mcp` is sent as `resource`, setting the App ID URI to `BASE_URL/mcp` (e.g. `https://your-domain.com/mcp`) and assigning the same value to the `IDENTIFIER_URI` environment variable keeps everything consistent.

#### 1-2. Set the token version to v2.0 (optional)

**"Manifest"** tab → edit JSON

```json
"requestedAccessTokenVersion": 2
```

> If not set, v1.0 tokens (issuer: `sts.windows.net`) will be issued. To accept v1 tokens, set `ENTRA_VERSION=1` instead of changing this setting.

#### 1-3. Add optional claims (`email` claim, if needed)

**"Token configuration"** tab → **"Add optional claim"** → select **"Access"** → check `email`

> Required when Databricks federation policy identifies users by the `email` claim.

#### 1-4. Note these values

| Value | Location |
|---|---|
| `AZURE_TENANT_ID` | Azure Portal → Entra ID → Overview → Tenant ID |
| `AZURE_CLIENT_ID` | Created App Registration → Overview → Application (client) ID |

---

### 2. Entra ID — App Registration for the MCP client app (optional)

If ChatGPT, Claude Desktop, or other clients run the OAuth flow themselves, create a separate App Registration for the client app.

- **API permissions** → **"Add a permission"** → **"My APIs"** → select the App created in step 1 → check the `access` scope
- Set the redirect URI according to the client app's requirements

> For testing, Device Code Flow is the easiest approach. See [Acquiring a test token](#acquiring-a-test-token).

---

### 3. Databricks — Configure Account-wide Federation policy

Account Console → **Security** → **Authentication** → **Federation policies** → **"Create policy"**

| Field | Value |
|---|---|
| Issuer | v2: `https://login.microsoftonline.com/<AZURE_TENANT_ID>/v2.0` / v1: `https://sts.windows.net/<AZURE_TENANT_ID>/` |
| Audiences | The value of the `aud` claim in the Entra ID token (e.g. `api://<AZURE_CLIENT_ID>` or `<AZURE_CLIENT_ID>`) |
| Subject claim | `email` (or `sub`) |

> **How to find the audience value:** Obtain a token with `scripts/get_entra_token.py` and decode the `aud` claim at [jwt.ms](https://jwt.ms).

---

### 4. Local setup

```bash
# Clone the repository
git clone https://github.com/y-iwano/dbx-token-exchange-sample.git
cd dbx-token-exchange-sample

# Install dependencies
uv sync

# Create the environment file
cp .env.example .env
```

Edit `.env` and fill in each value:

```bash
# Entra ID
AZURE_TENANT_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
AZURE_CLIENT_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx

# Databricks
DATABRICKS_HOST=https://<workspace>.azuredatabricks.net

# Server (http://localhost:3000 is also accepted for local development)
BASE_URL=http://localhost:3000
PORT=3000

# OAuth scopes advertised to MCP clients (JSON array).
# Must match the App ID URI and scope defined in Azure Portal "Expose an API".
# OAUTH_SCOPES='["openid", "https://your-domain.com/mcp/access"]'

# Short-form scope names required in incoming token scp claims.
# Must match scope names defined in Azure Portal "Expose an API".
# If not set, scp validation is skipped.
# REQUIRED_SCOPES='["access"]'

# Application ID URI of the Entra App Registration.
# Set to BASE_URL/mcp to align with the resource parameter sent by MCP Inspector.
# IDENTIFIER_URI=https://your-domain.com/mcp

# Entra ID token version: "1" or "2" (default: "2")
# ENTRA_VERSION=2

# Managed MCP servers to proxy
# name: tool namespace prefix (e.g. "sql" → tools named "sql_*")
# path: Databricks API path
MCP_SERVERS='[{"name": "sql", "path": "/api/2.0/mcp/sql"}]'

# Safety margin (seconds) subtracted from expires_in when caching Databricks tokens.
# expires_at = acquired_at + expires_in - DBX_TOKEN_CACHE_TTL_BUFFER
# DBX_TOKEN_CACHE_TTL_BUFFER=60
```

> **Note on `OAUTH_SCOPES` and Entra ID consistency:** MCP Inspector and similar clients send `BASE_URL/mcp` as the `resource` parameter to Entra ID. Entra ID v2.0 requires that `resource` and `OAUTH_SCOPES` point to the same app, so `BASE_URL` and the App ID URI must match. For local development (`BASE_URL=http://localhost:...`), the OAuth flow will not work because Entra ID does not recognise `http://localhost` as a registered resource. Obtain a token with `scripts/get_entra_token.py` and pass it directly as a Bearer token instead.

#### `MCP_SERVERS` path patterns

| Type | Path |
|---|---|
| Genie Space | `/api/2.0/mcp/genie/{genie_space_id}` |
| Databricks SQL | `/api/2.0/mcp/sql` |
| Vector Search | `/api/2.0/mcp/vector-search/{catalog}/{schema}/{index_name}` |
| Unity Catalog Functions | `/api/2.0/mcp/functions/{catalog}/{schema}` |

---

### 5. Start the server

```bash
uv run python -m app.main
```

After startup, `http://localhost:3000/mcp` is available as the MCP endpoint.

---

## Acquiring a test token

When you need an Entra ID access token for MCP clients or integration tests, you can obtain one without a browser using Device Code Flow.

**One-time setup:** Azure Portal → App Registration from step 1 → **"Authentication"** → **"Allow public client flows"** → set to **ON**

```bash
# v2 token (default) — saved as ENTRA_ACCESS_TOKEN
uv run python scripts/get_entra_token.py

# v1 token — saved as ENTRA_ACCESS_TOKEN_V1
uv run python scripts/get_entra_token.py --version 1
```

Open the URL displayed (`https://microsoft.com/devicelogin`), enter the code, and the token will be written to `.env`. Tokens expire in approximately 1 hour.

---

## Running tests

```bash
# Unit tests only (no external services required)
uv run pytest tests/unit/

# Integration tests (requires credentials in .env)
INTEGRATION_TESTS=true uv run pytest tests/integration/

# All tests
INTEGRATION_TESTS=true uv run pytest

# Without coverage
uv run pytest --no-cov
```

Coverage report is output to `htmlcov/index.html`.

---

## Development commands

```bash
uv run pylint src/app   # lint check
```

---

## Environment variable reference

| Variable | Required | Default | Description |
|---|---|---|---|
| `AZURE_TENANT_ID` | ✅ | — | Azure tenant ID |
| `AZURE_CLIENT_ID` | ✅ | — | Client ID of the proxy server App Registration |
| `DATABRICKS_HOST` | ✅ | — | Databricks workspace URL (must start with `https://`) |
| `BASE_URL` | ✅ | — | Public URL of this server (`https://`, or `http://localhost` for local dev) |
| `PORT` | — | `3000` | Listen port |
| `MCP_SERVERS` | ✅ | — | List of Managed MCP servers to proxy (JSON array) |
| `OAUTH_SCOPES` | — | — | OAuth scopes advertised to MCP clients (JSON array, e.g. `["openid", "https://your-domain.com/mcp/access"]`) |
| `REQUIRED_SCOPES` | — | — | Short-form scope names required in incoming token `scp` claims. If not set, `scp` validation is skipped (e.g. `["access"]`) |
| `IDENTIFIER_URI` | — | `api://<AZURE_CLIENT_ID>` | Application ID URI of the Entra App Registration (e.g. `https://your-domain.com/mcp`) |
| `ENTRA_VERSION` | — | `"2"` | Entra ID endpoint version (`"1"` or `"2"`). Switches both **token verification** (issuer / JWKS URI / audience) and the **authorization server URL advertised to MCP clients**. v1: `sts.windows.net` issuer, endpoint without `/v2.0`; v2: `login.microsoftonline.com/.../v2.0` issuer, endpoint with `/v2.0` |
| `DBX_TOKEN_CACHE_TTL_BUFFER` | — | `60` | Safety margin in seconds subtracted from `expires_in` when caching Databricks tokens. Computed as `expires_at = acquired_at + expires_in - DBX_TOKEN_CACHE_TTL_BUFFER`. Prevents using a token that is about to expire. |

Extra variables in `.env` are silently ignored (`extra="ignore"`).

---

## (Reference) Test deployment on AWS (EC2 + CloudFront)

See [docs/design/01_architecture.md](docs/design/01_architecture.md) for details. Summary:

1. Deploy on EC2 (private subnet) and start on port 3000
2. CloudFront VPC Origin terminates HTTPS → forwards HTTP:3000 to EC2
3. Manage the process with systemd:

```bash
# Specify .env as EnvironmentFile in /etc/systemd/system/mcp-proxy.service
sudo systemctl enable mcp-proxy
sudo systemctl start mcp-proxy
```

---

## Design documents

| Document | Contents |
|---|---|
| [docs/design/01_architecture.md](docs/design/01_architecture.md) | System architecture and deployment |
| [docs/design/02_auth_flow.md](docs/design/02_auth_flow.md) | Authentication and token exchange flow (sequence diagram) |
| [docs/design/03_components.md](docs/design/03_components.md) | Component design |
| [docs/design/04_api.md](docs/design/04_api.md) | Endpoint specification |
| [docs/design/05_config.md](docs/design/05_config.md) | Configuration and environment variables |
| [docs/design/06_error_handling.md](docs/design/06_error_handling.md) | Error handling policy |
| [docs/design/07_testing.md](docs/design/07_testing.md) | Test design |
