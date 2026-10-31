/* ============================================================================
   team-matrix.js —— 团队门户可见性矩阵（**生成文件，勿手改**）
   ----------------------------------------------------------------------------
   由 scripts/gen_team_matrix.py 从 v3/team_portal/scope-map.json 生成。
   改需求请改 scope-map.json（或改 Excel 后跑 --import-excel），
   不要直接编辑本文件 —— 手改会在下次重跑时被静默覆盖。

   结构：{ 域键: { 子键: [有勾的团队 id, ...] } }
   域键与门户组件的对应关系见 scope-map.json。
   ========================================================================== */
(function () {
  'use strict';
  window.OLBR_TEAM_MATRIX = {
  "bf": {
    "meta": [
      "smc",
      "cxo"
    ],
    "speed": [
      "smc",
      "cxo"
    ]
  },
  "complaint": {
    "vmax": [
      "fo",
      "bo",
      "flm",
      "smc"
    ]
  },
  "escalation": {
    "esc": [
      "fo",
      "bo",
      "flm",
      "smc",
      "cxo"
    ]
  },
  "feedback": {
    "fb": [
      "fo",
      "bo",
      "flm",
      "smc",
      "cxo"
    ]
  },
  "kpi": {
    "avail": [
      "fo",
      "bo",
      "flm",
      "smc",
      "cxo"
    ],
    "rich": [
      "fo",
      "bo",
      "smc",
      "cxo"
    ]
  },
  "map": {
    "gis": [
      "fo",
      "flm",
      "smc",
      "cxo"
    ],
    "mwRealTime": [
      "fo",
      "bo",
      "flm",
      "smc",
      "cxo"
    ],
    "person": [
      "fo",
      "flm",
      "smc",
      "cxo"
    ]
  },
  "oss": {
    "dcserver": [
      "fo",
      "bo",
      "smc"
    ],
    "eflow": [
      "fo",
      "bo",
      "smc"
    ],
    "fwumc": [
      "fo",
      "bo",
      "smc"
    ],
    "imonitor": [
      "fo",
      "bo",
      "smc"
    ],
    "ipran": [
      "fo",
      "bo",
      "smc"
    ],
    "mw": [
      "fo",
      "bo",
      "smc"
    ],
    "nmsccn": [
      "fo",
      "bo",
      "smc"
    ],
    "portalLogin": [
      "fo",
      "bo",
      "smc"
    ],
    "rais": [
      "fo",
      "bo",
      "smc"
    ],
    "vmaxcxo": [
      "fo",
      "bo",
      "smc"
    ]
  },
  "qa": {
    "assistant": [
      "fo",
      "bo",
      "flm",
      "smc",
      "cxo"
    ],
    "eflow": [
      "fo",
      "bo",
      "flm",
      "smc"
    ],
    "rag": [
      "fo",
      "bo",
      "flm",
      "smc",
      "cxo"
    ]
  },
  "qc": {
    "alarm": [
      "fo",
      "bo",
      "flm",
      "smc"
    ],
    "cr": [
      "fo",
      "bo"
    ],
    "pmt": [
      "flm"
    ],
    "spms": [
      "flm"
    ],
    "tt": [
      "fo",
      "flm",
      "smc"
    ],
    "wo": [
      "fo",
      "flm",
      "smc"
    ]
  },
  "report": {
    "battery": [
      "fo",
      "bo",
      "flm"
    ],
    "liberia_1h": [
      "fo",
      "flm"
    ],
    "liberia_8h": [
      "fo",
      "flm"
    ],
    "ms_contract": [
      "fo",
      "flm"
    ],
    "ms_wo_sla": [
      "fo",
      "flm"
    ],
    "packet_loss": [
      "fo",
      "bo"
    ],
    "ran_availability": [
      "fo",
      "bo"
    ],
    "sp_consumables": [
      "fo",
      "flm"
    ],
    "sp_spareparts": [
      "fo",
      "flm"
    ],
    "tt_mttr": [
      "fo",
      "flm"
    ]
  },
  "view": {
    "BO View": [
      "bo"
    ],
    "CXO View": [
      "bo",
      "cxo"
    ],
    "FLM View": [
      "flm"
    ],
    "FO View": [
      "fo"
    ],
    "SP View": [
      "flm"
    ]
  }
};
})();
