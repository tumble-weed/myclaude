# Planning mode

Load this when a drawio-chat is meant to **become an implementation plan**. The visual
chat is the easy human interface; the dumped plan md is complete LLM context. A fresh
Claude Code session then implements from the plan md alone — no draw.io, no extra context.

| Phase | Medium | For whom |
|-------|--------|----------|
| Chat | visual draw.io | the **human** — spatial, low friction |
| Plan md | text | the **LLM** — complete, foolproof, stands alone |
| Implement | LLM reads plan md only | no extra context needed |

The plan md and the mother spec `<name>.code.md` are **separate artifacts**. The spec
serves the diagram (diagram-bound, synced — see `code-representation.md`). The plan md
serves an isolated, draw.io-unaware implement session. Reading the spec as a *source* for
the dump is not coupling.

## When to trigger

User-driven. The user decides this chat is a plan (Claude may suggest it). There is no
trigger keyword — Stage 1 is just normal chat.

## Stage 1 — Explore

Normal free-form drawio-chat on **page 1**. Messy, spatial, exploratory. User kicks it off
(or asks Claude to). Nothing special — the base skill, unchanged.

## Stage 2 — Concretize

When the ideas firm up into code changes, spin a **new page** for the concrete code layout:

```
drawio_helper.py FILE add-page "code layout"
drawio_helper.py FILE <write-cmd> ... --page 1
```

The code-layout page's grammar (file-color identity, tree+detail, swimlanes, the
`<name>.code.md` mother spec, the sync loop) is **owned by `references/code-representation.md`**.
Read and follow that — planning.md does not restate it.

## Stage 3 — Dump

User calls the chat done. Then:

1. `drawio_helper.py FILE sync-status`
   - `diag-newer` → reconcile the spec **from** the diagram first, so the source is current.
   - `both-changed` → STOP, ask the user.
2. Read the mother spec `<name>.code.md` (via `code-md-path`) as the **primary source** for
   *what changes* — plus the chat context. Glance at page-2 cells only to catch diagram-only
   edits not yet synced. No helper export command exists; you hand-author.
3. Hand-author a **comprehensive** plan md into `.claude/todo/` (project-local plan home).
   - **No fixed skeleton.** Foolproof = comprehensive, not a template. Lay it out like any
     normal plan md, custom to this plan.
   - It must **stand alone**: an isolated session with only this file must be able to
     implement. Otherwise the plan md is drawio-unaware.

**Mutual link (both sides):**

| Side | Carries | Granularity |
|------|---------|-------------|
| plan md → chat | the `.drawio` file path | file path only — no page/cell pinning |
| chat → plan md | the plan md path, in a **cell on the code page** | not in `<name>.code.md` (that would couple the two separate artifacts) |

## Back-prop

If the plan **diverges** during implementation, update the draw.io chat to match **AND
inform the user**. Diagram and plan stay reconciled.
