# gridcodec.py -- MicroPython (embedded): decode + query only.
# Single file, no dependencies. Layer 2 skipped; 4-char queries degrade to field-level.
# Compatible with Wire Format v1 (see main README).

# Constants (match C)
GC_FIELD_LONS = 18
GC_FIELD_LATS = 18
GC_FIELDS = 324  # 18*18
GC_SQ_LONS = 10
GC_SQ_LATS = 10
GC_SQUARES = 100
GC_FIELD_MATRIX_BYTES = 13122  # (324*324+7)//8
GC_VERSION = 0x01
GC_FLAG_LAYER2 = 0x01

# Popcount table (bytes 0-255)
_POPCOUNT = b'\x00\x01\x01\x02\x01\x02\x02\x03\x01\x02\x02\x03\x02\x03\x03\x04' \
            b'\x01\x02\x02\x03\x02\x03\x03\x04\x02\x03\x03\x04\x03\x04\x04\x05' \
            b'\x01\x02\x02\x03\x02\x03\x03\x04\x02\x03\x03\x04\x03\x04\x04\x05' \
            b'\x02\x03\x03\x04\x03\x04\x04\x05\x03\x04\x04\x05\x04\x05\x05\x06' \
            b'\x01\x02\x02\x03\x02\x03\x03\x04\x02\x03\x03\x04\x03\x04\x04\x05' \
            b'\x02\x03\x03\x04\x03\x04\x04\x05\x03\x04\x04\x05\x04\x05\x05\x06' \
            b'\x02\x03\x03\x04\x03\x04\x04\x05\x03\x04\x04\x05\x04\x05\x05\x06' \
            b'\x03\x04\x04\x05\x04\x05\x05\x06\x04\x05\x05\x06\x05\x06\x06\x07' \
            b'\x01\x02\x02\x03\x02\x03\x03\x04\x02\x03\x03\x04\x03\x04\x04\x05' \
            b'\x02\x03\x03\x04\x03\x04\x04\x05\x03\x04\x04\x05\x04\x05\x05\x06' \
            b'\x02\x03\x03\x04\x03\x04\x04\x05\x03\x04\x04\x05\x04\x05\x05\x06' \
            b'\x03\x04\x04\x05\x04\x05\x05\x06\x04\x05\x05\x06\x05\x06\x06\x07' \
            b'\x02\x03\x03\x04\x03\x04\x04\x05\x03\x04\x04\x05\x04\x05\x05\x06' \
            b'\x03\x04\x04\x05\x04\x05\x05\x06\x04\x05\x05\x06\x05\x06\x06\x07' \
            b'\x03\x04\x04\x05\x04\x05\x05\x06\x04\x05\x05\x06\x05\x06\x06\x07' \
            b'\x04\x05\x05\x06\x05\x06\x06\x07\x05\x06\x06\x07\x06\x07\x07\x08'


def _bit_get(buf, bit):
    return (buf[bit >> 3] >> (bit & 7)) & 1


def _bit_set(buf, bit):
    buf[bit >> 3] |= 1 << (bit & 7)


def _popcount32(v):
    v = v & 0xFFFFFFFF
    return _POPCOUNT[v & 0xFF] + _POPCOUNT[(v >> 8) & 0xFF] + \
           _POPCOUNT[(v >> 16) & 0xFF] + _POPCOUNT[(v >> 24) & 0xFF]


def _unpack_mask(buf, pos, nbits):
    mask = 0
    for i in range(nbits):
        if _bit_get(buf, pos[0]):
            mask |= 1 << i
        pos[0] += 1
    return mask & 0xFFFFFFFF


def _mask_indices(mask, nbits):
    out = []
    for i in range(nbits):
        if (mask & (1 << i)) != 0:
            out.append(i)
    return out


def field_index(name):
    if not name or len(name) < 2:
        return -1
    c0 = name[0].upper()
    c1 = name[1].upper()
    if c0 < 'A' or c0 > 'R' or c1 < 'A' or c1 > 'R':
        return -1
    return (ord(c0) - 65) * GC_FIELD_LATS + (ord(c1) - 65)


def field_name(idx):
    if idx < 0 or idx >= GC_FIELDS:
        return '??'
    return chr(65 + idx // GC_FIELD_LATS) + chr(65 + idx % GC_FIELD_LATS)


def grid_index(name):
    if not name or len(name) < 4:
        return -1
    c0, c1 = name[0].upper(), name[1].upper()
    c2, c3 = name[2], name[3]
    if c0 < 'A' or c0 > 'R' or c1 < 'A' or c1 > 'R':
        return -1
    if c2 < '0' or c2 > '9' or c3 < '0' or c3 > '9':
        return -1
    fi = (ord(c0) - 65) * GC_FIELD_LATS + (ord(c1) - 65)
    si = (ord(c2) - 48) * GC_SQ_LATS + (ord(c3) - 48)
    return fi * GC_SQUARES + si


class GridCodecMatrix:
    """Embedded: decode only; gc_from/gc_to return field indices. Layer 2 skipped."""

    def __init__(self):
        self.field_bits = bytearray(GC_FIELD_MATRIX_BYTES)

    def decode(self, data):
        if len(data) < 2:
            return -3  # GC_ERR_FORMAT
        if data[0] != GC_VERSION:
            return -3
        flags = data[1]
        consumed = 2
        # Decode Layer 1
        consumed += _decode_projection(
            data, consumed, len(data) - consumed,
            GC_FIELD_LONS, GC_FIELD_LATS, self.field_bits)
        if consumed < 0:
            return consumed
        if not (flags & GC_FLAG_LAYER2):
            return consumed
        # Skip Layer 2: parse each sub-block to advance consumed
        slm, sam, dlm, dam = _compute_dim_masks(
            self.field_bits, GC_FIELD_LONS, GC_FIELD_LATS)
        src_lons = _mask_indices(slm, GC_FIELD_LONS)
        src_lats = _mask_indices(sam, GC_FIELD_LATS)
        dst_lons = _mask_indices(dlm, GC_FIELD_LONS)
        dst_lats = _mask_indices(dam, GC_FIELD_LATS)
        src_bmp, n_src = _build_entry_bitmap_embedded(
            self.field_bits, GC_FIELD_LONS, GC_FIELD_LATS,
            src_lons, src_lats, True)
        dst_bmp, n_dst = _build_entry_bitmap_embedded(
            self.field_bits, GC_FIELD_LONS, GC_FIELD_LATS,
            dst_lons, dst_lats, False)
        src_entries = _bitmap_to_entries_embedded(
            src_bmp, len(src_lons), len(src_lats),
            src_lons, src_lats, GC_FIELD_LATS)
        dst_entries = _bitmap_to_entries_embedded(
            dst_bmp, len(dst_lons), len(dst_lats),
            dst_lons, dst_lats, GC_FIELD_LATS)
        for si in range(len(src_entries)):
            for di in range(len(dst_entries)):
                src_fi = src_entries[si]
                dst_fi = dst_entries[di]
                if not _bit_get(self.field_bits, src_fi * GC_FIELDS + dst_fi):
                    continue
                # Skip one L2 sub-block: 5 bytes masks (4 x 10 bits), then src/dst bmp, inner
                seg = data[consumed:]
                if len(seg) < 5:
                    return -3
                pos = [0]
                sq_slm = _unpack_mask(seg, pos, GC_SQ_LONS)   # 10 bits
                sq_sam = _unpack_mask(seg, pos, GC_SQ_LATS)
                sq_dlm = _unpack_mask(seg, pos, GC_SQ_LONS)
                sq_dam = _unpack_mask(seg, pos, GC_SQ_LATS)
                ns_lon = _popcount32(sq_slm)
                ns_lat = _popcount32(sq_sam)
                nd_lon = _popcount32(sq_dlm)
                nd_lat = _popcount32(sq_dam)
                sbmp = (ns_lon * ns_lat + 7) // 8
                dbmp = (nd_lon * nd_lat + 7) // 8
                if 5 + sbmp + dbmp > len(seg):
                    return -3
                n_asq = _popcount_buf(seg[5:5 + sbmp])
                n_adq = _popcount_buf(seg[5 + sbmp:5 + sbmp + dbmp])
                inner = (n_asq * n_adq + 7) // 8
                if 5 + sbmp + dbmp + inner > len(seg):
                    return -3
                consumed += 5 + sbmp + dbmp + inner
        return consumed

    def gc_from(self, grid, max_out=324):
        grid = str(grid).strip()
        if len(grid) >= 2:
            fi = field_index(grid[:2])
            if fi >= 0:
                return _query_field_from(self.field_bits, fi, max_out)
        return []

    def gc_to(self, grid, max_out=324):
        grid = str(grid).strip()
        if len(grid) >= 2:
            fi = field_index(grid[:2])
            if fi >= 0:
                return _query_field_to(self.field_bits, fi, max_out)
        return []


def _popcount_buf(buf, nbytes=None):
    if nbytes is None:
        nbytes = len(buf)
    c = 0
    for i in range(nbytes):
        c += _POPCOUNT[buf[i]]
    return c


def _compute_dim_masks(matrix_bits, n_lons, n_lats):
    N = n_lons * n_lats
    slm = sam = dlm = dam = 0
    for s in range(N):
        for d in range(N):
            if _bit_get(matrix_bits, s * N + d):
                s_lon, s_lat = s // n_lats, s % n_lats
                d_lon, d_lat = d // n_lats, d % n_lats
                slm |= 1 << s_lon
                sam |= 1 << s_lat
                dlm |= 1 << d_lon
                dam |= 1 << d_lat
    return slm & 0xFFFFFFFF, sam & 0xFFFFFFFF, dlm & 0xFFFFFFFF, dam & 0xFFFFFFFF


def _build_entry_bitmap_embedded(matrix_bits, n_lons, n_lats, active_lons, active_lats, is_src):
    N = n_lons * n_lats
    n_al, n_alat = len(active_lons), len(active_lats)
    nbytes = (n_al * n_alat + 7) // 8
    out = bytearray(nbytes)
    count = 0
    for li in range(n_al):
        for ai in range(n_alat):
            entry = active_lons[li] * n_lats + active_lats[ai]
            bit_idx = li * n_alat + ai
            has_activity = False
            if is_src:
                for d in range(N):
                    if _bit_get(matrix_bits, entry * N + d):
                        has_activity = True
                        break
            else:
                for s in range(N):
                    if _bit_get(matrix_bits, s * N + entry):
                        has_activity = True
                        break
            if has_activity:
                _bit_set(out, bit_idx)
                count += 1
    return out, count


def _bitmap_to_entries_embedded(bitmap, n_al, n_alat, active_lons, active_lats, lats_per_row):
    out = []
    for li in range(n_al):
        for ai in range(n_alat):
            if _bit_get(bitmap, li * n_alat + ai):
                out.append(active_lons[li] * lats_per_row + active_lats[ai])
    return out


def _decode_projection(buf, offset, length, n_lons, n_lats, matrix_bits):
    N = n_lons * n_lats
    for i in range(len(matrix_bits)):
        matrix_bits[i] = 0
    seg = buf[offset:offset + length]
    seg_len = len(seg)
    mask_bytes = (n_lons * 2 + n_lats * 2 + 7) // 8
    if mask_bytes > seg_len:
        return -3
    pos = [0]
    src_lon_mask = _unpack_mask(seg, pos, n_lons)
    src_lat_mask = _unpack_mask(seg, pos, n_lats)
    dst_lon_mask = _unpack_mask(seg, pos, n_lons)
    dst_lat_mask = _unpack_mask(seg, pos, n_lats)
    consumed = mask_bytes
    pos_b = mask_bytes
    n_src_lon = _popcount32(src_lon_mask)
    n_src_lat = _popcount32(src_lat_mask)
    n_dst_lon = _popcount32(dst_lon_mask)
    n_dst_lat = _popcount32(dst_lat_mask)
    src_bmp_bytes = (n_src_lon * n_src_lat + 7) // 8
    if pos_b + src_bmp_bytes > seg_len:
        return -3
    src_bmp = seg[pos_b:pos_b + src_bmp_bytes]
    consumed += src_bmp_bytes
    pos_b += src_bmp_bytes
    dst_bmp_bytes = (n_dst_lon * n_dst_lat + 7) // 8
    if pos_b + dst_bmp_bytes > seg_len:
        return -3
    dst_bmp = seg[pos_b:pos_b + dst_bmp_bytes]
    consumed += dst_bmp_bytes
    pos_b += dst_bmp_bytes
    src_active_lons = _mask_indices(src_lon_mask, n_lons)
    src_active_lats = _mask_indices(src_lat_mask, n_lats)
    dst_active_lons = _mask_indices(dst_lon_mask, n_lons)
    dst_active_lats = _mask_indices(dst_lat_mask, n_lats)
    src_entries = _bitmap_to_entries_embedded(
        src_bmp, n_src_lon, n_src_lat, src_active_lons, src_active_lats, n_lats)
    dst_entries = _bitmap_to_entries_embedded(
        dst_bmp, n_dst_lon, n_dst_lat, dst_active_lons, dst_active_lats, n_lats)
    n_active_src = len(src_entries)
    n_active_dst = len(dst_entries)
    inner_bytes = (n_active_src * n_active_dst + 7) // 8
    if pos_b + inner_bytes > seg_len:
        return -3
    inner = seg[pos_b:pos_b + inner_bytes]
    consumed += inner_bytes
    for si in range(n_active_src):
        for di in range(n_active_dst):
            if _bit_get(inner, si * n_active_dst + di):
                _bit_set(matrix_bits, src_entries[si] * N + dst_entries[di])
    return consumed


def _query_field_from(field_bits, src_fi, max_out):
    out = []
    for d in range(GC_FIELDS):
        if len(out) >= max_out:
            break
        if _bit_get(field_bits, src_fi * GC_FIELDS + d):
            out.append(d)
    return out


def _query_field_to(field_bits, dst_fi, max_out):
    out = []
    for s in range(GC_FIELDS):
        if len(out) >= max_out:
            break
        if _bit_get(field_bits, s * GC_FIELDS + dst_fi):
            out.append(s)
    return out
