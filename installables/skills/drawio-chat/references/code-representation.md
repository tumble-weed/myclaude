# Code representation mode

Load this when the chat turns to **code changes** — depicting which files/classes/funcs
a change touches and how they relate. It layers a code-view grammar on top of the base
drawio-chat workflow and adds a durable markdown "mother" spec.

## When to trigger

Only when code changes are relevant to the current chat (a feature, refactor, bug fix the
user is discussing). Plain Q&A or non-code diagrams use the base skill unchanged. If unsure,
ask before switching into code-view.

## The two artifacts

| Artifact | Where | Role |
|----------|-------|------|
| `<name>.code.md` (mother spec) | the vault (`code-md-path` prints it) | durable, human-readable proposed-changes spec. Edit with Read/Write — it is NOT the .drawio, so normal tools are fine. |
| the `.drawio` diagram | the live file | visual render of the spec, exchanged with the user |

The md is the source of truth for *what changes*; the diagram is its picture. They are
versioned **together** in one snapshot (`snapshot` git-adds both).

## Layout (one page)

- **Tree** (left): monospace box listing ALL impacted file paths. Use a fenced ```text block
  in an `add-box` so it renders fixed-width.
- **Detail** (right): the per-file breakdown.
  - **1 theme** → flat per-file panels (one `add-box` per file), with arrows optional depicting relationship btw files.
  - **N themes** → one swimlane per theme (raw-XML `insert`), files grouped inside, again with arrows optional.

if adding the code representation to this page causes an overflow or if it represents a different "phase" of the chat → put it on a **new page** (`add-page NAME`), then
write to it with `--page`.

## Color / shape grammar

| Channel | Encodes |
|---------|---------|
| bg color of a code cell | **file identity** — 1 file = 1 stable color, reused in BOTH tree and detail. Same color across views = same file. |
| nested box | a class / function inside a file |
| arrow (labeled) | a file → file relationship (imports, calls, extends…) |
| swimlane | one theme (only when >1 theme) |

**Code-view overrides the blanket "Claude = yellow" rule.** But, code cells use NO yellow and
NO blue — those, plus the cloud shape, stay reserved for the chat layer (see below), which
is layered on top of the code view.

| Reserved (chat layer) | Meaning |
|------------------------|---------|
| yellow border/cell | Claude's message to the user |
| blue | user's acknowledgement |
| cloud | user's message to Claude |

Pick file colors from a palette that excludes yellow (`#FFF2CC`) and blue (`#DAE8FC`) — e.g.
greens, oranges, purples, greys. Record each file→color assignment in the mother spec so it
stays stable across turns.

## Mother spec shape (`<name>.code.md`)

```
# <feature / flow>

## page: <page name>        # mirrors the diagram's pages

### impacted files (tree)
<monospace tree of touched paths>

### file: path/to/a.py   [color: green]
- ClassX: <change>
- func y(): <change>
- relates-to -> path/to/b.py

## themes (if >1)
- theme1: a.py, c.py
- theme2: b.py
```

The spec mirrors page structure, carries the color assignments, and reads as a proposed-
changes document on its own.

## Sync workflow (the loop)

```
1. user asks for a code change  -> write/update <name>.code.md FIRST (Write tool)
2. render md -> diagram MANUALLY (add-page / add-box / add-edge), code cells: no yellow/blue
3. snapshot                      (joint: .drawio + .code.md, one version)
4. user chats on the diagram     (their edits land in the live .drawio)
5. next turn: sync-status
     clean        -> nothing to reconcile
     diag-newer   -> update .code.md from the diagram (sdiff to read their changes)
     md-newer     -> update the diagram from the md
     both-changed -> STOP, ask the user (no silent merge)
6. snapshot again
```

Rendering is manual for now — there is no md→drawio auto-layout engine in the helper.

## Helper commands this mode leans on

```
drawio_helper.py FILE code-md-path          # path of the mother spec (Read/Write it directly)
drawio_helper.py FILE sync-status           # clean | diag-newer | md-newer | both-changed
drawio_helper.py FILE pages                 # idx · name · id · cell-count
drawio_helper.py FILE add-page NAME         # new page; prints its index
drawio_helper.py FILE <write-cmd> ... --page N   # target a page (index or name=Foo)
```
