/* ============================================================================
   team-scope-map.js —— 团队门户的**作用域映射**（**生成文件，勿手改**）
   ----------------------------------------------------------------------------
   由 scripts/gen_team_matrix.py 从 v3/team_portal/scope-map.json 生成。
   与 team-matrix.js 同源 —— 一个说「勾了哪些」，一个说「怎么对应到门户组件」。

   结构：{ 域键: { 子键: { urlPatterns?: [...] } } }
   urlPatterns 只在 OSS 域出现：它是「槽位 → 门户目录条目」的匹配依据
   （用 url 片段而非标题 —— 标题在目录里可编辑，模糊匹配会突然失效）。
   ========================================================================== */
(function () {
  'use strict';
  window.OLBR_SCOPE_MAP = {
  "archive": {
    "archive": {}
  },
  "aux": {
    "aux": {}
  },
  "bf": {
    "meta": {},
    "speed": {}
  },
  "complaint": {
    "vmax": {}
  },
  "escalation": {
    "esc": {}
  },
  "feedback": {
    "fb": {}
  },
  "kpi": {
    "avail": {},
    "rich": {}
  },
  "map": {
    "gis": {},
    "mwRealTime": {},
    "person": {}
  },
  "oss": {
    "dcserver": {
      "urlPatterns": [
        "10.121.8.2"
      ]
    },
    "eflow": {
      "urlPatterns": [
        "10.100.20.8"
      ]
    },
    "fwumc": {
      "urlPatterns": [
        "10.100.2.101"
      ]
    },
    "imonitor": {
      "urlPatterns": [
        "172.17.208.1",
        "page=imonitor"
      ]
    },
    "ipran": {
      "urlPatterns": [
        "10.100.2.99"
      ]
    },
    "mw": {
      "urlPatterns": [
        "192.168.169.247"
      ]
    },
    "nmsccn": {
      "urlPatterns": [
        "192.168.100.19",
        "10.100.28.27",
        "10.121.1.2"
      ]
    },
    "portalLogin": {
      "urlPatterns": [
        "page=portalLogin"
      ]
    },
    "rais": {
      "urlPatterns": [
        "10.100.20.9"
      ]
    },
    "vmaxcxo": {
      "urlPatterns": [
        "10.123.255.12"
      ]
    }
  },
  "qa": {
    "assistant": {},
    "eflow": {},
    "rag": {}
  },
  "qc": {
    "alarm": {},
    "cr": {},
    "pmt": {},
    "spms": {},
    "tt": {},
    "wo": {}
  },
  "report": {
    "battery": {},
    "liberia_1h": {},
    "liberia_8h": {},
    "ms_contract": {},
    "ms_wo_sla": {},
    "packet_loss": {},
    "ran_availability": {},
    "sp_consumables": {},
    "sp_spareparts": {},
    "tt_mttr": {}
  },
  "view": {
    "BO View": {},
    "CXO View": {},
    "FLM View": {},
    "FO View": {},
    "MS View": {},
    "SP View": {}
  }
};
})();
