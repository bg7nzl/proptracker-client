#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Tests and performance for gridcodec (full-featured Python)."""
from __future__ import print_function
import os
import sys
import time

# Allow running from python/ so that "gridcodec" package is found
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gridcodec import (
    GC_FIELDS, GC_SQUARES, GC_GRIDS,
    field_index, field_name, grid_index, grid_name,
    grid_to_field, grid_to_square,
    GridCodecMatrix,
    GC_ERR_INVALID, GC_ERR_OVERFLOW, GC_ERR_FORMAT,
)


def test_helpers():
    print("  test field_index / field_name...", end="")
    assert field_index("FN") == 5 * 18 + 13
    assert field_index("fn") == field_index("FN")
    assert field_index("OL") == 14 * 18 + 11
    assert field_name(field_index("FN")) == "FN"
    assert field_index("RR") >= 0  # last valid field
    assert field_index("X") == -1
    assert field_index("") == -1
    print(" OK")

    print("  test grid_index / grid_name...", end="")
    assert grid_index("FN31") == field_index("FN") * 100 + 31
    assert grid_name(grid_index("FN31")) == "FN31"
    assert grid_index("OL72") >= 0
    assert grid_to_field(grid_index("FN31")) == field_index("FN")
    assert grid_to_square(grid_index("FN31")) == 31
    print(" OK")


def test_empty_roundtrip():
    print("  test_empty_roundtrip...", end="")
    m = GridCodecMatrix()
    data, n = m.encode()
    assert n > 0
    assert data[0] == 0x01 and data[1] == 0
    m2 = GridCodecMatrix()
    consumed = m2.decode(data)
    assert consumed == n
    print(" OK (encoded %d bytes)" % n)


def test_single_path_roundtrip():
    print("  test_single_path_roundtrip...", end="")
    m = GridCodecMatrix()
    r = m.set("FN31", "PM02")
    assert r == 0
    data, n = m.encode()
    assert n > 0
    m2 = GridCodecMatrix()
    consumed = m2.decode(data)
    assert consumed == n
    from_fn = m2.gc_from("FN31")
    assert len(from_fn) == 1
    assert grid_name(from_fn[0]) == "PM02"
    to_pm = m2.gc_to("PM02")
    assert len(to_pm) == 1
    assert grid_name(to_pm[0]) == "FN31"
    print(" OK (encoded %d bytes)" % n)


def test_layer1_only():
    print("  test_layer1_only (two paths, L1+L2)...", end="")
    m = GridCodecMatrix()
    m.set("FN31", "PM02")
    m.set("JO22", "FN31")
    data, n = m.encode()
    assert data[1] & 1  # has_layer2
    m2 = GridCodecMatrix()
    consumed = m2.decode(data)
    assert consumed == n
    assert len(m2.gc_from("FN")) == 1
    assert field_name(m2.gc_from("FN")[0]) == "PM"
    print(" OK (encoded %d bytes)" % n)


def test_query_from_to():
    print("  test_query_from_to...", end="")
    m = GridCodecMatrix()
    m.set("FN31", "PM02")
    m.set("FN31", "PM03")
    m.set("JO22", "FN31")
    from_fn = m.gc_from("FN31")
    assert len(from_fn) == 2
    assert set(grid_name(x) for x in from_fn) == {"PM02", "PM03"}
    to_fn = m.gc_to("FN31")
    assert len(to_fn) == 1
    assert grid_name(to_fn[0]) == "JO22"
    from_jo = m.gc_from("JO22")
    assert len(from_jo) == 1
    assert grid_name(from_jo[0]) == "FN31"
    # 2-char query
    from_f = m.gc_from("FN")
    assert len(from_f) == 1 and field_name(from_f[0]) == "PM"
    print(" OK")


def test_dedup():
    print("  test_dedup (same pair twice)...", end="")
    m = GridCodecMatrix()
    m.set("OL72", "FN31")
    m.set("OL72", "FN31")
    data, n = m.encode()
    m2 = GridCodecMatrix()
    m2.decode(data)
    from_ol = m2.gc_from("OL72")
    assert len(from_ol) == 1 and grid_name(from_ol[0]) == "FN31"
    print(" OK")


def test_realistic_roundtrip(n_paths=500):
    print("  test_realistic_roundtrip (%d paths)..." % n_paths, end="")
    import random
    random.seed(42)
    m = GridCodecMatrix()
    grids = []
    for _ in range(n_paths * 2):
        fi = random.randint(0, GC_FIELDS - 1)
        si = random.randint(0, GC_SQUARES - 1)
        grids.append(field_name(fi) + "%d%d" % (si // 10, si % 10))
    for i in range(0, len(grids) - 1, 2):
        m.set(grids[i], grids[i + 1])
    t0 = time.perf_counter()
    data, enc_len = m.encode()
    t1 = time.perf_counter()
    m2 = GridCodecMatrix()
    t2 = time.perf_counter()
    consumed = m2.decode(data)
    t3 = time.perf_counter()
    assert consumed == enc_len
    verified = 0
    for i in range(0, len(grids) - 1, 2):
        out = m2.gc_from(grids[i])
        if any(grid_name(x) == grids[i + 1] for x in out):
            verified += 1
    assert verified == n_paths
    enc_ms = (t1 - t0) * 1000
    dec_ms = (t3 - t2) * 1000
    print(" OK")
    print("    Encoded: %d bytes, Encode: %.2f ms, Decode: %.2f ms, Verified: %d" % (
        enc_len, enc_ms, dec_ms, verified))


def test_performance():
    print("  [Performance] 500 / 5000 / 2000 paths...")
    for n in (500, 5000, 2000):
        import random
        random.seed(123)
        m = GridCodecMatrix()
        for _ in range(n):
            a = (random.randint(0, GC_FIELDS - 1), random.randint(0, GC_SQUARES - 1))
            b = (random.randint(0, GC_FIELDS - 1), random.randint(0, GC_SQUARES - 1))
            from_g = field_name(a[0]) + "%d%d" % (a[1] // 10, a[1] % 10)
            to_g = field_name(b[0]) + "%d%d" % (b[1] // 10, b[1] % 10)
            m.set(from_g, to_g)
        t0 = time.perf_counter()
        data, enc_len = m.encode()
        t1 = time.perf_counter()
        m2 = GridCodecMatrix()
        consumed = m2.decode(data)
        t2 = time.perf_counter()
        enc_ms = (t1 - t0) * 1000
        dec_ms = (t2 - t1) * 1000
        print("    %d paths: encoded %d bytes, encode %.2f ms, decode %.2f ms" % (
            n, enc_len, enc_ms, dec_ms))


def test_c_interop():
    """Decode a payload produced by C (from test_embedded.c payload_l1_only)."""
    print("  test_c_interop (decode C payload)...", end="")
    payload_l1_only = bytes([
        0x01, 0x00, 0x20, 0x02, 0x00, 0x80, 0x01, 0x02, 0x08, 0x00, 0x0c, 0x09,
        0x06, 0x06
    ])
    m = GridCodecMatrix()
    consumed = m.decode(payload_l1_only)
    assert consumed == len(payload_l1_only)
    from_fn = m.gc_from("FN")
    assert len(from_fn) == 1 and field_name(from_fn[0]) == "PM"
    to_fn = m.gc_to("FN")
    assert len(to_fn) == 1 and field_name(to_fn[0]) == "JO"
    print(" OK")


def main():
    print("=== GridCodec Python Test Suite ===\n")
    print("[Helpers]")
    test_helpers()
    print("\n[Round-trip]")
    test_empty_roundtrip()
    test_single_path_roundtrip()
    test_layer1_only()
    print("\n[Query]")
    test_query_from_to()
    test_dedup()
    print("\n[Realistic]")
    test_realistic_roundtrip(500)
    test_realistic_roundtrip(5000)
    test_realistic_roundtrip(2000)  # 20k is very slow in pure Python
    print("\n[C interop]")
    test_c_interop()
    print("\n[Performance]")
    test_performance()
    print("\n=== All tests passed ===\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
