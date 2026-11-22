#!/usr/bin/env python3
"""Writes a tiny SWF that does `lv = new LoadVars(); lv.load("data.txt")`, plus a sibling data file whose
name has different letter case ("Data.TXT"), inside a sub-folder, for the Pages smoke test.
Usage: gen_vfs_smoke.py <out-dir>   (creates <out-dir>/gamefolder/{game.swf,Data.TXT})"""
import os, struct, sys
out = os.path.join(sys.argv[1], "gamefolder")
os.makedirs(out, exist_ok=True)
def act(code, body=b""): return bytes([code]) + (struct.pack("<H", len(body)) + body if code >= 0x80 else b"")
def s(x): return b"\x00" + x.encode() + b"\x00"
def i(n): return b"\x07" + struct.pack("<i", n)
code = (act(0x96, s("_root.lv") + i(0) + s("LoadVars")) + act(0x40) + act(0x1D)          # _root.lv = new LoadVars()
        + act(0x96, s("data.txt") + i(1)) + act(0x96, s("_root.lv")) + act(0x1C)        # args, numArgs, object
        + act(0x96, s("load")) + act(0x52) + b"\x00")                                   # lv.load("data.txt")
tag = lambda c, d: struct.pack("<HI", (c << 6) | 0x3F, len(d)) + d
body = bytes([0x78, 0x00, 0x05, 0x5F, 0x00, 0x00, 0x0F, 0xA0, 0x00]) + struct.pack("<HH", 12 << 8, 1)
body += tag(12, code) + tag(1, b"") + tag(0, b"")
open(os.path.join(out, "game.swf"), "wb").write(b"FWS" + bytes([6]) + struct.pack("<I", 8 + len(body)) + body)
open(os.path.join(out, "Data.TXT"), "w").write("msg=hello")
print("wrote", out)
