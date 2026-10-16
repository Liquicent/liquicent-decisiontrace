# MCP server

`dt mcp` runs a local MCP server (stdio) named `decisiontrace` with three tools:

| Tool | Use it to |
|---|---|
| `record` | Write a decision from a client without hooks: intent, rules checked (pass/fail), exceptions and who granted them, rejected options, approvals, actions, outcome |
| `recall` | Ask "have we decided something like this before?" — returns precedents with their rules, exceptions, approval path and outcome, not just text. Pass a decision id to rank by the DecisionTrace similarity function instead |
| `outcome` | Attach what happened to a past decision |

The server ships instructions telling the model to recall before rule/limit/exception
decisions and to record facts only — never secrets or its own reasoning. Everything is
redacted before it reaches the local store.

## Setup

```bash
dt install claude-desktop      # writes claude_desktop_config.json (backup kept)
dt install cursor              # writes ~/.cursor/mcp.json
dt mcp --config claude-code    # prints: claude mcp add --scope user decisiontrace -- …
```

Restart the app. Then ask, for example: *"How did we handle the last refund over the
limit?"* — the model calls `recall` and answers with the past decision, who waived the
limit and why.

To print the JSON for any other MCP client: `dt mcp --config cursor`.
Remove with `dt uninstall claude-desktop` / `dt uninstall cursor`.

## Example `recall` result

```json
{
  "precedents": [
    {
      "id": "01M53…",
      "kind": "refund.approve",
      "intent": "Refund $850 for order 7731, parcel crushed in transit",
      "rules": [{"rule": "refund.max_auto_amount", "result": "fail",
                 "detail": "Amount $850 exceeds the $500 limit"}],
      "exceptions": [{"rule": "refund.max_auto_amount", "waived_by": "Meera",
                      "role": "support lead", "reason": "VIP and carrier damage confirmed"}],
      "approval_path": [{"step": "requested", "by": "refunds agent"},
                        {"step": "approved", "by": "Meera"}],
      "outcome": "accepted",
      "score": 0.97
    }
  ]
}
```
