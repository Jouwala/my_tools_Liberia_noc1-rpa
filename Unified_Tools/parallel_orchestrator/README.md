# parallel_orchestrator — 多 Agent 并行编排器

> 目标：让本机的多个 Agent（codex / qoderclicn）**真正同时干活**，加快大任务执行速度。
> 设计原则：**派发/轮询模型** —— 长任务跑在后台进程里，编排器只做秒级的派发、查状态、收结果，
> 从结构上规避同步 RPC（MCP tools/call）的客户端请求超时（本机实测 `-32001 Request timed out`：
> 小探测能过、分钟级长任务必死）。

## 为什么不用 MCP 同步调用
| 方式 | 小任务 | 长任务（多文件改写） |
|---|---|---|
| MCP `tools/call` 同步 | ✅ 秒级返回 | ❌ 撞客户端超时 -32001，工作被丢弃或变孤儿 |
| 本编排器（后台进程） | ✅ | ✅ 无超时上限，随时 status 查进度 |

## 文件说明
| 文件 | 作用 |
|---|---|
| `parallel_orchestrator.py` | 编排器主体（纯标准库） |
| `tasks_phase3_remaining.json` | 示例任务清单：my_app Phase 3 收尾（真实可派发） |
| `verify_spec_phase3.json` | 示例验证规格：py_compile + 方言残留扫描 |
| `runs/<run_id>/` | 每次运行的状态、各任务 prompt、输出日志、退出码、汇总 |

## 快速开始
```powershell
cd d:\01_RPA\Unified_Tools\parallel_orchestrator
$PY = "C:\Users\ZTEEMS\AppData\Local\Programs\Python\Python312\python.exe"

# 1) 并行派发（秒级返回，任务在后台跑）
& $PY parallel_orchestrator.py dispatch --tasks tasks_phase3_remaining.json

# 2) 随时查进度（可反复执行）
& $PY parallel_orchestrator.py status

# 3) 轮询等完（可选；--timeout 为等待上限，超时不影响后台任务继续跑）
& $PY parallel_orchestrator.py wait --interval 20 --timeout 7200

# 4) 验证门：全部 py_compile + 残留扫描，PASS 才算完成
& $PY parallel_orchestrator.py verify --spec verify_spec_phase3.json

# 查看历史运行
& $PY parallel_orchestrator.py runs
```

## 任务清单格式（tasks JSON）
```json
{
  "defaults": { "cwd": "D:\\01_RPA\\Task\\my_app" },
  "executors": { },
  "tasks": [
    {
      "id": "fix-ran-ume-main-kpi",
      "executor": "codex",
      "cwd": "D:\\01_RPA\\Task\\my_app",
      "prompt": "给该 agent 的完整任务指令（长度不限，会写入文件/stdin 传递）"
    }
  ]
}
```
- `executor` 只支持 `codex` / `qoder`；`executors` 段可覆盖默认可执行文件路径。
- `prompt` 不限长：codex 走 stdin 注入；qoder 走"指令文件引读"（agent 先读文件再执行），
  规避 Windows 8K 命令行限制。

## 状态语义
| 状态 | 含义 |
|---|---|
| `RUNNING` | PID 存活，任务在跑 |
| `DONE rc=0` | 正常结束 |
| `DONE rc=N` | 进程退出但退出码非 0，看 `<task>.out.log` |
| `GONE(无rc且进程不在)` | 进程消失且没写退出码（多为系统重启/被强杀），需重派 |

## 安全须知
1. 两个执行器均以**免审批**模式运行（codex `--approve-for-me`、qoder `--dangerously-skip-permissions`），
   仅限可信本机工作区使用。（codex 新版已废弃 `--full-auto`，且与 `--sandbox` 互斥）
2. 每个任务的 prompt 必须写明**只允许修改列出的文件**；并行任务之间文件分区**不得重叠**，
   否则会互相覆盖。
3. qoderclicn 后端模型高峰期会进慢队列（FORBIDDEN code 10605 / isQueued），表现为长时间无输出；
   属服务端配额问题，重试或错峰即可。codex 不受此影响。
4. 验证门（verify）通过之前，不要把改写结果当成最终交付。

## 设计备忘
- 派发用 `powershell -EncodedCommand` + `CREATE_NO_WINDOW`：不弹 CMD 窗口、无引号转义问题。
- 每个任务的退出码由包装脚本写入 `<task>.rc`，轮询方无需持有进程句柄，编排器重启后仍可续查。
- status 的进程存活判定一次 `tasklist` 全量拉取后集合匹配（向量化，O(1) 查询）。
