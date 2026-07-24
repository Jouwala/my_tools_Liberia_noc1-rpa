# auth_manager.py - 多任务共享鉴权管理模块

## 概述

多个 RPA 任务使用相同 URL 获取数据时，通过本地 JSON 文件缓存鉴权信息，避免同一账户重复登录导致互踢。

## 工作原理

```
任务启动 → 读取本地 token 缓存文件 → 判断是否存在且未过期
  ├── 有效 → 直接使用（不登录）
  └── 无效/不存在 → 用户名密码登录 → 写入 token 缓存文件
```

## 缓存文件

- 存放目录：`d:\01_RPA\Task\auth_cache\`
- 文件命名：`{host}_{port}.json`（如 `10.100.28.27_28001.json`）
- 默认有效期：1800 秒（30分钟），可通过环境变量 `AUTH_TOKEN_TTL` 调整

## 使用方法

### 基本调用

```python
import sys
sys.path.insert(0, r"d:\01_RPA\Task")
from auth_manager import get_auth

auth = get_auth(
    host="10.100.28.27",
    port=28001,
    username="NOC",
    password="Zte@2025!"
)

cookie = auth["cookie"]
forgery_token = auth["forgery_token"]
from_cache = auth["from_cache"]  # True=使用缓存, False=重新登录
```

### 强制刷新

```python
auth = get_auth(host, port, user, pwd, force_refresh=True)
```

### 手动清除缓存（API返回401时）

```python
from auth_manager import invalidate_cache
invalidate_cache("10.100.28.27", 28001)
```

### 独立运行测试

```bash
python auth_manager.py --host 10.100.28.27 --port 28001 --user NOC --pass "Zte@2025!"
python auth_manager.py --force  # 强制重新登录
```

## 支持的网管系统

| 系统 | Host | Port | 用户 |
|------|------|------|------|
| RAN UME | 10.100.28.27 | 28001 | NOC |
| eFlow | 10.100.20.8 | 28001 | admin |

## 依赖

```
pip install -r requirements_auth.txt
```

## 注意事项

1. 缓存带文件锁，多进程并发安全
2. Token 过期后自动重新登录
3. 如果 API 调用返回鉴权失败，应先调用 `invalidate_cache()` 再重试
4. 同一 host:port 的所有任务共享同一份缓存
