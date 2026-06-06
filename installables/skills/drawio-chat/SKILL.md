---
name: drawio-chat
description: Chat with the user using draw.io files to visually exchange information.
---

Chat with the user using draw.io diagrams to visually and spatially exchange information

User's messages to you, like queries/TODOs etc. will be enclosed in a specific element. Unless overridden, it is the cloud element

Your modficiations to the diagram will be done in a specific color. Unless overridden it is the yellow color

The user might acknowledge your changes/messages while leaving them on the diagram. This notion of "acknowledged" will usually be conveyed by recoloring your elements to a specific color. unless overridden this is blue

Alternately, the user might assimilate your changes with his own modifications.

## File access — token discipline

ALL access to the .drawio file MUST go through `drawio_helper.py` (in this skill's base directory) via Bash. NEVER use the Read/Edit/Write tools on the .drawio file — once the harness tracks it, it re-injects the full file into context on every user save, which is the dominant token cost.

Reading — PREFER `sdiff` (one compact line per added/removed/changed cell, text
decoded to plain language). It auto-falls-back to full old/new XML per cell it
cannot classify. For unexpected/major changes, drill in with `get-cell` or raw `diff`:
```
python3 <skill-dir>/drawio_helper.py FILE sdiff SNAPSHOT     # semantic diff (default read)
python3 <skill-dir>/drawio_helper.py FILE snapshot DIR       # auto-numbered backup (prints path)
python3 <skill-dir>/drawio_helper.py FILE get-cell ID        # full XML of one cell
python3 <skill-dir>/drawio_helper.py FILE list-cells [PAT]   # id + text snippet; e.g. PAT shape=cloud
python3 <skill-dir>/drawio_helper.py FILE diff SNAPSHOT      # raw unified diff (last resort)
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
Text markup: **bold**, *italic*, newline = line break, blank line = paragraph.
add-* prints the new cell id (use it for edges).

Raw-XML fallback — ONLY when presets can't express what you need (clouds,
swimlanes, images, custom geometry on edges):
```
python3 <skill-dir>/drawio_helper.py FILE insert             # stdin: mxCell XML -> before </root>
python3 <skill-dir>/drawio_helper.py FILE replace-cell ID    # stdin: replacement mxCell XML
python3 <skill-dir>/drawio_helper.py FILE delete-cell ID
```

Workflow per exchange (use a session dir like /tmp/drawio-chat-<project>/ for snapshots):

1. session start: `snapshot`, then `list-cells shape=cloud` to find the user's messages (one initial full read via Bash `cat` is OK if needed for layout)
2. user turn: `diff` latest snapshot vs live to read only their changes, then `snapshot`
3. your turn: answer via `insert`/`replace-cell` (yellow elements), then `snapshot`

