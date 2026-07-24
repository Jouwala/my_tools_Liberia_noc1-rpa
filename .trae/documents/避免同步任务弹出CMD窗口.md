# 计划：避免同步任务执行时弹出 CMD 窗口

## 问题描述
在 Windows 系统上，当定时同步任务（eFlow、RAN UME、MS SLA 等）通过 `subprocess.run()` 调用外部命令（如 PowerShell、Python 脚本）时，会弹出一个 CMD 控制台窗口，影响用户体验。

## 根本原因
Windows 下 `subprocess.run()` 默认不隐藏子进程窗口。所有涉及 `subprocess` 调用的地方都需要添加 `creationflags=subprocess.CREATE_NO_WINDOW` 参数来抑制 CMD 窗口弹出。

## 当前状态分析

项目中以下文件使用了 `subprocess.run()`，均需要修复：

| 文件 | 调用位置 | 用途 |
|------|---------|------|
| `backend/services/ftp_sync.py:127` | `run_init_db()` | 运行 init_db.py 初始化数据库 |
| `backend/services/ran_ume_main_kpi.py:1045` | 文件清理 | PowerShell 删除锁定文件 |
| `backend/services/ran_ume_network_kpi.py:1061` | 文件清理 | PowerShell 删除锁定文件 |
| `backend/services/ms_sla_service.py:838` | 文件清理 | PowerShell 删除锁定文件 |
| `backend/services/whatsapp_service.py:67,79` | PowerShell 命令 | WhatsApp 相关操作 |

## 修改方案

### 修改 1: `backend/services/ftp_sync.py`
**行 127**: 在 `subprocess.run()` 中添加 `creationflags=subprocess.CREATE_NO_WINDOW`

```python
# 修改前
result = subprocess.run(
    [sys.executable, str(init_script)],
    capture_output=True,
    text=True,
    timeout=120,
    cwd=str(init_script.parent.parent.parent),
    env=env,
    encoding='utf-8',
    errors='replace',
)

# 修改后
result = subprocess.run(
    [sys.executable, str(init_script)],
    capture_output=True,
    text=True,
    timeout=120,
    cwd=str(init_script.parent.parent.parent),
    env=env,
    encoding='utf-8',
    errors='replace',
    creationflags=subprocess.CREATE_NO_WINDOW,
)
```

### 修改 2: `backend/services/ran_ume_main_kpi.py`
**行 1045**: 添加 `creationflags=subprocess.CREATE_NO_WINDOW`

### 修改 3: `backend/services/ran_ume_network_kpi.py`
**行 1061**: 添加 `creationflags=subprocess.CREATE_NO_WINDOW`

### 修改 4: `backend/services/ms_sla_service.py`
**行 838**: 添加 `creationflags=subprocess.CREATE_NO_WINDOW`

### 修改 5: `backend/services/whatsapp_service.py`
**行 67, 79**: 添加 `creationflags=subprocess.CREATE_NO_WINDOW`

## 假设与决策
- **决策**: 使用 `subprocess.CREATE_NO_WINDOW` 标志隐藏所有子进程窗口
- **假设**: Python 3.12+ 支持此标志（项目使用 Python 3.12）
- **注意**: 此标志仅适用于 Windows 平台，不影响其他平台

## 验证步骤
1. 修改所有文件后，手动触发一次 eFlow 同步任务
2. 观察是否还有 CMD 窗口弹出
3. 检查任务执行日志确认功能正常
