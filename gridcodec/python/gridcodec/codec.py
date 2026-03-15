"""
GridCodec — hierarchical dimensional-projection codec for Maidenhead grid
propagation matrices. Full-featured: encode, decode, set, from, to.
Wire format compatible with C/JS/Java implementations.
"""
from __future__ import division

import struct

# ---------------------------------------------------------------------------
# Constants (match C wire format)
# ---------------------------------------------------------------------------
GC_FIELD_LONS = 18
GC_FIELD_LATS = 18
GC_FIELDS = GC_FIELD_LONS * GC_FIELD_LATS  # 324
GC_SQ_LONS = 10
GC_SQ_LATS = 10
GC_SQUARES = GC_SQ_LONS * GC_SQ_LATS  # 100
GC_GRIDS = GC_FIELDS * GC_SQUARES  # 32400

GC_FIELD_MATRIX_BYTES = (GC_FIELDS * GC_FIELDS + 7) // 8   # 13122
GC_SQ_MATRIX_BYTES = (GC_SQUARES * GC_SQUARES + 7) // 8    # 1250

GC_VERSION = 0x01
GC_FLAG_LAYER2 = 0x01

GC_ERR_INVALID = -1
GC_ERR_OVERFLOW = -2
GC_ERR_FORMAT = -3
GC_ERR_CAPACITY = -4

# Popcount table for bytes (0-255)
_POPCOUNT_TABLE = bytes(
    [0, 1, 1, 2, 1, 2, 2, 3, 1, 2, 2, 3, 2, 3, 3, 4,
     1, 2, 2, 3, 2, 3, 3, 4, 2, 3, 3, 4, 3, 4, 4, 5,
     1, 2, 2, 3, 2, 3, 3, 4, 2, 3, 3, 4, 3, 4, 4, 5,
     2, 3, 3, 4, 3, 4, 4, 5, 3, 4, 4, 5, 4, 5, 5, 6,
     1, 2, 2, 3, 2, 3, 3, 4, 2, 3, 3, 4, 3, 4, 4, 5,
     2, 3, 3, 4, 3, 4, 4, 5, 3, 4, 4, 5, 4, 5, 5, 6,
     2, 3, 3, 4, 3, 4, 4, 5, 3, 4, 4, 5, 4, 5, 5, 6,
     3, 4, 4, 5, 4, 5, 5, 6, 4, 5, 5, 6, 5, 6, 6, 7,
     1, 2, 2, 3, 2, 3, 3, 4, 2, 3, 3, 4, 3, 4, 4, 5,
     2, 3, 3, 4, 3, 4, 4, 5, 3, 4, 4, 5, 4, 5, 5, 6,
     2, 3, 3, 4, 3, 4, 4, 5, 3, 4, 4, 5, 4, 5, 5, 6,
     3, 4, 4, 5, 4, 5, 5, 6, 4, 5, 5, 6, 5, 6, 6, 7,
     2, 3, 3, 4, 3, 4, 4, 5, 3, 4, 4, 5, 4, 5, 5, 6,
     3, 4, 4, 5, 4, 5, 5, 6, 4, 5, 5, 6, 5, 6, 6, 7,
     3, 4, 4, 5, 4, 5, 5, 6, 4, 5, 5, 6, 5, 6, 6, 7,
     4, 5, 5, 6, 5, 6, 6, 7, 5, 6, 6, 7, 6, 7, 7, 8]
)


def _bit_get(buf, bit):
    return (buf[bit >> 3] >> (bit & 7)) & 1


def _bit_set(buf, bit):
    buf[bit >> 3] |= 1 << (bit & 7)


def _popcount32(v):
    v = v & 0xFFFFFFFF
    return (_POPCOUNT_TABLE[v & 0xFF] + _POPCOUNT_TABLE[(v >> 8) & 0xFF] +
            _POPCOUNT_TABLE[(v >> 16) & 0xFF] + _POPCOUNT_TABLE[(v >> 24) & 0xFF])


def _popcount_buf(buf, nbytes):
    return sum(_POPCOUNT_TABLE[buf[i]] for i in range(nbytes))


def _pack_mask(buf, pos, mask, nbits):
    for i in range(nbits):
        if mask & (1 << i):
            _bit_set(buf, pos[0])
        pos[0] += 1


def _unpack_mask(buf, pos, nbits):
    mask = 0
    for i in range(nbits):
        if _bit_get(buf, pos[0]):
            mask |= 1 << i
        pos[0] += 1
    return mask


def _mask_indices(mask, nbits):
    return [i for i in range(nbits) if mask & (1 << i)]


# ---------------------------------------------------------------------------
# Helpers (public API)
# ---------------------------------------------------------------------------

def field_index(name):
    """'FN' -> 0..323, -1 if invalid. Case-insensitive."""
    if not name or len(name) < 2:
        return -1
    c0, c1 = name[0].upper(), name[1].upper()
    if not ('A' <= c0 <= 'R' and 'A' <= c1 <= 'R'):
        return -1
    return (ord(c0) - ord('A')) * GC_FIELD_LATS + (ord(c1) - ord('A'))


def field_name(idx):
    """0..323 -> 'FN'. Returns '??' if out of range."""
    if idx < 0 or idx >= GC_FIELDS:
        return '??'
    return chr(ord('A') + idx // GC_FIELD_LATS) + chr(ord('A') + idx % GC_FIELD_LATS)


def grid_index(name):
    """'FN31' -> 0..32399, -1 if invalid. Case-insensitive for letters."""
    if not name or len(name) < 4:
        return -1
    c0, c1 = name[0].upper(), name[1].upper()
    c2, c3 = name[2], name[3]
    if not ('A' <= c0 <= 'R' and 'A' <= c1 <= 'R'):
        return -1
    if not ('0' <= c2 <= '9' and '0' <= c3 <= '9'):
        return -1
    fi = (ord(c0) - ord('A')) * GC_FIELD_LATS + (ord(c1) - ord('A'))
    si = (ord(c2) - ord('0')) * GC_SQ_LATS + (ord(c3) - ord('0'))
    return fi * GC_SQUARES + si


def grid_name(idx):
    """0..32399 -> 'FN31'. Returns '????' if out of range."""
    if idx < 0 or idx >= GC_GRIDS:
        return '????'
    fi = idx // GC_SQUARES
    si = idx % GC_SQUARES
    return (chr(ord('A') + fi // GC_FIELD_LATS) +
            chr(ord('A') + fi % GC_FIELD_LATS) +
            chr(ord('0') + si // GC_SQ_LATS) +
            chr(ord('0') + si % GC_SQ_LATS))


def grid_to_field(grid_idx):
    if grid_idx < 0 or grid_idx >= GC_GRIDS:
        return -1
    return grid_idx // GC_SQUARES


def grid_to_square(grid_idx):
    if grid_idx < 0 or grid_idx >= GC_GRIDS:
        return -1
    return grid_idx % GC_SQUARES


# ---------------------------------------------------------------------------
# Dimensional projection (internal)
# ---------------------------------------------------------------------------

def _compute_dim_masks(matrix_bits, n_lons, n_lats):
    N = n_lons * n_lats
    src_lon_mask = src_lat_mask = dst_lon_mask = dst_lat_mask = 0
    for s in range(N):
        for d in range(N):
            if _bit_get(matrix_bits, s * N + d):
                s_lon, s_lat = s // n_lats, s % n_lats
                d_lon, d_lat = d // n_lats, d % n_lats
                src_lon_mask |= 1 << s_lon
                src_lat_mask |= 1 << s_lat
                dst_lon_mask |= 1 << d_lon
                dst_lat_mask |= 1 << d_lat
    return src_lon_mask, src_lat_mask, dst_lon_mask, dst_lat_mask


def _build_entry_bitmap(matrix_bits, n_lons, n_lats,
                        active_lons, active_lats, is_src):
    N = n_lons * n_lats
    n_al = len(active_lons)
    n_alat = len(active_lats)
    bmp_size = n_al * n_alat
    nbytes = (bmp_size + 7) // 8
    bitmap_out = bytearray(nbytes)
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
                _bit_set(bitmap_out, bit_idx)
                count += 1
    return bitmap_out, count


def _bitmap_to_entries(bitmap, n_active_lons, n_active_lats,
                      active_lons, active_lats, lats_per_row):
    out = []
    for li in range(n_active_lons):
        for ai in range(n_active_lats):
            bit_idx = li * n_active_lats + ai
            if _bit_get(bitmap, bit_idx):
                out.append(active_lons[li] * lats_per_row + active_lats[ai])
    return out


def _build_inner_matrix(matrix_bits, n_lons, n_lats,
                       src_entries, dst_entries):
    N = n_lons * n_lats
    n_src, n_dst = len(src_entries), len(dst_entries)
    nbytes = (n_src * n_dst + 7) // 8
    inner = bytearray(nbytes)
    for si in range(n_src):
        for di in range(n_dst):
            if _bit_get(matrix_bits, src_entries[si] * N + dst_entries[di]):
                _bit_set(inner, si * n_dst + di)
    return inner


def _encode_projection(matrix_bits, n_lons, n_lats, buf, offset, cap):
    src_lon_mask, src_lat_mask, dst_lon_mask, dst_lat_mask = \
        _compute_dim_masks(matrix_bits, n_lons, n_lats)
    n_src_lon = _popcount32(src_lon_mask)
    n_src_lat = _popcount32(src_lat_mask)
    n_dst_lon = _popcount32(dst_lon_mask)
    n_dst_lat = _popcount32(dst_lat_mask)

    mask_bits = n_lons * 2 + n_lats * 2
    mask_bytes = (mask_bits + 7) // 8
    if offset + mask_bytes > cap:
        return GC_ERR_OVERFLOW
    tmp = bytearray(mask_bytes)
    pos = [0]
    _pack_mask(tmp, pos, src_lon_mask, n_lons)
    _pack_mask(tmp, pos, src_lat_mask, n_lats)
    _pack_mask(tmp, pos, dst_lon_mask, n_lons)
    _pack_mask(tmp, pos, dst_lat_mask, n_lats)
    buf[offset:offset + mask_bytes] = tmp
    written = mask_bytes
    pos_b = offset + mask_bytes

    src_active_lons = _mask_indices(src_lon_mask, n_lons)
    src_active_lats = _mask_indices(src_lat_mask, n_lats)
    dst_active_lons = _mask_indices(dst_lon_mask, n_lons)
    dst_active_lats = _mask_indices(dst_lat_mask, n_lats)

    src_bmp, n_active_src = _build_entry_bitmap(
        matrix_bits, n_lons, n_lats,
        src_active_lons, src_active_lats, True)
    src_bmp_bytes = (n_src_lon * n_src_lat + 7) // 8
    if pos_b + src_bmp_bytes > cap:
        return GC_ERR_OVERFLOW
    buf[pos_b:pos_b + src_bmp_bytes] = src_bmp[:src_bmp_bytes]
    written += src_bmp_bytes
    pos_b += src_bmp_bytes

    dst_bmp, n_active_dst = _build_entry_bitmap(
        matrix_bits, n_lons, n_lats,
        dst_active_lons, dst_active_lats, False)
    dst_bmp_bytes = (n_dst_lon * n_dst_lat + 7) // 8
    if pos_b + dst_bmp_bytes > cap:
        return GC_ERR_OVERFLOW
    buf[pos_b:pos_b + dst_bmp_bytes] = dst_bmp[:dst_bmp_bytes]
    written += dst_bmp_bytes
    pos_b += dst_bmp_bytes

    src_entries = _bitmap_to_entries(
        src_bmp, n_src_lon, n_src_lat, src_active_lons, src_active_lats, n_lats)
    dst_entries = _bitmap_to_entries(
        dst_bmp, n_dst_lon, n_dst_lat, dst_active_lons, dst_active_lats, n_lats)
    inner = _build_inner_matrix(matrix_bits, n_lons, n_lats, src_entries, dst_entries)
    inner_bytes = (n_active_src * n_active_dst + 7) // 8
    if pos_b + inner_bytes > cap:
        return GC_ERR_OVERFLOW
    buf[pos_b:pos_b + inner_bytes] = inner[:inner_bytes]
    written += inner_bytes
    return written


def _decode_projection(buf, offset, length, n_lons, n_lats, matrix_bits):
    N = n_lons * n_lats
    matrix_bytes = (N * N + 7) // 8
    for i in range(matrix_bytes):
        matrix_bits[i] = 0
    segment = buf[offset:offset + length]
    seg_len = len(segment)

    mask_bits = n_lons * 2 + n_lats * 2
    mask_bytes = (mask_bits + 7) // 8
    if mask_bytes > seg_len:
        return GC_ERR_FORMAT
    pos = [0]
    src_lon_mask = _unpack_mask(segment, pos, n_lons)
    src_lat_mask = _unpack_mask(segment, pos, n_lats)
    dst_lon_mask = _unpack_mask(segment, pos, n_lons)
    dst_lat_mask = _unpack_mask(segment, pos, n_lats)
    consumed = mask_bytes
    pos_b = mask_bytes

    n_src_lon = _popcount32(src_lon_mask)
    n_src_lat = _popcount32(src_lat_mask)
    n_dst_lon = _popcount32(dst_lon_mask)
    n_dst_lat = _popcount32(dst_lat_mask)

    src_bmp_bits = n_src_lon * n_src_lat
    src_bmp_bytes = (src_bmp_bits + 7) // 8
    if pos_b + src_bmp_bytes > seg_len:
        return GC_ERR_FORMAT
    src_bmp = segment[pos_b:pos_b + src_bmp_bytes]
    consumed += src_bmp_bytes
    pos_b += src_bmp_bytes

    dst_bmp_bits = n_dst_lon * n_dst_lat
    dst_bmp_bytes = (dst_bmp_bits + 7) // 8
    if pos_b + dst_bmp_bytes > seg_len:
        return GC_ERR_FORMAT
    dst_bmp = segment[pos_b:pos_b + dst_bmp_bytes]
    consumed += dst_bmp_bytes
    pos_b += dst_bmp_bytes

    src_active_lons = _mask_indices(src_lon_mask, n_lons)
    src_active_lats = _mask_indices(src_lat_mask, n_lats)
    dst_active_lons = _mask_indices(dst_lon_mask, n_lons)
    dst_active_lats = _mask_indices(dst_lat_mask, n_lats)

    src_entries = _bitmap_to_entries(
        src_bmp, n_src_lon, n_src_lat, src_active_lons, src_active_lats, n_lats)
    dst_entries = _bitmap_to_entries(
        dst_bmp, n_dst_lon, n_dst_lat, dst_active_lons, dst_active_lats, n_lats)
    n_active_src = len(src_entries)
    n_active_dst = len(dst_entries)

    inner_bits = n_active_src * n_active_dst
    inner_bytes = (inner_bits + 7) // 8
    if pos_b + inner_bytes > seg_len:
        return GC_ERR_FORMAT
    inner = segment[pos_b:pos_b + inner_bytes]
    consumed += inner_bytes

    for si in range(n_active_src):
        for di in range(n_active_dst):
            if _bit_get(inner, si * n_active_dst + di):
                _bit_set(matrix_bits, src_entries[si] * N + dst_entries[di])
    return consumed


# ---------------------------------------------------------------------------
# Matrix and public API
# ---------------------------------------------------------------------------

class GridCodecMatrix(object):
    """Full-featured propagation matrix: set, encode, decode, from, to."""

    def __init__(self):
        self.field_bits = bytearray(GC_FIELD_MATRIX_BYTES)
        self.pair_src = []
        self.pair_dst = []
        self.sq_bits = []  # list of bytearray(GC_SQ_MATRIX_BYTES)

    def set(self, from4, to4):
        """Add a 4-char -> 4-char propagation path. Idempotent."""
        src_gi = grid_index(from4)
        dst_gi = grid_index(to4)
        if src_gi < 0 or dst_gi < 0:
            return GC_ERR_INVALID
        src_fi = src_gi // GC_SQUARES
        dst_fi = dst_gi // GC_SQUARES
        src_si = src_gi % GC_SQUARES
        dst_si = dst_gi % GC_SQUARES
        _bit_set(self.field_bits, src_fi * GC_FIELDS + dst_fi)
        pair_idx = self._find_or_create_pair(src_fi, dst_fi)
        if pair_idx < 0:
            return pair_idx
        _bit_set(self.sq_bits[pair_idx], src_si * GC_SQUARES + dst_si)
        return 0

    def _find_or_create_pair(self, src_fi, dst_fi):
        for i in range(len(self.pair_src)):
            if self.pair_src[i] == src_fi and self.pair_dst[i] == dst_fi:
                return i
        self.pair_src.append(src_fi)
        self.pair_dst.append(dst_fi)
        self.sq_bits.append(bytearray(GC_SQ_MATRIX_BYTES))
        return len(self.sq_bits) - 1

    def _find_pair(self, src_fi, dst_fi):
        for i in range(len(self.pair_src)):
            if self.pair_src[i] == src_fi and self.pair_dst[i] == dst_fi:
                return i
        return -1

    def encode(self, buf=None, cap=None):
        """Serialize to wire format. Returns (bytes, length) or (None, negative error)."""
        if cap is None:
            cap = 1024 * 1024
        if buf is None:
            buf = bytearray(cap)
        elif isinstance(buf, (bytes, bytearray)):
            buf = bytearray(buf)
            if cap is None:
                cap = len(buf)
        else:
            buf = bytearray(cap)
        if cap < 2:
            return None, GC_ERR_OVERFLOW
        has_l2 = 1 if len(self.pair_src) > 0 else 0
        buf[0] = GC_VERSION
        buf[1] = GC_FLAG_LAYER2 if has_l2 else 0
        written = 2
        l1_bytes = _encode_projection(
            self.field_bits, GC_FIELD_LONS, GC_FIELD_LATS,
            buf, written, cap)
        if l1_bytes < 0:
            return None, l1_bytes
        written += l1_bytes
        if not has_l2:
            return bytes(buf[:written]), written
        # Layer 2: get active field pairs in encoding order
        src_lon_mask, src_lat_mask, dst_lon_mask, dst_lat_mask = \
            _compute_dim_masks(self.field_bits, GC_FIELD_LONS, GC_FIELD_LATS)
        src_active_lons = _mask_indices(src_lon_mask, GC_FIELD_LONS)
        src_active_lats = _mask_indices(src_lat_mask, GC_FIELD_LATS)
        dst_active_lons = _mask_indices(dst_lon_mask, GC_FIELD_LONS)
        dst_active_lats = _mask_indices(dst_lat_mask, GC_FIELD_LATS)
        src_bmp, _ = _build_entry_bitmap(
            self.field_bits, GC_FIELD_LONS, GC_FIELD_LATS,
            src_active_lons, src_active_lats, True)
        dst_bmp, _ = _build_entry_bitmap(
            self.field_bits, GC_FIELD_LONS, GC_FIELD_LATS,
            dst_active_lons, dst_active_lats, False)
        n_sl, n_sa = len(src_active_lons), len(src_active_lats)
        n_dl, n_da = len(dst_active_lons), len(dst_active_lats)
        src_entries = _bitmap_to_entries(
            src_bmp, n_sl, n_sa, src_active_lons, src_active_lats, GC_FIELD_LATS)
        dst_entries = _bitmap_to_entries(
            dst_bmp, n_dl, n_da, dst_active_lons, dst_active_lats, GC_FIELD_LATS)
        sqcfg_n_lons, sqcfg_n_lats = GC_SQ_LONS, GC_SQ_LATS
        for si in range(len(src_entries)):
            for di in range(len(dst_entries)):
                src_fi = src_entries[si]
                dst_fi = dst_entries[di]
                if not _bit_get(self.field_bits, src_fi * GC_FIELDS + dst_fi):
                    continue
                pair_idx = self._find_pair(src_fi, dst_fi)
                if pair_idx < 0:
                    need = (sqcfg_n_lons * 2 + sqcfg_n_lats * 2 + 7) // 8
                    if written + need > cap:
                        return None, GC_ERR_OVERFLOW
                    buf[written:written + need] = bytearray(need)
                    written += need
                else:
                    sub = _encode_projection(
                        self.sq_bits[pair_idx], sqcfg_n_lons, sqcfg_n_lats,
                        buf, written, cap)
                    if sub < 0:
                        return None, sub
                    written += sub
        return bytes(buf[:written]), written

    def decode(self, data):
        """Deserialize from wire format. Returns bytes consumed or negative error."""
        if len(data) < 2:
            return GC_ERR_FORMAT
        if data[0] != GC_VERSION:
            return GC_ERR_FORMAT
        flags = data[1]
        consumed = 2
        self.field_bits = bytearray(GC_FIELD_MATRIX_BYTES)
        self.pair_src = []
        self.pair_dst = []
        self.sq_bits = []
        l1_bytes = _decode_projection(
            data, consumed, len(data) - consumed,
            GC_FIELD_LONS, GC_FIELD_LATS, self.field_bits)
        if l1_bytes < 0:
            return l1_bytes
        consumed += l1_bytes
        if not (flags & GC_FLAG_LAYER2):
            return consumed
        # Decode Layer 2: same order as encode
        src_lon_mask, src_lat_mask, dst_lon_mask, dst_lat_mask = \
            _compute_dim_masks(self.field_bits, GC_FIELD_LONS, GC_FIELD_LATS)
        src_active_lons = _mask_indices(src_lon_mask, GC_FIELD_LONS)
        src_active_lats = _mask_indices(src_lat_mask, GC_FIELD_LATS)
        dst_active_lons = _mask_indices(dst_lon_mask, GC_FIELD_LONS)
        dst_active_lats = _mask_indices(dst_lat_mask, GC_FIELD_LATS)
        src_bmp, _ = _build_entry_bitmap(
            self.field_bits, GC_FIELD_LONS, GC_FIELD_LATS,
            src_active_lons, src_active_lats, True)
        dst_bmp, _ = _build_entry_bitmap(
            self.field_bits, GC_FIELD_LONS, GC_FIELD_LATS,
            dst_active_lons, dst_active_lats, False)
        src_entries = _bitmap_to_entries(
            src_bmp, len(src_active_lons), len(src_active_lats),
            src_active_lons, src_active_lats, GC_FIELD_LATS)
        dst_entries = _bitmap_to_entries(
            dst_bmp, len(dst_active_lons), len(dst_active_lats),
            dst_active_lons, dst_active_lats, GC_FIELD_LATS)
        for si in range(len(src_entries)):
            for di in range(len(dst_entries)):
                src_fi = src_entries[si]
                dst_fi = dst_entries[di]
                if not _bit_get(self.field_bits, src_fi * GC_FIELDS + dst_fi):
                    continue
                pair_idx = self._find_or_create_pair(src_fi, dst_fi)
                sub = _decode_projection(
                    data, consumed, len(data) - consumed,
                    GC_SQ_LONS, GC_SQ_LATS, self.sq_bits[pair_idx])
                if sub < 0:
                    return sub
                consumed += sub
        return consumed

    def gc_from(self, grid, max_out=32400):
        """Query reachable destinations from grid (2- or 4-char). Returns list of indices."""
        if not grid or max_out <= 0:
            return []
        grid = str(grid).strip()
        if len(grid) == 2:
            fi = field_index(grid)
            if fi < 0:
                return []
            return self._query_field_from(fi, max_out)
        if len(grid) >= 4:
            gi = grid_index(grid)
            if gi < 0:
                return []
            return self._query_grid_from(gi, max_out)
        return []

    def gc_to(self, grid, max_out=32400):
        """Query sources that can reach grid (2- or 4-char). Returns list of indices."""
        if not grid or max_out <= 0:
            return []
        grid = str(grid).strip()
        if len(grid) == 2:
            fi = field_index(grid)
            if fi < 0:
                return []
            return self._query_field_to(fi, max_out)
        if len(grid) >= 4:
            gi = grid_index(grid)
            if gi < 0:
                return []
            return self._query_grid_to(gi, max_out)
        return []

    def _query_field_from(self, src_fi, max_out):
        out = []
        for d in range(GC_FIELDS):
            if len(out) >= max_out:
                break
            if _bit_get(self.field_bits, src_fi * GC_FIELDS + d):
                out.append(d)
        return out

    def _query_field_to(self, dst_fi, max_out):
        out = []
        for s in range(GC_FIELDS):
            if len(out) >= max_out:
                break
            if _bit_get(self.field_bits, s * GC_FIELDS + dst_fi):
                out.append(s)
        return out

    def _query_grid_from(self, src_gi, max_out):
        src_fi = src_gi // GC_SQUARES
        src_si = src_gi % GC_SQUARES
        out = []
        for dst_fi in range(GC_FIELDS):
            if not _bit_get(self.field_bits, src_fi * GC_FIELDS + dst_fi):
                continue
            pair_idx = self._find_pair(src_fi, dst_fi)
            if pair_idx < 0:
                continue
            for dst_si in range(GC_SQUARES):
                if len(out) >= max_out:
                    return out
                if _bit_get(self.sq_bits[pair_idx], src_si * GC_SQUARES + dst_si):
                    out.append(dst_fi * GC_SQUARES + dst_si)
        return out

    def _query_grid_to(self, dst_gi, max_out):
        dst_fi = dst_gi // GC_SQUARES
        dst_si = dst_gi % GC_SQUARES
        out = []
        for src_fi in range(GC_FIELDS):
            if not _bit_get(self.field_bits, src_fi * GC_FIELDS + dst_fi):
                continue
            pair_idx = self._find_pair(src_fi, dst_fi)
            if pair_idx < 0:
                continue
            for src_si in range(GC_SQUARES):
                if len(out) >= max_out:
                    return out
                if _bit_get(self.sq_bits[pair_idx], src_si * GC_SQUARES + dst_si):
                    out.append(src_fi * GC_SQUARES + src_si)
        return out
