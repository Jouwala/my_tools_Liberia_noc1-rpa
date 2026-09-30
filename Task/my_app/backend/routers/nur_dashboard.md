# NUR / SLA 看板 API 说明

路由前缀：`/api/nur`，计算引擎 `backend/services/nur_calc.py`。
数据源：主库 `eflow_tt` + `cm_site_summary`（DB_MODE=pg/sqlite 双模兼容）。

## 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/nur/options | 筛选项：vendors(ZTE/3RD)、projects(site_information 去重值)、site_filters(站点四维候选值)、排除名单加载状态 |
| GET | /api/nur/overview | 一次返回 6 张表（NUR/SLA × daily/weekly/monthly） |
| GET | /api/nur/detail | 单元格下钻（TT 明细），筛选口径与 /overview 逐条一致 |

`/overview` 参数：

| 参数 | 说明 |
|------|------|
| vendor | ZTE=ticket_no 非空；3RD=ticket_no 空；空=全部 |
| project | site_information 站点类型（REGULAR/ERA/...），空=全部 |
| exclude | Y=排除名单内；N=名单外；空=全部 |
| trm_type | 站点主数据 master_site_db.trm_type 精确匹配，空=全部 |
| site_caregory | 站点主数据 site_caregory 精确匹配，空=全部 |
| province_county | 站点主数据 province_county 精确匹配，空=全部 |
| region | 站点主数据 region 精确匹配，空=全部 |
| start / end | YYYY-MM-DD，作用于 alarm_occur_time（end 含当天） |
| refresh_exclude | true=强制刷新 FTP 排除名单缓存 |

`/detail` 除上述筛选参数（vendor/project/exclude + 站点四维）外，另有
`metric` / `gran` / `period` / `tech` / `severity` / `item`。

## NUR 计算口径

1. Tech 模糊匹配：取 title 最后一个 `]` 之后的告警类型段
   - 单制式：含 2G/3G/4G(或 LTE)/5G → 对应制式小区数
   - 整站：Complete site down(CSD)/Partial site down(PSD)/SITE DOWN DUE TO POWER OFF
     → 该站在 cm_site_summary 中全部制式小区数
   - 其余（MW LINK DOWN、Fiber Break 等）→ 不计入 NUR（仍计入 SLA）
2. 小区数关联：site_id → cm_site_summary.Site_ID，空值回退 site_name 小写匹配
3. MTTR = (alarm_clear_time − alarm_occur_time) 分钟；剔除 ≤0 或 ≥43200；未清除不计 NUR
4. NUR_tech(期间) = Σ(小区数×MTTR分钟)×60 / (分母小区数×GR)
   - GR：日=86400 秒；周=604800 秒；月=当月天数×86400 秒（当期未过完按已过天数）
   - 整站类 TT 按该站自身各制式小区数分别归属到 2G/3G/4G/5G
   - Global = 所有制式分子分母求和；输出原始数值（不乘 100）
   - 前端展示口径：表格与趋势图均按 原始值 × 100000 显示（后端仍返回原始值）
5. 分母适配：默认全网该制式小区总数；Project 筛选生效时改为
   cm_site_summary.site_caregory 与所选站点类型归一化包含匹配（去括号小写，
   如 'REGULAR（Normal)' 匹配 'REGULAR'）圈定的小区数。Vendor/时间/Exclude 仅作用于分子。
6. 站点四维过滤（trm_type / site_caregory / province_county / region，2026-09-30 新增）：
   见下节。

## 站点四维过滤（trm_type / site_caregory / province_county / region）

- **属性来源是站点主数据 `master_site_db`**，不是 `cm_site_summary` —— 后者只有
  region / province_county / site_caregory 三列、没有 trm_type；四列同源才能保证
  「分子圈定的站点」与「分母圈定的站点」是同一批。口径与 GISMap / TT&WO Dashboard 的
  站点维度筛选一致（同一个真相源）。
- **精确匹配**（`=`，不用 LIKE），候选值由 `/api/nur/options` 的 `site_filters` 下发，
  前端不硬编码（`nur_calc.get_site_filter_options`，每列上限 200 个）。
- **同时作用于分子与分母**：TT 行按站点属性过滤，`cm_site_summary` 小区数按同一属性
  圈定后重算 `denominator_cells` 与 `persite_nur` 的分母站点集合。只筛分子会让 NUR
  的比值不再是「这批站点的不可用率」（`nur_calc.compute_overview` 的 `site_filters`）。
- **站点归属规则**（`nur_calc.attach_site_attrs` / `build_site_index`）：
  1. `site_id` 命中优先（实测 36510 行 TT 中 36040 行命中，主库 site_id 唯一，不产生扇出）；
  2. 未命中时回退**站名小写**匹配，但**重名站点不参与回退** —— 主数据有 11 个重名站
     （如 'Gbarplay' 同时是 9049=ERA / 3620=NORMAL），任选一个都是静默错归。
- **未归属的行在站点过滤生效时被排除**（不猜属性）。因此各分档求和会略小于全网：
  实测 TT 36067/36510（差 443 行）、小区数 14069/15064（差 995 个）—— 这是
  「只统计能证明属于该筛选项的站点」的预期结果，不是漏算。
- 与 `project` 筛选**叠加**（AND），二者语义不同：`project` 取 `eflow_tt.site_information`
  （REGULAR / ERA），四维里的 `site_caregory` 取主数据（NORMAL / ERA / COOL）。

## SLA 口径

按 ticket_severity(P1~P4) 分组，行 = P1~P4 + Total：
Total（总单数）/ Within SLA（sla_status='Pass'）/ Achieve（达成率）。
与 NUR 使用相同筛选条件，按日/周/月透视。

## Exclude 排除名单

来源：FTP 192.168.100.19 `/webroot/WEB-INF/reportlets/excel/TT_Exclude.xlsx`
（凭据 FINEBI/DX，由 remote_ftp.creds_for 按 /webroot 前缀映射）。
自动识别列名含 TT/Ticket/单号 的列（回退第一列）；eflow_tt 的 ticket_no 或
tt_no 任一命中即 Exclude=Y。内存缓存 30 分钟；FTP 失败降级：有旧缓存用旧缓存，
否则空集并在响应 warnings / exclude.error 中提示。

## 运行时间

compute_overview 全量（约 3 万行）实测 < 1 秒（pandas 全向量化）。

## 回归自检脚本

`Task/my_app/TMP/_probe_nur_site_filters.py`（2026-09-30 随站点四维过滤一起落地）：
核对「过滤后分子分母同步收窄」「各 region 分档求和 ≈ 全网（差额=未归属站）」以及
**概览数字 ↔ 下钻行数逐字一致**（SLA 用 `<period>__total` 对账、NUR 用 Σ(小区数×MTTR)
复原分子对账）。改动 `nur_calc` 的筛选口径后先跑它，再让人看页面：

```
cd Task/my_app; $env:PYTHONPATH="."; python TMP/_probe_nur_site_filters.py
```
