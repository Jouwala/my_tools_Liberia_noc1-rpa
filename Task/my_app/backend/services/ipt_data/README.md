# IPT Digital Platform（RMS 能源监控）站点电源信息

> 状态：✅ 已打通并实测（2026-11-03）。客户端：`ipt_energy_client.py`（纯 requests，无浏览器依赖）。
> 来源：同目录 `url.txt`（Chrome DevTools 抓包转储）逆向 + 实测验证。**本文件不记录任何口令**。

## 一、认证（OIDC 隐式流）

门户 `https://portal.iptdigitalplatform.com` 是 Angular SPA，OIDC 配置（前端 `env.js` + main bundle 确认）：

| 项 | 值 |
| --- | --- |
| authority | `https://login.iptdigitalplatform.com`（OpenIddict） |
| client_id | `rubix-web` |
| response_type | `id_token token`（**隐式流**，无 code / 无 PKCE） |
| redirect_uri | `https://portal.iptdigitalplatform.com/cb` |
| scope | `openid rubix-api email profile` |

纯 requests 登录流程（`IptEnergyClient._login`）：

1. `GET /connect/authorize?client_id=rubix-web&redirect_uri=...&response_type=id_token token&scope=...&nonce=...&state=...`
   → 未登录 302 到 `/account/login?returnUrl=...`
2. 登录页表单字段：`ReturnUrl`、`Username`、`Password`、`__RequestVerificationToken`（页内 hidden input）
3. `POST /account/login`（同 Session cookie）→ 302 `/connect/authorize/callback?...` → 302 `portal/cb#access_token=...&id_token=...`
4. 从回调 **fragment** 取 `access_token`（RS256 JWT，**TTL 1 小时**）

- `password` grant 实测被拒（`unauthorized_client`），`rubix-admin` 等其它 client 均 `invalid_client`，只有 `rubix-web` 有效但仅限授权流 → 走上面的表单模拟。
- token 缓存在 `auth_cache/ipt_token.json`（已被 `.gitignore` 的 `**/auth_cache/` 覆盖，不入库）；过期前 120s 或遇 401 自动重登。

## 二、业务接口（Bearer access_token，请求头带 portal 的 Origin/Referer）

Base：`https://backend.iptdigitalplatform.com/api/v0.1/assets/clients/<client_ref>/energy`

| 接口 | 用途 |
| --- | --- |
| `GET /sites?query=<站名>` | 站点模糊搜索，返回概要（id/name/参考号/cluster/坐标/优先级/连接状态） |
| `GET /sites?query=&page=N&pageSize=100` | 分页列全站完整属性（服务端 pageSize 上限 100），用于回填站点表 |
| `GET /sites/<site_id>/diagram` | **电源全景（明细层，~5KB）**：loads / batterySets / generators / grids / gridBackups / rectifiers / fuelTanks / fuelTankClusters / solarSets / environment |
| `GET /sites/<site_id>/popup` | **站点弹窗摘要（KPI 层，~1.5KB）**：site 属性 + site.events 活动告警 + 精简 diagram（loadPower / batteryVoltage / SOC / solarPower / fuelTankLevel / generatorOn）。501 站并发 32 线程实测 60.1s、0 错误 |
| `POST /events/recent`（body `{"duration": 60}`） | 全站近 N 分钟「新发生」事件（1 个请求）。⚠ 只含最近发生，**不含**长期未清除的活动告警；活动告警以 `/popup` 的 site.events 为准 |
| `GET /sites/<site_id>/with-events` | 站点+设备详情（网关、SIM、SNMP 等；含设备凭据字段，注意脱敏） |
| `GET /sites/<site_id>/devices/<device_id>/attributes/values` | 单设备属性（实测该站点返回 `[]`，数据主要在 diagram） |
| `POST /sites/filter-map` | 全站过滤地图（body 为空过滤器组合；**不含任何电源数值**） |

`client_ref` 默认 `9eda5e46b0294eb589881ee74f8940da`（Orange Liberia 租户，抓包确认）。

## 三、用法

```bash
# 系统 Python 3.12（C:\Users\ZTEEMS\AppData\Local\Programs\Python\Python312\python.exe）
cd backend/services/ipt_data
python ipt_energy_client.py "Jahtondo Town"        # 中文摘要
python ipt_energy_client.py "Jahtondo" --list      # 只列站点（id | 名称 | 参考号 | 区域）
python ipt_energy_client.py "Jahtondo Town" --json # 归一化 JSON
```

代码调用：`IptEnergyClient().get_site_power(站名)` → `(site, 归一化电源 dict)`。

凭据来源（优先级）：环境变量 `IPT_USERNAME` / `IPT_PASSWORD` > 同目录 `url.txt` 头部「用户名：…/密码：…」两行。

## 四、注意事项

- ✅ `url.txt` 含明文凭据，已被 `.gitignore` 的 `/backend/services/ipt_data/url*.txt` 覆盖（2026-11-03 确认），不会被误入库。
- `with-events` 响应含网关设备密码/SNMP community 等敏感字段，任何落库/日志输出前须脱敏。
- 外网 API 需直连（客户端已设 `trust_env=False`，规避本机 http_proxy 干扰）。
- 会话同源：`rubix-web` 单账号多端登录不互踢（隐式流无服务端会话绑定限制，实测多次登录均有效）。

## 五、采集架构：全站 5 分钟分辨率（2026-11-04 重设计 / 2026-11-06 降频）

`filter-map` 只返回 `id / name / 坐标 / connectivity / criticality`，**不含任何电源数值**；
上游也**没有批量电源接口**（逐一核对过抓包里的全部端点，含 `events/recent`——它只有
最近新发生的事件，不是活动告警快照）。因此电源数值只能逐站请求，全站 5 分钟分辨率
靠**并发逐站拉取**实现（2026-11-04 实测）：

| 层 | 接口 | 实测吞吐（32 线程） | 节奏 |
| --- | --- | --- | --- |
| KPI 层 | `/popup`（~1.5KB） | 501 站 60.1s、0 错误 | **每轮全采** → 全站每 5 分钟一条快照 |
| 明细层 | `/diagram`（~5KB） | 200 站 73.8s、外推 501 站 ~185s 且有超时 | 分片轮采 ≤60 站/轮（3 线程）→ 约 20 分钟覆盖全站 |

两池**并发同时跑**，整轮受 **240s** 硬上限（`KPI_ROUND_HARD_DEADLINE_S`，
任务入口起算）约束，到时放弃未完成站点，保证 5 分钟节拍不漂移（`*/5`
周期 300s，留 60s 给落库与下一轮）；未采到的站下轮补上（popup 在硬上限内
**补采一轮**，diagram 游标接着走）。`_drain` 跑完即止，放宽上限**不会让
正常轮变慢，也不增加一个请求的瞬时压力**；它只让上游偶发变慢的轮次
不再把尾部站提前放弃。

**并发调优（2026-11-04 ~ 11-05 实测）**：最初 32 + 16 线程在上游健康时能跑满
501 站/60s，但持续 2 分钟节拍下会把上游拖出批量读超时（21:58 轮 113/501）；
降到 12 + 8 后当晚恢复到 359~405/501，**11-05 上午又退化到 0~40/501**。
空闲期顺序探测 0.9~4.3s、采集期批量 12s 超时，确认是**自身并发把上游压垮**：
高并发下每个慢请求被客户端提前放弃，服务端却仍在计算，连接越堆越慢形成
超时风暴。现行配置为 **popup 8 线程 + diagram 3 线程（合计 11 并发）+
每线程 0.3s 间隔**，以单轮覆盖率换上游稳定；漏采站由 `kpi_cursor` 环形游标
下轮续采，配合 `shard_cursor` 明细游标，全站最终都能轮到。

**弹性与脱敏（2026-11-04 晚高峰 / 11-05 上午两次复盘后加固）**：

- **池内超时 20s**（`POOL_REQ_TIMEOUT_S`）：11-05 顺序探测出现过 17s 仍成功，
  12s 会把「慢但会成功」的请求误杀，且提前放弃的请求仍占用服务端 → 放宽到
  20s，减少超时风暴；真正卡死的站仍由硬上限 + 补采兜底。
- **popup 环形游标**（`ipt_power_meta.kpi_cursor`）：每轮从上次断点轮转任务顺序，
  避免硬上限截断时 `sorted(site_id)` 列表尾部的站永远拿不到新快照（11-05 实测
  1 小时内 62 站无快照）。
- **低成功率熔断**（`DEGRADED_RATIO=0.25`）：一轮 popup 成功率低于 25% 即视为
  上游被压垮/故障，计入退避（`last_run.degraded=true`），不再每 5 分钟打满
  240s 却拿不到数据。
- **熔断退避**：上游故障（filter-map 连续 500 / 读超时，或上述低成功率）时，
  按连续失败次数指数退避（5/10/20... 分钟，封顶 30 分钟，`BACKOFF_*` 常量，
  状态存 `ipt_power_meta.failure_backoff`），退避期内整轮**静默跳过**
  （success=true，不触发失败通知轰炸）；任一轮成功即清零。
- 页面数据新鲜度由 `/api/ipt-power/status` 的 `last_run.time` 判断，
  超过 10 分钟即说明上游异常或退避中。

**2026-11-06 降频、单点加固与放宽硬上限（A+B+C+D）**：复盘见
`outputs/ipt_power_collect_失败复盘_2026-11-06.md`。原 `*/2` 节拍下单轮
100s 硬上限几乎占满周期、上游只有约 20s 喘息，近 3 天 81.4% 轮次撞硬
上限截断、popup 覆盖率中位数仅 84.1%，19 次任务失败里 17 次都是
`filter-map` 单点读超时后整轮判失败。四项改动：

- **A 降频**：`default_cron` 与运行时 `task_schedule_config` 同改 `*/5`，
  请求压力 -60%，上游喘息窗口 20s→200s。
- **D 补完 A（22:20）**：改后发现 A 只做了一半 —— 周期放到 300s，
  但 2 分钟时代定的 100s 硬上限没跟着调，空出的 200s 全被浪费。
  改后 10 轮仍有 7 轮撞截断（21:27=333/501、21:46=327/501），
  尽管 21:56 起已连续 3 轮 501/501。`KPI_ROUND_HARD_DEADLINE_S`
  `100→240`，留 60s 给下一轮；`full_kpi.budget_s` 同步 80→200
  （**注意：该字段目前在 collector 中未被读取**，只是配置与文档口径一致，
  实际约束一律由 `hard_deadline` 给出）。不改并发、不改单请求超时。
  安全性：`max_instances=1` 保证轮次不重叠，`STALE_RUNNING_SECONDS=1800s`
  不会把 240s 长轮误判成僵尸。
- **B 告警语义**：瞬时上游抖动不再判任务失败；只有连续 3 轮「连上轮站点
  清单都拿不到、整轮完全无法采集」才告警。数据陈旧仍由
  `db_freshness_check` 的「IPT 站点电源快照」20 分钟巡检兜底。
- **C 单点加固**：`IptEnergyClient.filter_map` 对超时 / 408 / 5xx 做 1 次
  短重试（第 2 次 12s 超时，401 重登不占次数）；仍失败时 collector 用
  上一轮 `ipt_power_sites` 清单降级继续采，本轮跳过站点表刷新与属性回填，
  `last_run.stale_sites` 留痕。**一个请求不再毁掉整轮快照。**

`watch_sites.json`（对象形态）：

```json
{
  "sites": ["Jahtondo Town", "Brewerville 4", "Zwedru 4"],
  "full_kpi":   { "enabled": true, "workers": 8, "budget_s": 200 },
  "full_shard": { "enabled": true, "max_sites": 60, "budget_s": 70 }
}
```

- `sites`：关注站，**每轮必采 diagram 完整明细**（5 分钟明细分辨率）。
- `full_kpi`：全站 popup KPI 层；关闭则退回「只有分片轮采」的旧行为。
- `full_shard`：diagram 明细分片轮采。站点按 `site_id` 排序，
  用 `ipt_power_meta.shard_cursor` 做环形游标，每轮从游标处计划最多 60 站，
  下一轮接着采。明细字段（油机相电压/电池容量/油箱容量/主源状态）以每站
  **最新一条 diagram** 为准（`ipt_power_site_detail`），页面「立即刷新」可实时补齐。
- 站点属性由 `GET /sites?query=&page=N&pageSize=100` 分页（约 6 个请求）**一次性回填**
  `ipt_power_sites`，之后只在出现缺值且距上次回填 >1h 时重跑。
- ⚠ **不要在 `sites` 里配 `"*"`**：旧语义是单轮全采 500 站 diagram（>10 分钟），会超时并冲击外网平台。
  修改 `ipt_power_collector.py` 后需重启 m 组 worker：
  `python restart_workers.py --groups m --reason "重载 ipt_power_collector"`；
  只改 `watch_sites.json` 不用重启（每轮重读）。

存储与脱敏：

- `ipt_power_snapshots`：全站每轮一条（513 站 × 288 轮/天，5 分钟节拍）。popup 行 `raw=NULL`
  控表体积，diagram 行补全明细列；**保留 7 天**自动清理（`RETENTION_DAYS`，2026-11-08 由 2 天放宽，
  让页面 72h / 7d 两档时间窗真的有数据；此前 2 天保留期下这两档永远只能画出 2 天曲线）。
  新增列：`source / alarm_count / alarm_names / solar_available / fuel_capacity / main_source_on`。
- `ipt_power_site_detail`：每站最新一条 diagram 精简明细（`slim_diagram()` 已剥除
  设备凭据）。⚠ 2026-11-04 前 raw 存全量 diagram 且被 `/api/ipt-power/site/{id}`
  原样下发，其中 `fuelTanks[].device` 带控制器明文口令，属凭据泄漏，已修复
  （raw 改存 slim、API 不再下发 raw）。
- 太阳能取值口径：`solarSets[].solarPower` 与 `rectifiers[].solarPower` 上游是同一份
  镜像值（对 3945 条历史快照逐条核对），取 max 避免重复累加，多组太阳能先求和；
  `solar_available=0` 表示站点无太阳能设备（页面显示 `-`），有设备时夜间
  （利比里亚 GMT，约 18:30~06:30）为 0 W 属正常。
