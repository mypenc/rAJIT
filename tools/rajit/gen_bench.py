#!/usr/bin/env python3
"""Hand-assembles the AVM1 benchmark SWFs used by the rAJIT regression/benchmark tests.

There is no Flash compiler in CI, so these are written directly as AVM1 bytecode.
Usage: python3 tools/rajit/gen_bench.py   (from the repository root)
"""
import os
import struct

# ---- tiny AVM1 assembler -------------------------------------------------
def act(code, body=b""):
    return bytes([code]) + (struct.pack("<H", len(body)) + body if code >= 0x80 else b"")

def p_str(s):  return b"\x00" + s.encode() + b"\x00"
def p_int(n):  return b"\x07" + struct.pack("<i", n)
def p_reg(r):  return b"\x04" + bytes([r])
def p_cp(i):   return b"\x08" + bytes([i])
def constant_pool(*strs):
    return act(0x88, struct.pack("<H", len(strs)) + b"".join(x.encode() + b"\x00" for x in strs))
def push(*items): return act(0x96, b"".join(items))

ADD2, SUB, MUL, POP, LESS2, TRACE = (act(c) for c in (0x47, 0x0B, 0x0C, 0x17, 0x48, 0x26))
GETVAR, SETVAR, CALLFN, RETURN = (act(c) for c in (0x1C, 0x1D, 0x3D, 0x3E))
def store_reg(r): return act(0x87, bytes([r]))
def if_back(body_len): return act(0x9D, struct.pack("<h", -(body_len + 5)))  # relative to end of If

def define_function(name, params, code):
    hdr = name.encode() + b"\x00" + struct.pack("<H", len(params))
    for p in params:
        hdr += p.encode() + b"\x00"
    hdr += struct.pack("<H", len(code))
    return act(0x9B, hdr) + code  # the body follows the action, outside its length

def swf(code):
    rect = bytes([0x78, 0x00, 0x05, 0x5F, 0x00, 0x00, 0x0F, 0xA0, 0x00])
    rest = rect + struct.pack("<HH", 12 << 8, 1)
    code = code + b"\x00"
    tag = struct.pack("<HI", (12 << 6) | 0x3F, len(code)) + code + b"\x00\x00"
    body = rest + tag
    return b"FWS" + bytes([6]) + struct.pack("<I", 8 + len(body)) + body

def write(name, code, expected):
    d = os.path.join("tests", "tests", "swfs", "avm1", name)
    os.makedirs(d, exist_ok=True)
    open(os.path.join(d, "test.swf"), "wb").write(swf(code))
    open(os.path.join(d, "test.toml"), "w").write(
        "num_ticks = 1\n\n"
        "# CPU-heavy benchmark: kept out of the default parallel suite because it starves\n"
        "# wall-clock-sensitive tests (e.g. getTimer_test). Run with `-- --ignored rajit_`.\n"
        "ignore = true\n"
    )
    open(os.path.join(d, "output.txt"), "w").write(expected + "\n")

# ---- rajit_noop: measures the fixed cost of the test harness ----------------
write("rajit_noop", push(p_str("ok")) + TRACE, "ok")

# ---- rajit_loop: pure register arithmetic ---------------------------------
N = 30_000_000
body = push(p_reg(0)) + push(p_int(1)) + ADD2 + store_reg(0) + POP + push(p_reg(0)) + push(p_int(N)) + LESS2
code = push(p_int(0)) + store_reg(0) + POP + body + if_back(len(body)) + push(p_reg(0)) + TRACE
write("rajit_loop", code, str(N))

# ---- rajit_vars: variable-heavy loop ---------------------------------------
N = 3_000_000
body = (
    push(p_str("sum"), p_str("sum")) + GETVAR + push(p_str("i")) + GETVAR + push(p_int(2)) + MUL + ADD2 + SETVAR
    + push(p_str("i"), p_str("i")) + GETVAR + push(p_int(1)) + ADD2 + SETVAR
    + push(p_str("i")) + GETVAR + push(p_int(N)) + LESS2
)
code = (
    push(p_str("i"), p_int(0)) + SETVAR + push(p_str("sum"), p_int(0)) + SETVAR
    + body + if_back(len(body)) + push(p_str("sum")) + GETVAR + TRACE
)
write("rajit_vars", code, str(N * (N - 1)))

# ---- rajit_calls: function-call-heavy loop ----------------------------------
N = 1_000_000
f = define_function("f", ["x"], push(p_str("x")) + GETVAR + push(p_int(1)) + ADD2 + RETURN)
body = (
    push(p_str("acc"), p_str("acc")) + GETVAR + push(p_int(1), p_str("f")) + CALLFN + SETVAR
    + push(p_str("i"), p_str("i")) + GETVAR + push(p_int(1)) + ADD2 + SETVAR
    + push(p_str("i")) + GETVAR + push(p_int(N)) + LESS2
)
code = (
    f + push(p_str("i"), p_int(0)) + SETVAR + push(p_str("acc"), p_int(0)) + SETVAR
    + body + if_back(len(body)) + push(p_str("acc")) + GETVAR + TRACE
)
write("rajit_calls", code, str(N))

# ---- the same two loops, but naming variables through a ConstantPool like real compilers do ----
N = 3_000_000
SUM, I = p_cp(0), p_cp(1)
body = (
    push(SUM, SUM) + GETVAR + push(I) + GETVAR + push(p_int(2)) + MUL + ADD2 + SETVAR
    + push(I, I) + GETVAR + push(p_int(1)) + ADD2 + SETVAR
    + push(I) + GETVAR + push(p_int(N)) + LESS2
)
code = (
    constant_pool("sum", "i") + push(I, p_int(0)) + SETVAR + push(SUM, p_int(0)) + SETVAR
    + body + if_back(len(body)) + push(SUM) + GETVAR + TRACE
)
write("rajit_vars_cp", code, str(N * (N - 1)))

N = 1_000_000
I, ACC, F, X = p_cp(0), p_cp(1), p_cp(2), p_cp(3)
f = define_function("f", ["x"], push(X) + GETVAR + push(p_int(1)) + ADD2 + RETURN)
body = (
    push(ACC, ACC) + GETVAR + push(p_int(1), F) + CALLFN + SETVAR
    + push(I, I) + GETVAR + push(p_int(1)) + ADD2 + SETVAR
    + push(I) + GETVAR + push(p_int(N)) + LESS2
)
code = (
    constant_pool("i", "acc", "f", "x") + f + push(I, p_int(0)) + SETVAR + push(ACC, p_int(0)) + SETVAR
    + body + if_back(len(body)) + push(ACC) + GETVAR + TRACE
)
write("rajit_calls_cp", code, str(N))
print("ok")
