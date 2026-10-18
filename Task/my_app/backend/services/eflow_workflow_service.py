"""eFlow TT 工作流（Workflow）定义服务。

## 这个模块解决什么

`Workflow` 里程碑（`?page=tt` / `?page=wo` 的 TT Statistics 下方）原先的阶段顺序是
**手写在两个地方**的（前端 `STATUS_MILESTONES`、后端导出），凭经验排；
eFlow 本身是有一套权威流程图的，本模块把它取回来并**翻译成可核对的阶段顺序**。

## 上游接口（2026-10-17 实测确认，勿凭直觉改）

    POST /api/eflow-ticket/v1/flow/runtime/queryAllSteps
    Content-Type: text/plain
    Body: eflow-tt            ← **裸字符串**，不是 JSON，也不是单号

返回的是**流程定义**（8 个节点 + 节点间连边），不是某一张单的步骤历史。
踩坑记录：最初按 JSON 传 `{"ttNo": "TT2026..."}` 等键名，一律
`500 {"code":48990002,"message":"Failed to send request!"}` —— 那个 500 是
「body 解析失败」，不是「单号不存在」。body 必须就是 `eflow-tt` 这个字面量。

响应形状（已裁剪，仅保留本模块用到的字段）::

    [{"id": "bootstrap", "name": "Create", "type": "startEvent",
      "sequenceElements": [{"name": "WaitFOAccept", "nextName": "FOAccept",
                            "condition": "${(result == '1') == true}"}, ...]}, ...]

- `name`        —— 节点名（`Create` / `FOAccept` / `FOProcess` / `Confirm` / `Closed` …）
- `sequenceElements[].name`      —— 这一步**完成时**转入的等待状态（`WaitFOAccept` …），
  与 DB 里 `eflow_tt.status` 的 `Waiting for FO Accept` 是同义的不同写法
- `sequenceElements[].nextName`  —— 转入的下一节点
- `condition`   —— 操作码条件（`result == '1'` = FO 受理 …）

## 为什么要「翻译」而不是直接画图

流程图是有环的（`Confirm` 可以驳回回 `FOProcess`、`ThirdProcess`），
画成线性的里程碑展示会误导值班。本模块只提取**主干顺序**（从 `Create` 出发、
沿 `nextName` 的最长路径到 `Closed`），并把每个节点映射到 DB 里真实的
`status` 取值 —— 前者给顺序，后者给数字，两者交叉校验。
"""
from __future__ import annotations

import logging
from functools import lru_cache

from backend.services import eflow_api_client as api

logger = logging.getLogger("eflow_workflow")

WORKFLOW_STEPS_PATH = "/api/eflow-ticket/v1/flow/runtime/queryAllSteps"
# 上游认的 body（裸字符串）与 Referer。Referer 必须指向票据管理页，
# 否则 forgerydefense 校验不过；与 `_headers_extra` 的其余头一起使用。
WORKFLOW_BODY = "eflow-tt"
WORKFLOW_REFERER_SUFFIX = "/iui/ticket-mgt/v1/"

# eFlow 节点名 → 本项目的阶段 key。节点名是驼峰英文（`FOAccept`），
# DB 状态是自然语言（`Waiting for FO Accept`），两者在这里对齐。
# ⚠ 新增节点时**必须**同时确认前端 `STATUS_MILESTONES` 里有对应阶段，
# 否则该节点的单会落进「其他」（不会丢，但会单列）。
NODE_TO_STAGE: dict[str, str] = {
    "Create": "reassign",
    "FOAccept": "waitAccept",
    "BOAccept": "waitAccept",
    "ThirdAccept": "waitAccept",
    "FOProcess": "waitProcess",
    "BOProcess": "waitProcess",
    "ThirdProcess": "waitProcess",
    "Confirm": "waitConfirm",
    "Closed": "closed",
}

# 上游 `nextName` 里出现的节点名 → 阶段（`Closed` 是唯一由 `nextName` 引用、
# 但**不在**节点列表里的名字，见 `_longest_path` 的说明）。
CLOSED_NODE_NAME = "Closed"

# 阶段间的主干顺序（长路径）。已按上游图核对：
#   Create → FOAccept → FOProcess → ThirdAccept/ThirdProcess → Confirm → Closed
# 注意 `FOProcess` 之后才可能轮到 `ThirdAccept`（见 Create 的多条出边），
# 所以「受理」与「处理」在图上**互相可达**，线性化时按「首次出现」定序，
# 与用户 2026-10-17 提供的 Workflow History 实测链一致。
#
# ⚠ 这里列的是**前端展示用的全部阶段 key**，不只图上出现的节点：
#   - `arriveSite` / `leaveSite` 来自 `eflow_wo`（WO 表有走到场/离站的状态），
#     TT 图上没有对应节点，但 WO 页共用同一个里程碑渲染器，必须保留顺序位；
#   - `waitConfirmFO`（现场确认）是 TT 状态里 `Waiting for FO Process(WO RCA…)`
#     等三个变体的阶段，图上并入 `FOProcess` 节点，展示上仍单列。
# 两端 key 必须**逐字一致**，否则前端 `rank` 查不到 → 该阶段被挤到末尾。
CANONICAL_STAGE_ORDER = [
    "reassign",
    "waitAccept",
    "arriveSite",
    "waitProcess",
    "leaveSite",
    "waitConfirmFO",
    "waitConfirm",
    "closed",
]


def _plain_headers(referer: str) -> str:
    """把 `_headers_extra` 的 JSON Content-Type 换成 text/plain。

    上游对 `queryAllSteps` 走的是裸文本 body，Content-Type 必须跟着改；
    其余 Cookie / forgerydefense / timeZoneInfo 等保持与其它端点一致。
    """
    return api._headers_extra(referer).replace(
        "Content-Type: application/json", "Content-Type: text/plain"
    )


@lru_cache(maxsize=1)
def _fetch_workflow_graph_cached() -> tuple:
    """取流程图（进程内缓存）。

    返回 tuple（可缓存），元素为 dict —— 调用方只读，不要就地修改。
    流程定义是**版本级静态数据**，一个进程生命周期内取一次足够；
    进程重启会重新取，跟 worker 的日常重启节奏对齐。
    """
    api.ensure_login()
    referer = f"https://{api.HOST}:{api.PORT}{WORKFLOW_REFERER_SUFFIX}"
    status, _headers, _raw, body = api._http_request(
        "POST", WORKFLOW_STEPS_PATH,
        headers_extra=_plain_headers(referer),
        body=WORKFLOW_BODY,
    )
    if "200" not in status:
        raise RuntimeError(f"queryAllSteps 失败: {status} {body[:200]!r}")
    import json
    nodes = json.loads(body.decode("utf-8"))
    if not isinstance(nodes, list):
        raise RuntimeError(f"queryAllSteps 返回非数组: {type(nodes).__name__}")
    return tuple(nodes)


def fetch_workflow_graph() -> list[dict]:
    """流程图节点列表（含缓存）。失败时抛异常，由路由层转成 503。"""
    return [dict(n) for n in _fetch_workflow_graph_cached()]


def _longest_path(nodes: list[dict]) -> list[str]:
    """从 `Create` 出发、经 `Closed` 的最长节点路径（只取 `nextName`）。

    流程有环（Confirm → FOProcess …），用 DFS + 访问栈防环，取最长的一条作主干。
    节点规模是 8 个，穷举完全够用；不要改成启发式。
    """
    out_edges: dict[str, list[str]] = {}
    for n in nodes:
        name = n.get("name") or ""
        nxt = []
        for s in n.get("sequenceElements") or []:
            nn = s.get("nextName")
            if nn:
                nxt.append(nn)
        out_edges[name] = nxt

    best: list[str] = []

    def walk(cur: str, path: list[str], seen: set[str]) -> None:
        nonlocal best
        if len(path) > len(best):
            best = list(path)
        for nn in out_edges.get(cur, []):
            if nn in seen:          # 成环，剪掉这条支路
                continue
            seen.add(nn)
            path.append(nn)
            walk(nn, path, seen)
            path.pop()
            seen.discard(nn)

    if "Create" in out_edges:
        walk("Create", ["Create"], {"Create"})
    return best


def workflow_summary() -> dict:
    """给前端的流程图摘要：主干顺序 + 节点→阶段的对照 + 节点清单。"""
    nodes = fetch_workflow_graph()
    path = _longest_path(nodes)
    return {
        "nodes": [
            {
                "id": n.get("id"),
                "name": n.get("name"),
                "type": n.get("type"),
                "stage": NODE_TO_STAGE.get(n.get("name") or "", None),
            }
            for n in nodes
        ],
        "main_path": path,
        "node_to_stage": dict(NODE_TO_STAGE),
        "stage_order": list(CANONICAL_STAGE_ORDER),
        "body": WORKFLOW_BODY,
    }
