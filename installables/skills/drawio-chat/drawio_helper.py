#!/usr/bin/env python3
"""Thin draw.io file manipulator for drawio-chat sessions.

Lets an agent read/write a .drawio file purely via Bash so the file never
enters the harness's Read/Edit tracking (avoids full-file context injections).

Usage:
Versioning — own index (private git repo per diagram under ~/.cache/drawio-chat/<name>-<pathhash>/,
independent of any .git the diagram's directory may have; override root with $DRAWIO_VAULT):
  drawio_helper.py FILE snapshot [-m MSG]    # commit current state to vault (no-op if unchanged);
                                             # also commits <name>.code.md (mother spec) if present
  drawio_helper.py FILE versions             # list versions: vN <rev> <date> <msg>
  drawio_helper.py FILE restore REF          # write version back to FILE (auto-snapshots live first)
  drawio_helper.py FILE import-dir DIR       # one-off: migrate legacy .NNN.drawio copies into vault
  drawio_helper.py FILE sync-status          # clean | diag-newer | md-newer | both-changed
  drawio_helper.py FILE code-md-path         # print path of <name>.code.md (the durable mother spec)
REF = vN | git rev | HEAD~k. Legacy mode kept: `snapshot DIR` copies to DIR/<name>.NNN.drawio.

Pages — multi-page .drawio files have one <diagram> per page. `--page N` (index, default
0) or `--page name=Foo` targets a page on every write/inspect command; `--page all` widens
list-cells/get-cell to the whole file. Legacy single-page files keep working with no --page.
  drawio_helper.py FILE pages                # list  idx <TAB> name <TAB> id <TAB> cell-count
  drawio_helper.py FILE add-page NAME        # append a new empty page; prints its index

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
    """Returns 'vN <rev>' or None if nothing changed.

    Commits the live .drawio and, if present, the mother spec <name>.code.md
    as ONE joint version so the diagram and its spec stay in lockstep."""
    vd = ensure_vault(path)
    name = os.path.basename(path)
    write_atomic(os.path.join(vd, name), read(path))
    git(vd, "add", name)
    mdp = code_md_path(path)
    if os.path.exists(mdp):
        git(vd, "add", os.path.basename(mdp))
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


# ---- multi-page support -------------------------------------------------
# A draw.io file holds one <diagram name=.. id=..><mxGraphModel><root>..</root>
# </mxGraphModel></diagram> per page. We operate within a single page's body.
# Legacy files with no <diagram> wrapper are treated as a single page 0.


def split_diagrams(text):
    """Ordered list of page dicts. Empty if the file has no <diagram> wrapper."""
    res = []
    for m in re.finditer(r"<diagram\b([^>]*)>(.*?)</diagram>", text, re.DOTALL):
        attrs = m.group(1)
        nm = re.search(r'name="([^"]*)"', attrs)
        did = re.search(r'id="([^"]*)"', attrs)
        res.append({
            "name": nm.group(1) if nm else "",
            "id": did.group(1) if did else "",
            "inner": m.group(2),
            "start": m.start(2),
            "end": m.end(2),
        })
    return res


def resolve_page_index(diags, page):
    """page: int-like string, or 'name=Foo'. Returns 0-based index."""
    if isinstance(page, str) and page.startswith("name="):
        nm = page[5:]
        for i, d in enumerate(diags):
            if d["name"] == nm:
                return i
        die("no page named %r (have: %s)" % (nm, ", ".join(d["name"] for d in diags)))
    try:
        idx = int(page)
    except (TypeError, ValueError):
        die("bad --page %r (use an index or name=Foo)" % page)
    if idx < 0 or idx >= len(diags):
        die("page index %d out of range (have 0..%d)" % (idx, len(diags) - 1))
    return idx


def page_span(text, page):
    """Return (body_text, abs_start, abs_end) for the chosen page.

    page='all' (or a legacy file with no pages) -> whole text.
    Legacy file + a specific non-zero page -> error."""
    diags = split_diagrams(text)
    if page == "all":
        return text, 0, len(text)
    if not diags:
        if page not in (None, "0", 0):
            die("file has no pages (legacy single-page); only page 0 is valid")
        return text, 0, len(text)
    idx = resolve_page_index(diags, page if page is not None else "0")
    d = diags[idx]
    return d["inner"], d["start"], d["end"]


def pop_page(args):
    """Strip a `--page VALUE` flag from positional args. Returns (value|None, rest)."""
    page, out, i = None, [], 0
    while i < len(args):
        if args[i] == "--page" and i + 1 < len(args):
            page, i = args[i + 1], i + 2
        else:
            out.append(args[i])
            i += 1
    return page, out


def new_diagram_id():
    import uuid

    return uuid.uuid4().hex[:20]


# ---- joint md + diagram versioning --------------------------------------


def code_md_path(path):
    """The mother spec lives in the vault, versioned alongside the .drawio."""
    base = os.path.splitext(os.path.basename(path))[0]
    return os.path.join(vault_dir(path), base + ".code.md")


def sync_status(path):
    """clean | diag-newer | md-newer | both-changed (or a no-vault note)."""
    vd = vault_dir(path)
    if not os.path.isdir(os.path.join(vd, ".git")):
        print("no-vault (run snapshot first)")
        return
    if git(vd, "rev-parse", "--verify", "HEAD").returncode != 0:
        print("no-snapshots (run snapshot first)")
        return
    name = os.path.basename(path)
    committed_diag = git(vd, "show", "HEAD:%s" % name)
    diag_dirty = committed_diag.returncode != 0 or read(path) != committed_diag.stdout

    mdp = code_md_path(path)
    committed_md = git(vd, "show", "HEAD:%s" % os.path.basename(mdp))
    has_committed_md = committed_md.returncode == 0
    working_md_exists = os.path.exists(mdp)
    if not has_committed_md and not working_md_exists:
        md_dirty = False
    elif has_committed_md and working_md_exists:
        md_dirty = read(mdp) != committed_md.stdout
    else:
        md_dirty = True  # exists on exactly one side

    status = {
        (False, False): "clean",
        (True, False): "diag-newer",
        (False, True): "md-newer",
        (True, True): "both-changed",
    }[(diag_dirty, md_dirty)]
    print(status)


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
    """id -> {value, style, edge, geo, raw, page} for every cell except roots 0/1.

    `page` is the 0-based diagram index the cell lives in (0 for legacy files)."""
    cells = {}
    diags = split_diagrams(text)
    regions = [(i, d["inner"]) for i, d in enumerate(diags)] or [(0, text)]
    for pidx, body in regions:
        for m in re.finditer(
            r'[ \t]*<mxCell id="([^"]+)"([^>]*?)(?:/>|>(.*?)</mxCell>)', body, re.DOTALL
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
                "page": pidx,
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
    multipage = max(
        [len(split_diagrams(old_text)), len(split_diagrams(new_text))]
    ) > 1
    tag = lambda c: ("[p%d] " % c["page"]) if multipage else ""
    lines = []
    for cid in new:
        if cid not in old:
            c = new[cid]
            where = c["ends"] if c["edge"] else geo_str(c["geo"])
            lines.append("+ %s%s %s %s :: %s" % (tag(c), cid, cell_kind(c), where, value_to_text(c["value"])))
    for cid in old:
        if cid not in new:
            c = old[cid]
            lines.append("- %s%s %s :: %.60s" % (tag(c), cid, cell_kind(c), value_to_text(c["value"])))
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
            lines.append("~ %s%s UNCLASSIFIED, full old/new:\nOLD: %s\nNEW: %s" % (tag(c), cid, o["raw"], c["raw"]))
        elif changes:
            lines.append("~ %s%s %s" % (tag(c), cid, " | ".join(changes)))
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


def _esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _nbsp_text_nodes(html_line):
    """spaces -> &nbsp; in text nodes only (keeps spaces inside tags/attrs)."""
    parts = re.split(r"(<[^>]+>)", html_line)
    return "".join(p if p.startswith("<") else p.replace(" ", "&nbsp;") for p in parts)


def _code_block_html(code, lang):
    """fenced code -> mono grey block; pygments inline-styled spans if lang known."""
    body = None
    if lang:
        try:
            from pygments import highlight
            from pygments.lexers import get_lexer_by_name
            from pygments.formatters import HtmlFormatter

            body = highlight(
                code, get_lexer_by_name(lang), HtmlFormatter(noclasses=True, nowrap=True)
            )
        except Exception:
            body = None
    if body is None:
        body = _esc(code)
    lines = body.rstrip("\n").split("\n")
    return (
        '<div style="background-color:#F8F8F8;font-family:Courier New,monospace;'
        'font-size:11px;padding:4px;text-align:left;">%s</div>'
        % "".join("<div>%s</div>" % (_nbsp_text_nodes(ln) or "<br>") for ln in lines)
    )


def text_to_value(text):
    """markdown -> draw.io html value, attribute-escaped.

    Supports **bold**, *italic*, `code`, ```lang fenced blocks (pygments
    syntax colors), # / ## / ### headings, - and 1. lists; newline = line
    break, blank line = paragraph.

    Two escape layers, matching draw.io's on-disk form (e.g. &amp;nbsp;):
    1. html layer: literal &,<,> in user text -> entities
    2. attr layer: the whole html (tags + entities) xml-escaped for value="..."
    """
    tokens = {}

    def stash(html):  # protect pre-built html from escaping/markdown passes
        key = "\x00%d\x00" % len(tokens)
        tokens[key] = html
        return key

    t = text.strip()
    t = re.sub(
        r"```([\w+-]*)[ \t]*\n(.*?)\n?```",
        lambda m: stash(_code_block_html(m.group(2), m.group(1))),
        t,
        flags=re.S,
    )
    t = re.sub(
        r"`([^`\n]+)`",
        lambda m: stash(
            '<font face="Courier New" style="background-color:#F0F0F0;">%s</font>'
            % _esc(m.group(1))
        ),
        t,
    )
    h = _esc(t)
    h = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", h)
    h = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"<i>\1</i>", h)

    hsize = {1: 17, 2: 14, 3: 12}
    out, list_tag = [], [None]

    def close_list():
        if list_tag[0]:
            out.append("</%s>" % list_tag[0])
            list_tag[0] = None

    for ln in (l.rstrip() for l in h.split("\n")):
        m_h = re.match(r"(#{1,3})\s+(.*)", ln)
        m_li = re.match(r"-\s+(.*)", ln)
        m_ol = re.match(r"\d+[.)]\s+(.*)", ln)
        if m_h:
            close_list()
            out.append(
                '<div style="font-size:%dpx;"><b>%s</b></div>'
                % (hsize[len(m_h.group(1))], m_h.group(2))
            )
        elif m_li or m_ol:
            tag = "ul" if m_li else "ol"
            if list_tag[0] != tag:
                close_list()
                out.append('<%s style="margin:0;padding-left:18px;">' % tag)
                list_tag[0] = tag
            out.append("<li>%s</li>" % (m_li or m_ol).group(1))
        elif not ln:
            close_list()
            out.append("<div><br></div>")
        else:
            close_list()
            out.append("<div>%s</div>" % ln)
    close_list()

    res = "".join(out)
    for key, html in tokens.items():
        res = res.replace(key, html)
    return xml_attr_escape(res)


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


def insert_before_root(path, text, xml, page="0"):
    marker = "      </root>"
    body, s, e = page_span(text, page)
    if marker not in body:
        die("no </root> marker found on page %s" % page)
    new_body = body.replace(marker, xml + "\n" + marker, 1)
    write_atomic(path, text[:s] + new_body + text[e:])


def edit_cell_in_page(path, text, page, cell_id, transform):
    """Find cell_id within `page`, replace its block with transform(block).

    transform returns the replacement text ('' deletes the cell)."""
    body, s, e = page_span(text, page)
    m = find_cell(body, cell_id)
    new_block = transform(m.group(0))
    new_body = body[: m.start()] + new_block + body[m.end() :]
    write_atomic(path, text[:s] + new_body + text[e:])


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

    if cmd == "sync-status":
        sync_status(path)
        return

    if cmd == "code-md-path":
        # where the mother spec lives (track this one with Read/Write, it is durable)
        print(code_md_path(path))
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

    if cmd == "pages":
        diags = split_diagrams(text)
        cells = parse_cells(text)
        if not diags:
            print("0\t(legacy single-page)\t-\t%d cells" % len(cells))
            return
        counts = {i: 0 for i in range(len(diags))}
        for c in cells.values():
            counts[c["page"]] += 1
        for i, d in enumerate(diags):
            print("%d\t%s\t%s\t%d cells" % (i, d["name"] or "-", d["id"] or "-", counts[i]))
        return

    if cmd == "add-page":
        if not args:
            die("add-page needs NAME")
        name = args[0]
        if "</mxfile>" not in text:
            die("no </mxfile> marker (cannot add a page to a bare-mxGraphModel file)")
        new_idx = len(split_diagrams(text))
        block = (
            '  <diagram id="%s" name="%s">\n'
            '    <mxGraphModel dx="800" dy="600" grid="1" gridSize="10" guides="1" '
            'tooltips="1" connect="1" arrows="1" fold="1" page="1" pageScale="1" '
            'pageWidth="850" pageHeight="1100" math="0" shadow="0">\n'
            "      <root>\n"
            '        <mxCell id="0" />\n'
            '        <mxCell id="1" parent="0" />\n'
            "      </root>\n"
            "    </mxGraphModel>\n"
            "  </diagram>\n" % (new_diagram_id(), xml_attr_escape(name))
        )
        write_atomic(path, text.replace("</mxfile>", block + "</mxfile>", 1))
        print("added page %d: %s" % (new_idx, name))
        return

    if cmd == "insert":
        page, _ = pop_page(args)
        xml = sys.stdin.read().rstrip("\n")
        if "<mxCell" not in xml:
            die("stdin had no <mxCell")
        insert_before_root(path, text, xml, page or "0")
        print("inserted %d cell(s)" % xml.count("<mxCell"))
        return

    if cmd == "replace-cell":
        page, rest = pop_page(args)
        if not rest:
            die("replace-cell needs ID")
        xml = sys.stdin.read().rstrip("\n")
        if "<mxCell" not in xml:
            die("stdin had no <mxCell")
        edit_cell_in_page(path, text, page or "0", rest[0], lambda _block: xml + "\n")
        print("replaced %s" % rest[0])
        return

    if cmd == "delete-cell":
        page, rest = pop_page(args)
        if not rest:
            die("delete-cell needs ID")
        edit_cell_in_page(path, text, page or "0", rest[0], lambda _block: "")
        print("deleted %s" % rest[0])
        return

    if cmd == "get-cell":
        page, rest = pop_page(args)
        if not rest:
            die("get-cell needs ID")
        # id is unique -> search all pages by default; --page just narrows
        body, _, _ = page_span(text, page or "all")
        print(find_cell(body, rest[0]).group(0).rstrip("\n"))
        return

    if cmd in ("add-note", "add-box"):
        o = parse_flags(args, {"w": "240", "h": None, "color": "yellow", "id": None,
                               "x": None, "y": None, "page": "0"})
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
        insert_before_root(path, text,
                           vertex_xml(cid, text_to_value(raw), style, o["x"], o["y"], o["w"], h),
                           o["page"])
        print(cid)
        return

    if cmd == "add-edge":
        page, rest = pop_page(args)
        if len(rest) < 2:
            die("add-edge needs SRC DST")
        src, dst = rest[0], rest[1]
        o = parse_flags(rest[2:], {"label": "", "color": "yellow", "id": None, "arrow": True})
        _, stroke = COLORS.get(o["color"]) or die("unknown color: %s" % o["color"])
        body, _, _ = page_span(text, page or "0")
        for c in (src, dst):
            find_cell(body, c)  # both endpoints must live on the same page
        cid = o["id"] or auto_id(text)
        xml = (
            '        <mxCell id="%s" edge="1" parent="1" source="%s" target="%s" '
            'style="edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;endArrow=%s;endFill=%s;strokeColor=%s;" value="%s">\n'
            '          <mxGeometry relative="1" as="geometry" />\n'
            "        </mxCell>"
            % (cid, src, dst, "classic" if o["arrow"] else "none",
               1 if o["arrow"] else 0, stroke, text_to_value(o["label"]) if o["label"] else "")
        )
        insert_before_root(path, text, xml, page or "0")
        print(cid)
        return

    if cmd == "set-text":
        page, rest = pop_page(args)
        if not rest:
            die("set-text needs ID")
        raw = sys.stdin.read()

        def _retext(block):
            new_block, n = re.subn(r'value="[^"]*"', 'value="%s"' % text_to_value(raw), block, count=1)
            if not n:
                die("cell %s has no value attribute" % rest[0])
            return new_block

        edit_cell_in_page(path, text, page or "0", rest[0], _retext)
        print("set-text %s" % rest[0])
        return

    if cmd == "recolor":
        page, rest = pop_page(args)
        if len(rest) < 2:
            die("recolor needs ID COLOR")
        fill, stroke = COLORS.get(rest[1]) or die("unknown color: %s" % rest[1])

        def _recolor(block):
            for attr, val in (("fillColor", fill), ("strokeColor", stroke)):
                if "%s=" % attr in block:
                    block = re.sub(r"%s=[^;\"]*" % attr, "%s=%s" % (attr, val), block)
                else:
                    block = block.replace('style="', 'style="%s=%s;' % (attr, val), 1)
            return block

        edit_cell_in_page(path, text, page or "0", rest[0], _recolor)
        print("recolored %s -> %s" % (rest[0], rest[1]))
        return

    if cmd == "list-cells":
        page, rest = pop_page(args)
        pat = rest[0] if rest else ""
        body, _, _ = page_span(text, page or "0")
        for m in re.finditer(r"<mxCell id=\"([^\"]+)\"([^>]*)>?", body):
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
