---
description: explain a term or phrase the user didn't get, grounded in this conversation, and log it
argument-hint: "[term or phrase] (optional — omit to point at something just said)"
---

The user doesn't understand a term or phrase. Identify it, explain it, log it.

## 1. Identify the term

- If `$ARGUMENTS` is non-empty, that's the term/phrase (e.g. `/idk shim`).
- If empty, the user is pointing at something from your recent output or theirs. Pick the most likely candidate from the last message or two. If genuinely ambiguous, ask which phrase — don't guess wildly.

## 2. Explain it

Ground the explanation in THIS conversation, not a generic dictionary entry. If we're setting up a symlink installer and they ask "what's a shim", explain shim *relative to what we're doing*.

Style: terse, example-first (match the `no-bs` output style). Lead with a concrete case tied to our current work, then generalize in one line. No throat-clearing, no "great question".

## 3. Log it

Append one entry to `~/.claude/idk-log.md` (create the file with an `# IDK log` header if it doesn't exist). This is a durable gaps catalogue for later introspection — it must stand alone, because the conversation it came from may be deleted. You have the full conversation in context right now, so capture the context hook *now*; never write a pointer back to the conversation.

Use today's date and the current working directory's project. Format:

```md
## <term> — <YYYY-MM-DD>
**Context:** <one line: what we were doing when they asked>
**Got:** <the compressed answer you gave, one line>
**Project:** <repo path or name, or "—" if none>
```

Keep `Context` and `Got` to one line each. Append only — never rewrite or reorder existing entries.
