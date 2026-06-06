#!/usr/bin/env python3
"""Thin draw.io file manipulator for drawio-chat sessions.

Lets an agent read/write a .drawio file purely via Bash so the file never
enters the harness's Read/Edit tracking (avoids full-file context injections).

Usage:
Versioning — own index (private git repo per diagram under ~/.cache/drawio-chat/<name>-<pathhash>/,
independent of any .git the diagram's directory may have; override root with $DRAWIO_VAULT):
  drawio_helper.py FILE snapshot [-m MSG]    # commit current state to vault (no-op if unchanged)
  drawio_helper.py FILE versions             # list versions: vN <rev> <date> <msg>
  drawio_helper.py FILE restore REF          # write version back to FILE (auto-snapshots live first)
  drawio_helper.py FILE import-dir DIR       # one-off: migrate legacy .NNN.drawio copies into vault
REF = vN | git rev | HEAD~k. Legacy mode kept: `snapshot DIR` copies to DIR/<name>.NNN.drawio.

  drawio_helper.py FILE sdiff [REF|PATH]     # SEMANTIC diff version -> live (default HEAD): one
                                             # compact line per added/removed/changed cell, values
                                             # decoded to plain text. PREFER this for reading.
  drawio_helper.py FILE diff [REF|PATH]      # raw unified diff (fallback, e.g. to debug XML)
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


VAULT_ROOT = os.environ.get(
    "DRAWIO_VAULT", os.path.expanduser("~/.cache/drawio-chat")
)


def vault_dir(path):
    import hashlib

    ap = os.path.abspath(path)
    slug = "%s-%s" % (
        os.path.splitext(os.path.basename(ap))[0],
        hashlib.sha1(ap.encode()).hexdigest()[:8],
    )
    return os.path.join(VAULT_ROOT, slug)


def git(vd, *a):
    return subprocess.run(["git", "-C", vd] + list(a), text=True, capture_output=True)


GIT_ID = ["-c", "user.name=drawio-helper", "-c", "user.email=drawio-helper@local"]


def ensure_vault(path):
    vd = vault_dir(path)
    if not os.path.isdir(os.path.join(vd, ".git")):
        os.makedirs(vd, exist_ok=True)
        r = git(vd, "init", "-q")
        if r.returncode != 0:
            die("git init failed: %s" % r.stderr)
    return vd


def resolve_ref(vd, ref):
    """vN -> git rev; anything else passes through."""
    m = re.fullmatch(r"v(\d+)", ref)
    if not m:
        return ref
    total = git(vd, "rev-list", "--count", "HEAD").stdout.strip()
    if not total.isdigit() or int(m.group(1)) > int(total) or int(m.group(1)) < 1:
        die("no such version %s (have v1..v%s)" % (ref, total or 0))
    return "HEAD~%d" % (int(total) - int(m.group(1)))


def vault_show(path, ref):
    vd = vault_dir(path)
    r = git(vd, "show", "%s:%s" % (resolve_ref(vd, ref), os.path.basename(path)))
    if r.returncode != 0:
        die("cannot read version %s: %s" % (ref, r.stderr.strip()))
    return r.stdout


def vault_commit(path, msg):
    """Returns 'vN <rev>' or None if nothing changed."""
    vd = ensure_vault(path)
    name = os.path.basename(path)
    write_atomic(os.path.join(vd, name), read(path))
    git(vd, "add", name)
    r = git(vd, *GIT_ID, "commit", "-q", "-m", msg)
    if r.returncode != 0:
        if "nothing to commit" in r.stdout + r.stderr:
            return None
        die("commit failed: %s%s" % (r.stdout, r.stderr))
    n = git(vd, "rev-list", "--count", "HEAD").stdout.strip()
    rev = git(vd, "rev-parse", "--short", "HEAD").stdout.strip()
    return "v%s %s" % (n, rev)


def old_content(path, args):
    """For diff/sdiff: arg may be a legacy snapshot file path or a vault REF."""
    ref = args[0] if args else "HEAD"
    return read(ref) if os.path.exists(ref) else vault_show(path, ref)


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
    t = html_mod.unescape(t).strip()  # html layer
    return re.sub(r"\s*\n\s*", " / ", t)


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
        import tempfile

        with tempfile.NamedTemporaryFile("w", suffix=".drawio", delete=False) as tf:
            tf.write(old_content(path, args))
        r = subprocess.run(["diff", tf.name, path], text=True)
        os.unlink(tf.name)
        sys.exit(0 if r.returncode in (0, 1) else r.returncode)

    if cmd == "sdiff":
        sdiff(old_content(path, args), read(path))
        return

    if cmd == "snapshot":
        if args and not args[0].startswith("-"):  # legacy: snapshot DIR
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
        msg = args[args.index("-m") + 1] if "-m" in args else "snapshot"
        print(vault_commit(path, msg) or "no changes since last snapshot")
        return

    if cmd == "versions":
        vd = vault_dir(path)
        log = git(vd, "log", "--format=%h\t%ad\t%s", "--date=format:%m-%d %H:%M")
        if log.returncode != 0:
            die("no vault yet for %s (run snapshot first)" % path)
        entries = log.stdout.strip().split("\n")
        total = len(entries)
        for i, e in enumerate(entries):
            print("v%d\t%s" % (total - i, e))
        print("vault: %s" % vd)
        return

    if cmd == "restore":
        if not args:
            die("restore needs REF (vN | rev | HEAD~k)")
        content = vault_show(path, args[0])
        pre = vault_commit(path, "pre-restore auto-snapshot")
        write_atomic(path, content)
        print("restored %s -> %s%s" % (args[0], path,
              " (live state saved as %s)" % pre if pre else ""))
        return

    if cmd == "import-dir":
        if not args:
            die("import-dir needs DIR of legacy .NNN.drawio copies")
        base = os.path.splitext(os.path.basename(path))[0]
        files = sorted(
            f for f in os.listdir(args[0])
            if re.fullmatch(re.escape(base) + r"\.\d{3}\.drawio", f)
        )
        if not files:
            die("no %s.NNN.drawio files in %s" % (base, args[0]))
        vd = ensure_vault(path)
        name = os.path.basename(path)
        n = 0
        for f in files:
            write_atomic(os.path.join(vd, name), read(os.path.join(args[0], f)))
            git(vd, "add", name)
            if git(vd, *GIT_ID, "commit", "-q", "-m", "import %s" % f).returncode == 0:
                n += 1
        print("imported %d/%d (skipped no-change duplicates), vault: %s" % (n, len(files), vd))
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
