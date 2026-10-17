# Self-hosted MCP server (for teams)

`dt mcp --http` serves DecisionTrace's three tools (`record`, `recall`, `outcome`) over HTTPS
from the company's own infrastructure, so a whole team can use them: Claude.ai and ChatGPT
workspace connectors, Claude Code, and the company's own agents. Records go into one store
the company controls; nothing is sent anywhere else.

```
Claude.ai / ChatGPT connector ─┐
Claude Code (remote MCP) ──────┼──HTTPS──> reverse proxy (TLS) ──> dt mcp --http ──> /data (traces.db)
Company agents (MCP client) ───┘
```

**What it records.** A decision is recorded when the assistant calls `record` (the server's
instructions ask it to, around rules, limits, exceptions and approvals). It is not a
transcript of every conversation. For complete capture of developer work use the Claude Code
hooks (`dt install claude-code`); for your own agents use the SDK wrapper.

## 1. Run it

```bash
export DT_MCP_TOKEN=$(dt mcp --new-token)        # keep it in your secret store
DT_HOME=/srv/decisiontrace dt mcp --http --host 0.0.0.0 --port 8765 --allowed-host dt.acme.com
```

| Option | Default | Meaning |
|---|---|---|
| `--http` | off | Serve over HTTP instead of stdio |
| `--host`, `--port` | 127.0.0.1, 8765 | Where to listen |
| `--token` / `DT_MCP_TOKEN` | none | Shared token, at least 24 characters. **Required** on any host other than localhost |
| `--tools` | `record,recall,outcome` | Tools to expose. Use `record,outcome` if precedents should not be readable by everyone with access |
| `--client-name` | `mcp-http` | Stored as the client on every decision (e.g. `claude.ai connector`) |
| `--allowed-host` | none | Accepted `Host` header(s), e.g. your public name (repeatable) |
| `--access-log` | off | Log requests. Leave off: logs would contain the secret URL |

Endpoints: `POST /mcp` (header token), `POST /t/<token>/mcp` (secret URL), `GET /healthz`
(`ok`, no token, no data). Responses are plain JSON (stateless streamable HTTP), so several
replicas can share one volume behind a load balancer if needed; one is plenty for most teams.

### With Docker and automatic HTTPS

`deploy/self-hosted-mcp/` holds a Dockerfile, `compose.yaml` and a Caddyfile:

```bash
cd deploy/self-hosted-mcp
cp .env.example .env            # set DT_PUBLIC_HOST=dt.acme.com and DT_MCP_TOKEN
docker compose up -d --build    # Caddy obtains the TLS certificate for DT_PUBLIC_HOST
curl https://dt.acme.com/healthz
```

The store lives in the `dt-data` volume. Back it up like any database volume.

## 2. Connect clients

Connector screens change names often; look for "custom connector" or "MCP server" in your
admin console.

| Client | How | URL / setting |
|---|---|---|
| **Claude.ai** (Team / Enterprise: an owner adds it for the organisation; individual plans: in your own settings) | Add a custom connector | `https://dt.acme.com/t/<token>/mcp` |
| **ChatGPT** (business workspaces that allow custom MCP connectors) | An admin adds a custom connector / MCP server, no authentication | `https://dt.acme.com/t/<token>/mcp` |
| **Claude Code** | `claude mcp add --transport http decisiontrace https://dt.acme.com/mcp --header "Authorization: Bearer $DT_MCP_TOKEN"` | header token |
| **Your agents** | Any MCP client over streamable HTTP | `https://dt.acme.com/mcp` + `Authorization: Bearer <token>` |

Connectors are called from the AI provider's cloud, not from the employee's browser, so the
server must be reachable from the internet over HTTPS. Where the provider publishes its
egress IP ranges, restrict the reverse proxy to them.

## 3. Security model

- **One shared token.** Anyone with it can call the exposed tools. Treat the secret URL like a
  password: share it only through the admin console, rotate it by restarting with a new
  token (then update the connector), and use `--tools record,outcome` for broad rollouts.
- **No user identity.** Connectors do not tell the server who the employee is. The assistant
  may pass `on_behalf_of` (e.g. "Meera (support lead)"); otherwise the decision has no
  principal. The server never attributes decisions to its own OS account.
- **Same privacy as local use.** Secrets and personal data are redacted before write, no
  prompt bodies are stored, model reasoning is never stored, and the store is hash-chained
  (`dt verify`).
- **Refusals.** The server will not start off localhost without a token, or with a token
  shorter than 24 characters. Without a token on localhost it checks the `Host` header
  (DNS-rebinding protection).
- The conversation itself is processed by the AI provider as usual; DecisionTrace only
  receives what the assistant sends to its tools.

## 4. Operate

```bash
docker compose exec decisiontrace dt verify
docker compose exec decisiontrace dt log -n 20
docker compose exec decisiontrace dt outcomes detect --assume-accepted-after 14   # e.g. daily from cron
docker compose exec decisiontrace dt export -o /data/export.jsonl                 # for Valence / Liquicent
```
