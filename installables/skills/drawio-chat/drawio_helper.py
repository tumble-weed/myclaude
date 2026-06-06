#!/usr/bin/env python3
"""Thin draw.io file manipulator for drawio-chat sessions.

Lets an agent read/write a .drawio file purely via Bash so the file never
enters the harness's Read/Edit tracking (avoids full-file context injections).

Usage:
  drawio_helper.py FILE sdiff SNAPSHOT       # SEMANTIC diff snapshot -> live: one compact line
                                             # per added/removed/changed cell, values decoded to
                                             # plain text. PREFER this over raw diff for reading.
  drawio_helper.py FILE diff SNAPSHOT        # raw unified diff (fallback, e.g. to debug XML)
  drawio_helper.py FILE snapshot DIR         # cp to DIR/<name>.NNN.drawio, prints path
  drawio_helper.py FILE insert               # stdin: mxCell XML -> inserted before </root>
  drawio_helper.py FILE replace-cell ID      # stdin: full new <mxCell .../> XML for ID
  drawio_helper.py FILE delete-cell ID       # remove cell with ID
  drawio_helper.py FILE get-cell ID          # print cell XML for ID
  drawio_helper.py FILE list-cells [PATTERN] # print "id<TAB>value-snippet" lines (PATTERN: substring of style or value, e.g. shape=cloud)

Scaffolded writes — PREFERRED: emit only text/coords, script builds the XML
(escaping, style presets, auto id). Fall back to raw insert/replace-cell only
when presets can't express what you need.
  drawio_helper.py FILE add-note --x X --y Y [--w 240] [--h H] [--color yellow] [--id ID]
                                             # stdin: plain text; **bold**, *italic*,
                                             # newline = line break, blank line = paragraph.
                                             # h auto-estimated from text if omitted. prints id.
  drawio_helper.py FILE add-box  ...         # same flags; square corners (schema/code boxes)
  drawio_helper.py FILE add-edge SRC DST [--label L] [--color yellow] [--no-arrow]
  drawio_helper.py FILE set-text ID          # stdin: new text (same markup); keeps style/geometry
  drawio_helper.py FILE recolor ID COLOR     # restyle fill/stroke of an existing cell
Colors: yellow (agent, default) | blue (acked) | plain.

Notes:
- Operates on raw text, not an XML parser, to preserve formatting exactly.
- A cell's block = its <mxCell ...> open tag through matching </mxCell>, or the
  single self-closing line. Relies on draw.io's stable 8-space indentation.
- insert/replace/delete write atomically (tmp file + os.replace).
"""
import html as html_mod
import os
import re
import subprocess
import sys


def die(msg):
    sys.stderr.write(msg + "\n")
    sys.exit(1)


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def write_atomic(path, text):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def cell_block_re(cell_id):
    # <mxCell id="ID" ...> ... </mxCell>  OR  self-closing <mxCell id="ID" ... />
    eid = re.escape(cell_id)
    return re.compile(
        r"[ \t]*<mxCell id=\"%s\"(?:[^>]*/>|.*?</mxCell>)[ \t]*\n" % eid,
        re.DOTALL,
    )


def find_cell(text, cell_id):
    m = cell_block_re(cell_id).search(text)
    if not m:
        die("cell not found: %s" % cell_id)
    return m


def parse_cells(text):
    """id -> {value, style, edge, geo, raw} for every cell except roots 0/1."""
    cells = {}
    for m in re.finditer(
        r'[ \t]*<mxCell id="([^"]+)"([^>]*?)(?:/>|>(.*?)</mxCell>)', text, re.DOTALL
    ):
        cid, attrs, inner = m.group(1), m.group(2), m.group(3) or ""
        if cid in ("0", "1"):
            continue
        v = re.search(r'value="([^"]*)"', attrs)
        s = re.search(r'style="([^"]*)"', attrs)
        geo = {}
        g = re.search(r"<mxGeometry([^>]*)", inner)
        if g:
            for k in ("x", "y", "width", "height"):
                gm = re.search(r'%s="([^"]+)"' % k, g.group(1))
                if gm:
                    geo[k] = gm.group(1)
        cells[cid] = {
            "value": v.group(1) if v else "",
            "style": s.group(1) if s else "",
            "edge": 'edge="1"' in attrs,
            "ends": "->".join(
            (re.search(r'%s="([^"]*)"' % k, attrs) or [None, "?"])[1]
            for k in ("source", "target")
        ),
            "geo": geo,
            "raw": m.group(0).strip("\n"),
        }
    return cells


def value_to_text(v):
    """reverse of text_to_value: attr-escaped html -> plain text, newlines as ' / '."""
    t = html_mod.unescape(v)  # attr layer
    t = re.sub(r"<br\s*/?>", "\n", t)
    t = re.sub(r"</?div[^>]*>\s*|</?p[^>]*>\s*", "\n", t)
    t = re.sub(r"<[^>]+>", "", t)
    t = html_mod.unescape(t)  # html layer
    return re.sub(r"\s*\n\s*", " / ", t).strip()


def cell_kind(c):
    s = c["style"]
    if c["edge"]:
        return "edge"
    for k in ("cloud", "swimlane", "image"):
        if k in s:
            return k
    return "text" if s.startswith("text;") else "box"


def style_color(style):
    f = re.search(r"fillColor=([^;]*)", style)
    k = re.search(r"strokeColor=([^;]*)", style)
    return (f.group(1) if f else "-", k.group(1) if k else "-")


def geo_str(geo):
    return "(%s,%s %sx%s)" % (
        geo.get("x", "?"), geo.get("y", "?"), geo.get("width", "?"), geo.get("height", "?"))


def sdiff(old_text, new_text):
    old, new = parse_cells(old_text), parse_cells(new_text)
    lines = []
    for cid in new:
        if cid not in old:
            c = new[cid]
            where = c["ends"] if c["edge"] else geo_str(c["geo"])
            lines.append("+ %s %s %s :: %s" % (cid, cell_kind(c), where, value_to_text(c["value"])))
    for cid in old:
        if cid not in new:
            c = old[cid]
            lines.append("- %s %s :: %.60s" % (cid, cell_kind(c), value_to_text(c["value"])))
    for cid, c in new.items():
        if cid not in old or old[cid]["raw"] == c["raw"]:
            continue
        o = old[cid]
        changes, unexplained = [], False
        if o["value"] != c["value"]:
            changes.append("text :: %s" % value_to_text(c["value"]))
        if o["geo"] != c["geo"]:
            changes.append("geom %s->%s" % (geo_str(o["geo"]), geo_str(c["geo"])))
        if o["style"] != c["style"]:
            oc, nc = style_color(o["style"]), style_color(c["style"])
            if oc != nc:
                changes.append("color %s->%s" % ("/".join(oc), "/".join(nc)))
            # style changed beyond colors?
            strip = lambda s: re.sub(r"(fill|stroke)Color=[^;]*;?", "", s)
            if strip(o["style"]) != strip(c["style"]):
                unexplained = True
        # attrs changed outside value/style/geo (e.g. edge endpoints)?
        norm = lambda cell: re.sub(r'(value|style)="[^"]*"|<mxGeometry[^>]*', "", cell["raw"])
        if norm(o) != norm(c):
            unexplained = True
        if unexplained:
            # detail fallback: this change is beyond the compact vocabulary
            lines.append("~ %s UNCLASSIFIED, full old/new:\nOLD: %s\nNEW: %s" % (cid, o["raw"], c["raw"]))
        elif changes:
            lines.append("~ %s %s" % (cid, " | ".join(changes)))
    print("\n".join(lines) if lines else "no cell changes")


COLORS = {  # (fill, stroke)
    "yellow": ("#FFF2CC", "#D6B656"),
    "blue": ("#DAE8FC", "#6C8EBF"),
    "plain": ("#FFFFFF", "#000000"),
}


def xml_attr_escape(s):
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def text_to_value(text):
    """markdown-lite -> draw.io html value, attribute-escaped.

    Two escape layers, matching draw.io's on-disk form (e.g. &amp;nbsp;):
    1. html layer: literal &,<,> in user text -> entities
    2. attr layer: the whole html (tags + entities) xml-escaped for value="..."
    """
    h = text.strip().replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    h = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", h)
    h = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"<i>\1</i>", h)
    paras = re.split(r"\n\s*\n", h)
    out = "<div><br></div>".join(
        "".join("<div>%s</div>" % ln for ln in p.split("\n")) for p in paras
    )
    return xml_attr_escape(out)


def est_height(text, width):
    chars_per_line = max(10, int(width / 6.5))
    lines = sum(
        max(1, -(-len(ln) // chars_per_line)) for ln in text.strip().split("\n")
    )
    return max(40, lines * 17 + 20)


def parse_flags(args, defaults):
    opts = dict(defaults)
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--no-arrow":
            opts["arrow"] = False
            i += 1
        elif a.startswith("--") and i + 1 < len(args):
            opts[a[2:]] = args[i + 1]
            i += 2
        else:
            die("bad flag: %s" % a)
    return opts


def auto_id(text):
    ns = [int(m) for m in re.findall(r'id="claude-(\d+)"', text)]
    return "claude-%d" % (max(ns, default=0) + 1)


def vertex_xml(cell_id, value, style, x, y, w, h):
    return (
        '        <mxCell id="%s" parent="1" style="%s" value="%s" vertex="1">\n'
        '          <mxGeometry height="%s" width="%s" x="%s" y="%s" as="geometry" />\n'
        "        </mxCell>" % (cell_id, style, value, h, w, x, y)
    )


def insert_before_root(path, text, xml):
    marker = "      </root>"
    if marker not in text:
        die("no </root> marker found")
    write_atomic(path, text.replace(marker, xml + "\n" + marker, 1))


def main():
    if len(sys.argv) < 3:
        die(__doc__)
    path, cmd = sys.argv[1], sys.argv[2]
    args = sys.argv[3:]

    if cmd == "diff":
        if not args:
            die("diff needs SNAPSHOT path")
        r = subprocess.run(["diff", args[0], path], text=True)
        sys.exit(0 if r.returncode in (0, 1) else r.returncode)

    if cmd == "sdiff":
        if not args:
            die("sdiff needs SNAPSHOT path")
        sdiff(read(args[0]), read(path))
        return

    if cmd == "snapshot":
        if not args:
            die("snapshot needs DIR")
        d = args[0]
        os.makedirs(d, exist_ok=True)
        base = os.path.splitext(os.path.basename(path))[0]
        ns = [
            int(m.group(1))
            for f in os.listdir(d)
            if (m := re.fullmatch(re.escape(base) + r"\.(\d{3})\.drawio", f))
        ]
        dest = os.path.join(d, "%s.%03d.drawio" % (base, max(ns, default=-1) + 1))
        write_atomic(dest, read(path))
        print(dest)
        return

    text = read(path)

    if cmd == "insert":
        xml = sys.stdin.read().rstrip("\n")
        if "<mxCell" not in xml:
            die("stdin had no <mxCell")
        marker = "      </root>"
        if marker not in text:
            die("no </root> marker found")
        write_atomic(path, text.replace(marker, xml + "\n" + marker, 1))
        print("inserted %d cell(s)" % xml.count("<mxCell"))
        return

    if cmd == "replace-cell":
        if not args:
            die("replace-cell needs ID")
        xml = sys.stdin.read().rstrip("\n")
        if "<mxCell" not in xml:
            die("stdin had no <mxCell")
        m = find_cell(text, args[0])
        write_atomic(path, text[: m.start()] + xml + "\n" + text[m.end() :])
        print("replaced %s" % args[0])
        return

    if cmd == "delete-cell":
        if not args:
            die("delete-cell needs ID")
        m = find_cell(text, args[0])
        write_atomic(path, text[: m.start()] + text[m.end() :])
        print("deleted %s" % args[0])
        return

    if cmd == "get-cell":
        if not args:
            die("get-cell needs ID")
        print(find_cell(text, args[0]).group(0).rstrip("\n"))
        return

    if cmd in ("add-note", "add-box"):
        o = parse_flags(args, {"w": "240", "h": None, "color": "yellow", "id": None, "x": None, "y": None})
        if o["x"] is None or o["y"] is None:
            die("%s needs --x and --y" % cmd)
        raw = sys.stdin.read()
        if not raw.strip():
            die("no text on stdin")
        fill, stroke = COLORS.get(o["color"]) or die("unknown color: %s" % o["color"])
        h = o["h"] or est_height(raw, int(o["w"]))
        cid = o["id"] or auto_id(text)
        style = "rounded=%d;whiteSpace=wrap;html=1;align=left;fillColor=%s;strokeColor=%s;" % (
            1 if cmd == "add-note" else 0, fill, stroke)
        insert_before_root(path, text, vertex_xml(cid, text_to_value(raw), style, o["x"], o["y"], o["w"], h))
        print(cid)
        return

    if cmd == "add-edge":
        if len(args) < 2:
            die("add-edge needs SRC DST")
        src, dst = args[0], args[1]
        o = parse_flags(args[2:], {"label": "", "color": "yellow", "id": None, "arrow": True})
        _, stroke = COLORS.get(o["color"]) or die("unknown color: %s" % o["color"])
        for c in (src, dst):
            find_cell(text, c)
        cid = o["id"] or auto_id(text)
        xml = (
            '        <mxCell id="%s" edge="1" parent="1" source="%s" target="%s" '
            'style="edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;endArrow=%s;endFill=%s;strokeColor=%s;" value="%s">\n'
            '          <mxGeometry relative="1" as="geometry" />\n'
            "        </mxCell>"
            % (cid, src, dst, "classic" if o["arrow"] else "none",
               1 if o["arrow"] else 0, stroke, text_to_value(o["label"]) if o["label"] else "")
        )
        insert_before_root(path, text, xml)
        print(cid)
        return

    if cmd == "set-text":
        if not args:
            die("set-text needs ID")
        raw = sys.stdin.read()
        m = find_cell(text, args[0])
        block = m.group(0)
        new_block, n = re.subn(r'value="[^"]*"', 'value="%s"' % text_to_value(raw), block, count=1)
        if not n:
            die("cell %s has no value attribute" % args[0])
        write_atomic(path, text[: m.start()] + new_block + text[m.end() :])
        print("set-text %s" % args[0])
        return

    if cmd == "recolor":
        if len(args) < 2:
            die("recolor needs ID COLOR")
        fill, stroke = COLORS.get(args[1]) or die("unknown color: %s" % args[1])
        m = find_cell(text, args[0])
        block = m.group(0)
        for attr, val in (("fillColor", fill), ("strokeColor", stroke)):
            if "%s=" % attr in block:
                block = re.sub(r"%s=[^;\"]*" % attr, "%s=%s" % (attr, val), block)
            else:
                block = block.replace('style="', 'style="%s=%s;' % (attr, val), 1)
        write_atomic(path, text[: m.start()] + block + text[m.end() :])
        print("recolored %s -> %s" % (args[0], args[1]))
        return

    if cmd == "list-cells":
        pat = args[0] if args else ""
        for m in re.finditer(r"<mxCell id=\"([^\"]+)\"([^>]*)>?", text):
            cell_id, attrs = m.group(1), m.group(2)
            if pat and pat not in attrs:
                continue
            v = re.search(r"value=\"([^\"]*)\"", attrs)
            snippet = re.sub(r"&[a-z]+;|<[^>]+>", " ", v.group(1))[:80] if v else ""
            print("%s\t%s" % (cell_id, snippet.strip()))
        return

    die("unknown command: %s\n\n%s" % (cmd, __doc__))


if __name__ == "__main__":
    main()
