# ip_trace_service

IP 链路探测业务逻辑层（改写自 `Unified_Tools/IP_Trace_Tool/ip_detect_tool.py`）。

## 能力
- `traceroute_host(target)`：自动识别 OS，`tracert`(Win) / `traceroute`(Linux/Mac)，解析每跳 IP/时延/抖动/位置。
- 持续探测：每跳并行 ICMP + TCP 双协议 ping（`ping_with_fallback`），后台线程 `continuous_ping_test` 循环统计时延/抖动/丢包（最近 100 样本）。
- 多会话内存态：`analysis_sessions[session_id]`，`get_or_create_session` 隔离，带 `lock`。
- GeoIP2 可选：`geo_reader` 加载 `data/ip_trace/GeoLite2-City.mmdb`；缺失时位置降级为 `Local Gateway`/`ISP Backbone`/`Hop N Node`。
- AI 分析：`analyze_with_ai`（provider 分发）+ `analyze_with_local_rules`（忠实改写原本地规则引擎，输出质量评级/瓶颈/差异/建议/健康评分）。

## 对外入口（供 router 调用）
| 函数 | 说明 |
|---|---|
| `start_trace(target, session_id?)` | 启动 traceroute + 探测线程，返回 hops + session_id |
| `stop_trace(session_id)` | 置 should_stop，线程退出 |
| `get_status(session_id)` | 快照 hops/ping_data/icmp_data/tcp_data（含最近 20 个时延点 + 坐标） |
| `build_analysis_payload(session_id)` | 聚合 icmp/tcp 统计，供 analyze 使用 |
| `analyze_with_ai(...)` | provider 选择；local/无 key 走本地规则 |

## 改造点（相对原 Flask 版）
- `print` → `logging`
- 落盘目录改为 `my_app/data/ip_trace/`（仅初始化，不做每次 ping 写盘）
- 移除硬编码 OpenAI key，改环境变量 / 默认本地规则
- 去掉 `/shutdown`，生命周期由 my_app 统一管理
- GeoIP mmdb 不在仓库内，缺失时自动降级
