#!/usr/bin/env python3
"""
rbx2vrtx.py - convert parts exported from Roblox Studio (JSON) into a Vortex Studio .vrtx

Usage:
    pip install zstandard
    python rbx2vrtx.py Place1.rbxlx out.vrtx --template project26.vrtx [--scale 1.0] [--new-id]
    python rbx2vrtx.py parts.json  out.vrtx --template project26.vrtx   (JSON from ExportParts.lua)
    python rbx2vrtx.py --dump some.vrtx            # print the parts inside a .vrtx

How it works (reverse-engineered from your saves, format version 5):
    file    = b"VRTX" + version byte + zstd( body )
    body    = 0x01 | u64 len + 32-char project id | u64 entryCount | entries... | tail
    entry   = u32 class | str name | u64 1 | 0x00 0x01 | str name | payload
    str     = u64 length + utf8 bytes
    payload (for a plain Part, 118 bytes):
              pos xyz (3f) | rotation quaternion xyzw (4f) | size xyz (3f) |
              color rgb (3f) | alpha (f) | flag/unknown bytes (62 bytes)
Everything we do not understand yet (flags, tail, services) is copied from the template
save, so it stays valid.
"""
import argparse, json, os, re, struct, sys
import zstandard as zstd

# Built-in template (a blank Vortex save), so no --template file is needed.
TEMPLATE_B64 = (
    "VlJUWAUotS/9AFgNEQBGVlZDIFGcMbmANQH0XkOAOnTZHn1iLV+IpH2uTRIGht1C3SBLFe2Fsya9"
    "6aHK2KCtfJMiO2S78X3OYNXWKQcOIYQMAejLFEMAPABEAJ6A/yKdq8XtbfC+YOjJuEGA/yDvfMIt"
    "oRNqrv/zGLwZNEGLDz5eILtoF85nyb7Kl30aiCDDcDAaZgNWLpZbyTjasRmSzznnf44AicM2GpFo"
    "6udIu/q5/1bGP+dHDPcFRc2Hws3eyH/JQRaup9N467u9yf+QcNTY2znUoKfxqHEVwIUWJrraUEND"
    "pRFoqKjJXjNqV2N8nk4iNhQKhYVQP2L2xb/17Tz+Szrm/FYqdUiQWTYyoZ+Sfyb0c+RTeF9PxqBr"
    "AxwDUWbbnMixrWB4WOHihoO5AAcXarUUqCAxdDaDyF6VYkfYEilKElVRcllhAMVi5VgxVmmp6TSF"
    "/QemAY78ZaKyqCHqVR/IPCFhQQRsoJFYUaZEmqRQWNYwA5pJ0wFrACK/mmcGHNXNnzElYfeDYX49"
    "recgnbjyyaISsT14yMeZ5jVMadocgcSSlX5ozoSx9DjT/QamlJtzeMx8hkpzS8+aiVgpGXQCKyGD"
    "SsQmZFAJ2L2sKRXs92lipz/XmshQSK3aKxlc0HrXlzkVHr55Q5gB3Haf6hF4bOKTE+49pmg1CN/G"
    "SOCjg4JYaSMkad2Q+B8pT+iaBTvOTfxm+x76l+0g63/NNnz6y3bqnEzrrob1BA=="
)

MAGIC = b"VRTX"
N_BUILTIN = 7          # Workspace, Lighting, ReplicatedStorage, ServerScriptService,
                       # StarterPlayerScripts, SpawnLocation, Baseplate
ENTRY_COUNT_OFF = 1 + 8 + 32

# Shape lives in the 62-byte tail of a part entry (decoded from a Vortex test save):
#   tail[22] = 0 Block, 1 Wedge, 2 CornerWedge, 3 Cylinder, 4 Ball      tail[11] = 1 -> Truss
# Entry class ids (first u32 of every entry), decoded from Vortex saves
CLASS_PART, CLASS_MODEL, CLASS_SCRIPT, CLASS_MODULE = 2, 3, 8, 9

# Built-in entries of a Vortex save, in file order. A child's "parent" number is its parent's position in this list.
SVC_WORKSPACE, SVC_LIGHTING, SVC_REPLICATED, SVC_SERVER_SCRIPTS, SVC_PLAYER_SCRIPTS = 0, 1, 2, 3, 4
SVC_NAMES = {0: "Workspace", 1: "Lighting", 2: "ReplicatedStorage", 3: "ServerScriptService", 4: "StarterPlayerScripts"}
# Roblox services that have no home in a Vortex save (scripts there are reported, not imported)
UNMAPPED_SERVICES = ("StarterGui", "StarterPack", "ServerStorage", "ReplicatedFirst", "Teams", "SoundService", "Chat", "Lighting")

SHAPE_CODE = {"Block": 0, "Wedge": 1, "CornerWedge": 2, "Cylinder": 3, "Ball": 4}


def read_vrtx(path):
    if path is None:
        import base64
        d = base64.b64decode("".join(TEMPLATE_B64))
    else:
        d = open(path, "rb").read()
    assert d[:4] == MAGIC, "not a .vrtx file"
    return d[4], zstd.ZstdDecompressor().decompressobj().decompress(d[5:])


def write_vrtx(path, version, body):
    comp = zstd.ZstdCompressor(level=3).compress(body)
    open(path, "wb").write(MAGIC + bytes([version]) + comp)


def pstr(s):
    s = s.encode("utf8")
    return struct.pack("<Q", len(s)) + s


def split_template(body):
    """Return (prefix_incl_builtins, part_template_bytes, tail) from a template body."""
    # find first generic "Part" entry: class u32=2 followed by str "Part"
    m = re.search(rb"\x02\x00\x00\x00\x04\x00\x00\x00\x00\x00\x00\x00Part", body)
    if not m:
        sys.exit("template has no plain 'Part' in it - add one part in Vortex and save")
    start = m.start()
    entry_len = 156  # for a 4-char name; see layout above
    first = body[start:start + entry_len]
    # payload tail (62 bytes of flags etc) = last 62 bytes of a part entry
    flags = first[-62:]
    # find where the part run ends: keep reading entries of identical size
    end = start
    while body[end:end + 4] == b"\x02\x00\x00\x00" and body[end + 12:end + 16] == b"Part":
        end += entry_len
    return body[:start], flags, body[end:], (end - start) // entry_len


def build_part(name, pos, quat, size, rgb, alpha, flags, shape="Block", parent=0):
    flags = bytearray(flags)
    if shape == "Truss":
        flags[11] = 1
    else:
        flags[22] = SHAPE_CODE.get(shape, 0)
    flags = bytes(flags)
    return (struct.pack("<I", CLASS_PART) + pstr(name) + b"\x01" + struct.pack("<Q", parent) + b"\x01" + pstr(name)
            + struct.pack("<14f", *pos, *quat, *size, *rgb, alpha) + flags)


def build_model(name, parent=0):
    """A Model/Folder-like container: class 3, then [01][parent][13 zero bytes]."""
    return struct.pack("<I", CLASS_MODEL) + pstr(name) + b"\x01" + struct.pack("<Q", parent) + b"\x00" * 13


def build_script(name, source, parent=0, module=False):
    """Script (class 8) or ModuleScript (class 9). Source is stored as plain text."""
    return (struct.pack("<I", CLASS_MODULE if module else CLASS_SCRIPT) + pstr(name)
            + b"\x01" + struct.pack("<Q", parent) + b"\x00\x00\x00\x01"
            + pstr(source) + b"\x01" + b"\x00" * 9)


def parse_parts(body):
    out = []
    for m in re.finditer(rb"\x02\x00\x00\x00(.{8})", body, re.S):
        n = struct.unpack("<Q", m.group(1))[0]
        if n > 64:
            continue
        p = m.end()
        name = body[p:p + n].decode("utf8", "replace")
        q = p + n + 10
        if q + 8 > len(body):
            continue
        if body[p + n:p + n + 1] != b"\x01":
            continue
        n2 = struct.unpack("<Q", body[q:q + 8])[0]
        f = struct.unpack_from("<14f", body, q + 8 + n2)
        tl = body[q + 8 + n2 + 56:q + 8 + n2 + 56 + 62]
        inv = {v: k for k, v in SHAPE_CODE.items()}
        shape = "Truss" if len(tl) > 22 and tl[11] == 1 else inv.get(tl[22] if len(tl) > 22 else 0, "?")
        out.append(dict(name=name, shape=shape, pos=f[0:3], quat=f[3:7], size=f[7:10], rgb=f[10:13], alpha=f[13]))
    return out


def _quat_from_matrix(m):
    """3x3 rotation matrix (row-major list of 9) -> quaternion x,y,z,w"""
    r00, r01, r02, r10, r11, r12, r20, r21, r22 = m
    tr = r00 + r11 + r22
    if tr > 0:
        s = (tr + 1.0) ** 0.5 * 2
        return [(r21 - r12) / s, (r02 - r20) / s, (r10 - r01) / s, 0.25 * s]
    if r00 > r11 and r00 > r22:
        s = (1.0 + r00 - r11 - r22) ** 0.5 * 2
        return [0.25 * s, (r01 + r10) / s, (r02 + r20) / s, (r21 - r12) / s]
    if r11 > r22:
        s = (1.0 + r11 - r00 - r22) ** 0.5 * 2
        return [(r01 + r10) / s, 0.25 * s, (r12 + r21) / s, (r02 - r20) / s]
    s = (1.0 + r22 - r00 - r11) ** 0.5 * 2
    return [(r02 + r20) / s, (r12 + r21) / s, 0.25 * s, (r10 - r01) / s]


def load_rbxlx(path, include_baseplate=False):
    """Read parts from a Roblox .rbxlx (XML) place file. Only Workspace is scanned."""
    import xml.etree.ElementTree as ET
    root = ET.parse(path).getroot()
    ws = root.find("Item[@class='Workspace']")
    out = []
    parent_of = {c: p for p in ws.iter("Item") for c in p.findall("Item")}
    def _name(e):
        n = e.find("Properties/string[@name='Name']")
        return n.text if n is not None else e.get("class")
    SHAPES = {"0": "Ball", "1": "Block", "2": "Cylinder"}
    CLASS_SHAPE = {"WedgePart": "Wedge", "CornerWedgePart": "CornerWedge", "TrussPart": "Truss"}
    for it in ws.iter("Item"):
        cls = it.get("class")
        if cls not in ("Part", "MeshPart", "WedgePart", "CornerWedgePart", "TrussPart", "SpawnLocation", "UnionOperation"):
            continue
        pr = it.find("Properties")
        g = lambda n: pr.find(f"*[@name='{n}']")
        name = g("Name").text if g("Name") is not None else cls
        if name == "Baseplate" and not include_baseplate:
            continue
        cf = {c.tag: float(c.text) for c in g("CFrame")}
        size = g("size") if g("size") is not None else g("Size")
        size = [float(size.find(a).text) for a in "XYZ"]
        c3 = g("Color3uint8")
        if c3 is not None:
            v = int(c3.text)
            rgb = [((v >> 16) & 255) / 255, ((v >> 8) & 255) / 255, (v & 255) / 255]
        else:
            c3 = g("Color3")
            rgb = [float(c3.find(a).text) for a in "RGB"] if c3 is not None else [0.64, 0.64, 0.65]
        tr = g("Transparency")
        sh = g("shape") if g("shape") is not None else g("Shape")
        path, p = [], parent_of.get(it)
        while p is not None and p is not ws:
            path.append(_name(p)); p = parent_of.get(p)
        out.append(dict(
            shape=(CLASS_SHAPE.get(cls) or (SHAPES.get(sh.text, "Block") if sh is not None else "Block")),
            path=path[::-1],
            name=name,
            position=[cf["X"], cf["Y"], cf["Z"]],
            rotation=_quat_from_matrix([cf[k] for k in ("R00", "R01", "R02", "R10", "R11", "R12", "R20", "R21", "R22")]),
            size=size, color=rgb,
            transparency=float(tr.text) if tr is not None else 0.0,
        ))
    return out


def desktop_dir():
    """The user's real Desktop folder (handles OneDrive-redirected desktops on Windows)."""
    try:
        if os.name == "nt":
            import ctypes
            buf = ctypes.create_unicode_buffer(260)
            # CSIDL_DESKTOPDIRECTORY = 0x10
            if ctypes.windll.shell32.SHGetFolderPathW(None, 0x10, None, 0, buf) == 0 and buf.value:
                return buf.value
    except Exception:
        pass
    d = os.path.join(os.path.expanduser("~"), "Desktop")
    return d if os.path.isdir(d) else None


# ---- Luau compatibility fixes for old Roblox scripts -------------------------------------------
# Based on errors seen when running the haunted house in Vortex. Each rule is (name, regex, replacement).
import re as _re
LUAU_FIXES = [
    # Players.ChildAdded is nil in Vortex -> use the real PlayerAdded event
    ("Players.ChildAdded -> PlayerAdded",
     r'\bgame\.Players\.ChildAdded\s*:\s*[cC]onnect\(', 'game:GetService("Players").PlayerAdded:Connect('),
    # game.Lighting is nil in Vortex
    ("game.Lighting -> GetService", r'\bgame\.Lighting\b', 'game:GetService("Lighting")'),
    # the 2008-era lowercase aliases
    (":service( -> :GetService(", r':service\(', ':GetService('),
    (":connect( -> :Connect(", r':connect\(', ':Connect('),
    (":findFirstChild( -> :FindFirstChild(", r':findFirstChild\(', ':FindFirstChild('),
    (":findFirstChildOfClass(", r':findFirstChildOfClass\(', ':FindFirstChildOfClass('),
    (":clone() -> :Clone()", r':clone\(\)', ':Clone()'),
    (":remove() -> :Destroy()", r':remove\(\)', ':Destroy()'),
    (":getChildren() -> :GetChildren()", r':(?:getChildren|children)\(\)', ':GetChildren()'),
    (":isA( -> :IsA(", r':isA\(', ':IsA('),
    # Message/Hint objects no longer exist: a plain table swallows .Text/.Parent assignments harmlessly
    ("Instance.new(Message/Hint) -> {}", r'Instance\.new\(\s*["\'](?:Message|Hint)["\']\s*\)', '{}'),
    # makeJoints is a deprecated no-op
    (":makeJoints() removed", r'^[ \t]*[\w.]+:makeJoints\(\)[ \t]*;?[ \t]*$', ''),
]


def fix_luau(source):
    """Apply LUAU_FIXES. Returns (new_source, {rule_name: count})."""
    counts = {}
    for name, pat, rep_ in LUAU_FIXES:
        source, n = _re.subn(pat, rep_, source, flags=_re.M)
        if n:
            counts[name] = n
    return source, counts


def build_bytes(src, template=None, scale=1.0, new_id=False, include_baseplate=False, fix_scripts=True):
    """Convert a .rbxlx (or parts JSON) into the bytes of a .vrtx file. Returns (bytes, stats dict)."""
    ver, tbody = read_vrtx(template)
    prefix, flags, tail, _ = split_template(tbody)
    skipped, lights = {}, {}
    if src.lower().endswith((".rbxlx", ".rbxmx")):
        nodes = load_tree(src, include_baseplate)
        skipped = count_unmapped(src)
        lights = count_lights(src)
    else:
        data = json.load(open(src))
        nodes = [dict(kind="part", parent=-1, **p) for p in (data["parts"] if isinstance(data, dict) else data)]
    blobs, stats = [], dict(parts=0, models=0, scripts=0, localscripts=0, fixes=0, where={}, skipped={})
    for nd in nodes:
        # parent = position of the parent entry in the whole list (Workspace = 0, then our nodes after the 7 built-ins)
        if nd["parent"] < 0:   # top-level node: count it under the service it lands in
            sname = SVC_NAMES[nd.get("svc", 0)]
            stats["where"][sname] = stats["where"].get(sname, 0) + 1
        par = N_BUILTIN + nd["parent"] if nd["parent"] >= 0 else nd.get("svc", 0)
        if nd["kind"] == "part":
            blobs.append(build_part(nd.get("name", "Part"), [c * scale for c in nd["position"]],
                                    nd.get("rotation", [0, 0, 0, 1]), [c * scale for c in nd["size"]],
                                    nd["color"], 1.0 - nd.get("transparency", 0.0), flags,
                                    nd.get("shape", "Block"), par))
            stats["parts"] += 1
        elif nd["kind"] == "model":
            blobs.append(build_model(nd["name"], par))
            stats["models"] += 1
        else:
            code = nd["source"]
            if fix_scripts:
                code, applied = fix_luau(code)
                stats["fixes"] += sum(applied.values())
            blobs.append(build_script(nd["name"], code, par, module=(nd["cls"] == "ModuleScript")))
            stats["scripts"] += 1
            if nd["cls"] == "LocalScript":
                stats["localscripts"] += 1   # Vortex has no LocalScript: imported as a normal Script
    stats["skipped"] = skipped
    stats["lights"] = lights
    prefix = bytearray(prefix)
    struct.pack_into("<Q", prefix, ENTRY_COUNT_OFF, N_BUILTIN + len(blobs))
    if new_id:
        prefix[9:41] = os.urandom(16).hex().encode()
    body = bytes(prefix) + b"".join(blobs) + tail
    comp = zstd.ZstdCompressor(level=3).compress(body)
    return MAGIC + bytes([ver]) + comp, stats


def summarize(st):
    """Human-readable lines describing what a conversion did (used by the command line and the app)."""
    lines = [f"{st['parts']} parts, {st['models']} models, {st['scripts']} scripts."]
    if st["where"]:
        lines.append("Placed in: " + ", ".join(f"{k} ({v})" for k, v in st["where"].items()) + ".")
    if st["fixes"]:
        lines.append(f"{st['fixes']} old Roblox script calls fixed.")
    if st["localscripts"]:
        lines.append(f"{st['localscripts']} LocalScript(s) imported as normal Scripts (Vortex has none).")
    if st["skipped"]:
        lines.append("Not imported (no Vortex equivalent): " + ", ".join(f"{v} script(s) in {k}" for k, v in st["skipped"].items()) + ".")
    if st.get("lights"):
        lines.append("Lights found but not imported yet: " + ", ".join(f"{v} {k}" for k, v in st["lights"].items()) + ".")
    return lines


def convert(src, dst, template=None, scale=1.0, new_id=False, include_baseplate=False, fix_scripts=True):
    print(f"Reading {src} ...")
    data, st = build_bytes(src, template, scale, new_id, include_baseplate, fix_scripts)
    open(dst, "wb").write(data)
    print(f"Done! Wrote {dst}")
    for line in summarize(st):
        print("  " + line)


PART_CLASSES = ("Part", "MeshPart", "WedgePart", "CornerWedgePart", "TrussPart", "SpawnLocation", "UnionOperation")
CONTAINER_CLASSES = ("Model", "Folder")
IGNORED_FOLDERS = ("TreeBrushFolder", "PlacementFolder", "MoonAnimatorBackups")
LIGHT_CLASSES = ("PointLight", "SpotLight", "SurfaceLight")
SCRIPT_CLASSES = ("Script", "LocalScript", "ModuleScript")


def load_tree(path, include_baseplate=False):
    """Read Workspace of a .rbxlx as an ordered list of nodes (parents always come before children).
    Each node: kind ('part'|'model'|'script'), name, parent (index into this list, or -1 = Workspace)."""
    import xml.etree.ElementTree as ET
    root = ET.parse(path).getroot()
    ws = root.find("Item[@class='Workspace']")
    SHAPES = {"0": "Ball", "1": "Block", "2": "Cylinder"}
    CLASS_SHAPE = {"WedgePart": "Wedge", "CornerWedgePart": "CornerWedge", "TrussPart": "Truss"}
    nodes = []

    def prop(it, name):
        pr = it.find("Properties")
        return pr.find(f"*[@name='{name}']") if pr is not None else None

    def nm(it):
        n = prop(it, "Name")
        return n.text if n is not None and n.text else it.get("class")

    def walk(elem, parent, svc=0):
        for it in elem.findall("Item"):
            cls = it.get("class")
            if cls in PART_CLASSES:
                name = nm(it)
                if name == "Baseplate" and not include_baseplate:
                    continue
                cf = {c.tag: float(c.text) for c in prop(it, "CFrame")}
                sz = prop(it, "size") if prop(it, "size") is not None else prop(it, "Size")
                size = [float(sz.find(a).text) for a in "XYZ"]
                c3 = prop(it, "Color3uint8")
                if c3 is not None:
                    v = int(c3.text)
                    rgb = [((v >> 16) & 255) / 255, ((v >> 8) & 255) / 255, (v & 255) / 255]
                else:
                    c3 = prop(it, "Color3")
                    rgb = [float(c3.find(a).text) for a in "RGB"] if c3 is not None else [0.64, 0.64, 0.65]
                tr, sh = prop(it, "Transparency"), prop(it, "shape")
                if sh is None:
                    sh = prop(it, "Shape")
                nodes.append(dict(
                    kind="part", name=name, parent=parent, svc=svc,
                    shape=CLASS_SHAPE.get(cls) or (SHAPES.get(sh.text, "Block") if sh is not None else "Block"),
                    position=[cf["X"], cf["Y"], cf["Z"]],
                    rotation=_quat_from_matrix([cf[k] for k in ("R00", "R01", "R02", "R10", "R11", "R12", "R20", "R21", "R22")]),
                    size=size, color=rgb, transparency=float(tr.text) if tr is not None else 0.0))
                walk(it, len(nodes) - 1, svc)
            elif cls in CONTAINER_CLASSES:
                if nm(it) in IGNORED_FOLDERS:   # leftovers from Roblox Studio and plugins, not part of the game
                    continue
                nodes.append(dict(kind="model", name=nm(it), parent=parent, svc=svc, cls=cls))
                walk(it, len(nodes) - 1, svc)
            elif cls in SCRIPT_CLASSES:
                src = prop(it, "Source")
                nodes.append(dict(kind="script", name=nm(it), parent=parent, svc=svc, cls=cls,
                                  source=(src.text or "") if src is not None else ""))
                walk(it, len(nodes) - 1, svc)
            else:
                walk(it, parent, svc)   # skipped class: its useful descendants attach to the nearest kept ancestor

    walk(ws, -1, SVC_WORKSPACE)
    # other services: whatever is inside them is placed in the matching Vortex service
    for cls, svc in (("ReplicatedStorage", SVC_REPLICATED), ("ServerScriptService", SVC_SERVER_SCRIPTS)):
        e = root.find(f"Item[@class='{cls}']")
        if e is not None:
            walk(e, -1, svc)
    sp = root.find("Item[@class='StarterPlayer']")
    if sp is not None:
        for sub in ("StarterPlayerScripts", "StarterCharacterScripts"):   # no separate character-scripts service in Vortex
            e = sp.find(f"Item[@class='{sub}']")
            if e is not None:
                walk(e, -1, SVC_PLAYER_SCRIPTS)
    return nodes


def count_unmapped(path):
    """Scripts sitting in Roblox services that Vortex has no equivalent for. Returns {service: script_count}."""
    import xml.etree.ElementTree as ET
    root = ET.parse(path).getroot()
    out = {}
    for cls in UNMAPPED_SERVICES:
        e = root.find(f"Item[@class='{cls}']")
        if e is not None:
            n = sum(1 for i in e.iter("Item") if i.get("class") in SCRIPT_CLASSES)
            if n:
                out[cls] = n
    return out


def count_lights(path):
    """Lights in the Roblox file (not imported yet - Vortex's light format is still unknown)."""
    import xml.etree.ElementTree as ET
    out = {}
    for i in ET.parse(path).getroot().iter("Item"):
        if i.get("class") in LIGHT_CLASSES:
            out[i.get("class")] = out.get(i.get("class"), 0) + 1
    return out


def load_scripts(path):
    """Scripts/LocalScripts/ModuleScripts under Workspace of a .rbxlx, with their Luau source and folder path."""
    import xml.etree.ElementTree as ET
    ws = ET.parse(path).getroot().find("Item[@class='Workspace']")
    parent_of = {c: p for p in ws.iter("Item") for c in p.findall("Item")}
    out = []
    for it in ws.iter("Item"):
        if it.get("class") in ("Script", "LocalScript", "ModuleScript"):
            pr = it.find("Properties")
            nm = pr.find("string[@name='Name']")
            src = pr.find("ProtectedString[@name='Source']")
            chain, p = [], parent_of.get(it)
            while p is not None and p is not ws:
                n = p.find("Properties/string[@name='Name']")
                chain.append(n.text if n is not None else p.get("class")); p = parent_of.get(p)
            out.append(dict(name=nm.text if nm is not None else "Script", cls=it.get("class"),
                            path=chain[::-1], source=(src.text or "") if src is not None else ""))
    return out


def main():
    ap = argparse.ArgumentParser(description="Roblox .rbxlx -> Vortex Studio .vrtx")
    ap.add_argument("files", nargs="*", help="drop .rbxlx files here (or give input [output])")
    ap.add_argument("--template", help="optional .vrtx to use instead of the built-in blank one")
    ap.add_argument("--scale", type=float, default=1.0, help="multiply positions and sizes")
    ap.add_argument("--new-id", action="store_true", help="generate a new project id")
    ap.add_argument("--include-baseplate", action="store_true")
    ap.add_argument("--no-fix-scripts", action="store_true", help="copy script source exactly, without compatibility fixes")
    ap.add_argument("--dump", metavar="VRTX", help="print the parts inside a .vrtx")
    ap.add_argument("--no-pause", action="store_true")
    a = ap.parse_args()
    try:
        if a.dump:
            for p in parse_parts(read_vrtx(a.dump)[1]):
                print(p)
            return
        if not a.files:
            print("Drag and drop a Roblox .rbxlx file onto this program.")
        else:
            files = a.files
            # explicit "input output.vrtx" form
            if len(files) == 2 and files[1].lower().endswith(".vrtx"):
                jobs = [(files[0], files[1])]
            else:
                out_dir = desktop_dir()
                jobs = []
                for f in files:
                    base = os.path.splitext(os.path.basename(f))[0] + ".vrtx"
                    # save on the Desktop; fall back to next to the input if no Desktop found
                    jobs.append((f, os.path.join(out_dir, base) if out_dir
                                 else os.path.splitext(f)[0] + ".vrtx"))
            for src, dst in jobs:
                convert(src, dst, a.template, a.scale, a.new_id, a.include_baseplate, not a.no_fix_scripts)
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"\nERROR: {e}")
    if not a.no_pause and not a.dump:
        input("\nPress Enter to close...")


if __name__ == "__main__":
    main()
