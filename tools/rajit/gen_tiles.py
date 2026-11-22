#!/usr/bin/env python3
"""Hand-assembles synthetic tile-game SWFs for the rAJIT render benchmark.

Each tile is a sprite containing a vector shape (like a typical Flash tile game); all tiles live
in a "world" sprite that autoscrolls via a two-frame AVM1 loop. Output: tests/rajit_bench_assets/
Usage: python3 tools/rajit/gen_tiles.py   (from the repository root)
"""
import os, struct

class Bits:
    def __init__(self): self.bits = []
    def ub(self, v, n):
        for i in range(n - 1, -1, -1): self.bits.append((v >> i) & 1)
    def sb(self, v, n): self.ub(v & ((1 << n) - 1), n)
    def bytes(self):
        b = self.bits + [0] * (-len(self.bits) % 8)
        return bytes(int("".join(map(str, b[i:i + 8])), 2) for i in range(0, len(b), 8))

def nbits_signed(*vals):
    n = 1
    for v in vals:
        while not (-(1 << (n - 1)) <= v < (1 << (n - 1))): n += 1
    return n

def tag(code, data=b""): return struct.pack("<HI", (code << 6) | 0x3F, len(data)) + data
def rect(xmin, xmax, ymin, ymax):
    n = nbits_signed(xmin, xmax, ymin, ymax); b = Bits(); b.ub(n, 5)
    for v in (xmin, xmax, ymin, ymax): b.sb(v, n)
    return b.bytes()
def matrix_translate(tx, ty):
    b = Bits(); b.ub(0, 1); b.ub(0, 1); n = nbits_signed(tx, ty); b.ub(n, 5); b.sb(tx, n); b.sb(ty, n)
    return b.bytes()

def define_rect_shape(shape_id, size_px, rgb):
    s = size_px * 20
    d = struct.pack("<H", shape_id) + rect(0, s, 0, s)
    d += b"\x01\x00" + bytes(rgb)                      # 1 solid fill (DefineShape1: RGB)
    d += b"\x01" + struct.pack("<H", 20) + bytes((0, 0, 0))  # 1 line style, 1px black
    d += b"\x11"                                       # NumFillBits=1, NumLineBits=1
    b = Bits()
    b.ub(0, 1); b.ub(0, 1); b.ub(1, 1); b.ub(1, 1); b.ub(0, 1); b.ub(1, 1)  # style change: line, fill1, moveto
    b.ub(1, 5); b.sb(0, 1); b.sb(0, 1)                 # moveto (0,0)
    b.ub(1, 1); b.ub(1, 1)                             # fill1 = 1, line = 1
    nb = nbits_signed(s, -s)
    for dx, dy in ((s, 0), (0, s), (-s, 0), (0, -s)):  # general-line edges
        b.ub(1, 1); b.ub(1, 1); b.ub(nb - 2, 4); b.ub(1, 1); b.sb(dx, nb); b.sb(dy, nb)
    b.ub(0, 1); b.ub(0, 5)                             # end of shape
    return tag(2, d + b.bytes())

def place(depth, char=None, mat=None, name=None):
    flags = (0x02 if char is not None else 0) | (0x04 if mat else 0) | (0x20 if name else 0)
    d = bytes([flags]) + struct.pack("<H", depth)
    if char is not None: d += struct.pack("<H", char)
    if mat: d += mat
    if name: d += name.encode() + b"\x00"
    return tag(26, d)

def sprite(sprite_id, inner): return tag(39, struct.pack("<HH", sprite_id, 1) + inner + tag(1) + tag(0))

# --- AVM1: world._x -= dx; world._y -= dy  (SetProperty on a path string) ---
def act(code, body=b""): return bytes([code]) + (struct.pack("<H", len(body)) + body if code >= 0x80 else b"")
def push(*items): return act(0x96, b"".join(items))
def p_str(s): return b"\x00" + s.encode() + b"\x00"
def p_int(n): return b"\x07" + struct.pack("<i", n)
def scroll_script(dx, dy):
    def step(prop, delta):
        return (push(p_str("world"), p_int(prop)) + push(p_str("world"), p_int(prop)) + act(0x22)
                + push(p_int(delta)) + act(0x0B) + act(0x23))
    return step(0, dx) + step(1, dy)

def build(path, cols, rows, tile_px, dx, dy, frames_hint=2):
    out = define_rect_shape(1, tile_px, (60, 140, 60))
    out += sprite(2, place(1, char=1))                                 # tile = sprite wrapping the shape
    world = b"".join(place(1 + r * cols + c, char=2, mat=matrix_translate(c * tile_px * 20, r * tile_px * 20))
                     for r in range(rows) for c in range(cols))
    out += sprite(3, world)
    out += place(1, char=3, name="world")
    out += tag(12, scroll_script(dx, dy) + b"\x00") + tag(1)           # frame 1: scroll
    out += tag(12, act(0x81, struct.pack("<H", 0)) + act(0x06) + b"\x00") + tag(1)  # frame 2: gotoAndPlay(1)
    out += tag(0)
    hdr = bytes([0x78, 0x00, 0x05, 0x5F, 0x00, 0x00, 0x0F, 0xA0, 0x00]) + struct.pack("<HH", 30 << 8, 2)  # 550x400, 30fps
    body = hdr + out
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "wb").write(b"FWS" + bytes([6]) + struct.pack("<I", 8 + len(body)) + body)
    print(path, cols * rows, "tiles")

def scroll_layers(names, dx, dy):
    def step(name, prop, delta):
        return (push(p_str(name), p_int(prop)) + push(p_str(name), p_int(prop)) + act(0x22)
                + push(p_int(delta)) + act(0x0B) + act(0x23))
    return b"".join(step(n, 0, dx) + step(n, 1, dy) for n in names)

def build_layers(path, cache, version=8):
    """Generic layered tile scene: a large static layer, an overlay layer and a small 'active' layer,
    all scrolled together every frame. With cache=True the two big layers use cacheAsBitmap."""
    T = 30
    out = define_rect_shape(1, T, (90, 130, 90)) + sprite(2, place(1, char=1))
    def grid(cols, rows, keep=lambda c, r: True):
        pl, d = b"", 1
        for r in range(rows):
            for c in range(cols):
                if keep(c, r):
                    pl += place(d, char=2, mat=matrix_translate(c * T * 20, r * T * 20)); d += 1
        return pl
    out += sprite(3, grid(100, 30))                                         # "still": 3000 tiles
    out += sprite(4, grid(50, 30))                                          # "shadow": 1500 tiles
    out += sprite(5, grid(100, 30, lambda c, r: (c * 7 + r * 13) % 10 == 0))  # "active": 300 tiles
    out += place(1, char=3, name="still") + place(2, char=4, name="shadow") + place(3, char=5, name="active")
    flags = b""
    if cache:
        for n in ("still", "shadow"):
            flags += push(p_str("_root." + n)) + act(0x1C) + push(p_str("cacheAsBitmap"), b"\x05\x01") + act(0x4F)
    out += (tag(12, flags + b"\x00") if flags else b"") + tag(1)               # frame 1: enable caching once
    out += tag(12, scroll_layers(["still", "shadow", "active"], 2, 1) + b"\x00") + tag(1)   # frame 2: scroll
    out += tag(12, act(0x81, struct.pack("<H", 1)) + act(0x06) + b"\x00") + tag(1)          # frame 3: back to frame 2
    out += tag(0)
    hdr = bytes([0x78, 0x00, 0x05, 0x5F, 0x00, 0x00, 0x0F, 0xA0, 0x00]) + struct.pack("<HH", 30 << 8, 3)
    body = hdr + out
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "wb").write(b"FWS" + bytes([version]) + struct.pack("<I", 8 + len(body)) + body)
    print(path, "cache" if cache else "no cache")

if __name__ == "__main__":
  A = "tests/rajit_bench_assets"
  build(f"{A}/tiles_visible.swf", 40, 30, 12, 1, 1)   # 1200 tiles, all on screen (no culling possible)
  build(f"{A}/tiles_scroll.swf", 40, 30, 32, 2, 1)    # 1200 tiles in a 1280x960 world, most off screen
  build_layers(f"{A}/layers_cached.swf", True)
  build_layers(f"{A}/layers_plain.swf", False)
