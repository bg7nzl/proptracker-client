# test_gridcodec.py -- MicroPython tests (decode + query only). Run on device or with Python 3.

try:
    import gridcodec
except ImportError:
    import sys
    sys.path.insert(0, '.')
    import gridcodec

import time
if hasattr(time, 'ticks_ms'):
    def _time_ms():
        return time.ticks_ms()
    def _elapsed_ms(start, end):
        return time.ticks_diff(end, start)
else:
    def _time_ms():
        return int(time.perf_counter() * 1000)
    def _elapsed_ms(start, end):
        return end - start

# Payloads from C test_embedded.c (Layer 1 only and L1+L2)
payload_l1_only = bytes([
    0x01, 0x00, 0x20, 0x02, 0x00, 0x80, 0x01, 0x02, 0x08, 0x00, 0x0c, 0x09,
    0x06, 0x06
])
payload_l1l2 = bytes([
    0x01, 0x01, 0x20, 0x02, 0x00, 0x80, 0x01, 0x02, 0x08, 0x00, 0x0c, 0x09,
    0x06, 0x06, 0x08, 0x08, 0x10, 0x00, 0x01, 0x01, 0x01, 0x01, 0x04, 0x10,
    0x80, 0x80, 0x00, 0x01, 0x01, 0x01
])


def test_decode_l1():
    print("test_decode_l1...", end="")
    m = gridcodec.GridCodecMatrix()
    n = m.decode(payload_l1_only)
    assert n == len(payload_l1_only)
    from_fn = m.gc_from("FN")
    assert len(from_fn) == 1
    assert gridcodec.field_name(from_fn[0]) == "PM"
    to_fn = m.gc_to("FN")
    assert len(to_fn) == 1
    assert gridcodec.field_name(to_fn[0]) == "JO"
    from_jo = m.gc_from("JO")
    assert len(from_jo) == 1
    assert gridcodec.field_name(from_jo[0]) == "FN"
    from_pm = m.gc_from("PM")
    assert len(from_pm) == 0
    print(" OK")


def test_decode_l1l2_skip():
    print("test_decode_l1l2_skip...", end="")
    m = gridcodec.GridCodecMatrix()
    n = m.decode(payload_l1l2)
    assert n == len(payload_l1l2)
    from_fn = m.gc_from("FN")
    assert len(from_fn) == 1 and gridcodec.field_name(from_fn[0]) == "PM"
    to_fn = m.gc_to("FN")
    assert len(to_fn) == 1 and gridcodec.field_name(to_fn[0]) == "JO"
    print(" OK (L2 skipped, consumed %d bytes)" % n)


def test_4char_degrades_to_field():
    print("test_4char_degrades_to_field...", end="")
    m = gridcodec.GridCodecMatrix()
    m.decode(payload_l1_only)
    from_fn = m.gc_from("FN31")
    assert len(from_fn) == 1
    assert from_fn[0] < gridcodec.GC_FIELDS
    assert gridcodec.field_name(from_fn[0]) == "PM"
    print(" OK")


def test_helpers():
    print("test_helpers...", end="")
    assert gridcodec.field_index("FN") >= 0
    assert gridcodec.field_name(gridcodec.field_index("FN")) == "FN"
    assert gridcodec.grid_index("FN31") >= 0
    print(" OK")


def test_decode_latency():
    """Measure decode latency (ms) for L1-only and L1+L2 payloads."""
    print("test_decode_latency...")
    n_iters = 20
    m = gridcodec.GridCodecMatrix()
    # L1-only (14 bytes)
    t0 = _time_ms()
    for _ in range(n_iters):
        m.decode(payload_l1_only)
    t1 = _time_ms()
    ms_l1 = _elapsed_ms(t0, t1) / n_iters
    # L1+L2 (30 bytes, L2 skipped)
    t0 = _time_ms()
    for _ in range(n_iters):
        m.decode(payload_l1l2)
    t1 = _time_ms()
    ms_l1l2 = _elapsed_ms(t0, t1) / n_iters
    print("  L1-only (%d B): %.2f ms/decode" % (len(payload_l1_only), ms_l1))
    print("  L1+L2 skip (%d B): %.2f ms/decode" % (len(payload_l1l2), ms_l1l2))
    print(" OK")


def main():
    print("=== GridCodec MicroPython tests ===\n")
    test_helpers()
    test_decode_l1()
    test_decode_l1l2_skip()
    test_4char_degrades_to_field()
    test_decode_latency()
    print("\n=== All tests passed ===\n")


if __name__ == "__main__":
    main()
