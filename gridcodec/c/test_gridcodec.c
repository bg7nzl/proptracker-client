#define GRIDCODEC_IMPLEMENTATION
#include "gridcodec.h"

#include <stdio.h>
#include <stdlib.h>
#include <assert.h>
#include <time.h>

/* Simple deterministic PRNG (xorshift32) for reproducible tests */
static uint32_t rng_state = 12345;
static uint32_t xorshift32(void) {
    uint32_t x = rng_state;
    x ^= x << 13;
    x ^= x >> 17;
    x ^= x << 5;
    rng_state = x;
    return x;
}

static int rand_range(int lo, int hi) {
    return lo + (int)(xorshift32() % (uint32_t)(hi - lo));
}

/* ================================================================
 *  Helper index/name tests
 * ================================================================ */

static void test_field_index(void) {
    printf("  test_field_index...");

    assert(gc_field_index("AA") == 0);
    assert(gc_field_index("AB") == 1);
    assert(gc_field_index("BA") == GC_FIELD_LATS);
    assert(gc_field_index("RR") == GC_FIELDS - 1);

    assert(gc_field_index("aa") == 0);  /* case insensitive */
    assert(gc_field_index("SS") == -1); /* out of range */
    assert(gc_field_index(NULL) == -1);
    assert(gc_field_index("A")  == -1); /* too short - reads garbage, but first char valid check might pass... */

    char buf[3];
    gc_field_name(0, buf);
    assert(buf[0] == 'A' && buf[1] == 'A' && buf[2] == 0);
    gc_field_name(GC_FIELDS - 1, buf);
    assert(buf[0] == 'R' && buf[1] == 'R');
    gc_field_name(-1, buf);
    assert(buf[0] == '?');

    printf(" OK\n");
}

static void test_grid_index(void) {
    printf("  test_grid_index...");

    assert(gc_grid_index("AA00") == 0);
    assert(gc_grid_index("AA01") == 1);
    assert(gc_grid_index("AA10") == GC_SQ_LATS);
    assert(gc_grid_index("AB00") == GC_SQUARES);
    assert(gc_grid_index("RR99") == GC_GRIDS - 1);

    assert(gc_grid_index("aa00") == 0);
    assert(gc_grid_index("SS00") == -1);
    assert(gc_grid_index(NULL) == -1);

    char buf[5];
    gc_grid_name(0, buf);
    assert(buf[0]=='A' && buf[1]=='A' && buf[2]=='0' && buf[3]=='0');
    gc_grid_name(GC_GRIDS - 1, buf);
    assert(buf[0]=='R' && buf[1]=='R' && buf[2]=='9' && buf[3]=='9');

    assert(gc_grid_to_field(0) == 0);
    assert(gc_grid_to_field(GC_SQUARES) == 1);
    assert(gc_grid_to_square(0) == 0);
    assert(gc_grid_to_square(GC_SQUARES + 5) == 5);

    /* Round-trip all grids */
    for (int i = 0; i < GC_GRIDS; i++) {
        gc_grid_name(i, buf);
        assert(gc_grid_index(buf) == i);
    }

    printf(" OK\n");
}

/* ================================================================
 *  Layer 1 round-trip tests
 * ================================================================ */

static void test_empty_roundtrip(void) {
    printf("  test_empty_roundtrip...");

    gc_matrix_t m;
    gc_init(&m);

    uint8_t buf[256];
    int enc_len = gc_encode(&m, buf, sizeof(buf));
    assert(enc_len > 0);

    gc_matrix_t m2;
    int dec_len = gc_decode(buf, enc_len, &m2);
    assert(dec_len == enc_len);

    assert(memcmp(m.field_bits, m2.field_bits, GC_FIELD_MATRIX_BYTES) == 0);

    gc_free(&m);
    gc_free(&m2);
    printf(" OK (encoded %d bytes)\n", enc_len);
}

static void test_single_path_roundtrip(void) {
    printf("  test_single_path_roundtrip...");

    gc_matrix_t m;
    gc_init(&m);
    assert(gc_set(&m, "FN31", "PM02") == 0);

    uint8_t buf[4096];
    int enc_len = gc_encode(&m, buf, sizeof(buf));
    assert(enc_len > 0);

    gc_matrix_t m2;
    int dec_len = gc_decode(buf, enc_len, &m2);
    assert(dec_len == enc_len);

    /* Verify Layer 1 */
    int src_fi = gc_grid_to_field(gc_grid_index("FN31"));
    int dst_fi = gc_grid_to_field(gc_grid_index("PM02"));
    assert(gc__bit_get(m2.field_bits, src_fi * GC_FIELDS + dst_fi));

    /* Verify gc_from at field level */
    int results[16];
    int n = gc_from(&m2, "FN", results, 16);
    assert(n == 1);
    char name[3];
    gc_field_name(results[0], name);
    assert(name[0] == 'P' && name[1] == 'M');

    /* Verify gc_to at field level */
    n = gc_to(&m2, "PM", results, 16);
    assert(n == 1);
    gc_field_name(results[0], name);
    assert(name[0] == 'F' && name[1] == 'N');

    /* Verify gc_from at grid level */
    int grid_results[64];
    n = gc_from(&m2, "FN31", grid_results, 64);
    assert(n == 1);
    char gname[5];
    gc_grid_name(grid_results[0], gname);
    assert(gname[0]=='P' && gname[1]=='M' && gname[2]=='0' && gname[3]=='2');

    /* Verify gc_to at grid level */
    n = gc_to(&m2, "PM02", grid_results, 64);
    assert(n == 1);
    gc_grid_name(grid_results[0], gname);
    assert(gname[0]=='F' && gname[1]=='N' && gname[2]=='3' && gname[3]=='1');

    gc_free(&m);
    gc_free(&m2);
    printf(" OK (encoded %d bytes)\n", enc_len);
}

/* ================================================================
 *  Realistic scenario test
 * ================================================================ */

typedef struct { int from_gi; int to_gi; } path_t;

static void test_realistic_roundtrip(int n_paths) {
    printf("  test_realistic_roundtrip (%d paths)...", n_paths);

    rng_state = 42;

    gc_matrix_t m;
    gc_init(&m);

    path_t *paths = (path_t *)malloc((size_t)n_paths * sizeof(path_t));
    assert(paths);

    /* Generate realistic paths: cluster around a few active regions */
    static const char *regions[] = {
        "FN", "FM", "EN", "EM", "DN",       /* North America */
        "JO", "JN", "IO", "IN",             /* Europe */
        "PM", "QM", "PN", "QN",             /* East Asia */
    };
    int n_regions = (int)(sizeof(regions) / sizeof(regions[0]));

    for (int i = 0; i < n_paths; i++) {
        int src_region = rand_range(0, n_regions);
        int dst_region = rand_range(0, n_regions);
        while (dst_region == src_region)
            dst_region = rand_range(0, n_regions);

        char src[5], dst[5];
        src[0] = regions[src_region][0];
        src[1] = regions[src_region][1];
        src[2] = (char)('0' + rand_range(0, 10));
        src[3] = (char)('0' + rand_range(0, 10));
        src[4] = 0;

        dst[0] = regions[dst_region][0];
        dst[1] = regions[dst_region][1];
        dst[2] = (char)('0' + rand_range(0, 10));
        dst[3] = (char)('0' + rand_range(0, 10));
        dst[4] = 0;

        int rc = gc_set(&m, src, dst);
        assert(rc == 0);

        paths[i].from_gi = gc_grid_index(src);
        paths[i].to_gi   = gc_grid_index(dst);
    }

    /* Encode */
    int buf_size = 256 * 1024;
    uint8_t *buf = (uint8_t *)malloc((size_t)buf_size);
    assert(buf);

    clock_t t0 = clock();
    int enc_len = gc_encode(&m, buf, buf_size);
    clock_t t1 = clock();
    assert(enc_len > 0);

    /* Decode */
    gc_matrix_t m2;
    gc_init(&m2);
    clock_t t2 = clock();
    int dec_len = gc_decode(buf, enc_len, &m2);
    clock_t t3 = clock();
    assert(dec_len == enc_len);

    /* Verify Layer 1 match */
    assert(memcmp(m.field_bits, m2.field_bits, GC_FIELD_MATRIX_BYTES) == 0);

    /* Verify all original paths exist after round-trip */
    int verified = 0;
    for (int i = 0; i < n_paths; i++) {
        int src_fi = paths[i].from_gi / GC_SQUARES;
        int dst_fi = paths[i].to_gi / GC_SQUARES;
        assert(gc__bit_get(m2.field_bits, src_fi * GC_FIELDS + dst_fi));

        /* Check Layer 2 */
        int pair_idx = gc__find_pair(&m2, src_fi, dst_fi);
        assert(pair_idx >= 0);
        int src_si = paths[i].from_gi % GC_SQUARES;
        int dst_si = paths[i].to_gi % GC_SQUARES;
        assert(gc__bit_get(m2.sq_bits[pair_idx], src_si * GC_SQUARES + dst_si));
        verified++;
    }

    /* Verify no extra bits in Layer 1 */
    int orig_popcount = gc__popcount_buf(m.field_bits, GC_FIELD_MATRIX_BYTES);
    int decoded_popcount = gc__popcount_buf(m2.field_bits, GC_FIELD_MATRIX_BYTES);
    assert(orig_popcount == decoded_popcount);

    /* Verify no extra bits in Layer 2 */
    for (int p = 0; p < m.n_pairs; p++) {
        int p2 = gc__find_pair(&m2, m.pair_src[p], m.pair_dst[p]);
        assert(p2 >= 0);
        int orig_sq = gc__popcount_buf(m.sq_bits[p], GC_SQ_MATRIX_BYTES);
        int dec_sq  = gc__popcount_buf(m2.sq_bits[p2], GC_SQ_MATRIX_BYTES);
        assert(orig_sq == dec_sq);
        assert(memcmp(m.sq_bits[p], m2.sq_bits[p2], GC_SQ_MATRIX_BYTES) == 0);
    }

    /* Memory usage: static struct + dynamic Layer 2 */
    size_t static_size = sizeof(gc_matrix_t);
    size_t dynamic_size = (size_t)m.pairs_cap * (sizeof(uint16_t) * 2 + GC_SQ_MATRIX_BYTES);
    size_t total_mem = static_size + dynamic_size;

    double enc_ms = (double)(t1 - t0) / CLOCKS_PER_SEC * 1000.0;
    double dec_ms = (double)(t3 - t2) / CLOCKS_PER_SEC * 1000.0;
    double raw_l1 = GC_FIELD_MATRIX_BYTES;
    double raw_full = (double)GC_GRIDS * GC_GRIDS / 8.0;

    printf(" OK\n");
    printf("    Paths: %d, Field pairs: %d, Verified: %d\n",
           n_paths, orig_popcount, verified);
    printf("    Encoded: %d bytes (L1+L2)\n", enc_len);
    printf("    Raw L1: %.0f bytes, compression: %.1fx\n",
           raw_l1, raw_l1 / enc_len);
    printf("    Raw full: %.0f MB, compression: %.0fx\n",
           raw_full / 1048576.0, raw_full / enc_len);
    printf("    Encode: %.2f ms, Decode: %.2f ms\n", enc_ms, dec_ms);
    printf("    Memory: struct=%zu, dynamic=%zu (pairs_cap=%d), total=%zu bytes (%.1f KB)\n",
           static_size, dynamic_size, m.pairs_cap, total_mem, (double)total_mem / 1024.0);

    free(paths);
    free(buf);
    gc_free(&m);
    gc_free(&m2);
}

/* ================================================================
 *  Query tests
 * ================================================================ */

static void test_query_from_to(void) {
    printf("  test_query_from_to...");

    gc_matrix_t m;
    gc_init(&m);

    gc_set(&m, "FN31", "PM02");
    gc_set(&m, "FN31", "JO22");
    gc_set(&m, "FN42", "PM02");
    gc_set(&m, "JO22", "FN31");

    /* Field-level FROM "FN" should return PM and JO */
    int results[64];
    int n = gc_from(&m, "FN", results, 64);
    assert(n == 2);

    /* Field-level TO "PM" should return FN */
    n = gc_to(&m, "PM", results, 64);
    assert(n == 1);
    char fname[3];
    gc_field_name(results[0], fname);
    assert(fname[0] == 'F' && fname[1] == 'N');

    /* Grid-level FROM "FN31" should return PM02 and JO22 */
    n = gc_from(&m, "FN31", results, 64);
    assert(n == 2);

    /* Grid-level FROM "FN42" should return only PM02 */
    n = gc_from(&m, "FN42", results, 64);
    assert(n == 1);
    char gname[5];
    gc_grid_name(results[0], gname);
    assert(gname[0]=='P' && gname[1]=='M' && gname[2]=='0' && gname[3]=='2');

    /* Grid-level TO "FN31" should return JO22 (JO22→FN31) */
    n = gc_to(&m, "FN31", results, 64);
    assert(n == 1);
    gc_grid_name(results[0], gname);
    assert(gname[0]=='J' && gname[1]=='O' && gname[2]=='2' && gname[3]=='2');

    gc_free(&m);
    printf(" OK\n");
}

/* ================================================================
 *  Buffer overflow test
 * ================================================================ */

static void test_buffer_overflow(void) {
    printf("  test_buffer_overflow...");

    gc_matrix_t m;
    gc_init(&m);
    gc_set(&m, "FN31", "PM02");

    uint8_t tiny[4];
    int rc = gc_encode(&m, tiny, sizeof(tiny));
    assert(rc < 0);

    gc_free(&m);
    printf(" OK\n");
}

/* ================================================================
 *  Encode-decode with Layer 1 only (no L2)
 * ================================================================ */

static void test_layer1_only(void) {
    printf("  test_layer1_only...");

    gc_matrix_t m;
    gc_init(&m);

    /* Manually set field bits without using gc_set (no Layer 2) */
    int fi_fn = gc_field_index("FN");
    int fi_pm = gc_field_index("PM");
    gc__bit_set(m.field_bits, fi_fn * GC_FIELDS + fi_pm);

    uint8_t buf[4096];
    int enc_len = gc_encode(&m, buf, sizeof(buf));
    assert(enc_len > 0);

    /* Verify flags indicate no Layer 2 */
    assert((buf[1] & GC_FLAG_LAYER2) == 0);

    gc_matrix_t m2;
    int dec_len = gc_decode(buf, enc_len, &m2);
    assert(dec_len == enc_len);
    assert(gc__bit_get(m2.field_bits, fi_fn * GC_FIELDS + fi_pm));

    gc_free(&m);
    gc_free(&m2);
    printf(" OK (encoded %d bytes)\n", enc_len);
}

/* ================================================================
 *  Dense / worst-case tests
 * ================================================================ */

static void test_dense_layer1_full(void) {
    printf("  test_dense_layer1_full (324x324 all 1s)...");

    gc_matrix_t m;
    gc_init(&m);

    /* Set all 324x324 field bits directly (no gc_set, no L2) */
    memset(m.field_bits, 0xFF, GC_FIELD_MATRIX_BYTES);

    clock_t t0 = clock();
    int buf_size = 16384;
    uint8_t *buf = (uint8_t *)malloc((size_t)buf_size);
    assert(buf);
    int enc_len = gc_encode(&m, buf, buf_size);
    clock_t t1 = clock();
    assert(enc_len > 0);

    /* No L2, so encoded is just L1 */
    assert((buf[1] & GC_FLAG_LAYER2) == 0);

    gc_matrix_t m2;
    gc_init(&m2);
    clock_t t2 = clock();
    int dec_len = gc_decode(buf, enc_len, &m2);
    clock_t t3 = clock();
    assert(dec_len == enc_len);

    /* Verify all bits set */
    int popcount = gc__popcount_buf(m2.field_bits, GC_FIELD_MATRIX_BYTES);
    /* 324*324 = 104976, but bitmap is 13122 bytes = 104976 bits, all set */
    assert(popcount == GC_FIELDS * GC_FIELDS);
    assert(memcmp(m.field_bits, m2.field_bits, GC_FIELD_MATRIX_BYTES) == 0);

    double enc_ms = (double)(t1 - t0) / CLOCKS_PER_SEC * 1000.0;
    double dec_ms = (double)(t3 - t2) / CLOCKS_PER_SEC * 1000.0;

    printf(" OK\n");
    printf("    Encoded: %d bytes (L1 only, all 1s)\n", enc_len);
    printf("    Expected worst case L1: ~13215 bytes (raw field matrix: %d bytes)\n",
           GC_FIELD_MATRIX_BYTES);
    printf("    Overhead vs raw: %.1f%%\n",
           ((double)enc_len / GC_FIELD_MATRIX_BYTES - 1.0) * 100.0);
    printf("    Encode: %.2f ms, Decode: %.2f ms\n", enc_ms, dec_ms);

    free(buf);
    gc_free(&m);
    gc_free(&m2);
}

static void test_dense_l2_subset(void) {
    printf("  test_dense_l2_subset (100 field pairs, each 100x100 full)...");

    gc_matrix_t m;
    gc_init(&m);

    /* Pick 10 src fields x 10 dst fields = 100 pairs, each fully dense */
    int src_fields[10], dst_fields[10];
    for (int i = 0; i < 10; i++) {
        src_fields[i] = i;                /* AA, AB, AC, ... AI */
        dst_fields[i] = GC_FIELDS - 1 - i; /* RR, RQ, RP, ... RI */
    }

    int total_paths = 0;
    for (int si = 0; si < 10; si++) {
        for (int di = 0; di < 10; di++) {
            int src_fi = src_fields[si];
            int dst_fi = dst_fields[di];

            gc__bit_set(m.field_bits, src_fi * GC_FIELDS + dst_fi);

            int pair_idx = gc__find_or_create_pair(&m, src_fi, dst_fi);
            assert(pair_idx >= 0);
            /* Fill all 100x100 square bits */
            memset(m.sq_bits[pair_idx], 0xFF, GC_SQ_MATRIX_BYTES);
            total_paths += GC_SQUARES * GC_SQUARES;
        }
    }

    clock_t t0 = clock();
    int buf_size = 256 * 1024;
    uint8_t *buf = (uint8_t *)malloc((size_t)buf_size);
    assert(buf);
    int enc_len = gc_encode(&m, buf, buf_size);
    clock_t t1 = clock();
    assert(enc_len > 0);

    gc_matrix_t m2;
    gc_init(&m2);
    clock_t t2 = clock();
    int dec_len = gc_decode(buf, enc_len, &m2);
    clock_t t3 = clock();
    assert(dec_len == enc_len);

    /* Verify L1 */
    assert(memcmp(m.field_bits, m2.field_bits, GC_FIELD_MATRIX_BYTES) == 0);

    /* Verify L2 for each pair */
    for (int p = 0; p < m.n_pairs; p++) {
        int p2 = gc__find_pair(&m2, m.pair_src[p], m.pair_dst[p]);
        assert(p2 >= 0);
        assert(memcmp(m.sq_bits[p], m2.sq_bits[p2], GC_SQ_MATRIX_BYTES) == 0);
    }

    size_t mem_used = sizeof(gc_matrix_t)
        + (size_t)m.pairs_cap * (sizeof(uint16_t) * 2 + GC_SQ_MATRIX_BYTES);
    double enc_ms = (double)(t1 - t0) / CLOCKS_PER_SEC * 1000.0;
    double dec_ms = (double)(t3 - t2) / CLOCKS_PER_SEC * 1000.0;

    printf(" OK\n");
    printf("    Pairs: %d, Paths per pair: %d, Total paths: %d\n",
           m.n_pairs, GC_SQUARES * GC_SQUARES, total_paths);
    printf("    Encoded: %d bytes (%.1f KB)\n", enc_len, (double)enc_len / 1024.0);
    printf("    Per pair encoded: ~%d bytes (raw sq matrix: %d bytes)\n",
           (enc_len > 100 ? (enc_len - 100) / m.n_pairs : 0), GC_SQ_MATRIX_BYTES);
    printf("    Memory: %zu bytes (%.1f KB)\n", mem_used, (double)mem_used / 1024.0);
    printf("    Encode: %.2f ms, Decode: %.2f ms\n", enc_ms, dec_ms);

    /* Estimate theoretical full worst case */
    int full_pairs = GC_FIELDS * GC_FIELDS;
    double est_l2_per_pair = (enc_len > 100) ? (double)(enc_len - 100) / m.n_pairs : 1281.0;
    double est_full_enc = 13215.0 + full_pairs * est_l2_per_pair;
    double est_full_mem = (double)sizeof(gc_matrix_t)
        + (double)full_pairs * (sizeof(uint16_t) * 2 + GC_SQ_MATRIX_BYTES);
    printf("    --- Theoretical full 32400x32400 worst case ---\n");
    printf("    Full pairs: %d\n", full_pairs);
    printf("    Est. encoded: %.0f bytes (%.1f MB)\n", est_full_enc, est_full_enc / 1048576.0);
    printf("    Est. memory: %.0f bytes (%.1f MB)\n", est_full_mem, est_full_mem / 1048576.0);
    printf("    Raw matrix: %.1f MB\n", (double)GC_GRIDS * GC_GRIDS / 8.0 / 1048576.0);
    printf("    Note: encoding > raw at full density (projection adds overhead on dense data)\n");

    free(buf);
    gc_free(&m);
    gc_free(&m2);
}

/* ================================================================
 *  Extreme test: 10% random uniform connections
 * ================================================================ */

static void test_extreme_random_10pct(void) {
    printf("  test_extreme_random_10pct (10%% of 32400x32400)...\n");

    rng_state = 7777;

    gc_matrix_t m;
    gc_init(&m);

    /* 10% of 32400^2 ≈ 105 million paths — way too many for gc_set().
     * Instead, directly populate the bitmaps:
     *   - For each field pair (324x324), ~10% chance of being active
     *   - For each active pair, ~10% of 100x100 squares are set */

    int field_pairs_set = 0;
    long long total_sq_paths = 0;

    for (int sf = 0; sf < GC_FIELDS; sf++) {
        for (int df = 0; df < GC_FIELDS; df++) {
            if ((xorshift32() % 100) >= 10) continue; /* ~10% field pairs */

            gc__bit_set(m.field_bits, sf * GC_FIELDS + df);
            field_pairs_set++;

            int pair_idx = gc__find_or_create_pair(&m, sf, df);
            assert(pair_idx >= 0);

            for (int ss = 0; ss < GC_SQUARES; ss++) {
                for (int ds = 0; ds < GC_SQUARES; ds++) {
                    if ((xorshift32() % 100) < 10) { /* ~10% squares */
                        gc__bit_set(m.sq_bits[pair_idx], ss * GC_SQUARES + ds);
                        total_sq_paths++;
                    }
                }
            }
        }
    }

    printf("    Built: %d field pairs, %lld grid paths\n",
           field_pairs_set, total_sq_paths);

    /* Encode */
    int buf_size = 32 * 1024 * 1024; /* 32 MB */
    uint8_t *buf = (uint8_t *)malloc((size_t)buf_size);
    assert(buf);

    clock_t t0 = clock();
    int enc_len = gc_encode(&m, buf, buf_size);
    clock_t t1 = clock();
    assert(enc_len > 0);

    /* Decode */
    gc_matrix_t m2;
    gc_init(&m2);
    clock_t t2 = clock();
    int dec_len = gc_decode(buf, enc_len, &m2);
    clock_t t3 = clock();
    assert(dec_len == enc_len);

    /* Verify L1 */
    assert(memcmp(m.field_bits, m2.field_bits, GC_FIELD_MATRIX_BYTES) == 0);

    /* Verify L2 for every pair */
    int l2_verified = 0;
    for (int p = 0; p < m.n_pairs; p++) {
        int p2 = gc__find_pair(&m2, m.pair_src[p], m.pair_dst[p]);
        assert(p2 >= 0);
        assert(memcmp(m.sq_bits[p], m2.sq_bits[p2], GC_SQ_MATRIX_BYTES) == 0);
        l2_verified++;
    }

    size_t mem_used = sizeof(gc_matrix_t)
        + (size_t)m.pairs_cap * (sizeof(uint16_t) * 2 + GC_SQ_MATRIX_BYTES);
    double enc_ms = (double)(t1 - t0) / CLOCKS_PER_SEC * 1000.0;
    double dec_ms = (double)(t3 - t2) / CLOCKS_PER_SEC * 1000.0;
    double raw_full = (double)GC_GRIDS * GC_GRIDS / 8.0;

    printf("    L2 pairs verified: %d\n", l2_verified);
    printf("    Encoded: %d bytes (%.1f KB, %.2f MB)\n",
           enc_len, (double)enc_len / 1024.0, (double)enc_len / 1048576.0);
    printf("    Raw full matrix: %.1f MB, compression: %.1fx\n",
           raw_full / 1048576.0, raw_full / enc_len);
    printf("    Memory: %.1f MB (pairs_cap=%d)\n",
           (double)mem_used / 1048576.0, m.pairs_cap);
    printf("    Encode: %.1f ms, Decode: %.1f ms\n", enc_ms, dec_ms);

    free(buf);
    gc_free(&m);
    gc_free(&m2);
    printf("    OK\n");
}

/* ================================================================
 *  Extreme test: 10 hotspots with Poisson-distributed activity
 *
 *  Each hotspot has a center field. Activity radiates outward:
 *    P(active) ∝ exp(-distance / lambda)
 *  Links between hotspot grids are created randomly, ~10% of total.
 * ================================================================ */

/* Approximate exp(-x) using integer math for portability */
static double gc__approx_exp_neg(double x) {
    if (x > 20.0) return 0.0;
    /* Pade approximant: exp(-x) ≈ 1/(1 + x + x²/2 + x³/6 + x⁴/24) */
    double x2 = x * x;
    return 1.0 / (1.0 + x + x2 * 0.5 + x2 * x / 6.0 + x2 * x2 / 24.0);
}

static void test_extreme_hotspot_poisson(void) {
    printf("  test_extreme_hotspot_poisson (10 hotspots, Poisson spread)...\n");

    rng_state = 31415;

    /* 10 hotspot center fields (realistic ham radio population centers) */
    static const struct { int lon; int lat; const char *name; } hotspots[] = {
        { 5, 13, "FN (NE USA)"     },
        { 4, 12, "EM (SE USA)"     },
        { 3, 13, "DN (Central US)" },
        { 9, 14, "JO (W Europe)"   },
        { 9, 13, "JN (S Europe)"   },
        { 8, 14, "IO (UK/Ireland)" },
        {15, 12, "PM (Japan)"      },
        {16, 12, "QM (E Japan)"    },
        { 1, 13, "BN (W Canada)"   },
        {11, 10, "LK (India)"      },
        {14, 11, "OL (China)"      },
    };
    int n_hotspots = (int)(sizeof(hotspots) / sizeof(hotspots[0]));

    /* Phase 1: Determine active grids around each hotspot using Poisson falloff.
     * lambda = 3.0 field units for inter-field spread
     * Within each active field, squares follow Poisson from center of field */
    double lambda_field = 3.0;
    double lambda_sq = 3.0;

    /* Collect active grids per hotspot */
    #define MAX_HOTSPOTS 16
    #define MAX_ACTIVE_PER_HOTSPOT 4096
    int active_grids[MAX_HOTSPOTS][MAX_ACTIVE_PER_HOTSPOT];
    int n_active[MAX_HOTSPOTS];

    int total_active_grids = 0;
    for (int h = 0; h < n_hotspots; h++) {
        n_active[h] = 0;
        int cx = hotspots[h].lon;
        int cy = hotspots[h].lat;

        for (int fx = 0; fx < GC_FIELD_LONS; fx++) {
            for (int fy = 0; fy < GC_FIELD_LATS; fy++) {
                double fd = (double)((fx-cx)*(fx-cx) + (fy-cy)*(fy-cy));
                fd = fd > 0 ? fd : 0.01;
                double fp = gc__approx_exp_neg(fd / (lambda_field * lambda_field));
                /* Threshold: need > 0.01 to be considered */
                if (fp < 0.01) continue;

                int fi = fx * GC_FIELD_LATS + fy;

                for (int sx = 0; sx < GC_SQ_LONS; sx++) {
                    for (int sy = 0; sy < GC_SQ_LATS; sy++) {
                        double sd = (double)((sx-5)*(sx-5) + (sy-5)*(sy-5));
                        double sp = gc__approx_exp_neg(sd / (lambda_sq * lambda_sq));
                        double combined = fp * sp;
                        /* Probabilistic: use random threshold */
                        if ((xorshift32() % 1000) < (uint32_t)(combined * 1000)) {
                            if (n_active[h] < MAX_ACTIVE_PER_HOTSPOT) {
                                int si = sx * GC_SQ_LATS + sy;
                                active_grids[h][n_active[h]++] = fi * GC_SQUARES + si;
                            }
                        }
                    }
                }
            }
        }
        total_active_grids += n_active[h];
    }

    printf("    Hotspot active grids: ");
    for (int h = 0; h < n_hotspots; h++)
        printf("%s=%d ", hotspots[h].name, n_active[h]);
    printf("\n    Total active grid nodes: %d\n", total_active_grids);

    /* Phase 2: Create links between hotspots.
     * For each pair of hotspots, randomly link ~10% of their active grids */
    gc_matrix_t m;
    gc_init(&m);

    long long total_links = 0;
    for (int h1 = 0; h1 < n_hotspots; h1++) {
        for (int h2 = 0; h2 < n_hotspots; h2++) {
            if (h1 == h2) continue;
            /* Link probability depends on "distance" between hotspots */
            int dx = hotspots[h1].lon - hotspots[h2].lon;
            int dy = hotspots[h1].lat - hotspots[h2].lat;
            double dist = (double)(dx*dx + dy*dy);
            /* Closer hotspots have more links */
            double link_rate = 0.10 * gc__approx_exp_neg(dist / 100.0);
            if (link_rate < 0.005) link_rate = 0.005; /* minimum 0.5% for DX */

            for (int i = 0; i < n_active[h1]; i++) {
                for (int j = 0; j < n_active[h2]; j++) {
                    if ((xorshift32() % 10000) < (uint32_t)(link_rate * 10000)) {
                        int src_gi = active_grids[h1][i];
                        int dst_gi = active_grids[h2][j];
                        int src_fi = src_gi / GC_SQUARES;
                        int dst_fi = dst_gi / GC_SQUARES;
                        int src_si = src_gi % GC_SQUARES;
                        int dst_si = dst_gi % GC_SQUARES;

                        gc__bit_set(m.field_bits, src_fi * GC_FIELDS + dst_fi);
                        int pair_idx = gc__find_or_create_pair(&m, src_fi, dst_fi);
                        if (pair_idx >= 0) {
                            gc__bit_set(m.sq_bits[pair_idx],
                                        src_si * GC_SQUARES + dst_si);
                            total_links++;
                        }
                    }
                }
            }
        }
    }

    int field_pairs = gc__popcount_buf(m.field_bits, GC_FIELD_MATRIX_BYTES);
    printf("    Links created: %lld, Field pairs: %d\n", total_links, field_pairs);

    /* Encode */
    int buf_size = 8 * 1024 * 1024;
    uint8_t *buf = (uint8_t *)malloc((size_t)buf_size);
    assert(buf);

    clock_t t0 = clock();
    int enc_len = gc_encode(&m, buf, buf_size);
    clock_t t1 = clock();
    assert(enc_len > 0);

    /* Decode */
    gc_matrix_t m2;
    gc_init(&m2);
    clock_t t2 = clock();
    int dec_len = gc_decode(buf, enc_len, &m2);
    clock_t t3 = clock();
    assert(dec_len == enc_len);

    /* Verify */
    assert(memcmp(m.field_bits, m2.field_bits, GC_FIELD_MATRIX_BYTES) == 0);
    for (int p = 0; p < m.n_pairs; p++) {
        int p2 = gc__find_pair(&m2, m.pair_src[p], m.pair_dst[p]);
        assert(p2 >= 0);
        assert(memcmp(m.sq_bits[p], m2.sq_bits[p2], GC_SQ_MATRIX_BYTES) == 0);
    }

    size_t mem_used = sizeof(gc_matrix_t)
        + (size_t)m.pairs_cap * (sizeof(uint16_t) * 2 + GC_SQ_MATRIX_BYTES);
    double enc_ms = (double)(t1 - t0) / CLOCKS_PER_SEC * 1000.0;
    double dec_ms = (double)(t3 - t2) / CLOCKS_PER_SEC * 1000.0;
    double raw_full = (double)GC_GRIDS * GC_GRIDS / 8.0;
    double density = (double)total_links / ((double)GC_GRIDS * GC_GRIDS) * 100.0;

    printf("    Density: %.4f%% of full matrix\n", density);
    printf("    Encoded: %d bytes (%.1f KB)\n", enc_len, (double)enc_len / 1024.0);
    printf("    Raw full: %.1f MB, compression: %.0fx\n",
           raw_full / 1048576.0, raw_full / enc_len);
    printf("    Memory: %.1f KB (pairs_cap=%d)\n",
           (double)mem_used / 1024.0, m.pairs_cap);
    printf("    Encode: %.1f ms, Decode: %.1f ms\n", enc_ms, dec_ms);

    free(buf);
    gc_free(&m);
    gc_free(&m2);
    printf("    OK\n");
}

/* ================================================================
 *  Memory usage overview
 * ================================================================ */

static void test_memory_usage(void) {
    printf("  sizeof(gc_matrix_t) = %zu bytes (%.1f KB)\n",
           sizeof(gc_matrix_t), (double)sizeof(gc_matrix_t) / 1024.0);
    printf("    field_bits[%d] = %d bytes (Layer 1, fixed)\n",
           GC_FIELD_MATRIX_BYTES, GC_FIELD_MATRIX_BYTES);
    printf("    Layer 2 pointers + metadata = %zu bytes\n",
           sizeof(gc_matrix_t) - GC_FIELD_MATRIX_BYTES);
    printf("    Layer 2 per pair: %zu bytes (uint16 src + uint16 dst + sq_bits[%d])\n",
           sizeof(uint16_t) * 2 + GC_SQ_MATRIX_BYTES, GC_SQ_MATRIX_BYTES);

    /* Show memory at different pair counts */
    size_t base = sizeof(gc_matrix_t);
    size_t per_pair = sizeof(uint16_t) * 2 + GC_SQ_MATRIX_BYTES;
    printf("    Total memory at various pair counts:\n");
    int counts[] = {0, 64, 256, 512, 1024, 2048, 4096};
    for (int i = 0; i < (int)(sizeof(counts)/sizeof(counts[0])); i++) {
        size_t total = base + (size_t)counts[i] * per_pair;
        printf("      %4d pairs: %7zu bytes (%6.1f KB)\n",
               counts[i], total, (double)total / 1024.0);
    }
}

/* ================================================================
 *  Main
 * ================================================================ */

int main(void) {
    printf("=== GridCodec Test Suite (default mode) ===\n\n");

    printf("[Memory layout]\n");
    test_memory_usage();

    printf("\n[Helper functions]\n");
    test_field_index();
    test_grid_index();

    printf("\n[Round-trip tests]\n");
    test_empty_roundtrip();
    test_single_path_roundtrip();
    test_layer1_only();

    printf("\n[Query tests]\n");
    test_query_from_to();

    printf("\n[Edge cases]\n");
    test_buffer_overflow();

    printf("\n[Realistic scenarios]\n");
    test_realistic_roundtrip(500);
    test_realistic_roundtrip(5000);
    test_realistic_roundtrip(20000);

    printf("\n[Dense / worst-case tests]\n");
    test_dense_layer1_full();
    test_dense_l2_subset();

    if (getenv("SKIP_EXTREME") == NULL) {
        printf("\n[Extreme tests]\n");
        test_extreme_random_10pct();
        test_extreme_hotspot_poisson();
    } else {
        printf("\n[Extreme tests] SKIPPED (SKIP_EXTREME set)\n");
    }

    printf("\n=== All tests passed ===\n");
    return 0;
}
