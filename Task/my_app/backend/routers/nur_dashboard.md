# NUR / SLA 看板 API 说明

路由前缀：`/api/nur`，计算引擎 `backend/services/nur_calc.py`。
数据源：主库 `eflow_tt` + `cm_site_summary`（DB_MODE=pg/sqlite 双模兼容）。

## 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/nur/options | 筛选项：vendors(ZTE/3RD)、projects(site_information 去重值)、排除名单加载状态 |
| GET | /api/nur/overview | 一次返回 6 张表（NUR/SLA × daily/weekly/monthly） |

`/overview` 参数：

| 参数 | 说明 |
|------|------|
| vendor | ZTE=ticket_no 非空；3RD=ticket_no 空；空=全部 |
| project | site_information 站点类型（REGULAR/ERA/...），空=全部 |
| exclude | Y=排除名单内；N=名单外；空=全部 |
| start / end | YYYY-MM-DD，作用于 alarm_occur_time（end 含当天） |
| refresh_exclude | true=强制刷新 FTP 排除名单缓存 |

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
