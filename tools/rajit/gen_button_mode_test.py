#!/usr/bin/env python3
"""Regression test for the rAJIT button-mode cache (MovieClip::is_button_mode).

Mouse-picking warms the "this clip has no onPress & co" cache, then handlers appear late, once via
an own property and once by re-linking __proto__. A press afterwards must reach them exactly as in
stock behaviour (RAJIT_DISABLE=1). Usage: python3 tools/rajit/gen_button_mode_test.py
"""
import json, os, struct, sys
sys.path.insert(0, os.path.dirname(__file__))
from gen_tiles import tag, place, sprite, define_rect_shape, matrix_translate

def act(code, body=b""): return bytes([code]) + (struct.pack("<H", len(body)) + body if code >= 0x80 else b"")
def push(*items): return act(0x96, b"".join(items))
def s(x): return b"\x00" + x.encode() + b"\x00"
def i(n): return b"\x07" + struct.pack("<i", n)
GETVAR, SETVAR, SETMEMBER, ADD2, TRACE, NEWOBJ, STOP = (act(c) for c in (0x1C, 0x1D, 0x4F, 0x47, 0x26, 0x40, 0x07))
def anon_fn(body): return act(0x9B, b"\x00" + struct.pack("<H", 0) + struct.pack("<H", len(body))) + body
def inc(var): return push(s("_root." + var), s("_root." + var)) + GETVAR + push(i(1)) + ADD2 + SETVAR
DBG = bool(os.environ.get("DBG"))
def dbg(msg): return (push(s(msg)) + TRACE) if DBG else b""
def set_var(var, n): return push(s("_root." + var), i(n)) + SETVAR

# Each phase makes exactly one epoch-changing edit between a clip's warm-up and its use:
#   bA: own onPress assigned (a new handler-like key)      -> F14, after both clips were warmed
#   bB: re-linked to Q, which has onPress (a __proto__ change) -> F23, after bB was re-warmed
frames = {
    1: set_var("pA", 0) + set_var("pB", 0),
    # Q has an onPress handler but no clip is linked to it yet; fnA is created now so that assigning it
    # later changes nothing except the one property insertion.
    2: push(s("_root.Q"), i(0), s("Object")) + NEWOBJ + SETVAR
       + push(s("_root.Q")) + GETVAR + push(s("onPress")) + anon_fn(inc("pB") + dbg("pressB")) + SETMEMBER
       + push(s("_root.fnA")) + anon_fn(inc("pA") + dbg("pressA")) + SETVAR,
    14: dbg("F14 assign bA") + push(s("_root.bA")) + GETVAR + push(s("onPress"), s("_root.fnA")) + GETVAR + SETMEMBER,
    23: dbg("F23 relink bB") + push(s("_root.bB")) + GETVAR + push(s("__proto__"), s("_root.Q")) + GETVAR + SETMEMBER,
    60: push(s("_root.pA")) + GETVAR + TRACE + push(s("_root.pB")) + GETVAR + TRACE + STOP,
}
NFRAMES = 60

def build(version):
    out = define_rect_shape(1, 100, (200, 60, 60)) + sprite(2, place(1, char=1))
    out += place(1, char=2, mat=matrix_translate(0, 0), name="bA")
    out += place(2, char=2, mat=matrix_translate(200 * 20, 0), name="bB")
    for n in range(1, NFRAMES + 1):
        if n in frames: out += tag(12, frames[n] + b"\x00")
        out += tag(1)
    out += tag(0)
    hdr = bytes([0x78, 0x00, 0x05, 0x5F, 0x00, 0x00, 0x0F, 0xA0, 0x00]) + struct.pack("<HH", 30 << 8, NFRAMES)
    body = hdr + out
    return b"FWS" + bytes([version]) + struct.pack("<I", 8 + len(body)) + body

def ev(kind, x=None, y=None):
    e = {"type": kind}
    if x is not None: e["pos"] = [float(x), float(y)]
    if kind in ("MouseDown", "MouseUp"): e["btn"] = "Left"
    return e

W = ev("Wait")
inputs = ([W,
           ev("MouseMove", 50, 50), W, W,                 # hover bA: warms its cache
           ev("MouseMove", 250, 50), W, W,                # hover bB: warms its cache
           ev("MouseMove", 400, 300)] + [W] * 9 +         # leave; bA gets its handler (F14) in here
          [ev("MouseMove", 60, 60), W,                    # hover bA, now button-like
           ev("MouseDown", 60, 60), W, ev("MouseUp", 60, 60), W,                  # press bA
           ev("MouseMove", 250, 50), W, W] + [W] * 6 +    # re-warm bB after bA's change; bB is re-linked (F23) in here
          [ev("MouseMove", 260, 60), W,
           ev("MouseDown", 260, 60), W, ev("MouseUp", 260, 60), W] + [W] * 6)     # press bB

for name, version in (("rajit_button_mode_cache_swf6", 6), ("rajit_button_mode_cache_swf7", 7)):
    d = os.path.join("tests", "tests", "swfs", "avm1", name)
    os.makedirs(d, exist_ok=True)
    open(os.path.join(d, "test.swf"), "wb").write(build(version))
    open(os.path.join(d, "test.toml"), "w").write("num_ticks = 66\n")
    open(os.path.join(d, "input.json"), "w").write(json.dumps(inputs, indent=2) + "\n")
    open(os.path.join(d, "output.txt"), "w").write("PLACEHOLDER\n")  # replaced by the stock-behaviour output
    print(name, "written")
