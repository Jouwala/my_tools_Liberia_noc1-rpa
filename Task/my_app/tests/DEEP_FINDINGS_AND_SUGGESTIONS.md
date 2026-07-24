# 深度测试发现与建议

> 测试时间: 2026-07-24 17:05 (UTC+8)
> 测试范围: 后端深度(30例) + 前端深度E2E(4例) = **34 例, 32 通过 / 2 失败**
> 失败的 2 例均为真实 Bug（非测试问题），详见下方 [F-1] [F-2]

---

## 一、发现汇总（按严重程度排序）

| 编号 | 类别 | 严重度 | 标题 | 影响端 | 状态 |
|------|------|--------|------|--------|------|
| F-1 | 🔴 Bug | **高** | stats 列名未校验 → 未处理异常 500 | 后端 | ❌ 待修复 |
| F-2 | 🟡 质量 | **中** | sort_by 列名未校验 → 排序静默失效 | 后端 | ❌ 待修复 |
| F-3 | 🟠 安全 | **中** | 上传文件名未净化（write-before-validate） | 后端 | ⚠️ 需加固 |
| F-4 | 🟠 安全 | **低** | CORS 通配符 + 凭据 无效配置 | 后端 | ⚠️ 建议修复 |
| F-5 | 🟡 API设计 | **低** | 任务 run 不存在时返回 200 而非 404 | 后端 | 建议改进 |
| F-6 | 🔵 依赖 | **中** | apscheduler 版本未锁定 → 新环境崩溃 | 构建 | ❌ 应修复 |
| F-7 | 🟣 UX | **中** | 移动端布局不适配（固定侧边栏） | 前端 | 建议优化 |
| F-8 | 🟢 韧性 | ✅ 正常 | API 故障降级不崩溃 | 前端 | 已验证通过 |

---

## 二、详细发现与建议

### F-1 [🔴 高] `/api/tables/{table}/stats/{column}` 列名未校验 → 500

**测试用例**: BE-BND-07

**现象**: 传入不存在的列名（如 `no_such_col_xyz`）时，后端执行 `df[column]` 触发 `KeyError`，返回 HTTP 500（未处理异常）。前端收到 500 后可能显示白屏或错误提示。

**根因**: `tables.py` 第 131 行直接使用用户输入的 `column` 参数拼 SQL 并取 DataFrame 列，无存在性校验：

```python
# tables.py:131 — 当前代码
df = pd.read_sql_query(f'SELECT "{column}" FROM "{table_name}" LIMIT 50000', conn)
series = df[column]  # ← KeyError if column doesn't exist
```

**建议修复**:
```python
# ���案 A：在 SQL 层用 PRAGMA 校验列是否存在
col_info = conn.execute(f'PRAGMA table_info("{table_name}")').fetchall()
valid_cols = {c[1] for c in col_info}
if column not in valid_cols:
    raise HTTPException(status_code=404, detail=f"列 {column} 在表 {table_name} 中不存在")

# 方案 B：try/except 包裹 + 返回 404
try:
    series = df[column]
except KeyError:
    raise HTTPException(status_code=404, detail=f"列 {column} 不存在")
```

**优先级**: 高 — 直接影响用户体验（白屏/报错），且是信息泄露风险（堆栈信息暴露内部结构）。

---

### F-2 [🟡 中] `/api/tables/{table}/data` sort_by 列名未校验

**测试用例**: BE-BND-06

**现象**: 传入无效 `sort_by` 值（如 `no_such_col_xyz`）时，接口返回 **200** 但排序实际未生效。SQLite 将双引号包裹的未知标识符视为字符串常量（兼容性容错），导致 `ORDER BY "no_such_col_xyz"` 等同于排序一个常量值——所有行顺序不变。

**影响**: 用户拼写错误或前端传错字段名时，数据看似正常但排序失效，**静默错误**难以排查。

**根因**: `tables.py` 第 68-69 行：
```python
if sort_by:
    order_clause = f' ORDER BY "{sort_by}" {"ASC" if sort_order == "asc" else "DESC"}'
```
`sort_by` 直接拼入 SQL，未对照表的实际列名做白名单校验。

**建议修复**:
```python
if sort_by:
    valid_cols = {c[1] for c in conn.execute(f'PRAGMA table_info("{table_name}")').fetchall()}
    if sort_by not in valid_cols:
        raise HTTPException(status_code=400, detail=f"排序字段 {sort_by} 不存在")
    order_clause = f' ORDER BY "{sort_by}" ...'
```

**注意**: 注入安全性方面已确认 **不可利用**（双引号阻断标识符逃逸、sqlite3 单语句限制），但缺少输入验证仍是质量缺陷。

---

### F-3 [🟠 安全 中] 上传文件名未净化（路径遍历风险）

**测试用例**: BE-SEC-04

**现象**: 文件上传接口 (`POST /api/upload`) 的处理流程为：
1. **先写入磁盘** (`open(file_path, "wb")`)
2. **再解析内容** (`pd.ExcelFile(...)`)

文件名仅加 uuid 前缀（`{uuid8}_{original_filename}`），未使用 `os.path.basename()` 或 `werkzeug.secure_filename()` 做净化。当前靠 uuid 前缀偶然缓解了路径遍历（前缀使首段路径组件成为不存在的字面目录，导致 `open()` 因中间目录不存在而失败），但这不是可靠的安全措施。

**风险场景**:
- 恶意文件名含大量 `../` 可尝试逃逸 uploads 目录
- 文件在内容校验**之前**写入磁盘 → 可被用于磁盘填充攻击（DoS）
- 无文件大小限制 → 单次上传可写任意大小

**建议修复**:
```python
from werkzeug.utils import secure_filename  # 或手写 basename 清洗
import os

@router.post("")
async def upload_excel(file: UploadFile = File(...)):
    # 1. 净化文件名
    safe_basename = secure_filename(file.filename) or "upload"
    if not safe_basename.endswith(('.xlsx', '.xls', '.csv')):
        raise HTTPException(status_code=400, ...)
    
    # 2. 大小限制（在读取内容前检查 Content-Length 或流式读取时截断）
    
    # 3. 写入临时目录，校验后再移到正式目录
    tmp_path = UPLOAD_DIR / f"{uuid.uuid4().hex[:8]}_{safe_basename}"
    with open(tmp_path, "wb") as f:
        content = await file.read()
        if len(content) > MAX_UPLOAD_SIZE:  # e.g., 50MB
            os.remove(tmp_path)
            raise HTTPException(status_code=413, ...)
        f.write(content)
    
    # 4. 解析校验（此时才读取 Excel 内容）
    try:
        ...
    except Exception:
        os.remove(tmp_path)  # 校验失败则删除
        raise
```

**优先级**: 中 — 当前环境为内网工具风险可控，但公网部署前必须修复。

---

### F-4 [🟠 安全 低] CORS 配置无效

**测试用例**: BE-SEC-01

**现象**: `main.py` 第 30-36 行：
```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    ...
)
```

浏览器规范明确拒绝 `Access-Control-Allow-Origin: *` 与 `Allow-Credentials: true` 同时存在的组合。当凭据模式启用时，浏览器会忽略通配符 origin，可能导致跨域请求失败。

**建议**:
- 内网工具可保持 `allow_origins=["*"]` + `allow_credentials=False`（如果不需要 cookie/auth）
- 如需凭据，改为 `allow_origins=["http://localhost:7090", "http://localhost:7038"]`（限定前后端地址）

---

### F-5 [🟡 API 设计 低] 任务执行不存在任务返回 200

**测试用例**: BE-ERR-11

**现象**: `POST /api/tasks/{task_id}/run` 对不存在的 task_id 返回 HTTP 200 + body `{"success": false, "error": "..."}`。RESTful 惯例应返回 **404 Not Found**。

同样的问题也出现在 `toggle_task` 和 `update_task_schedule` —— 对不存在的任务返回 200+success:false。

**建议**: 在路由层先检查 task 存在性，不存在则抛出 404：
```python
@app.post("/api/tasks/{task_id}/run")
def run_task_now(task_id: str):
    task = _task_registry.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"任务 {task_id} 未找到")
    return task_runner.run_task(task_id, trigger="manual")
```

---

### F-6 [🔵 依赖 中] apscheduler 版本未锁定

**来源**: 冒烟测试阶段发现

**现象**: `requirements.txt` 声明 `apscheduler>=3.10.0`，全新环境 `pip install` 会拉取 **apscheduler 4.x**。4.x 移除了 `Job.next_run_time` 属性，导致应用启动时 `task_runner.list_tasks()` 崩溃。

**建议**: 固定版本号：
```
apscheduler==3.10.4
```

所有第三方依赖建议锁定精确版本（使用 `pip freeze > requirements-lock.txt`）。

---

### F-7 [🟣 UX 中] 移动端布局不适配

**测试用例**: FE-D-03

**现象**: 375px（iPhone SE）视口下：
- 左侧导航栏保持固定宽度 (~200px)，占去屏幕 56%
- 右侧内容区被压缩至 ~175px，几乎不可用
- 技术上无横向滚动条溢出（scrollWidth == clientWidth），但功能不可用

**截图证据**: `tests/reports/deep_shots_*/FE-D-03.png`

**建议方案**（按复杂度递增）:
1. **快速修复**: 小屏下隐藏侧边栏，显示汉堡菜单按钮（Ant Design Layout Sider 已支持 `breakpoint="lg"`）
2. **中等方案**: 移动端独立页面布局（顶部 Tab 导航 + 全宽内容）
3. **完整方案**: 使用 Ant Design Mobile 组件库重写移动端视图

---

### F-8 [🟢 韧性 ✅] API 故障降级正常

**测试用例**: FE-D-02

**现象**: 强制 `/api/gis/sites` 返回 500 后：
- 页面**不崩溃**（0 个未捕获 JS 异常）
- 页面仍可渲染（可能展示缓存/旧数据）

**结论**: 前端对 API 失败有基本的容错能力。建议进一步增强：
- 显示明确的错误提示横幅（而非静默展示旧数据）
- 关键操作（如上传）增加重试按钮
- 网络请求统一拦截器中记录失败日志

---

## 三、性能基线（本次测试环境）

| 端点 | p50 延迟 | p95 延迟 | 备注 |
|------|----------|----------|------|
| `/api/gis/sites` (站点聚合+TT/WO统计) | ~45ms | ~58ms | 10次调用 |
| `/api/gis/region-boundaries` (Voronoi计算) | — | **125ms** | 含 scipy/shapely 计算 |
| `/api/tables/eflow_tt/profile` (画像1万行) | — | **1491ms** | pandas profiling |
| `/api/db/info` (轻量) | ~5ms | **10ms** | 20次调用 |

> 注：性能数据基于本机 SQLite (189MB)、headless Chromium 环境，仅供参考。

---

## 四、安全审计总结

| 维度 | 评估 | 说明 |
|------|------|------|
| 认证/授权 | ⚠️ 无 | 所有端点无需鉴权（内网工具可接受，公网必须加认证） |
| SQL 注入 | ✅ 安全 | search 参数参数化绑定；sort_by/column 引号包裹不可执行注入；table_name 白名单校验 |
| 路径遍历 | ⚠️ 部分缓解 | uuid 前缀偶然阻止，但 write-before-validate 是不良实践 |
| CORS | ⚠️ 配置不当 | * + credentials 无效组合 |
| 文件上传 DoS | ⚠️ 无限制 | 无大小限制、无类型深度校验 |
| 敏感信息泄露 | ⚠️ 低 | 500 错误可能暴露堆栈/内部结构（生产应关闭 debug） |

---

## 五、优先修复路线图

### P0 — 本周内（阻塞性/高严重度）
1. **[F-1]** stats 列名校验 → 防 500 崩溃
2. **[F-6]** 锁定 apscheduler==3.10.4

### P1 — 两周内（安全/质量）
3. **[F-2]** sort_by 列名白名单校验
4. **[F-3]** 上传文件名净化 + 写入前校验 + 大小限制
5. **[F-5]** 任务 API 404 规范化

### P2 — 下个迭代（体验/加固）
6. **[F-4]** CORS 配置修正
7. **[F-7]** 移动端响应式适配
8. **[F-8]** API 错误 UI 增强（重试/提示）
9. 生产环境关闭 debug 模式（FastAPI `debug=False`）

---

*报告由自动化深度测试套件生成。完整测试记录见 `tests/reports/deep_test_record_*.md`（Markdown/JSON/Excel）及截图 `deep_shots_*/` 目录。*
