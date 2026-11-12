# UME 拓扑路由（routers/ipran_topo.py）

前缀：`/api/ipran-topo`。只读，无写接口。四层共用同一套路由与服务实现。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/layers` | 页签清单（key / 中英名 / 是否有 UME 人工布局 / 层级标签）。**不返回 lid** |
| GET | `/graph?layer=ipran&refresh=0` | 完整图数据（网元 + 折叠后的边 + meta）。`layer` 缺省为 `ipran` |

`layer` 走 `layers.LAYERS` 白名单，非法值直接 **400**，**不接受前端传任意 lid**。
不带 `layer` 时默认 `ipran`，与改造前一致（旧调用兼容）；前端四层页签会显式传 `layer`。
`refresh=1` 只清**当前层**图缓存并重载共用的站点坐标缓存，不会把另外三层缓存一起打掉。

实现与聚合口径见 `backend/services/ipran_topo/ipran_topo_service.py` 与同目录 `.md`；
层清单、lid 与每层口径见 `backend/services/ipran_topo/layers.py`。

取数失败时返回**空图 + `meta.warnings[load_failed]`**（HTTP 200，`meta` 里带 `layer`），
不抛 500 —— 前端据此渲染错误条，与项目内其他看板路由一致。参数非法与取数失败是两回事，
前者不该被吞成 200。

本路由**不在** `_PUBLIC_API` 白名单内，需要登录。
