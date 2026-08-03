# my_app 迁移到 192.168.100.19 可行性评估

> 评估对象：`D:\01_RPA\Task\my_app`（Task Manager，uvicorn :7038，20 个定时任务）
> 目标机：`192.168.100.19`（已运行 DB Writer 服务 :8765 + FineBI）
> 评估日期：2026-08-03

---

## 一、结论（先给答案）

**可行，但有一个硬前提必须先验证**：目标机 `192.168.100.19` 必须能访问 `10.100.x.x` 段的数据源（UME / eFlow / SFTP），且 UME 不能把当前机器 IP 写死在白名单里。

**API 写入不会变差、反而更好**：my_app 是 DB Writer 的**客户端**，把数据 POST 到 `192.168.100.19:8765`。搬到同机后，这次写入从"跨网"变成"本机 loopback"——延迟更低、不会因网络抖动失败、大批量上传（如 IPRAN 1.6M 行 full_replace）明显更快。**对写入路径零负面影响**。

真正的阻力不在 API 写入，而在**数据源网络连通性 + 路径硬编码**，下面展开。

---

## 二、当前数据流（谁连谁）

```
[my_app @ 本机 D:\01_RPA\Task\my_app]
   │
   ├─► 拉取(只读) ──► UME/eFlow 10.100.2.99:28001 / 10.100.28.27:28001
   │                 eFlow 10.100.20.8、SFTP 备件 10.100.20.11
   │
   ├─► 推送(写) ───► DB Writer API 192.168.100.19:8765  ──► 落本地 SQLite
   │                 (DB_WRITER_HOST 可 env 覆盖)            (FineBI 主库等)
   │
   ├─► FTP 读/传 ──► 192.168.100.19 (remote_ftp.py)
   ├─► EWS 邮件 ───► Orange Exchange (internet)
   └─► 微信(已 blocked) ─► 本机 OpenClaw 127.0.0.1:18789
```

**关键认知**：my_app 本身**不依赖** `192.168.100.19` 上的 FineBI/Writer 来"读"数据；它只是把处理后的结果"推"过去。所以把 my_app 和 Writer 放同一台机器，推送这一跳只会更稳。

---

## 三、外部依赖清单（迁移必查）

| 依赖 | 主机/端口 | 用途 | 是否硬编码 | 迁移影响 |
|---|---|---|---|---|
| DB Writer | `192.168.100.19:8765` | my_app 推数据 | `DB_WRITER_HOST` env 可覆盖 | 同机→loopback，**更好** |
| IPRAN UME | `10.100.2.99:28001` | IPRAN KPI 拉取 | 硬编码 | **致命：需 192.168.100.19 能达** |
| RAN/UME/auth/MS_SLA | `10.100.28.27:28001` | RAN/可用性 KPI | 部分 env 可覆盖 | **致命：需可达** |
| eFlow | `10.100.20.8:28001` | 告警/工单 | `EFLOW_HOST` env 可覆盖 | **需可达** |
| SFTP 备件 | `10.100.20.11` | 备件报表 | 硬编码 | **需可达** |
| FTP | `192.168.100.19:21` | 报表读/传 | 硬编码(同机) | 同机→localhost，更好 |
| EWS 邮件 | Orange Exchange | 日报邮件 | — | 需远程机能出 internet + 邮箱 EWS 开 |
| OpenClaw 微信 | `127.0.0.1:18789` | 微信推送 | 本机 | 远程若无机则失效（已 blocked，影响小） |

> ⚠️ 数据源源全在 `10.100.x.x`，与 `192.168.100.x` 是**不同子网**。若 `192.168.100.19` 因 VLAN/路由/防火墙无法路由到 `10.100.x.x`，**所有同步类任务（IPRAN、RAN、MS_SLA、eFlow、备件）将全部失败**——这是唯一能"一票否决"的点。

---

## 四、API 写入影响（明确回答）

**方向 A：my_app → DB Writer（它写的）**
- 现状：跨网 POST `http://192.168.100.19:8765/api/write`。
- 迁移后：同机，建议设 `DB_WRITER_HOST=127.0.0.1`（不设在同机也照常，因为 192.168.100.19 就是自己）。
- 结论：**更快、更稳、无丢失风险**。
- 已知遗留问题（与迁移无关）：`lbr_ms_sla_kpi.sqlite3` 在 Writer 侧**未注册**，仍会返 HTTP 400 `Unknown database`。这是 Writer 映射缺失，搬机不修复，需另在 `db_writer_api.py` 的 `_get_db_path` 补映射。

**方向 B：外部 → my_app（别人写它的）**
- 若本机有脚本/浏览器/其他 RPA 调 `localhost:7038` 或当前机 IP`:7038`（如 `/api/upload`、`/api/eflow/sync`、`/api/tasks/{id}/run`），搬走后这些调用方必须改指 `192.168.100.19:7038`，且需：①网络可达；②`MY_APP_CORS_ORIGINS` 含调用方来源；③带 `X-API-Token`（非回环强制）。

---

## 五、迁移前必须验证 / 准备（Checklist）

### 🔴 阻断项（先做）
1. **从 `192.168.100.19` 本机测 10.100.x.x 连通性**（不是从当前机测！）：
   ```powershell
   Test-NetConnection 10.100.2.99  -Port 28001
   Test-NetConnection 10.100.28.27 -Port 28001
   Test-NetConnection 10.100.20.8  -Port 28001
   Test-NetConnection 10.100.20.11 -Port 22
   ```
2. **UME/eFlow 登录实测**：用 `noc1` 账号从 `192.168.100.19` 跑一次登录。若 UME 按源 IP 白名单放行，换 IP 会 401——这种只能让 UME 侧加白 `192.168.100.19`。

### 🟡 路径 / 配置项
3. **安装路径一致性**：大量代码硬编码 `d:\01_RPA\Task\my_app\...`（ran_ume_service / ms_sla / packet_loss_dashboard 的 data 目录；`owa_mail_report.py` 的 `D:/01_RPA/LBR_Tools/...`）。若远程不落在 **完全相同** 的 `D:\01_RPA\Task\my_app`，需批量改路径，或尽量用已支持的 env 覆盖（`EFLOW_HOST`/`RAN_UME_HOST`/`DB_WRITER_HOST`）。
4. **Python 环境**：远程需 Python 3.12 + `requirements.lock.txt`（56 个精确依赖，含 fastapi/uvicorn/exchangelib/pandas/requests）。建议整 venv 随项目迁移，别用系统 Python。
5. **端口**：确认 `:7038` 在远程空闲（远程已用 `:8765` 给 Writer，不冲突；若同机还跑 FineBI/其他服务，核对 7038 未被占）。
6. **自动启动**：当前是手动 `uvicorn` 长跑。远程搬过去后必须配自启（nssm / Windows 任务计划 / 服务），否则重启即停。

### 🟢 小项
7. `MY_APP_API_TOKEN`、`MY_APP_CORS_ORIGINS`、`UME_TLS_VERIFY`、`EFLOW_HIS_ALARM_DAYS` 等 env 需在远程一并迁移。
8. 微信推送若将来要恢复，远程需也跑 OpenClaw 网关（当前已因缺 media 权限 blocked，暂不影响）。
9. 前端 UI：dev server 在 `:7090`，生产 dist 由 `:7038` 托管。若用户从本机浏览器访问，需 `192.168.100.19:7038` 网络可达 + CORS 放行。

---

## 六、建议落地步骤（若决定搬）

1. 在 `192.168.100.19` 跑上面的连通性 + UME 登录测试 → 不过则先解决网络/白名单。
2. 整目录复制 `D:\01_RPA\Task\my_app` 到远程**同路径** `D:\01_RPA\Task\my_app`（避免路径硬编码返工）。
3. 远程建 venv 装 `requirements.lock.txt`。
4. 设 env：`DB_WRITER_HOST=127.0.0.1`（可选）、`MY_APP_API_TOKEN` 等。
5. 远程起 uvicorn :7038，验证 20 任务注册、手动跑 1 个 IPRAN + 1 个 RAN 看是否真写入 `192.168.100.19:8765`（此时即 localhost）。
6. 配自启，观察 1~2 个完整调度周期（含 03:35 eflow_history_alarm、整点 ipran）再切流量。
7. 旧机保留 my_app 一段时间作回滚备份，确认稳定后停掉。

---

## 七、一句话总结

> **能搬，且把"推数据到 192.168.100.19"这一跳变成本机调用是纯收益；唯一会让你白搬的风险是 192.168.100.19 摸不到 10.100.x.x 的数据源——这一步务必先在远程本机验证，别在本机测完就以为通了。**
