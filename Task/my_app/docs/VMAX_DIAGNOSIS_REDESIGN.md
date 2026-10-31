# VMAX 用户查询 —— 投诉定位视角重构方案

> 状态：**方案待评审**（未动代码）  
> 日期：2026-10-31　|　作者：小微  
> 页面：`?page=vmax_user_query`　|　相关代码：`frontend/src/pages/VmaxUserQuery.tsx`、`frontend/src/components/Vmax*.tsx`、`backend/services/vmax_cca/*`、`backend/routers/vmax_*.py`

---

## 一、先说结论（为什么会空、乱在哪）

### 1.1 现场复现（2026-10-31 10:00 实测，窗口 08:00~10:00）

| 号码             | 用户面 1300（分类流量取数表） | 1100 会话/信令 | RAN 32 按号码        | RAN 32 按 IMSI |
| -------------- | ----------------- | ---------- | ----------------- | ------------- |
| `231773777115` | **645 条**         | 107 条      | **0（3100100202）** | **101 条**     |
| `231777550122` | **0**             | —          | 0                 | —             |

`/api/vmax-flow-xdr?msisdn=231777550122&start=07:30&end=10:30` 返回  
`{"found":false,"records":0,"apps":[],"categories":[]}` —— 这正是用户看到的「Categorized Traffic 是空的」。

### 1.2 空的三层原因

**原因 A：号码在用户面表里真的没有记录（不是 bug）**  
`231777550122` 在 `fact_5gsa_psup_flow` 里 0 条，在 CCA 的 DPI 表里同样 0 条。  
分类流量对「没上网/没被 DPI 采到」的号码天然为空。现在的界面把这种「业务正常」渲染成一个空页签，用户无法区分「没数据」与「功能坏了」。

**原因 B：只问了一种问法就放弃了**  
分类流量只查 `fact_5gsa_psup_flow`（serviceType=1300）。同一号码的同类数据其实在别的表里还存在：

- `1100` 会话/信令面 —— 判「有没有连接、为什么连不上」的唯一证据（`procedure_status` / `fail_cause` / `request_cause`）；
- `32` RAN —— 判「空口好不好」的唯一证据（`serving_rsrp` / `ulsinr` / `cqi` / `ta_ts` / `phr`）；
- `1301` 视频专表 —— 带 `vmos` / `resolution`，判「视频清不清晰」。

现在这四个数据源被摊在四个互不相干的页签里，各自用自己的口径、各自空各自，用户得自己在脑子里拼。

**原因 C：Merged XDR 与 XDR Records 按号码查 RAN 永远查不到（真 bug，已定位）**  
`backend/services/vmax_cca/vmax_xdr_client.py:529-538`

```python
if spec["domain"] == DOMAIN_RAN:
    number_field, number_name = "$msisdn", "User Number"
```

实测：RAN 表的 `$msisdn` 列**全为空串**（记录只带 IMSI，实测样本 `imsi=618070113596304`，`$msisdn=""`）。  
于是「按号码查 RAN」= 「按空值匹配」→ 必然 `3100100202`。  
把条件字段换成 `imsi` 后同一窗口立刻返回 **101 条** —— **根因确认**。

> 这条 bug 的后果是：页面上「空口质量」这一整块证据链，**从来没有真正工作过**。用户说「卡」，我们拿不出 RSRP/SINR。

### 1.3 「混乱」的根源：页签是按**数据源**切的，不是按**问题**切的

```
现在的页签：  Overview(CCA) │ Categorized Traffic(1300) │ Merged XDR(合并表) │ XDR Records(32分表)
                  ↓                ↓                       ↓                  ↓
              用户/终端/根因    应用流量分类            一堆原始信令列        另一堆原始列
```

四个页签是四套**上游接口**的镜像。它们各自完整，但**回答不了同一个问题**：

> 「用户投诉语音断断续续 / OTT 卡 / 看视频转圈 —— 到底是什么原因？」

要回答这个问题，需要的是**把四个源按时间对齐后做交叉判断**，而不是让用户自己去三个表里找同一分钟的记录。现在的设计把「判断」这件事交给了用户。

---

## 二、重构目标（先定「页面要回答什么」）

页面从「**数据查询台**」变成「**投诉定位台**」。一次查询必须能直接输出一句话结论 + 可下钻的证据。

### 2.1 三类投诉 → 需要的证据链

| 投诉类型                    | 用户能感知的现象       | 判定需要的证据                                                                                                                              | 数据来源                                                                              |
| ----------------------- | -------------- | ------------------------------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------- |
| **语音类**（VoLTE / OTT 语音） | 断续、无声、单通、掉话    | ① 是否有 VoIP/RTP 话单与 QCI=1 承载<br />② RTP 抖动/丢包/时延<br />③ 对应时段的 `ulsinr`/`rsrp` 是否劣化<br />④ 是否发生 `S1-U Path Failure`、`PAGING` 失败、TAU 失败 | 1300 `service=VoIP` + `ul_avg_rtt`；32 `ulsinr`；1100 `procedure_status/fail_cause` |
| **OTT / 视频类**           | 转圈、起播慢、清晰度掉、卡顿 | ① 视频/OTT 应用的流量与时长<br />② 首包/首响时延（`$first_resp_delay`）<br />③ 下行速率与峰值、TCP 重传率<br />④ 视频 MOS / 分辨率（1301）<br />⑤ 同时段空口 SINR/RSRP/CQI    | 1300 分类聚合；1301 `vmos/resolution`；32 `cqi/ulsinr`                                  |
| **上网慢 / 其他**            | 网页打不开、微信转圈     | ① DNS/TCP 握手时延<br />② 重传率、乱序率<br />③ 会话建立失败原因<br />④ 小区级拥塞/弱覆盖                                                                       | 1300 `$tcp_resp_delay/$syn_cnt`；1100 `fail_cause`；32 `phr/cqi`                    |

### 2.2 页面必须给出的三样东西

1. **一句结论**：`语音投诉 / 疑似空口弱覆盖`（带置信度与证据条数）
2. **一张证据列表**：每条结论后面挂「哪一分钟、哪条记录、哪个字段」
3. **可下钻明细**：点证据 → 落到该时段的原始 XDR 行（沿用现有 `DraggableClickModal`）

---

## 三、数据现实核查（设计必须建立在这些事实上）

> 以下全部是 2026-10-31 用真号实测，不是推测。**口径以此为准。**

### 3.1 用户面 1300 `fact_5gsa_psup_flow`（分类流量的主表）

- 88 列，**600 条实测样本，关键字段填充率 100%**：  
  `ul_traffic / dl_traffic / $ul_pkt / $dl_pkt / $ul_retrans_pkt / $dl_retrans_pkt /
  $ul_disorder_pkt / $dl_disorder_pkt / $tcp_resp_delay / $tcp_ack_delay /
  $first_req_delay / $first_resp_delay / ul_avg_rtt / dl_avg_rtt / duration`
- **不可用**：`host` / `url` 全为空串；`ue_model` 为 `-`；`procedure_status` 全空。  
  → **不能按 URL 域名做分类**，只能靠 `service` / `subservice` / `app_content_name`。
- `service` 实测取值只有 8 类：`Public Traffic / Web Browse / IM / Others / Comm Traffic / Social / Network Storage / VoIP`  
  → **没有 Video、没有 Game**。「视频/OTT视频/游戏」三个页签在当前数据下**结构性为空**，不是 bug。
- 流量单位是 **KB**（`dl_traffic=2267422.0` ≈ 2.2 GB）。
- `$first_resp_delay` 单位 **ms**（实测均值 455、最大 118765 = 118 秒 ——「转圈」的直接证据）。
- `duration` 单位 **ms**（实测均值 47724）。

### 3.2 RAN 32（空口质量）

- 表：`ods_lte_xdr_uu_cmcc(UU_XDR)` / `ods_lte_xdr_x2_cmcc(X2_XDR)` / `fact_lte_uemr(UEMR_XDR)`
- **只能按 IMSI 查**（见 1.2 原因 C）。
- UEMR 列：`serving_rsrp / serving_rsrq / ulsinr / cqi / ta_ts / phr / neighbor_* / mrlat / mrlon / cell / enbid` —— 弱覆盖、上行受限、频繁切换都能判。
- 时间字段是 `btime`，保留期 **24h**（比其它类型短，页面级窗口下限就是被它卡住的）。
- 实测该号 2 小时 **101 条 MR**，量级足够做分钟级趋势。

### 3.3 会话/信令面 1100（连接与失败原因）

实测 107 条，可用判据：

- `procedure_type`：`LOCATION-UPDATE / MM-INFORMATION / TMSI-REALLOCATION / PAGING / Update PDP / Purge_UE / Authentication_Information`
- `procedure_status`：`Success` / 失败
- `request_cause`：实测出现 `S1-U Path Failure. See NOTE 8`（**用户面路径中断 = 业务直接断**，语音/视频投诉的强证据）
- `fail_cause`、`interface`（SGs / S6a / Gn）

### 3.4 性能

| 查询            | 实测耗时                      |
| ------------- | ------------------------- |
| 1300 单页 200 条 | ~2-3 s                    |
| 1300 三页 600 条 | ~12 s（**当前分类流量接口就是这个量级**） |
| 32 单表         | ~0.3-1.7 s                |
| 1100 单页 50 条  | ~1-2 s                    |

→ **四个源串行不可接受**。必须并行 + 分源独立降级（一个慢不能拖死整页）。

### 3.5 会话纪律（血泪）

上游按用户限并发，多个探测进程各自登录会触发  
`The maximum number of connections for the user is reached`（本次调研就踩到了）。  
**所有取数必须复用后端单例 `get_xdr_client()` 的会话，禁止探针式并发登录。**

---

## 四、新设计：从「四个数据源」到「一个诊断结论」

### 4.1 页签重构

```
【输入】 号码 + 时间窗（沿用现有：整页唯一、默认近 3h、滚动）

【输出】 ① 诊断结论卡（新增，置顶）
        ② 证据时间线（新增，按分钟聚合，可下钻）
        ③ 三个证据页签（重命名 + 重排序，职责互斥）
```

| 新页签                        | 旧页签                 | 职责（一句话）              | 数据源                  |
| -------------------------- | ------------------- | -------------------- | -------------------- |
| **诊断结论** `Diagnosis`       | *（新增）*              | 一句话结论 + 证据条 + 分项评分   | 全部四源交叉               |
| **业务流量** `Service Traffic` | Categorized Traffic | 用户用它做了什么（按业务分类 + 应用） | 1300 + 1301          |
| **连接过程** `Connectivity`    | Merged XDR          | 连上了没有、失败在哪个环节        | 1100 + 1300 的 TCP 指标 |
| **无线质量** `Radio Quality`   | XDR Records         | 空口好不好、在哪个小区          | 32（按 IMSI）           |

> 刻意保留「Merged XDR / XDR Records」的原始明细能力，但它们**降级为「证据明细」入口**，从诊断结论和证据时间线跳进去，而不是让用户自己去翻。  
> 产品名建议保留英文原词（`Merged XDR` / `XDR Records`）作副标题，避免现场对照上游截图时对不上。

### 4.2 诊断结论卡（页面的核心，先做这个）

四个并列的**分项评分**（0-100，越低越差），每项都可点开看证据：

| 分项        | 计算口径（只用实测可用字段）                                                     | 阈值（初版，可配置）                     |
| --------- | ------------------------------------------------------------------ | ------------------------------ |
| **业务可用性** | 1100 中 `procedure_status≠Success` 占比；出现 `S1-U Path Failure` 直接扣到 0 | 失败率 >5% 告警                     |
| **响应时延**  | 1300 `$first_resp_delay` P90、`$tcp_resp_delay` 均值、`ul_avg_rtt` 均值  | P90 > 3 s 告警                   |
| **传输质量**  | `(ul+dl_retrans_pkt)/(ul+dl_pkt)` 重传率；乱序率                          | >1% 告警                         |
| **无线质量**  | 32 的 `serving_rsrp` P10、`ulsinr` P10、`cqi` P10                     | RSRP < -110 dBm、SINR < 0 dB 告警 |

**结论生成规则**（确定性规则，不用 LLM；理由：可复现、可解释、能写进报告）

```
if 业务可用性 < 50  → "连接失败为主因"       证据：N 条失败过程 + 失败原因 top3
elif 无线质量 < 50  → "空口弱覆盖/上行受限"   证据：最差 10 分钟 RSRP/SINR + 所在小区
elif 传输质量 < 50  → "网络传输质量差（重传/乱序）" 证据：重传率最高的 10 个应用
elif 响应时延 < 50  → "应用侧响应慢（DNS/首包）"   证据：首包时延最长的应用
else               → "四维正常，未复现问题"
```

再叠加**投诉类型预设**（用户进页面第一件事就是选/被系统猜出投诉类型）：

- 选了「语音」→ 只看 `service ∈ {VoIP}` 与 `qci=1` 的话单，加判 `ul_avg_rtt` 抖动、`jitter`
- 选了「视频/OTT」→ 只看 `service ∈ {Video, Web Browse}` 且 `app_content_name` 命中 OTT 名单，加判 `$first_resp_delay` 与 1301 的 `vmos`
- 选了「上网慢」→ 全量

### 4.3 证据时间线（把四个源按分钟对齐）

按分钟一列聚合，同一行里四源并列 —— 这是「交叉判断」的落地形态：

```
时间      业务流量        响应时延      传输质量        无线质量      结论
08:14  视频 320MB ↓      首包 8.2s↑    重传 3.1%↑    RSRP -118↓   弱覆盖导致卡顿
08:15  视频 88MB ↓       首包 2.1s     重传 0.2%     RSRP -95     正常
08:31  VoIP 会话中断       —            —            SINR -3↓     S1-U 路径失败
```

- 每一格都可点 → 弹 `DraggableClickModal` 看该分钟该源的原始 XDR 行
- 下行流量高 + 首包慢 + RSRP 差 ≈ 弱覆盖下的高码率视频（典型投诉场景）
- 无话单但有 `S1-U Path Failure` ≈ 用户「断网了」（比流量为 0 更有解释力）

### 4.4 空态必须说清楚「为什么空」

现在的空态是一句话。改成三段式：

```
该时段内无业务流量话单
· 已查数据源：用户面 1300（0 条）、视频专表 1301（0 条）
· 同号码在会话/信令面 1100 有 12 条记录 → 说明终端在网但未产生用户面话单
· 可能原因：仅待机/仅 VoLTE 语音（不走 5gsa 用户面）、或该时段超出采集范围
[查看连接过程]  [查看无线质量]
```

关键：**即使业务流量为 0，也要告诉用户「别的源有没有数据」**，把「空」变成一条结论。

---

## 五、后端改造

### 5.1 必须先修的 bug（P0）

**`vmax_xdr_client.py::_build_condition` —— RAN 域按号码查不到**

```python
# 现状（错）：$msisdn 列全为空串，匹配必然为空
if spec["domain"] == DOMAIN_RAN:
    number_field, number_name = "$msisdn", "User Number"
```

改为 **MSISDN → IMSI 解析后再按 `imsi` 查**：

1. 先用 1300（或 1100）取该号码的 `imsi`（1300 每行都带 `imsi`，实测可用）；
2. 用 `{"field": "imsi", "value": <imsi>, "type": "1", "name": "IMSI"}` 查 RAN；
3. IMSI 取不到时，RAN 相关卡片显示「无 IMSI 映射，无法查无线质量」，**不要静默返回 0 条**。

> 验证：`231773777115` → IMSI `618070113596304` → RAN 08:00~10:00 从 0 条变 **101 条**。

**`vmax_diagnosis.py::fetch_all` 漏传号码（P0，2026-10-31 补修）**

聚合层写出来时 `fetch_all(start, end)` 没有 `msisdn`，`_page_through` 里调的是
`query_table("", ...)` —— 条件成 `{"field":"msisdn","value":"","type":"1"}`，
上游如实按空号码过滤，**四个源恒 0 条**。上面那条 IMSI 修复因此一直"验证不了"：
1300 拿不到行 → 解析不出 IMSI → RAN 报「无 IMSI 映射」，被误读成上游会话被占满。

同表同窗口实测（`fact_5gsa_psup_flow` / 2026-10-30 17:00~10-31 16:59）：

| 调用方式 | records |
| --- | --- |
| `/api/vmax-xdr-records`（带号码） | **2484** |
| `/api/vmax-diagnosis`（当时） | **0** |

修法：`fetch_all(msisdn, start, end)` 必填，`msisdn` 一路传到 `query_table` 首参；
空号码直接 `ValueError`（宁可 500，也不要静默返回全空 —— 静默全空会被写进投诉工单）。

修完实测（`231773777115`，13:59~16:59）：1300 **512 条** / 1100 **792 条** /
32 RAN **216 条** / 1301 0 条，IMSI `618070113596304`，耗时 8.0s。

**RAN 字段契约（同批实测）**

| 项 | 实际 | 坑 |
| --- | --- | --- |
| 小区列 | `cell` | 只读 `cellname`/`cell_name` → 全部塌成「未知小区」 |
| `cqi` | 216/216 行 = **65535** | 哨兵值，`>0` 过滤不掉 → 平均 CQI 显示 65535 |
| `ulsinr` / `phr` | 出现 **255** | 同上，会把 P10/均值拉高，结论从「干扰」翻成「正常」 |
| `rat_name` / `interface_name` | 全为空串 | 制式分布只能显示 `—`（`$rat` 只有代码，未做码表映射） |

### 5.2 新增聚合层

新增 `backend/services/vmax_cca/vmax_diagnosis.py`：

```
VmaxDiagnosis
  ├─ fetch_all(msisdn, start, end)   # 并行取 1300 / 1301 / 1100 / 32，单源失败不影响其它
  ├─ _timeline(rows_by_source)       # 按分钟对齐，输出 evidence timeline
  ├─ _scores(...)                    # 四个分项评分
  └─ _verdict(...)                   # 规则引擎出结论 + 证据引用
```

- 新增路由 `GET /api/vmax-diagnosis?msisdn=&start=&end=&complaint=voice|video|data`
- 返回：`{verdict, scores[], evidence[], timeline[], sources: {1300: {n, ok, err}, 32: {...}}, window}`
- 单源超时/失败 → 该源 `ok=false` + 原因，其余照常返回（**不整页失败**）

### 5.3 现有接口的归并

| 现有                              | 处置                                                  |
| ------------------------------- | --------------------------------------------------- |
| `GET /api/vmax-flow-xdr`        | 保留，但内部改为**复用** `VmaxDiagnosis` 的 1300+1301 结果，不重复取数 |
| `GET /api/vmax-xdr-query`（合并表）  | 保留，作「连接过程」明细下钻                                      |
| `GET /api/vmax-xdr-records`（分表） | 保留，修 IMSI 后作「无线质量」明细下钻                              |
| `GET /api/vmax-cca-query`       | 保留（用户/终端/根因），诊断卡可引用其 `causes`                       |

> 原则：**聚合层只做一次取数，明细接口只做下钻**。现在的「同一份 1300 数据被取两遍」要收敛掉。

---

## 六、前端改造

| 文件                                                        | 动作                                                         |
| --------------------------------------------------------- | ---------------------------------------------------------- |
| `pages/VmaxUserQuery.tsx`                                 | 页签改四个（诊断结论 / 业务流量 / 连接过程 / 无线质量）；新增投诉类型选择；挂载诊断接口           |
| `components/VmaxDiagnosisCard.tsx`                        | **新增**：四维评分 + 结论 + 证据条（`StatCard` + 下钻）                    |
| `components/VmaxEvidenceTimeline.tsx`                     | **新增**：分钟级四源对齐表，格子可点下钻（`DraggableClickModal`）              |
| `components/VmaxFlowCategoryTabs.tsx`                     | 页签口径改：删掉结构性为空的 Video/Game 默认位，改为「按实测 service 动态生成 + 空分类折叠」 |
| `components/VmaxXdrPanel.tsx` / `VmaxXdrRecordsPanel.tsx` | 定位改为「明细下钻」，支持从时间线带 `start/end` 定位进来                        |
| `i18n.tsx`                                                | 中英各一套新键（`vmaxq.diag.*` / `vmaxq.tl.*`）                     |
| `helpContent.ts` + `docs/manual/11-feature-guide.md`      | 同步                                                         |

约束（照 AGENTS.md）：`CardBase`/`StatCard` 统一卡片、`exportAoaReport` 统一导出、`DraggableClickModal` 统一弹窗、i18n 中英两处、`check:i18n` 必须过。

---

## 七、口径与阈值（要你拍板的部分）

下面这些我按经验给了初值，**请确认或改**：

| 项      | 初值                                 | 依据                      |
| ------ | ---------------------------------- | ----------------------- |
| 默认窗口   | 3 小时（不变）                           | 现网保留期下限 24h，3h 足够定位     |
| 弱覆盖阈值  | `serving_rsrp < -110 dBm`          | LTE 常用门限                |
| 上行受限   | `ulsinr < 0 dB`                    | 实测样本 SINR 范围宽，需按现网再校准   |
| 重传率告警  | `>1%`                              | 实测命中样本均值 ~0.2%，1% 以上属异常 |
| 首包时延告警 | `$first_resp_delay` P90 `> 3s`     | 实测均值 455ms、峰值 118s      |
| 视频清晰度  | `vmos < 3.0` 或 `resolution < 480p` | 1301 表字段                |
| 流量单位   | 界面上 KB→自动换算 MB/GB                  | 上游是 KB                  |
| 分类页签   | 只展示**有数据**的分类，空的折叠进「其他」            | 实测没有 Video/Game         |


> ⚠️ 一个必须说明的限制：`$msisdn` 在 RAN 表为空这件事，说明**上游这一路的数据质量本身有缺口**。  
> 如果某个 IMSI 在 1300 里也查不到（纯待机用户），就完全无法定位无线侧 —— 这种号码的结论只能写「无数据可判」，不能写「正常」。

---

## 八、落地顺序（建议分三批）

| 批次     | 内容                                                         | 可独立验证                            |
| ------ | ---------------------------------------------------------- | -------------------------------- |
| **P0** | 修 RAN 按 IMSI 查的 bug + 空态三段式说明                              | 用 `231773777115` 验证 32 从 0→101 条 |
| **P1** | 后端 `vmax_diagnosis.py` 聚合层 + `/api/vmax-diagnosis`；前端诊断结论卡 | 四维评分与结论在本机可复现                    |
| **P2** | 证据时间线 + 页签重排 + 分类页签动态化 + 帮助文档                              | Playwright 实测四源对齐                |

---

## 九、需要你确认的 5 个问题

1. **投诉类型**要不要做成页面上手动选的下拉？（或默认「自动判断」，仅在选择后收窄口径）
2. 「游戏」页签在现网数据里**结构性为空**（上游 service 无 Game 类）。是**删掉**，还是保留并标注「本网暂无游戏识别」？
3. 语音投诉：本网是否部署 VoLTE？若语音走 CSFB，1300 里看不到，需要另找 1100 的 SGs 接口记录来判 —— 要不要纳入？
4. 结论是否要**允许人工覆写**（写备注、钉住结论），供后续做投诉闭环（类似 AP 行动计划）？
5. 诊断卡是否需要**导出 Excel/PDF** 直接贴进投诉工单？

---

## 附：本次调研的原始证据位置

- 复现命令与返回：窗口 `2026-10-31 07:30~10:30`，`/api/vmax-flow-xdr?msisdn=231777550122` → `records:0`
- RAN 根因：`vmax_xdr_client.py:529-538`，`$msisdn` 空串；换 `imsi` 后 101 条
- 1300 字段填充率：600 条样本，`$first_resp_delay` 均值 455ms / 最大 118765ms
- RAN 101 条样本：`imsi=618070113596304`，`rat_name=(4G)EUTRAN`
- 1100 107 条样本：`request_cause` 出现 `S1-U Path Failure`
