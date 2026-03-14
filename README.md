# FT8 Propagation Tracker — 简短介绍

## 项目是做什么的

**FT8 Propagation Tracker** 是一个面向业余无线电爱好者的传播观测工具。它以后台“外挂”的方式监听 **WSJT-X / JTDX** 的 UDP 报文，自动提取解码（RX）和已完成的 QSO（TX）中的传播信息，**匿名上报**到服务器，用于汇聚“谁在什么频率、什么时间、从哪到哪”的链路开通情况，尤其方便查看 **6m 等频段**的传播状况。

- **客户端**：单文件、零额外依赖，支持 GUI 和 CLI，可与 WSJT-X/JTDX 同时运行。
- **服务端**：汇聚各用户上报的数据，供后续查询与可视化（如 Phase 2/3 的地图、统计）。

---

## 随附的 GridCodec 是什么

客户端源码会与 **GridCodec** 一起发布。GridCodec 是本项目使用的 **Maidenhead 网格传播矩阵二进制编解码器**，用来高效广播“谁到谁有传播”的数据。

- **要解决的问题**：全 4 字网格有 32,400 个格点，原始邻接矩阵约 **125 MB**，向大量客户端广播不现实。
- **做法**：用分层维度投影算法利用传播的**地理稀疏性**，把典型 FT8 活动压缩到 **约 2–20 KB**（压缩比可达万倍以上），方便服务器推送、客户端接收。
- **在项目里的角色**：服务端用 GridCodec **编码**传播矩阵后下发给客户端；客户端的雷达/地图视图用 GridCodec **解码**并展示。因此发布客户端源码时会一并带上 GridCodec，便于编译和运行。
- **实现**：同一套线格式（v1）提供 **C（参考）、Python、MicroPython、JavaScript、Java** 等实现，可交叉编解码。详见仓库内 `src/gridcodec/` 及 [README-CN.md](gridcodec/README-CN.md)。

---

## 隐私如何保护

上报的数据**只包含传播相关的最小信息**，不包含任何可识别个人或电台身份的字段：

| 上报内容 | 说明 |
|----------|------|
| **有** | 四字 Maidenhead Grid（如 `PM01`）、频率、时间、类型（RX/TX） |
| **无** | 呼号、信号强度(SNR)、模式、具体消息内容 |

也就是说：服务器只知道“某个 grid 在某个频率、某个时间与另一个 grid 有传播”，**不知道是哪个呼号**，也无法反推你的呼号。所有上报都是匿名、仅基于 grid 的。

---

## Windows 客户端下载（exe）

若你使用 Windows 且不想安装 Python，可直接下载打包好的单文件 exe：

- **下载地址**：[点击下载 ft8_tracker_client.exe](https://github.com/YOUR_USERNAME/ft8_tracker/releases/latest/download/ft8_tracker_client.exe)

使用前请在 WSJT-X/JTDX 中开启 **Accept UDP requests**（默认端口 2237），运行 exe 后按界面或文档配置服务器地址即可。
