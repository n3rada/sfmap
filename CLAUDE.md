# sfmap: Claude Code Project Context

Read [AI.md](AI.md) first. It is the canonical engineering guide: architecture, design principles, module map, Python rules, and definition of done.

## Running the Tool

```bash
uv run sfmap <URL> <surface> <command> [options]
```

Session credential files (gitignored, place in repo root):
- `ctx.json`: Aura context JSON
- `token.txt`: Aura CSRF token
- `cookies.txt`: raw Cookie header
- `bearer.txt`: OAuth Bearer token (REST API only)

## Commit Rules

- No co-author lines. Never add `Co-Authored-By`.
- One-line commit messages only. No body.
- Stage specific files by name. Never `git add -A` or `git add .`.

## Code Rules

- `logger.exception(...)` inside every `except` block; never `logger.debug(f"... {exc}")`.
- No backward-compatibility shims. Delete old code, do not wrap it.
- No comments that explain what the code does. Only comment non-obvious WHY.
- Modern Python only: `X | Y`, `X | None`, `pathlib`, no `Optional`, no `Any`.
- Tools do one thing (SRP). sfmap downloads; external tools (trufflehog, etc.) analyze.

## Style

- No em-dashes or en-dashes anywhere in code, comments, strings, or responses. Use commas, colons, or rewrite the sentence.
- No trailing summaries at the end of responses ("I have updated...", "Here's what I did...").
