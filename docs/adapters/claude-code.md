# Claude Code adapter

Records one DecisionTrace per prompt you give Claude Code: what you asked, what it read, what
it changed, which permission checks ran, what was proposed but not done, what you approved
or denied, the model, tokens, and the git commit before and after.

## Install

```bash
pip install liquicent-decisiontrace
dt install claude-code            # all projects (~/.claude/settings.json)
dt install claude-code --scope project   # this repo, committed (.claude/settings.json)
dt install claude-code --scope local     # this repo, just you (.claude/settings.local.json)
```

Work as usual, then:

```bash
dt log
dt show <id>
```

Remove with `dt uninstall claude-code` (your recorded decisions are kept). Existing hooks
and settings are preserved; a backup is written next to the settings file.

## How it works

1. A hook (`python -I -S …/hook.py`) runs on `UserPromptSubmit`, `PreToolUse`,
   `PostToolUse`, `PostToolUseFailure`, `PermissionRequest`, `PermissionDenied`,
   `SubagentStart`, `SubagentStop`, `Stop`, `StopFailure` and `SessionEnd`.
2. It redacts the event and appends one line to `~/.decisiontrace/queue/<session>.jsonl`.
   It uses only the standard library: median ~35 ms, always exits 0, prints nothing,
   never makes a decision.
3. When a turn ends, a background drain groups the events by `prompt_id`, builds the
   decision, reads model/tokens/version from the transcript, and appends it to the store.
   `dt log` and `dt show` also drain first.

## What maps where

| Claude Code | DecisionTrace |
|---|---|
| your prompt | `intent` (redacted summary) + `context.inputs[user_prompt]` (hash) |
| Read / Grep / Glob, WebFetch | `context.inputs` (files, URLs) |
| git HEAD at prompt / at stop | `context.state_before` / `state_after` |
| tool calls that ran | `actions` (`file_write`, `memory_write` for CLAUDE.md and `.claude/`, `tool_call`) |
| permission outcome per tool | `policies` (`permission:<Tool>`, engine `claude_code_permissions`) |
| denied, auto-denied, interrupted, blocked calls | `alternatives` with `rejected_by` human / policy / system |
| permission prompt + your answer | `human_path` (`requested`, `approved` / `rejected`, latency) |
| subagent work | its own decision, linked from the parent by a `delegation` link |
| model, tokens, Claude Code version | `actor_time.model`, `.cost`, `.client` |

`decision_kind` and `capabilities` are inferred from the tools used (e.g. `code.edit`,
`code.commit`, `harness.update`) — you never declare them.

## Never recorded

Claude's reasoning, its replies, file contents, command output. Prompt bodies are stored
only if you set `bodies = true` in `~/.decisiontrace/config.toml`; otherwise a hash and a
redacted summary.

## Troubleshooting

- Nothing in `dt log`: run `dt drain`; check `~/.decisiontrace/hook-errors.log`.
- Using a custom store location: Claude Code must see the same `DT_HOME`.
- Events that fail to build are kept in `~/.decisiontrace/queue/failed/`, never dropped.
