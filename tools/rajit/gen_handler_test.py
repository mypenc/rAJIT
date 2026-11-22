#!/usr/bin/env python3
"""Regression test for the rAJIT event-handler lookup cache (see core/src/avm1/property_map.rs).

Warms the "clip has no onEnterFrame" cache, then makes handlers appear in every way the cache
must notice. The expected output is whatever stock behaviour (RAJIT_DISABLE=1) prints.
Usage: python3 tools/rajit/gen_handler_test.py   (from the repository root)
"""
import os, struct, sys
sys.path.insert(0, os.path.dirname(__file__))
from gen_tiles import tag, place, sprite  # tag/place/sprite helpers (importing also runs its builds)

def act(code, body=b""): return bytes([code]) + (struct.pack("<H", len(body)) + body if code >= 0x80 else b"")
def push(*items): return act(0x96, b"".join(items))
def s(x): return b"\x00" + x.encode() + b"\x00"
def i(n): return b"\x07" + struct.pack("<i", n)
GETVAR, SETVAR, GETMEMBER, SETMEMBER, ADD2, TRACE, NEWOBJ, STOP = (act(c) for c in (0x1C, 0x1D, 0x4E, 0x4F, 0x47, 0x26, 0x40, 0x07))

def anon_fn(body): return act(0x9B, b"\x00" + struct.pack("<H", 0) + struct.pack("<H", len(body))) + body
def inc(var):  # _root.<var> = _root.<var> + 1
    return push(s("_root." + var), s("_root." + var)) + GETVAR + push(i(1)) + ADD2 + SETVAR
def set_var(var, n): return push(s("_root." + var), i(n)) + SETVAR

# Four clips whose caches are all warm ("no handler") before each of the changes below:
#   t1: gets an own handler            (new handler-like key on the clip object)
#   t2: re-linked to P, which has one  (existing __proto__ modified)
#   t3: inherits via MovieClip.prototype (new handler-like key on a shared prototype)
#   t4: handler assigned by the root's own handler *after* t4's event was queued but before it runs
frames = [
    # F1: counters
    set_var("count", 0) + set_var("c2", 0) + set_var("c3", 0) + set_var("c4", 0),
    # F2: object P
    push(s("_root.P"), i(0), s("Object")) + NEWOBJ + SETVAR,
    # F3: P gets a handler (no clip is linked to P yet)
    push(s("_root.P")) + GETVAR + push(s("onEnterFrame")) + anon_fn(inc("c3")) + SETMEMBER,
    b"",
    # F5: t2's prototype is changed to P
    push(s("_root.t2")) + GETVAR + push(s("__proto__"), s("_root.P")) + GETVAR + SETMEMBER,
    # F6: t1 gets its own handler
    push(s("_root.t1")) + GETVAR + push(s("onEnterFrame")) + anon_fn(inc("c2")) + SETMEMBER,
    # F7: the root's handler assigns t4's handler while t4's event is already queued
    push(s("_root")) + GETVAR + push(s("onEnterFrame"))
    + anon_fn(push(s("_root.t4")) + GETVAR + push(s("onEnterFrame")) + anon_fn(inc("c4")) + SETMEMBER) + SETMEMBER,
    b"",
    # F9: every remaining MovieClip (t3) inherits a handler through MovieClip.prototype
    push(s("MovieClip")) + GETVAR + push(s("prototype")) + GETMEMBER + push(s("onEnterFrame")) + anon_fn(inc("count")) + SETMEMBER,
    b"", b"", b"",
    # F13: report
    push(s("_root.count")) + GETVAR + TRACE + push(s("_root.c2")) + GETVAR + TRACE
    + push(s("_root.c3")) + GETVAR + TRACE + push(s("_root.c4")) + GETVAR + TRACE + STOP,
]

def build(version):
    out = sprite(2, b"")                                     # empty sprite used for the clips
    for n, name in enumerate(("t1", "t2", "t3", "t4")):
        out += place(1 + n, char=2, name=name)               # all three placed on frame 1
    for code in frames:
        if code: out += tag(12, code + b"\x00")
        out += tag(1)
    out += tag(0)
    hdr = bytes([0x78, 0x00, 0x05, 0x5F, 0x00, 0x00, 0x0F, 0xA0, 0x00]) + struct.pack("<HH", 30 << 8, len(frames))
    body = hdr + out
    return b"FWS" + bytes([version]) + struct.pack("<I", 8 + len(body)) + body

for name, version in (("rajit_handler_cache_swf6", 6), ("rajit_handler_cache_swf7", 7)):
    d = os.path.join("tests", "tests", "swfs", "avm1", name)
    os.makedirs(d, exist_ok=True)
    open(os.path.join(d, "test.swf"), "wb").write(build(version))
    open(os.path.join(d, "test.toml"), "w").write("num_ticks = 17\n")
    open(os.path.join(d, "output.txt"), "w").write("PLACEHOLDER\n")  # replaced by the stock-behaviour output
    print(name, "written")
