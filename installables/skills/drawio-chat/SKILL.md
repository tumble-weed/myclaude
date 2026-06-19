---
name: drawio-chat
description: Chat with the user using draw.io files to visually exchange information.
---

Chat with the user using draw.io diagrams to visually and spatially exchange information

User's messages to you, like queries/TODOs etc. will be enclosed in a specific element. Unless overridden, it is the cloud element

Your modficiations to the diagram will be done in a specific color. Unless overridden it is the yellow color

The user might acknowledge your changes/messages while leaving them on the diagram. This notion of "acknowledged" will usually be conveyed by recoloring your elements to a specific color. unless overridden this is blue

Alternately, the user might assimilate your changes with his own modifications.

## Modes (load on demand)

- **Code representation** — when the chat turns to code changes (which files/classes/funcs a
  change touches and how they relate), read `references/code-representation.md` and follow it.
  It adds a durable `<name>.code.md` "mother" spec, a file-identity color grammar, and a
  diagram⇄spec sync loop. Note: code-view overrides the blanket "Claude = yellow" rule —
  code cells use no yellow/blue (those stay reserved for the chat layer); the reference has
  the details.
- **Planning** — when a chat is meant to become an implementation plan, read
  `references/planning.md` and follow it. Explore on page 1, concretize code on a new page
  (per code-representation.md), then dump a comprehensive, stand-alone plan md into
  `.claude/todo/`. Plan md and the `<name>.code.md` spec are separate artifacts; the link
  between chat and plan is mutual.

## File access — token discipline

ALL access to the .drawio file MUST go through `drawio_helper.py` (in this skill's base directory) via Bash. NEVER use the Read/Edit/Write tools on the .drawio file — once the harness tracks it, it re-injects the full file into context on every user save, which is the dominant token cost.

Creating a new diagram — start a blank canvas, then chat into it as usual:
```
python3 <skill-dir>/drawio_helper.py FILE new [--name PAGE] [--force]
```
Writes a valid empty single-page `.drawio` (page named `Page-1` unless `--name`),
seeds the vault as `v1`, and prints the path. Refuses to overwrite an existing
file unless `--force`. After this, use `add-page` / `add-note` / `add-edge` etc.

Versioning — backups live in a private per-diagram git vault under
`~/.cache/drawio-chat/<name>-<pathhash>/` (independent of the project's own .git;
survives reboots; delta-compressed). REF = `vN` | git rev | `HEAD~k`.
```
python3 <skill-dir>/drawio_helper.py FILE snapshot [-m MSG]  # commit to vault (no-op if unchanged)
python3 <skill-dir>/drawio_helper.py FILE versions           # list vN, rev, date, message
python3 <skill-dir>/drawio_helper.py FILE restore REF        # roll FILE back (auto-saves live first)
python3 <skill-dir>/drawio_helper.py FILE sync-status        # clean|diag-newer|md-newer|both-changed (code mode)
python3 <skill-dir>/drawio_helper.py FILE code-md-path       # path of <name>.code.md mother spec (code mode)
```

Reading — PREFER `sdiff` (one compact line per added/removed/changed cell, text
decoded to plain language). It auto-falls-back to full old/new XML per cell it
cannot classify. For unexpected/major changes, drill in with `get-cell` or raw `diff`:
```
python3 <skill-dir>/drawio_helper.py FILE sdiff [REF]        # semantic diff vs vault (default HEAD)
python3 <skill-dir>/drawio_helper.py FILE get-cell ID        # full XML of one cell
python3 <skill-dir>/drawio_helper.py FILE list-cells [PAT]   # id + text snippet; e.g. PAT shape=cloud
python3 <skill-dir>/drawio_helper.py FILE diff [REF]         # raw unified diff (last resort)
```

Writing — PREFER the scaffolded commands (you emit only text + coords; the script
builds the XML, handles escaping, styles, ids — much cheaper than emitting XML):
```
python3 <skill-dir>/drawio_helper.py FILE add-note --x X --y Y [--w 240] [--h H] [--color yellow] < text
python3 <skill-dir>/drawio_helper.py FILE add-box  ...same flags... < text   # square corners
python3 <skill-dir>/drawio_helper.py FILE add-edge SRC_ID DST_ID [--label L] [--no-arrow]
python3 <skill-dir>/drawio_helper.py FILE set-text ID < text                 # keeps style/geometry
python3 <skill-dir>/drawio_helper.py FILE recolor ID yellow|blue|plain
```
Multi-page: files can hold several pages (one `<diagram>` each). Every write/inspect command
takes `--page N` (index, default 0) or `--page name=Foo`; `list-cells`/`get-cell` also accept
`--page all`. Single-page diagrams keep working with no `--page`.
```
python3 <skill-dir>/drawio_helper.py FILE pages              # idx, name, id, cell-count
python3 <skill-dir>/drawio_helper.py FILE add-page NAME      # append a page; prints its index
```
Text markup (add-note/add-box/set-text stdin is markdown; the helper converts it
to draw.io HTML — never hand-write HTML in stdin):
- `**bold**`, `*italic*`, newline = line break, blank line = paragraph
- `#` / `##` / `###` headings; `- ` and `1. ` lists
- `` `inline code` `` -> monospace with grey background
- fenced code blocks -> syntax-highlighted via Pygments. ALWAYS tag the
  language (```python, ```sql, ```js, ...) — that's what triggers coloring;
  untagged fences render as plain monospace. Indentation is preserved.
  Any Pygments lexer name works; unknown names fall back to plain mono.
- code blocks render fixed-width: size the note (`--w`) to the longest line
add-* prints the new cell id (use it for edges).

Raw-XML fallback — ONLY when presets can't express what you need (clouds,
swimlanes, images, custom geometry on edges):
```
python3 <skill-dir>/drawio_helper.py FILE insert             # stdin: mxCell XML -> before </root>
python3 <skill-dir>/drawio_helper.py FILE replace-cell ID    # stdin: replacement mxCell XML
python3 <skill-dir>/drawio_helper.py FILE delete-cell ID
```

Workflow per exchange:

1. session start: `snapshot -m "session start"`, then `list-cells shape=cloud` to find the user's messages (one initial full read via Bash `cat` is OK if needed for layout)
2. user turn: `sdiff` (defaults to vs last snapshot) to read only their changes, then `snapshot -m "<what they added>"`
3. your turn: answer via `add-note`/`add-edge` (yellow), then `snapshot -m "answered <topic>"`

