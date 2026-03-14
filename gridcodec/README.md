[English](README.md) | [中文](README-CN.md) | [日本語](README-JP.md) | [Français](README-FR.md)

---

# GridCodec

A compact binary codec for Maidenhead grid propagation matrices. Designed to
efficiently broadcast FT8/WSPR radio propagation data to many clients
simultaneously.

## Problem

FT8 and similar weak-signal digital modes produce large volumes of
propagation reports. A full 4-character Maidenhead grid system has
32,400 grid squares, making the raw adjacency matrix 32,400 × 32,400 —
roughly **125 MB** of bitmap data. Broadcasting this to hundreds of
clients in text or raw bitmap form is impractical.

GridCodec solves this with a **hierarchical dimensional projection**
algorithm that exploits the geographic sparsity of radio propagation.
Typical real-world FT8 activity compresses to **~2–20 KB**, a reduction
of 10,000× or more.

## Algorithm

### Maidenhead Grid System

A 4-character Maidenhead locator (e.g. `FN31`) encodes a position on the
Earth's surface:

| Character | Meaning    | Range | Count |
| --------- | ---------- | ----- | ----- |
| 1st       | Lon field  | A – R | 18    |
| 2nd       | Lat field  | A – R | 18    |
| 3rd       | Lon square | 0 – 9 | 10    |
| 4th       | Lat square | 0 – 9 | 10    |

This gives 18 × 18 = **324 fields**, each subdivided into 10 × 10 = **100
squares**, for a total of **32,400 grid squares**.

### Index Scheme

```
field_index  = lon_field * 18 + lat_field        [0, 323]
square_index = lon_square * 10 + lat_square      [0, 99]
grid_index   = field_index * 100 + square_index  [0, 32399]
```

### Hierarchical Dimensional Projection

The propagation matrix is a binary adjacency matrix: entry (i, j) = 1
means "signals transmitted from grid i have been received at grid j."

Rather than storing this matrix directly, GridCodec decomposes it into two
layers and applies **dimensional projection** at each layer.

Dimensional projection treats a 2D bitmap whose row/column indices each
decompose into (longitude, latitude) coordinates as a 4D tensor:

```
M[src_lon, src_lat, dst_lon, dst_lat]
```

It then:

1. **Computes dimension masks** — one bitmask per axis recording which
   coordinate values participate in any active entry.
2. **Builds entry bitmaps** — within the bounding box defined by the
   masks, marks which (lon, lat) combinations are actually active as
   sources or destinations.
3. **Builds an inner matrix** — the dense sub-matrix connecting only
   active sources to active destinations.

This is applied at two levels:

- **Layer 1 (field level):** compresses the 324 × 324 field-to-field
  propagation matrix.
- **Layer 2 (square level):** for each active field pair from Layer 1,
  compresses the 100 × 100 square-to-square sub-matrix.

The result is a self-describing binary stream where every size is derived
from previously decoded data — no explicit length fields are needed.

### Why This Works

Radio propagation is geographically clustered. On a typical FT8 band:

- Only 30–60 of 324 fields are active (amateur population is concentrated
  in North America, Europe, Japan, etc.)
- Active fields cluster along a few longitude/latitude bands
- Within each field pair, only a fraction of the 10,000 possible
  square-to-square paths are active

Dimensional projection captures this structure directly: if only 5 of 18
longitude values and 4 of 18 latitude values are active, the bounding box
shrinks from 324 entries to 20, and the entry bitmap further prunes it to
only the truly active cells.

## Wire Format (v1)

All multi-byte bitmaps are packed **little-endian, LSB first**. Bit 0 of
byte 0 is the lowest-indexed element.

### Overall Structure

```
[Header: 2 bytes] [Layer 1] [Layer 2 (optional)]
```

### Header

| Byte | Field   | Description                                       |
| ---- | ------- | ------------------------------------------------- |
| 0    | version | `0x01`                                            |
| 1    | flags   | bit 0: `has_layer2` (1 = Layer 2 follows Layer 1) |
|      |         | bits 1–7: reserved, must be 0                     |

### Layer 1: Field-Level Propagation

Layer 1 encodes propagation between the 324 Maidenhead fields.

**Dimension Masks** (9 bytes = 4 × 18 bits = 72 bits, packed):

| Bit range | Mask          | Width   |
| --------- | ------------- | ------- |
| 0 – 17    | src_lon_field | 18 bits |
| 18 – 35   | src_lat_field | 18 bits |
| 36 – 53   | dst_lon_field | 18 bits |
| 54 – 71   | dst_lat_field | 18 bits |

Bit `i` is set if coordinate index `i` participates in any active path.

**Source Field Bitmap:**

- Size: `ceil(popcount(src_lon) * popcount(src_lat) / 8)` bytes
- Row-major: longitude varies slowly, latitude varies fast
- Bit (i, j) = 1 means the field at (active_src_lon[i], active_src_lat[j])
  is an active source

**Destination Field Bitmap:**

- Same layout as source bitmap, using destination masks

**Inner Matrix:**

- Size: `ceil(n_active_src_fields * n_active_dst_fields / 8)` bytes
- Row-major: source varies slowly, destination varies fast
- Bit (s, d) = 1 means propagation exists from active_src[s] to active_dst[d]

### Layer 2: Square-Level Detail

Present only when `flags & 0x01`. For each set bit in the Layer 1 inner
matrix (enumerated in row-major order), one sub-block follows.

Each sub-block has the same structure as Layer 1, but uses 10-bit
dimension masks (lon_square, lat_square):

**Square Dimension Masks** (5 bytes = 4 × 10 bits = 40 bits, packed):

| Bit range | Mask           | Width   |
| --------- | -------------- | ------- |
| 0 – 9     | src_lon_square | 10 bits |
| 10 – 19   | src_lat_square | 10 bits |
| 20 – 29   | dst_lon_square | 10 bits |
| 30 – 39   | dst_lat_square | 10 bits |

Followed by source square bitmap, destination square bitmap, and inner
matrix — identical in structure to Layer 1 but operating on the 100 × 100
square space.

## Compression Performance

Raw full matrix = 32,400 × 32,400 bits = **125 MB**.

The table below combines theoretical estimates with measured results from
the C test suite (GCC -O2, single x86-64 core):

| Scenario                           | Field pairs | Grid paths | Encoded size | Compression | Encode    | Decode    |
| ---------------------------------- | ----------: | ---------: | -----------: | ----------: | --------: | --------: |
| Quiet band                         |        ~100 |     ~1,000 |       ~2 KB  |  ~64,000×   |         — |         — |
| Normal activity (500 paths)\*      |         150 |        500 |      1.7 KB  |  ~78,700×   |    1.6 ms |    0.2 ms |
| Moderate activity (5,000 paths)\*  |         156 |      5,000 |     19.1 KB  |   ~6,700×   |    2.7 ms |    0.4 ms |
| Busy band (20,000 paths)\*         |         156 |     20,000 |    105.6 KB  |   ~1,200×   |    3.1 ms |    0.8 ms |
| Dense — 10% random fill\*          |     ~10,500 |     ~10.5M |     12.9 MB  |      ~9.7×  |    301 ms |    131 ms |
| Dense — 11 hotspots (Poisson)\*    |      46,955 |     ~4.02M |      4.0 MB  |       ~31×  |    801 ms |    318 ms |

\* Measured in C test suite. Rows without timing are order-of-magnitude
estimates.

**11-hotspot scenario:** 11 fields modeling real-world amateur population
centers (FN NE USA, EM SE USA, DN Central US, JO W Europe, JN S Europe,
IO UK/Ireland, PM Japan, QM E Japan, BN W Canada, LK India, OL China)
with Poisson-distributed activity. Active grid nodes: 8,131; density: 0.38%
of full matrix.

Typical real-world FT8 scenarios (500–5,000 paths) encode in under 3 ms
and decode in under 0.5 ms — well within the 15-second FT8 cycle.

> **Note:** The projection adds small overhead per block (masks + bitmaps).
> At extreme density (>50% fill), encoded output can exceed raw matrix
> size. The algorithm is optimized for the sparse, geographically
> clustered patterns typical of real radio propagation.

## Implementations

GridCodec has a reference C implementation and ports in four other
languages. All share the same Wire Format v1 and are cross-tested
(e.g. all non-C implementations decode the same C-generated test payload
and verify results).

### C — Reference Implementation

#### Single-Header Library

The entire codec is in **`c/gridcodec.h`**, a single-header C99 library
with no external dependencies beyond `<stdint.h>` and `<string.h>`
(plus `<stdlib.h>` in desktop mode for `malloc`).

**Usage pattern:**

```c
#include "gridcodec.h"            /* declarations only */

/* In exactly ONE .c file: */
#define GRIDCODEC_IMPLEMENTATION
#include "gridcodec.h"            /* pulls in implementations */
```

All functions are `static`, so each compilation unit gets its own copy with
no linker conflicts.

#### Compile-Time Modes

|                            | Default (Desktop/Server)         | `GC_EMBEDDED`           |
| -------------------------- | -------------------------------- | ----------------------- |
| Memory allocation          | Dynamic (`malloc` / `realloc`)   | Static only (~13 KB)    |
| Layer 2 support            | Full encode + decode             | Skipped on decode       |
| `gc_set` / `gc_encode`     | Available                        | **Not compiled**        |
| `gc_free`                  | Available                        | **Not compiled**        |
| `gc_from`/`gc_to` (4-char) | Grid-level results              | Degrades to field-level |
| `<stdlib.h>`               | Required                         | **Not required**        |
| `popcount`                 | `__builtin_popcount` (GCC/Clang) | 256-byte lookup table   |

Enable embedded mode:

```c
#define GC_EMBEDDED
#define GRIDCODEC_IMPLEMENTATION
#include "gridcodec.h"
```

#### API Reference

**Initialization and cleanup:**

```c
void gc_init(gc_matrix_t *m);
void gc_free(gc_matrix_t *m);   /* default mode only */
```

**Setting propagation paths:**

```c
int gc_set(gc_matrix_t *m, const char *from4, const char *to4);
```

Records a path between two 4-character grids. Idempotent — duplicates are
handled internally via bitwise OR. Returns `0` on success. Not available
in `GC_EMBEDDED` mode.

**Encoding and decoding:**

```c
int gc_encode(const gc_matrix_t *m, uint8_t *buf, int cap);
int gc_decode(const uint8_t *data, int len, gc_matrix_t *m);
```

`gc_encode` returns bytes written (or `GC_ERR_OVERFLOW`). Not available in
`GC_EMBEDDED` mode.

`gc_decode` returns bytes consumed. In `GC_EMBEDDED` mode, Layer 2 data is
parsed through (to return correct byte count) but discarded.

**Querying propagation:**

```c
int gc_from(const gc_matrix_t *m, const char *grid, int *out, int max_out);
int gc_to(const gc_matrix_t *m, const char *grid, int *out, int max_out);
```

- 2-char input (e.g. `"FN"`): returns field indices (0–323)
- 4-char input (e.g. `"FN31"`): returns grid indices (0–32399) in default
  mode, field indices in `GC_EMBEDDED` mode

`gc_from` returns destinations reachable from the given source.
`gc_to` returns sources that can reach the given destination.

**Index/name conversion:**

```c
int  gc_field_index(const char *name);     /* "FN"   -> 0..323   */
void gc_field_name(int idx, char out[3]);  /* 0..323 -> "FN\0"   */
int  gc_grid_index(const char *name);      /* "FN31" -> 0..32399 */
void gc_grid_name(int idx, char out[5]);   /* 0..32399 -> "FN31\0" */
int  gc_grid_to_field(int grid_idx);
int  gc_grid_to_square(int grid_idx);
```

All name inputs are case-insensitive.

**Error codes:**

| Constant          | Value | Meaning                    |
| ----------------- | ----: | -------------------------- |
| `GC_ERR_INVALID`  |    -1 | Invalid grid name          |
| `GC_ERR_OVERFLOW` |    -2 | Output buffer too small    |
| `GC_ERR_FORMAT`   |    -3 | Malformed wire format data |
| `GC_ERR_CAPACITY` |    -4 | Memory allocation failed   |

#### Memory Usage

**Default mode:**

| Component             | Size                              |
| --------------------- | --------------------------------- |
| Layer 1 field bitmap  | 13,122 bytes (fixed)              |
| Pair metadata         | 38 bytes (pointers + counters)    |
| Per active field pair | 1,254 bytes (src + dst + sq_bits) |

Total memory grows linearly with the number of active field pairs:

| Active pairs | Total memory |
| -----------: | -----------: |
|            0 |      12.9 KB |
|           64 |      91.2 KB |
|          256 |     326.4 KB |
|        1,024 |   1,266.9 KB |

**Embedded mode:** fixed **13,122 bytes** (12.8 KB), no heap allocation.

#### Building and Testing

Requirements: C99 compiler (GCC or Clang recommended), `make`.

```bash
cd c
make test
```

This compiles and runs two test suites:

1. **test_gridcodec** — default (desktop/server) mode: helper correctness,
   round-trip encode/decode, query verification, buffer overflow,
   realistic scenarios (500 / 5,000 / 20,000 paths), dense worst-case,
   extreme tests (10% random fill, 11-hotspot Poisson).
2. **test_embedded** — `GC_EMBEDDED` mode: static memory size verification,
   Layer 1 decode, Layer 1+2 decode (Layer 2 correctly skipped), 4-char
   query degradation, compile-time absence of encode API.

Skip extreme tests (useful under Valgrind or on slow hardware):

```bash
SKIP_EXTREME=1 ./test_gridcodec
```

Memory leak checking:

```bash
gcc -g -O0 -std=c99 -o test_dbg test_gridcodec.c
SKIP_EXTREME=1 valgrind --leak-check=full ./test_dbg
```

Both modes are verified leak-free (0 errors, all heap blocks freed).

### Python

**Location:** `python/` — pure Python package (`gridcodec`), full
encode/decode/query support.

```bash
cd python && python3 test_gridcodec.py
```

### MicroPython

**Location:** `micropython/` — single file `gridcodec.py`, decode + query
only. 4-char queries degrade to field-level. Designed for ESP32, Pyboard,
Raspberry Pi Pico, etc.

```bash
cd micropython && python3 test_gridcodec.py     # host
cd micropython && ./run_on_device.sh             # device via mpremote
```

### JavaScript

**Location:** `js/` — Node.js and browser, full encode/decode/query.

```bash
cd js && node test_gridcodec.js
```

### Java

**Location:** `java/gridcodec/` — Java 8+, full encode/decode/query.

```bash
cd java && javac -source 8 -target 8 gridcodec/*.java && java -cp . gridcodec.TestGridCodec
```

### Verified Toolchains

All implementations have been tested with the following toolchains:

| Language        | Toolchain               | Version  | Notes                                                        |
| --------------- | ----------------------- | -------- | ------------------------------------------------------------ |
| **C**           | GCC                     | 13.3.0   | Default + embedded mode, all tests passed                    |
| **Python**      | CPython                 | 3.12.3   | 500 paths: ~12 KB, encode ~470 ms, decode ~50 ms            |
| **MicroPython** | Pico (RP2040) mpremote  | 1.27.0   | L1-only 14 B: ~87 ms/decode; L1+L2 skip 30 B: ~3535 ms     |
| **JavaScript**  | Node.js                 | v18.19.1 | 500 paths: ~12 KB, encode ~6 ms, decode ~1 ms               |
| **Java**        | OpenJDK                 | 21.0.10  | 500 paths: ~12 KB, encode ~5 ms, decode ~1 ms               |

Cross-language interop: Python, JavaScript, and Java test suites each
decode the same C-generated payload (Layer 1 only, FN↔PM, JO↔FN) and
verify field-level results.

## Design Decisions

**Header-only library.** Simplifies integration for multi-language
bindings. Python, MicroPython, JavaScript, and Java implementations
ship in this repo; all share the same wire format.

**Static functions.** Avoids symbol conflicts when multiple compilation
units include the header. The compiler eliminates unused functions.

**Dual-mode compilation.** Embedded devices (e.g. ESP32, STM32) need
decode-only capability with zero heap usage. The `GC_EMBEDDED` flag strips
all encoding logic and dynamic memory, yielding a 13 KB static footprint
suitable for receive-only stations.

**Linear pair search.** `gc_set` and `gc_from`/`gc_to` use linear search
over field pairs. With typical pair counts under 500, this is faster than
hash table overhead. At 10,000+ pairs (extreme scenarios), this becomes a
measurable cost (~800 ms encode) but remains acceptable for batch
server-side encoding.

**Idempotent `gc_set`.** Since FT8 decoding may produce duplicate reports
within a time window, `gc_set` is designed to be called repeatedly with
the same pair at no additional cost.

**Self-describing wire format.** Every field size is derived from
previously decoded data. This eliminates length fields and makes the
format robust: a decoder either fully parses the stream or returns an
error code.

## License

TBD
