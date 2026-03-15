[English](README.md) | [中文](README-CN.md) | [日本語](README-JP.md) | [Français](README-FR.md)

---

# GridCodec

面向 Maidenhead 网格传播矩阵的紧凑二进制编解码器，用于向大量客户端高效广播 FT8/WSPR 无线电传播数据。

## 问题

FT8 等弱信号数字模式会产生大量传播报告。完整 4 字符 Maidenhead 网格有 32,400 个格点，原始邻接矩阵为 32,400 × 32,400，约 **125 MB** 位图数据。以文本或原始位图向数百客户端广播不现实。

GridCodec 通过**分层维度投影**算法利用传播的地理稀疏性，将典型真实 FT8 活动压缩到 **约 2–20 KB**，压缩比可达 10,000 倍以上。

## 算法

### Maidenhead 网格体系

4 字符 Maidenhead 定位符（如 `FN31`）表示地球表面位置：

| 字符   | 含义     | 范围 | 数量 |
| ------ | -------- | ---- | ---- |
| 第 1 位 | 经度场   | A–R  | 18   |
| 第 2 位 | 纬度场   | A–R  | 18   |
| 第 3 位 | 经度方格 | 0–9  | 10   |
| 第 4 位 | 纬度方格 | 0–9  | 10   |

即 18 × 18 ＝ **324 个场**，每场再分为 10 × 10 ＝ **100 个方格**，共 **32,400 个网格格点**。

### 索引约定

```
field_index  = lon_field * 18 + lat_field        [0, 323]
square_index = lon_square * 10 + lat_square      [0, 99]
grid_index   = field_index * 100 + square_index  [0, 32399]
```

### 分层维度投影

传播矩阵为二元邻接矩阵：项 (i, j) ＝ 1 表示「从格点 i 发出的信号在格点 j 被收到」。

GridCodec 不直接存该矩阵，而是分两层并逐层做**维度投影**。

维度投影将行/列可分解为 (经度, 纬度) 的二维位图视为 4D 张量：

```
M[src_lon, src_lat, dst_lon, dst_lat]
```

然后：

1. **计算维度掩码** — 每个轴一个位掩码，记录哪些坐标值参与任意活跃项。
2. **构建入口位图** — 在掩码定义的包围盒内，标记哪些 (经度, 纬度) 组合实际作为源或目的活跃。
3. **构建内矩阵** — 仅连接活跃源与活跃目的地的稠密子矩阵。

在两层分别应用：

- **Layer 1（场级）：** 压缩 324 × 324 的场到场传播矩阵。
- **Layer 2（方格级）：** 对 Layer 1 的每个活跃场对，压缩 100 × 100 的方格到方格子矩阵。

结果为自描述二进制流，所有长度由已解码数据推出，无需显式长度字段。

### 为何有效

传播在地理上成簇。典型 FT8 波段上：

- 324 个场中仅 30–60 个活跃（业余人口集中在北美、欧洲、日本等）
- 活跃场沿少数经度/纬度带聚集
- 每个场对中，10,000 条可能的方格到方格路径里只有一小部分活跃

维度投影直接利用这种结构：若 18 个经度中只有 5 个、18 个纬度中只有 4 个活跃，包围盒从 324 项缩到 20 项，入口位图再剪枝到真正活跃的单元。

## 线格式 (v1)

所有多字节位图**小端、LSB 优先**。字节 0 的 bit 0 为最低索引元素。

### 整体结构

```
[Header: 2 字节] [Layer 1] [Layer 2（可选）]
```

### 头部

| 字节 | 字段    | 说明                                                |
| ---- | ------- | --------------------------------------------------- |
| 0    | version | `0x01`                                              |
| 1    | flags   | bit 0: `has_layer2`（1 表示 Layer 1 后紧跟 Layer 2） |
|      |         | bit 1–7: 保留，须为 0                               |

### Layer 1：场级传播

Layer 1 编码 324 个 Maidenhead 场之间的传播。

**维度掩码**（9 字节 ＝ 4 × 18 bit ＝ 72 bit，打包）：

| 位范围 | 掩码           | 宽度   |
| ------ | -------------- | ------ |
| 0–17   | src_lon_field  | 18 bit |
| 18–35  | src_lat_field  | 18 bit |
| 36–53  | dst_lon_field  | 18 bit |
| 54–71  | dst_lat_field  | 18 bit |

若坐标索引 `i` 参与任意活跃路径则 bit `i` 置位。

**源场位图：**

- 大小：`ceil(popcount(src_lon) * popcount(src_lat) / 8)` 字节
- 行主序：经度变化慢，纬度变化快
- Bit (i, j) ＝ 1 表示 (active_src_lon[i], active_src_lat[j]) 处的场为活跃源

**目的场位图：**

- 布局同源场位图，使用目的掩码

**内矩阵：**

- 大小：`ceil(n_active_src_fields * n_active_dst_fields / 8)` 字节
- 行主序：源变化慢，目的变化快
- Bit (s, d) ＝ 1 表示从 active_src[s] 到 active_dst[d] 存在传播

### Layer 2：方格级细节

仅当 `flags & 0x01` 时存在。对 Layer 1 内矩阵中每个置位（按行主序枚举）紧跟一个子块。

每个子块与 Layer 1 结构相同，但使用 10 bit 维度掩码（lon_square, lat_square）：

**方格维度掩码**（5 字节 ＝ 4 × 10 bit ＝ 40 bit，打包）：

| 位范围 | 掩码            | 宽度   |
| ------ | --------------- | ------ |
| 0–9    | src_lon_square  | 10 bit |
| 10–19  | src_lat_square  | 10 bit |
| 20–29  | dst_lon_square  | 10 bit |
| 30–39  | dst_lat_square  | 10 bit |

其后为源方格位图、目的方格位图与内矩阵 — 与 Layer 1 结构相同，但作用于 100 × 100 方格空间。

## 压缩与性能

原始全矩阵 ＝ 32,400 × 32,400 bit ＝ **125 MB**。

下表将理论估计与 C 测试套件实测结果合并（GCC -O2，单核 x86-64）：

| 场景                           | 场对数   | 网格路径数 | 编码大小  | 压缩比   | 编码     | 解码     |
| ------------------------------ | -------- | ---------- | --------- | -------- | -------- | -------- |
| 安静波段                       | ~100     | ~1,000     | ~2 KB     | ~64,000× | —        | —        |
| 正常活动（500 路径）\*         | 150      | 500        | 1.7 KB    | ~78,700× | 1.6 ms   | 0.2 ms   |
| 中等活动（5,000 路径）\*      | 156      | 5,000      | 19.1 KB   | ~6,700×  | 2.7 ms   | 0.4 ms   |
| 繁忙波段（20,000 路径）\*     | 156      | 20,000     | 105.6 KB  | ~1,200×  | 3.1 ms   | 0.8 ms   |
| 稠密 — 10% 随机填充 \*        | ~10,500  | ~10.5M     | 12.9 MB   | ~9.7×    | 301 ms   | 131 ms   |
| 稠密 — 11 热点（泊松）\*      | 46,955   | ~4.02M     | 4.0 MB    | ~31×     | 801 ms   | 318 ms   |

\* 为 C 测试套件实测。无时序的行为量级估计。

**11 热点场景：** 11 个场模拟真实业余人口中心（FN 美东北、EM 美东南、DN 美中部、JO 西欧、JN 南欧、IO 英爱、PM 日本、QM 东日本、BN 加拿大西、LK 印度、OL 中国），泊松分布活动。活跃格点 8,131；密度为全矩阵的 0.38%。

典型真实 FT8 场景（500–5,000 路径）编码 <3 ms、解码 <0.5 ms，适合 15 秒 FT8 周期。

> **说明：** 投影会为每块增加少量开销（掩码 + 位图）。在极高密度（>50% 填充）下，编码输出可能超过原始矩阵大小。算法针对真实电波传播中典型的稀疏、地理成簇模式优化。

## 实现

GridCodec 提供参考 C 实现及四种其他语言移植。均使用同一线格式 v1，并做交叉测试（例如非 C 实现均可解码同一 C 生成测试负载并验证结果）。

### C — 参考实现

#### 单头库

完整编解码器在 **`c/gridcodec.h`** 中，单头 C99 库，仅依赖 `<stdint.h>` 与 `<string.h>`（桌面模式还需 `<stdlib.h>` 用于 `malloc`）。

**用法示例：**

```c
#include "gridcodec.h"            /* 仅声明 */

/* 在恰好一个 .c 文件中： */
#define GRIDCODEC_IMPLEMENTATION
#include "gridcodec.h"            /* 拉入实现 */
```

所有函数为 `static`，各编译单元各自一份，无链接冲突。

#### 编译时模式

|                            | 默认（桌面/服务器）           | `GC_EMBEDDED`           |
| -------------------------- | ----------------------------- | ------------------------ |
| 内存分配                   | 动态（`malloc` / `realloc`）  | 仅静态（约 13 KB）       |
| Layer 2 支持               | 完整编码 + 解码               | 解码时跳过               |
| `gc_set` / `gc_encode`     | 可用                          | **不编译**               |
| `gc_free`                  | 可用                          | **不编译**               |
| `gc_from`/`gc_to`（4 字符）| 格点级结果                    | 退化为场级               |
| `<stdlib.h>`               | 需要                          | **不需要**               |
| `popcount`                 | `__builtin_popcount` (GCC/Clang) | 256 字节查表         |

启用嵌入式模式：

```c
#define GC_EMBEDDED
#define GRIDCODEC_IMPLEMENTATION
#include "gridcodec.h"
```

#### API 参考

**初始化与释放：**

```c
void gc_init(gc_matrix_t *m);
void gc_free(gc_matrix_t *m);   /* 仅默认模式 */
```

**设置传播路径：**

```c
int gc_set(gc_matrix_t *m, const char *from4, const char *to4);
```

记录两个 4 字符网格间的路径。幂等 — 重复由内部按位或处理。成功返回 `0`。`GC_EMBEDDED` 模式下不可用。

**编码与解码：**

```c
int gc_encode(const gc_matrix_t *m, uint8_t *buf, int cap);
int gc_decode(const uint8_t *data, int len, gc_matrix_t *m);
```

`gc_encode` 返回写入字节数（或 `GC_ERR_OVERFLOW`）。`GC_EMBEDDED` 模式下不可用。

`gc_decode` 返回消费字节数。在 `GC_EMBEDDED` 模式下，Layer 2 数据会被解析通过（以返回正确字节数）但丢弃。

**查询传播：**

```c
int gc_from(const gc_matrix_t *m, const char *grid, int *out, int max_out);
int gc_to(const gc_matrix_t *m, const char *grid, int *out, int max_out);
```

- 2 字符输入（如 `"FN"`）：返回场索引（0–323）
- 4 字符输入（如 `"FN31"`）：默认模式返回格点索引（0–32399），`GC_EMBEDDED` 模式返回场索引

`gc_from` 返回从给定源可达的目的地。`gc_to` 返回能到达给定目的地的源。

**索引/名称转换：**

```c
int  gc_field_index(const char *name);     /* "FN"   -> 0..323   */
void gc_field_name(int idx, char out[3]);  /* 0..323 -> "FN\0"   */
int  gc_grid_index(const char *name);      /* "FN31" -> 0..32399 */
void gc_grid_name(int idx, char out[5]);   /* 0..32399 -> "FN31\0" */
int  gc_grid_to_field(int grid_idx);
int  gc_grid_to_square(int grid_idx);
```

所有名称输入大小写不敏感。

**错误码：**

| 常量             | 值  | 含义                 |
| ---------------- | --- | -------------------- |
| `GC_ERR_INVALID`  | -1 | 无效网格名           |
| `GC_ERR_OVERFLOW` | -2 | 输出缓冲区过小       |
| `GC_ERR_FORMAT`   | -3 | 线格式数据畸形       |
| `GC_ERR_CAPACITY` | -4 | 内存分配失败         |

#### 内存占用

**默认模式：**

| 组件               | 大小                              |
| ------------------ | --------------------------------- |
| Layer 1 场位图     | 13,122 字节（固定）               |
| 场对元数据         | 38 字节（指针 + 计数）            |
| 每活跃场对         | 1,254 字节（源 + 目的 + 方格位）  |

总内存随活跃场对数线性增长：

| 活跃场对数 | 总内存   |
| ---------- | -------- |
| 0          | 12.9 KB  |
| 64         | 91.2 KB  |
| 256        | 326.4 KB |
| 1,024      | 1,266.9 KB |

**嵌入式模式：** 固定 **13,122 字节**（12.8 KB），无堆分配。

#### 构建与测试

需要：C99 编译器（建议 GCC/Clang）、`make`。

```bash
cd c
make test
```

会编译并运行两套测试：

1. **test_gridcodec** — 默认（桌面/服务器）模式：辅助函数正确性、往返编码/解码、查询验证、缓冲区溢出、真实场景（500 / 5,000 / 20,000 路径）、稠密最坏情况、极端测试（10% 随机填充、11 热点泊松）。
2. **test_embedded** — `GC_EMBEDDED` 模式：静态内存大小验证、Layer 1 解码、Layer 1+2 解码（Layer 2 正确跳过）、4 字符查询退化、编译期无编码 API。

跳过极端测试（在 Valgrind 或慢速硬件上有用）：

```bash
SKIP_EXTREME=1 ./test_gridcodec
```

内存泄漏检查：

```bash
gcc -g -O0 -std=c99 -o test_dbg test_gridcodec.c
SKIP_EXTREME=1 valgrind --leak-check=full ./test_dbg
```

两种模式均已验证无泄漏（0 错误，所有堆块已释放）。

### Python

**位置：** `python/` — 纯 Python 包（`gridcodec`），完整编码/解码/查询支持。

```bash
cd python && python3 test_gridcodec.py
```

### MicroPython

**位置：** `micropython/` — 单文件 `gridcodec.py`，仅解码 + 查询。4 字符查询退化为场级。面向 ESP32、Pyboard、Raspberry Pi Pico 等。

```bash
cd micropython && python3 test_gridcodec.py     # 主机
cd micropython && ./run_on_device.sh             # 设备 via mpremote
```

### JavaScript

**位置：** `js/` — Node.js 与浏览器，完整编码/解码/查询。

```bash
cd js && node test_gridcodec.js
```

### Java

**位置：** `java/gridcodec/` — Java 8+，完整编码/解码/查询。

```bash
cd java && javac -source 8 -target 8 gridcodec/*.java && java -cp . gridcodec.TestGridCodec
```

### 已验证工具链

各实现已用下列工具链测试：

| 语言         | 工具链               | 版本     | 备注                                                        |
| ------------ | -------------------- | -------- | ----------------------------------------------------------- |
| **C**        | GCC                  | 13.3.0   | 默认 + 嵌入式模式，全部测试通过                              |
| **Python**   | CPython              | 3.12.3   | 500 路径：约 12 KB，编码 ~470 ms，解码 ~50 ms               |
| **MicroPython** | Pico (RP2040) mpremote | 1.27.0 | L1-only 14 B：~87 ms/解码；L1+L2 跳过 30 B：~3535 ms        |
| **JavaScript**  | Node.js             | v18.19.1 | 500 路径：约 12 KB，编码 ~6 ms，解码 ~1 ms                  |
| **Java**     | OpenJDK              | 21.0.10  | 500 路径：约 12 KB，编码 ~5 ms，解码 ~1 ms                  |

跨语言互操作：Python、JavaScript、Java 测试套件均解码同一 C 生成负载（仅 Layer 1，FN↔PM、JO↔FN）并验证场级结果。

## 设计取舍

**单头库。** 便于多语言绑定。本仓库提供 Python、MicroPython、JavaScript、Java 实现；均共用同一线格式。

**静态函数。** 多编译单元包含头文件时避免符号冲突。编译器会消除未用函数。

**双模式编译。** 嵌入式设备（如 ESP32、STM32）需要零堆、仅解码能力。`GC_EMBEDDED` 标志去掉所有编码逻辑与动态内存，得到约 13 KB 静态占用，适合仅接收站。

**线性场对搜索。** `gc_set` 与 `gc_from`/`gc_to` 对场对做线性搜索。典型场对数 <500 时比哈希表开销更快。在 10,000+ 对（极端场景）下会成为可测量成本（约 800 ms 编码），但对批处理服务端编码仍可接受。

**幂等 `gc_set`。** FT8 解码可能在同一时间窗内产生重复报告，`gc_set` 设计为可对同一对重复调用且无额外成本。

**自描述线格式。** 每个字段大小由已解码数据推出。无需长度字段，格式健壮：解码器要么完整解析流，要么返回错误码。

## License

TBD
