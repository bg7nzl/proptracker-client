/*
 * gridcodec.h — Single-header Maidenhead propagation matrix codec
 *
 * Hierarchical dimensional-projection compression for 32,400×32,400
 * binary propagation matrices (4-char Maidenhead grid pairs).
 *
 * Compile-time modes:
 *   Default        — full encode/decode/query, uses malloc, ~11 KB typical output
 *   GC_EMBEDDED    — decode+query only, zero malloc, ~13 KB static RAM
 *
 * Usage:
 *   #include "gridcodec.h"          // declarations
 *   // In exactly ONE .c file:
 *   #define GRIDCODEC_IMPLEMENTATION
 *   #include "gridcodec.h"
 */

#ifndef GRIDCODEC_H
#define GRIDCODEC_H

#include <stdint.h>
#include <string.h>

#ifndef GC_EMBEDDED
#include <stdlib.h>
#endif

/* ================================================================
 *  Constants
 * ================================================================ */

#define GC_FIELD_LONS   18
#define GC_FIELD_LATS   18
#define GC_FIELDS       (GC_FIELD_LONS * GC_FIELD_LATS)   /* 324 */
#define GC_SQ_LONS      10
#define GC_SQ_LATS      10
#define GC_SQUARES      (GC_SQ_LONS * GC_SQ_LATS)         /* 100 */
#define GC_GRIDS        (GC_FIELDS * GC_SQUARES)           /* 32400 */

#define GC_FIELD_MATRIX_BYTES  ((GC_FIELDS * GC_FIELDS + 7) / 8)  /* 13122 */
#define GC_SQ_MATRIX_BYTES     ((GC_SQUARES * GC_SQUARES + 7) / 8) /* 1250 */

#define GC_VERSION      0x01
#define GC_FLAG_LAYER2  0x01

#define GC_ERR_INVALID  (-1)
#define GC_ERR_OVERFLOW (-2)
#define GC_ERR_FORMAT   (-3)
#define GC_ERR_CAPACITY (-4)

/* ================================================================
 *  Types
 * ================================================================ */

#ifdef GC_EMBEDDED

typedef struct {
    uint8_t field_bits[GC_FIELD_MATRIX_BYTES];
} gc_matrix_t;

#else /* Desktop / Server */

typedef struct {
    uint8_t   field_bits[GC_FIELD_MATRIX_BYTES];
    uint16_t  *pair_src;
    uint16_t  *pair_dst;
    uint8_t   (*sq_bits)[GC_SQ_MATRIX_BYTES];
    int       n_pairs;
    int       pairs_cap;
} gc_matrix_t;

#endif

/* ================================================================
 *  Primary API
 * ================================================================ */

static void gc_init(gc_matrix_t *m);
static int  gc_decode(const uint8_t *data, int len, gc_matrix_t *m);
static int  gc_from(const gc_matrix_t *m, const char *grid, int *out, int max_out);
static int  gc_to(const gc_matrix_t *m, const char *grid, int *out, int max_out);

#ifndef GC_EMBEDDED
static void gc_free(gc_matrix_t *m);
static int  gc_set(gc_matrix_t *m, const char *from4, const char *to4);
static int  gc_encode(const gc_matrix_t *m, uint8_t *buf, int cap);
#endif

/* ================================================================
 *  Helper — index / name conversion
 * ================================================================ */

static int  gc_field_index(const char *name);
static void gc_field_name(int idx, char out[3]);
static int  gc_grid_index(const char *name);
static void gc_grid_name(int idx, char out[5]);
static int  gc_grid_to_field(int grid_idx);
static int  gc_grid_to_square(int grid_idx);

/* ================================================================
 *  IMPLEMENTATION
 * ================================================================ */
#ifdef GRIDCODEC_IMPLEMENTATION

/* ----------------------------------------------------------------
 *  Internal bit utilities
 * ---------------------------------------------------------------- */

static const uint8_t gc__popcount_table[256] = {
    0,1,1,2,1,2,2,3,1,2,2,3,2,3,3,4,1,2,2,3,2,3,3,4,2,3,3,4,3,4,4,5,
    1,2,2,3,2,3,3,4,2,3,3,4,3,4,4,5,2,3,3,4,3,4,4,5,3,4,4,5,4,5,5,6,
    1,2,2,3,2,3,3,4,2,3,3,4,3,4,4,5,2,3,3,4,3,4,4,5,3,4,4,5,4,5,5,6,
    2,3,3,4,3,4,4,5,3,4,4,5,4,5,5,6,3,4,4,5,4,5,5,6,4,5,5,6,5,6,6,7,
    1,2,2,3,2,3,3,4,2,3,3,4,3,4,4,5,2,3,3,4,3,4,4,5,3,4,4,5,4,5,5,6,
    2,3,3,4,3,4,4,5,3,4,4,5,4,5,5,6,3,4,4,5,4,5,5,6,4,5,5,6,5,6,6,7,
    2,3,3,4,3,4,4,5,3,4,4,5,4,5,5,6,3,4,4,5,4,5,5,6,4,5,5,6,5,6,6,7,
    3,4,4,5,4,5,5,6,4,5,5,6,5,6,6,7,4,5,5,6,5,6,6,7,5,6,6,7,6,7,7,8
};

static inline int gc__popcount8(uint8_t v) {
    return gc__popcount_table[v];
}

static inline int gc__popcount_buf(const uint8_t *buf, int nbytes) {
    int c = 0;
    for (int i = 0; i < nbytes; i++)
        c += gc__popcount_table[buf[i]];
    return c;
}

static inline int gc__bit_get(const uint8_t *buf, int bit) {
    return (buf[bit >> 3] >> (bit & 7)) & 1;
}

static inline void gc__bit_set(uint8_t *buf, int bit) {
    buf[bit >> 3] |= (uint8_t)(1u << (bit & 7));
}

static inline void gc__bit_clear(uint8_t *buf, int bit) {
    buf[bit >> 3] &= (uint8_t)~(1u << (bit & 7));
}

/* Pack nbits from a mask (max 18 bits) into buf starting at bit offset *pos.
 * Updates *pos. */
static void gc__pack_mask(uint8_t *buf, int *pos, uint32_t mask, int nbits) {
    for (int i = 0; i < nbits; i++) {
        if (mask & (1u << i))
            gc__bit_set(buf, *pos);
        (*pos)++;
    }
}

/* Unpack nbits from buf starting at bit offset *pos into a uint32_t mask. */
static uint32_t gc__unpack_mask(const uint8_t *buf, int *pos, int nbits) {
    uint32_t mask = 0;
    for (int i = 0; i < nbits; i++) {
        if (gc__bit_get(buf, *pos))
            mask |= (1u << i);
        (*pos)++;
    }
    return mask;
}

static inline int gc__popcount32(uint32_t v) {
#if !defined(GC_EMBEDDED) && (defined(__GNUC__) || defined(__clang__))
    return __builtin_popcount(v);
#else
    return gc__popcount_table[v & 0xFF]
         + gc__popcount_table[(v >> 8) & 0xFF]
         + gc__popcount_table[(v >> 16) & 0xFF]
         + gc__popcount_table[(v >> 24) & 0xFF];
#endif
}

/* Build list of set bit indices in a mask. Returns count. */
static int gc__mask_indices(uint32_t mask, int nbits, int *out) {
    int n = 0;
    for (int i = 0; i < nbits; i++)
        if (mask & (1u << i))
            out[n++] = i;
    return n;
}

/* ----------------------------------------------------------------
 *  Helper implementations
 * ---------------------------------------------------------------- */

static int gc_field_index(const char *name) {
    if (!name) return -1;
    char c0 = name[0], c1 = name[1];
    if (c0 >= 'a' && c0 <= 'r') c0 -= 32;
    if (c1 >= 'a' && c1 <= 'r') c1 -= 32;
    if (c0 < 'A' || c0 > 'R' || c1 < 'A' || c1 > 'R') return -1;
    return (c0 - 'A') * GC_FIELD_LATS + (c1 - 'A');
}

static void gc_field_name(int idx, char out[3]) {
    if (idx < 0 || idx >= GC_FIELDS) { out[0] = out[1] = '?'; out[2] = 0; return; }
    out[0] = (char)('A' + (idx / GC_FIELD_LATS));
    out[1] = (char)('A' + (idx % GC_FIELD_LATS));
    out[2] = 0;
}

static int gc_grid_index(const char *name) {
    if (!name || name[0] == 0 || name[1] == 0 || name[2] == 0 || name[3] == 0)
        return -1;
    char c0 = name[0], c1 = name[1], c2 = name[2], c3 = name[3];
    if (c0 >= 'a' && c0 <= 'r') c0 -= 32;
    if (c1 >= 'a' && c1 <= 'r') c1 -= 32;
    if (c0 < 'A' || c0 > 'R' || c1 < 'A' || c1 > 'R') return -1;
    if (c2 < '0' || c2 > '9' || c3 < '0' || c3 > '9') return -1;
    int fi = (c0 - 'A') * GC_FIELD_LATS + (c1 - 'A');
    int si = (c2 - '0') * GC_SQ_LATS + (c3 - '0');
    return fi * GC_SQUARES + si;
}

static void gc_grid_name(int idx, char out[5]) {
    if (idx < 0 || idx >= GC_GRIDS) { out[0]=out[1]=out[2]=out[3]='?'; out[4]=0; return; }
    int fi = idx / GC_SQUARES;
    int si = idx % GC_SQUARES;
    out[0] = (char)('A' + (fi / GC_FIELD_LATS));
    out[1] = (char)('A' + (fi % GC_FIELD_LATS));
    out[2] = (char)('0' + (si / GC_SQ_LATS));
    out[3] = (char)('0' + (si % GC_SQ_LATS));
    out[4] = 0;
}

static int gc_grid_to_field(int grid_idx) {
    if (grid_idx < 0 || grid_idx >= GC_GRIDS) return -1;
    return grid_idx / GC_SQUARES;
}

static int gc_grid_to_square(int grid_idx) {
    if (grid_idx < 0 || grid_idx >= GC_GRIDS) return -1;
    return grid_idx % GC_SQUARES;
}

/* ----------------------------------------------------------------
 *  Internal: dimensional projection encode/decode for a generic
 *  2D bitmap of size (n_lons * n_lats) x (n_lons * n_lats).
 *
 *  The projection works on a matrix whose row/col indices each
 *  decompose into (lon, lat) coordinates.
 * ---------------------------------------------------------------- */

typedef struct {
    int n_lons;
    int n_lats;
} gc__dim_cfg_t;

/* Compute dimension masks for a bitmap matrix.
 * matrix is row-major, total_entries = n_entries * n_entries where
 * n_entries = cfg->n_lons * cfg->n_lats. */
static void gc__compute_dim_masks(
    const uint8_t *matrix_bits, const gc__dim_cfg_t *cfg,
    uint32_t *src_lon_mask, uint32_t *src_lat_mask,
    uint32_t *dst_lon_mask, uint32_t *dst_lat_mask)
{
    int N = cfg->n_lons * cfg->n_lats;
    *src_lon_mask = *src_lat_mask = *dst_lon_mask = *dst_lat_mask = 0;

    for (int s = 0; s < N; s++) {
        for (int d = 0; d < N; d++) {
            if (gc__bit_get(matrix_bits, s * N + d)) {
                int s_lon = s / cfg->n_lats;
                int s_lat = s % cfg->n_lats;
                int d_lon = d / cfg->n_lats;
                int d_lat = d % cfg->n_lats;
                *src_lon_mask |= (1u << s_lon);
                *src_lat_mask |= (1u << s_lat);
                *dst_lon_mask |= (1u << d_lon);
                *dst_lat_mask |= (1u << d_lat);
            }
        }
    }
}

/* Build the field/square bitmap within the bounding box.
 * active_lons/lats are the indices of set bits in the dimension masks.
 * Returns popcount of the bitmap (number of active entries). */
static int gc__build_entry_bitmap(
    const uint8_t *matrix_bits, const gc__dim_cfg_t *cfg,
    const int *active_lons, int n_active_lons,
    const int *active_lats, int n_active_lats,
    int is_src, /* 1 = build source bitmap, 0 = build dst bitmap */
    uint8_t *bitmap_out)
{
    int N = cfg->n_lons * cfg->n_lats;
    int bmp_size = n_active_lons * n_active_lats;
    int nbytes = (bmp_size + 7) / 8;
    memset(bitmap_out, 0, (size_t)nbytes);

    int count = 0;
    for (int li = 0; li < n_active_lons; li++) {
        for (int ai = 0; ai < n_active_lats; ai++) {
            int entry = active_lons[li] * cfg->n_lats + active_lats[ai];
            int bit_idx = li * n_active_lats + ai;

            int has_activity = 0;
            if (is_src) {
                for (int d = 0; d < N && !has_activity; d++)
                    has_activity = gc__bit_get(matrix_bits, entry * N + d);
            } else {
                for (int s = 0; s < N && !has_activity; s++)
                    has_activity = gc__bit_get(matrix_bits, s * N + entry);
            }
            if (has_activity) {
                gc__bit_set(bitmap_out, bit_idx);
                count++;
            }
        }
    }
    return count;
}

/* Build the inner matrix between active sources and active destinations. */
static void gc__build_inner_matrix(
    const uint8_t *matrix_bits, const gc__dim_cfg_t *cfg,
    const int *src_entries, int n_src,
    const int *dst_entries, int n_dst,
    uint8_t *inner_out)
{
    int N = cfg->n_lons * cfg->n_lats;
    int nbytes = (n_src * n_dst + 7) / 8;
    memset(inner_out, 0, (size_t)nbytes);

    for (int si = 0; si < n_src; si++) {
        for (int di = 0; di < n_dst; di++) {
            if (gc__bit_get(matrix_bits, src_entries[si] * N + dst_entries[di]))
                gc__bit_set(inner_out, si * n_dst + di);
        }
    }
}

/* Expand entry bitmap to a list of absolute entry indices.
 * Returns count. */
static int gc__bitmap_to_entries(
    const uint8_t *bitmap, int n_active_lons, int n_active_lats,
    const int *active_lons, const int *active_lats,
    int lats_per_row, /* cfg->n_lats */
    int *entries_out)
{
    int count = 0;
    for (int li = 0; li < n_active_lons; li++) {
        for (int ai = 0; ai < n_active_lats; ai++) {
            int bit_idx = li * n_active_lats + ai;
            if (gc__bit_get(bitmap, bit_idx)) {
                entries_out[count++] = active_lons[li] * lats_per_row + active_lats[ai];
            }
        }
    }
    return count;
}

/* ----------------------------------------------------------------
 *  Encode one projection layer into buf.
 *  Returns bytes written, or negative on error.
 * ---------------------------------------------------------------- */
#ifndef GC_EMBEDDED

static int gc__encode_projection(
    const uint8_t *matrix_bits, const gc__dim_cfg_t *cfg,
    uint8_t *buf, int cap)
{
    uint32_t src_lon_mask, src_lat_mask, dst_lon_mask, dst_lat_mask;
    gc__compute_dim_masks(matrix_bits, cfg,
        &src_lon_mask, &src_lat_mask, &dst_lon_mask, &dst_lat_mask);

    int n_src_lon = gc__popcount32(src_lon_mask);
    int n_src_lat = gc__popcount32(src_lat_mask);
    int n_dst_lon = gc__popcount32(dst_lon_mask);
    int n_dst_lat = gc__popcount32(dst_lat_mask);

    /* Pack dimension masks */
    int mask_bits = cfg->n_lons * 2 + cfg->n_lats * 2;
    int mask_bytes = (mask_bits + 7) / 8;

    if (cap < mask_bytes) return GC_ERR_OVERFLOW;
    memset(buf, 0, (size_t)mask_bytes);

    int bpos = 0;
    gc__pack_mask(buf, &bpos, src_lon_mask, cfg->n_lons);
    gc__pack_mask(buf, &bpos, src_lat_mask, cfg->n_lats);
    gc__pack_mask(buf, &bpos, dst_lon_mask, cfg->n_lons);
    gc__pack_mask(buf, &bpos, dst_lat_mask, cfg->n_lats);
    int written = mask_bytes;

    /* Source entry bitmap */
    int src_active_lons[18], src_active_lats[18];
    int dst_active_lons[18], dst_active_lats[18];
    gc__mask_indices(src_lon_mask, cfg->n_lons, src_active_lons);
    gc__mask_indices(src_lat_mask, cfg->n_lats, src_active_lats);
    gc__mask_indices(dst_lon_mask, cfg->n_lons, dst_active_lons);
    gc__mask_indices(dst_lat_mask, cfg->n_lats, dst_active_lats);

    int src_bmp_bits = n_src_lon * n_src_lat;
    int src_bmp_bytes = (src_bmp_bits + 7) / 8;
    if (written + src_bmp_bytes > cap) return GC_ERR_OVERFLOW;

    int n_active_src = gc__build_entry_bitmap(
        matrix_bits, cfg,
        src_active_lons, n_src_lon, src_active_lats, n_src_lat,
        1, buf + written);
    written += src_bmp_bytes;

    /* Destination entry bitmap */
    int dst_bmp_bits = n_dst_lon * n_dst_lat;
    int dst_bmp_bytes = (dst_bmp_bits + 7) / 8;
    if (written + dst_bmp_bytes > cap) return GC_ERR_OVERFLOW;

    int n_active_dst = gc__build_entry_bitmap(
        matrix_bits, cfg,
        dst_active_lons, n_dst_lon, dst_active_lats, n_dst_lat,
        0, buf + written);
    written += dst_bmp_bytes;

    /* Build active entry lists for inner matrix */
    int src_entries[GC_FIELDS], dst_entries[GC_FIELDS];
    int ns = gc__bitmap_to_entries(
        buf + mask_bytes, n_src_lon, n_src_lat,
        src_active_lons, src_active_lats, cfg->n_lats, src_entries);
    int nd = gc__bitmap_to_entries(
        buf + mask_bytes + src_bmp_bytes, n_dst_lon, n_dst_lat,
        dst_active_lons, dst_active_lats, cfg->n_lats, dst_entries);
    (void)ns; (void)nd;

    /* Inner matrix */
    int inner_bits = n_active_src * n_active_dst;
    int inner_bytes = (inner_bits + 7) / 8;
    if (written + inner_bytes > cap) return GC_ERR_OVERFLOW;

    gc__build_inner_matrix(matrix_bits, cfg,
        src_entries, n_active_src, dst_entries, n_active_dst,
        buf + written);
    written += inner_bytes;

    return written;
}

#endif /* !GC_EMBEDDED */

/* ----------------------------------------------------------------
 *  Decode one projection layer from buf into matrix_bits.
 *  Returns bytes consumed, or negative on error.
 * ---------------------------------------------------------------- */

static int gc__decode_projection(
    const uint8_t *buf, int len, const gc__dim_cfg_t *cfg,
    uint8_t *matrix_bits)
{
    int N = cfg->n_lons * cfg->n_lats;
    int matrix_bytes = (N * N + 7) / 8;
    memset(matrix_bits, 0, (size_t)matrix_bytes);

    int mask_bits = cfg->n_lons * 2 + cfg->n_lats * 2;
    int mask_bytes = (mask_bits + 7) / 8;
    if (len < mask_bytes) return GC_ERR_FORMAT;

    int bpos = 0;
    uint32_t src_lon_mask = gc__unpack_mask(buf, &bpos, cfg->n_lons);
    uint32_t src_lat_mask = gc__unpack_mask(buf, &bpos, cfg->n_lats);
    uint32_t dst_lon_mask = gc__unpack_mask(buf, &bpos, cfg->n_lons);
    uint32_t dst_lat_mask = gc__unpack_mask(buf, &bpos, cfg->n_lats);

    int n_src_lon = gc__popcount32(src_lon_mask);
    int n_src_lat = gc__popcount32(src_lat_mask);
    int n_dst_lon = gc__popcount32(dst_lon_mask);
    int n_dst_lat = gc__popcount32(dst_lat_mask);

    int consumed = mask_bytes;

    /* Read source entry bitmap */
    int src_bmp_bits = n_src_lon * n_src_lat;
    int src_bmp_bytes = (src_bmp_bits + 7) / 8;
    if (consumed + src_bmp_bytes > len) return GC_ERR_FORMAT;
    const uint8_t *src_bmp = buf + consumed;
    consumed += src_bmp_bytes;

    /* Read destination entry bitmap */
    int dst_bmp_bits = n_dst_lon * n_dst_lat;
    int dst_bmp_bytes = (dst_bmp_bits + 7) / 8;
    if (consumed + dst_bmp_bytes > len) return GC_ERR_FORMAT;
    const uint8_t *dst_bmp = buf + consumed;
    consumed += dst_bmp_bytes;

    /* Expand to entry lists */
    int src_active_lons[18], src_active_lats[18];
    int dst_active_lons[18], dst_active_lats[18];
    gc__mask_indices(src_lon_mask, cfg->n_lons, src_active_lons);
    gc__mask_indices(src_lat_mask, cfg->n_lats, src_active_lats);
    gc__mask_indices(dst_lon_mask, cfg->n_lons, dst_active_lons);
    gc__mask_indices(dst_lat_mask, cfg->n_lats, dst_active_lats);

    int src_entries[GC_FIELDS], dst_entries[GC_FIELDS];
    int n_active_src = gc__bitmap_to_entries(
        src_bmp, n_src_lon, n_src_lat,
        src_active_lons, src_active_lats, cfg->n_lats, src_entries);
    int n_active_dst = gc__bitmap_to_entries(
        dst_bmp, n_dst_lon, n_dst_lat,
        dst_active_lons, dst_active_lats, cfg->n_lats, dst_entries);

    /* Read inner matrix and reconstruct */
    int inner_bits = n_active_src * n_active_dst;
    int inner_bytes = (inner_bits + 7) / 8;
    if (consumed + inner_bytes > len) return GC_ERR_FORMAT;
    const uint8_t *inner = buf + consumed;

    for (int si = 0; si < n_active_src; si++) {
        for (int di = 0; di < n_active_dst; di++) {
            if (gc__bit_get(inner, si * n_active_dst + di)) {
                gc__bit_set(matrix_bits, src_entries[si] * N + dst_entries[di]);
            }
        }
    }
    consumed += inner_bytes;

    return consumed;
}

/* ----------------------------------------------------------------
 *  gc_init / gc_free
 * ---------------------------------------------------------------- */

static void gc_init(gc_matrix_t *m) {
    memset(m, 0, sizeof(*m));
}

#ifndef GC_EMBEDDED

static void gc_free(gc_matrix_t *m) {
    if (m->pair_src)  { free(m->pair_src);  m->pair_src = NULL; }
    if (m->pair_dst)  { free(m->pair_dst);  m->pair_dst = NULL; }
    if (m->sq_bits)   { free(m->sq_bits);   m->sq_bits = NULL; }
    m->n_pairs = 0;
    m->pairs_cap = 0;
}

/* ----------------------------------------------------------------
 *  gc_set — add a 4-char → 4-char propagation path
 * ---------------------------------------------------------------- */

static int gc__ensure_pair_cap(gc_matrix_t *m, int needed) {
    if (needed <= m->pairs_cap) return 0;
    int new_cap = m->pairs_cap ? m->pairs_cap * 2 : 64;
    while (new_cap < needed) new_cap *= 2;

    uint16_t *ns = (uint16_t *)realloc(m->pair_src, (size_t)new_cap * sizeof(uint16_t));
    uint16_t *nd = (uint16_t *)realloc(m->pair_dst, (size_t)new_cap * sizeof(uint16_t));
    uint8_t (*nb)[GC_SQ_MATRIX_BYTES] = (uint8_t (*)[GC_SQ_MATRIX_BYTES])
        realloc(m->sq_bits, (size_t)new_cap * GC_SQ_MATRIX_BYTES);
    if (!ns || !nd || !nb) {
        if (ns) m->pair_src = ns;
        if (nd) m->pair_dst = nd;
        if (nb) m->sq_bits = nb;
        return GC_ERR_CAPACITY;
    }
    /* Zero new entries */
    for (int i = m->pairs_cap; i < new_cap; i++) {
        memset(nb[i], 0, GC_SQ_MATRIX_BYTES);
    }
    m->pair_src = ns;
    m->pair_dst = nd;
    m->sq_bits = nb;
    m->pairs_cap = new_cap;
    return 0;
}

static int gc__find_or_create_pair(gc_matrix_t *m, int src_fi, int dst_fi) {
    for (int i = 0; i < m->n_pairs; i++) {
        if (m->pair_src[i] == (uint16_t)src_fi &&
            m->pair_dst[i] == (uint16_t)dst_fi)
            return i;
    }
    int rc = gc__ensure_pair_cap(m, m->n_pairs + 1);
    if (rc < 0) return rc;
    int idx = m->n_pairs++;
    m->pair_src[idx] = (uint16_t)src_fi;
    m->pair_dst[idx] = (uint16_t)dst_fi;
    memset(m->sq_bits[idx], 0, GC_SQ_MATRIX_BYTES);
    return idx;
}

static int gc_set(gc_matrix_t *m, const char *from4, const char *to4) {
    int src_gi = gc_grid_index(from4);
    int dst_gi = gc_grid_index(to4);
    if (src_gi < 0 || dst_gi < 0) return GC_ERR_INVALID;

    int src_fi = src_gi / GC_SQUARES;
    int dst_fi = dst_gi / GC_SQUARES;
    int src_si = src_gi % GC_SQUARES;
    int dst_si = dst_gi % GC_SQUARES;

    /* Set Layer 1 */
    gc__bit_set(m->field_bits, src_fi * GC_FIELDS + dst_fi);

    /* Set Layer 2 */
    int pair_idx = gc__find_or_create_pair(m, src_fi, dst_fi);
    if (pair_idx < 0) return pair_idx;
    gc__bit_set(m->sq_bits[pair_idx], src_si * GC_SQUARES + dst_si);

    return 0;
}

/* ----------------------------------------------------------------
 *  gc_encode
 * ---------------------------------------------------------------- */

static int gc_encode(const gc_matrix_t *m, uint8_t *buf, int cap) {
    if (cap < 2) return GC_ERR_OVERFLOW;

    int has_l2 = (m->n_pairs > 0) ? 1 : 0;
    buf[0] = GC_VERSION;
    buf[1] = has_l2 ? GC_FLAG_LAYER2 : 0;
    int written = 2;

    /* Encode Layer 1 */
    gc__dim_cfg_t l1cfg = { GC_FIELD_LONS, GC_FIELD_LATS };
    int l1_bytes = gc__encode_projection(
        m->field_bits, &l1cfg, buf + written, cap - written);
    if (l1_bytes < 0) return l1_bytes;
    written += l1_bytes;

    if (!has_l2) return written;

    /* Encode Layer 2: iterate field inner matrix to find active pairs in order */
    /* We need to reconstruct the encoding order: decode our own L1 to get
     * the active src/dst field lists and inner matrix bit order. */
    gc__dim_cfg_t l1cfg2 = { GC_FIELD_LONS, GC_FIELD_LATS };
    uint32_t slm, sam, dlm, dam;
    gc__compute_dim_masks(m->field_bits, &l1cfg2, &slm, &sam, &dlm, &dam);

    int src_lons[18], src_lats[18], dst_lons[18], dst_lats[18];
    int nsl = gc__mask_indices(slm, GC_FIELD_LONS, src_lons);
    int nsa = gc__mask_indices(sam, GC_FIELD_LATS, src_lats);
    int ndl = gc__mask_indices(dlm, GC_FIELD_LONS, dst_lons);
    int nda = gc__mask_indices(dam, GC_FIELD_LATS, dst_lats);

    /* Build active source and dest field entry lists */
    uint8_t src_bmp_tmp[64], dst_bmp_tmp[64];
    memset(src_bmp_tmp, 0, sizeof(src_bmp_tmp));
    memset(dst_bmp_tmp, 0, sizeof(dst_bmp_tmp));

    int n_as = gc__build_entry_bitmap(m->field_bits, &l1cfg2,
        src_lons, nsl, src_lats, nsa, 1, src_bmp_tmp);
    int n_ad = gc__build_entry_bitmap(m->field_bits, &l1cfg2,
        dst_lons, ndl, dst_lats, nda, 0, dst_bmp_tmp);

    int src_entries[GC_FIELDS], dst_entries[GC_FIELDS];
    gc__bitmap_to_entries(src_bmp_tmp, nsl, nsa, src_lons, src_lats,
        GC_FIELD_LATS, src_entries);
    gc__bitmap_to_entries(dst_bmp_tmp, ndl, nda, dst_lons, dst_lats,
        GC_FIELD_LATS, dst_entries);

    /* For each active pair in row-major inner matrix order, encode L2 sub-block */
    gc__dim_cfg_t sqcfg = { GC_SQ_LONS, GC_SQ_LATS };
    for (int si = 0; si < n_as; si++) {
        for (int di = 0; di < n_ad; di++) {
            int src_fi = src_entries[si];
            int dst_fi = dst_entries[di];
            if (!gc__bit_get(m->field_bits, src_fi * GC_FIELDS + dst_fi))
                continue;

            /* Find the pair's sq_bits */
            int pair_idx = -1;
            for (int p = 0; p < m->n_pairs; p++) {
                if (m->pair_src[p] == (uint16_t)src_fi &&
                    m->pair_dst[p] == (uint16_t)dst_fi) {
                    pair_idx = p;
                    break;
                }
            }

            if (pair_idx < 0) {
                /* Field pair set but no square data; encode empty sub-block */
                int need = (sqcfg.n_lons * 2 + sqcfg.n_lats * 2 + 7) / 8;
                if (written + need > cap) return GC_ERR_OVERFLOW;
                memset(buf + written, 0, (size_t)need);
                written += need;
            } else {
                int sub_bytes = gc__encode_projection(
                    m->sq_bits[pair_idx], &sqcfg,
                    buf + written, cap - written);
                if (sub_bytes < 0) return sub_bytes;
                written += sub_bytes;
            }
        }
    }

    return written;
}

#endif /* !GC_EMBEDDED */

/* ----------------------------------------------------------------
 *  gc_decode
 * ---------------------------------------------------------------- */

static int gc_decode(const uint8_t *data, int len, gc_matrix_t *m) {
    gc_init(m);
    if (len < 2) return GC_ERR_FORMAT;
    if (data[0] != GC_VERSION) return GC_ERR_FORMAT;

    uint8_t flags = data[1];
    int consumed = 2;

    /* Decode Layer 1 */
    gc__dim_cfg_t l1cfg = { GC_FIELD_LONS, GC_FIELD_LATS };
    int l1_bytes = gc__decode_projection(
        data + consumed, len - consumed, &l1cfg, m->field_bits);
    if (l1_bytes < 0) return l1_bytes;
    consumed += l1_bytes;

    if (!(flags & GC_FLAG_LAYER2))
        return consumed;

#ifdef GC_EMBEDDED
    /* Embedded mode: skip Layer 2 data.
     * We must parse through it to return correct consumed count. */
    {
        /* Re-derive active pair count from field matrix */
        uint32_t slm = 0, sam = 0, dlm = 0, dam = 0;
        gc__dim_cfg_t cfg2 = { GC_FIELD_LONS, GC_FIELD_LATS };
        gc__compute_dim_masks(m->field_bits, &cfg2, &slm, &sam, &dlm, &dam);

        int src_lons[18], src_lats[18], dst_lons[18], dst_lats[18];
        int nsl = gc__mask_indices(slm, GC_FIELD_LONS, src_lons);
        int nsa = gc__mask_indices(sam, GC_FIELD_LATS, src_lats);
        int ndl = gc__mask_indices(dlm, GC_FIELD_LONS, dst_lons);
        int nda = gc__mask_indices(dam, GC_FIELD_LATS, dst_lats);

        uint8_t src_bmp[64], dst_bmp[64];
        memset(src_bmp, 0, sizeof(src_bmp));
        memset(dst_bmp, 0, sizeof(dst_bmp));
        int n_as = gc__build_entry_bitmap(m->field_bits, &cfg2,
            src_lons, nsl, src_lats, nsa, 1, src_bmp);
        int n_ad = gc__build_entry_bitmap(m->field_bits, &cfg2,
            dst_lons, ndl, dst_lats, nda, 0, dst_bmp);

        int src_entries[GC_FIELDS], dst_entries[GC_FIELDS];
        gc__bitmap_to_entries(src_bmp, nsl, nsa, src_lons, src_lats,
            GC_FIELD_LATS, src_entries);
        gc__bitmap_to_entries(dst_bmp, ndl, nda, dst_lons, dst_lats,
            GC_FIELD_LATS, dst_entries);

        /* Skip each sub-block */
        for (int si = 0; si < n_as; si++) {
            for (int di = 0; di < n_ad; di++) {
                if (!gc__bit_get(m->field_bits, src_entries[si] * GC_FIELDS + dst_entries[di]))
                    continue;
                /* Parse sub-block just to advance consumed */
                int sq_mask_bits = GC_SQ_LONS * 2 + GC_SQ_LATS * 2; /* 40 */
                int sq_mask_bytes = (sq_mask_bits + 7) / 8; /* 5 */
                if (consumed + sq_mask_bytes > len) return GC_ERR_FORMAT;

                int bpos = 0;
                const uint8_t *sb = data + consumed;
                uint32_t sq_slm = gc__unpack_mask(sb, &bpos, GC_SQ_LONS);
                uint32_t sq_sam = gc__unpack_mask(sb, &bpos, GC_SQ_LATS);
                uint32_t sq_dlm = gc__unpack_mask(sb, &bpos, GC_SQ_LONS);
                uint32_t sq_dam = gc__unpack_mask(sb, &bpos, GC_SQ_LATS);
                consumed += sq_mask_bytes;

                int ns_lon = gc__popcount32(sq_slm);
                int ns_lat = gc__popcount32(sq_sam);
                int nd_lon = gc__popcount32(sq_dlm);
                int nd_lat = gc__popcount32(sq_dam);

                int sbmp_bytes = (ns_lon * ns_lat + 7) / 8;
                if (consumed + sbmp_bytes > len) return GC_ERR_FORMAT;
                int n_asq = gc__popcount_buf(data + consumed, sbmp_bytes);
                consumed += sbmp_bytes;

                int dbmp_bytes = (nd_lon * nd_lat + 7) / 8;
                if (consumed + dbmp_bytes > len) return GC_ERR_FORMAT;
                int n_adq = gc__popcount_buf(data + consumed, dbmp_bytes);
                consumed += dbmp_bytes;

                int inner_bytes = (n_asq * n_adq + 7) / 8;
                if (consumed + inner_bytes > len) return GC_ERR_FORMAT;
                consumed += inner_bytes;
            }
        }
    }
#else
    /* Desktop mode: decode Layer 2 */
    {
        uint32_t slm = 0, sam = 0, dlm = 0, dam = 0;
        gc__dim_cfg_t cfg2 = { GC_FIELD_LONS, GC_FIELD_LATS };
        gc__compute_dim_masks(m->field_bits, &cfg2, &slm, &sam, &dlm, &dam);

        int src_lons[18], src_lats[18], dst_lons[18], dst_lats[18];
        int nsl = gc__mask_indices(slm, GC_FIELD_LONS, src_lons);
        int nsa = gc__mask_indices(sam, GC_FIELD_LATS, src_lats);
        int ndl = gc__mask_indices(dlm, GC_FIELD_LONS, dst_lons);
        int nda = gc__mask_indices(dam, GC_FIELD_LATS, dst_lats);

        uint8_t src_bmp[64], dst_bmp[64];
        memset(src_bmp, 0, sizeof(src_bmp));
        memset(dst_bmp, 0, sizeof(dst_bmp));
        int n_as = gc__build_entry_bitmap(m->field_bits, &cfg2,
            src_lons, nsl, src_lats, nsa, 1, src_bmp);
        int n_ad = gc__build_entry_bitmap(m->field_bits, &cfg2,
            dst_lons, ndl, dst_lats, nda, 0, dst_bmp);

        int src_entries[GC_FIELDS], dst_entries[GC_FIELDS];
        gc__bitmap_to_entries(src_bmp, nsl, nsa, src_lons, src_lats,
            GC_FIELD_LATS, src_entries);
        gc__bitmap_to_entries(dst_bmp, ndl, nda, dst_lons, dst_lats,
            GC_FIELD_LATS, dst_entries);

        gc__dim_cfg_t sqcfg = { GC_SQ_LONS, GC_SQ_LATS };
        for (int si = 0; si < n_as; si++) {
            for (int di = 0; di < n_ad; di++) {
                int src_fi = src_entries[si];
                int dst_fi = dst_entries[di];
                if (!gc__bit_get(m->field_bits, src_fi * GC_FIELDS + dst_fi))
                    continue;

                int pair_idx = gc__find_or_create_pair(m, src_fi, dst_fi);
                if (pair_idx < 0) return pair_idx;

                int sub_bytes = gc__decode_projection(
                    data + consumed, len - consumed, &sqcfg,
                    m->sq_bits[pair_idx]);
                if (sub_bytes < 0) return sub_bytes;
                consumed += sub_bytes;
            }
        }
    }
#endif

    return consumed;
}

/* ----------------------------------------------------------------
 *  gc_from / gc_to — query propagation paths
 * ---------------------------------------------------------------- */

static int gc__query_field_from(const gc_matrix_t *m, int src_fi,
                                int *out, int max_out) {
    int count = 0;
    for (int d = 0; d < GC_FIELDS && count < max_out; d++) {
        if (gc__bit_get(m->field_bits, src_fi * GC_FIELDS + d))
            out[count++] = d;
    }
    return count;
}

static int gc__query_field_to(const gc_matrix_t *m, int dst_fi,
                              int *out, int max_out) {
    int count = 0;
    for (int s = 0; s < GC_FIELDS && count < max_out; s++) {
        if (gc__bit_get(m->field_bits, s * GC_FIELDS + dst_fi))
            out[count++] = s;
    }
    return count;
}

#ifndef GC_EMBEDDED

static int gc__find_pair(const gc_matrix_t *m, int src_fi, int dst_fi) {
    for (int i = 0; i < m->n_pairs; i++) {
        if (m->pair_src[i] == (uint16_t)src_fi &&
            m->pair_dst[i] == (uint16_t)dst_fi)
            return i;
    }
    return -1;
}

static int gc__query_grid_from(const gc_matrix_t *m, int src_gi,
                               int *out, int max_out) {
    int src_fi = src_gi / GC_SQUARES;
    int src_si = src_gi % GC_SQUARES;
    int count = 0;

    for (int dst_fi = 0; dst_fi < GC_FIELDS; dst_fi++) {
        if (!gc__bit_get(m->field_bits, src_fi * GC_FIELDS + dst_fi))
            continue;
        int pair_idx = gc__find_pair(m, src_fi, dst_fi);
        if (pair_idx < 0) continue;
        for (int dst_si = 0; dst_si < GC_SQUARES && count < max_out; dst_si++) {
            if (gc__bit_get(m->sq_bits[pair_idx], src_si * GC_SQUARES + dst_si))
                out[count++] = dst_fi * GC_SQUARES + dst_si;
        }
    }
    return count;
}

static int gc__query_grid_to(const gc_matrix_t *m, int dst_gi,
                             int *out, int max_out) {
    int dst_fi = dst_gi / GC_SQUARES;
    int dst_si = dst_gi % GC_SQUARES;
    int count = 0;

    for (int src_fi = 0; src_fi < GC_FIELDS; src_fi++) {
        if (!gc__bit_get(m->field_bits, src_fi * GC_FIELDS + dst_fi))
            continue;
        int pair_idx = gc__find_pair(m, src_fi, dst_fi);
        if (pair_idx < 0) continue;
        for (int src_si = 0; src_si < GC_SQUARES && count < max_out; src_si++) {
            if (gc__bit_get(m->sq_bits[pair_idx], src_si * GC_SQUARES + dst_si))
                out[count++] = src_fi * GC_SQUARES + src_si;
        }
    }
    return count;
}

#endif /* !GC_EMBEDDED */

static int gc_from(const gc_matrix_t *m, const char *grid,
                   int *out, int max_out) {
    if (!grid || !out || max_out <= 0) return 0;
    int slen = (int)strlen(grid);

    if (slen == 2) {
        int fi = gc_field_index(grid);
        if (fi < 0) return 0;
        return gc__query_field_from(m, fi, out, max_out);
    }
    if (slen >= 4) {
        int gi = gc_grid_index(grid);
        if (gi < 0) return 0;
#ifdef GC_EMBEDDED
        int fi = gi / GC_SQUARES;
        return gc__query_field_from(m, fi, out, max_out);
#else
        return gc__query_grid_from(m, gi, out, max_out);
#endif
    }
    return 0;
}

static int gc_to(const gc_matrix_t *m, const char *grid,
                 int *out, int max_out) {
    if (!grid || !out || max_out <= 0) return 0;
    int slen = (int)strlen(grid);

    if (slen == 2) {
        int fi = gc_field_index(grid);
        if (fi < 0) return 0;
        return gc__query_field_to(m, fi, out, max_out);
    }
    if (slen >= 4) {
        int gi = gc_grid_index(grid);
        if (gi < 0) return 0;
#ifdef GC_EMBEDDED
        int fi = gi / GC_SQUARES;
        return gc__query_field_to(m, fi, out, max_out);
#else
        return gc__query_grid_to(m, gi, out, max_out);
#endif
    }
    return 0;
}

#endif /* GRIDCODEC_IMPLEMENTATION */
#endif /* GRIDCODEC_H */
