/* MsPortal / olbrportal 共用：目录数据里**只有中文取值**的那几个字段的英文映射。
   ---------------------------------------------------------------------------
   为什么不并进 data.js：data.js 由 TMP/gen_msportal.py 从 xlsx 重新生成，
   写进去的映射下一次同步就会被抹掉。放独立文件 + 只读引用，生成器管不到它。
   为什么不并进各自的字典（portal.js / olbr.js 的 I18N）：字典键是界面文案，
   这里是**数据值**的翻译，两者生命周期不同 —— 加一个看板可能就多一个部门名。
   olbrportal 已经跨目录只读引用 /MsPortal/assets/data.js，这里沿用同一套耦合。

   取值口径：/api/portal-catalog（服务端目录，优先级最高）∩ data.js ∩
   msportal-config*.json 三份目录的 dept / owner / freq 去重值全集，共
   dept 28 / owner 38 / freq 9。三份都在用，缺一份就会在英文模式露中文。

   兜底策略：查不到就原样返回中文，宁可露一个中文也不显示空白或键名。
   另外目录里存在 *En 字段被填成中文原值的历史脏数据（如 ownerEn="IP 传输工程师"），
   所以取英文字段时走 msPortalEnOf，含中文就当作没有。 */
(function (w) {
  'use strict';

  /* 只判汉字（CJK 统一表意文字 + 扩展 A + 兼容表意文字），够覆盖脏数据形态；
     全角标点不算，避免误伤 "FO / FLM" 这类正常写法。 */
  var HAN = /[一-鿿㐀-䶿豈-﫿]/;

  function pad2(n) { n = String(n); return n.length < 2 ? '0' + n : n; }

  w.MSPortalTerms = {
    /* 刷新频率 —— 卡片 meta 行直接显示（olbrportal）。这里是精确命中；
       运营在目录里填的时间点写法不固定，命中不了时走 FREQ_RULES。 */
    freq: {
      '实时流式': 'Real-time stream',
      '每小时': 'Hourly',
      '每日0点': 'Daily 00:00',
      '每日06:20': 'Daily 06:20',
      '周度更新': 'Weekly',
      '月度汇总': 'Monthly'
    },
    /* 责任部门 —— 三份目录 28 个去重值全覆盖（其中 10 个在目录里根本没有 deptEn）。
       命名沿用已有 deptEn 的口径（"FO Spare Parts Management Team" 那一类）。 */
    dept: {
      'BO 二线无线优化部': 'BO Back-office Wireless Optimization Dept',
      'BO 传输专家组': 'BO Transmission Expert Team',
      'BO 核心网专家组': 'BO Core Network Expert Team',
      'BO 综合分析部': 'BO Comprehensive Analysis Dept',
      'BO 网络安全组': 'BO Network Security Team',
      'BO 骨干传输组': 'BO Backbone Transmission Team',
      'DevOps 架构部': 'DevOps Architecture Dept',
      'FLM 现场抢修部': 'FLM Field Repair Dept',
      'FO / FLM 工单派发组': 'FO / FLM Ticket Dispatch Team',
      'FO 一线值班室': 'FO Front-line Duty Room',
      'FO 一线监控值班': 'FO Front-line Monitoring Duty',
      'FO 备件管理组': 'FO Spare Parts Management Team',
      'FO 监控中心': 'FO Monitoring Center',
      'FO 运维分析组': 'FO O&M Analysis Team',
      'IP 核心网部': 'IP Core Network Dept',
      'MS 性能统计组': 'MS Performance Statistics Team',
      'MS 质量管理组': 'MS Quality Management Team',
      'MS 运维部': 'MS Operation Dept',
      'MS 运营管理部': 'MS Operation Management Dept',
      '供应链与备件中心': 'Supply Chain & Spares Center',
      '动力配套部': 'Power & Environment Dept',
      '应急保障中心': 'Emergency Support Center',
      '数据仓库部': 'Data Warehouse Dept',
      '数据运营部': 'Data Operation Dept',
      '综合运营部': 'Integrated Operations Dept',
      '传输与 IP 网管部': 'Transmission & IP Network Management Dept',
      '网规网优部': 'Network Planning & Optimization Dept',
      '运维专家组': 'O&M Expert Team'
    },
    /* 责任人（实为岗位）—— 三份目录 38 个去重值全覆盖（11 个在目录里没有 ownerEn）。 */
    owner: {
      '2G 网优专家': '2G Network Optimization Expert',
      '3G 网优专家': '3G Network Optimization Expert',
      'LTE 网优专家': 'LTE Network Optimization Expert',
      'DBA': 'DBA',
      'FLM 总监': 'FLM Director',
      'FO 运营主管': 'FO Operation Manager',
      'GIS 工程师': 'GIS Engineer',
      'IP 传输工程师': 'IP Transmission Engineer',
      'MS SLA 专员': 'MS SLA Specialist',
      'MS 项目总监': 'MS Project Director',
      'NUR 专项工程师': 'NUR Special Engineer',
      'NUR 分析师': 'NUR Analyst',
      '事件总指挥': 'Incident Commander',
      '仓库主管': 'Warehouse Supervisor',
      '传输工程师': 'Transmission Engineer',
      '传输骨干工程师': 'Backbone Transmission Engineer',
      '值班长': 'Duty Manager',
      '动环工程师': 'Power & Environment Engineer',
      '告警监控岗': 'Alarm Monitoring Desk',
      '城域网工程师': 'Metro Network Engineer',
      '审计主管': 'Audit Manager',
      '工单分析师': 'Ticket Analyst',
      '工单调度员': 'Ticket Dispatcher',
      '性能分析师': 'Performance Analyst',
      '承载网主管': 'Bearer Network Manager',
      '数据处理员': 'Data Processing Clerk',
      '数据分析员': 'Data Analyst',
      '核心网主管': 'Core Network Manager',
      '核心网规划师': 'Core Network Planner',
      '系统管理员': 'System Administrator',
      '网络专家': 'Network Specialist',
      '网络安全官': 'Network Security Officer',
      '规则架构师': 'Rules Architect',
      '调度管理员': 'Scheduling Administrator',
      '质量主管': 'Quality Manager',
      '运维分析师': 'O&M Analyst',
      '运维经理': 'O&M Manager',
      '项目总经理': 'Project General Manager'
    }
  };

  var WEEKDAY = { '一': 'Mon', '二': 'Tue', '三': 'Wed', '四': 'Thu', '五': 'Fri', '六': 'Sat', '日': 'Sun', '天': 'Sun' };

  /* freq 的自由写法按规则翻译（回调收匹配数组，分组用 m[1] 起）：
     时间点直接搬过去，不做时区换算 —— 目录里填的是服务器出数时刻，浏览器与服务端同为 UTC。 */
  var FREQ_RULES = [
    [/^每日\s*(\d{1,2})\s*点$/, function (m) { return 'Daily ' + pad2(m[1]) + ':00'; }],
    [/^每日\s*(\d{1,2})[:：](\d{2})$/, function (m) { return 'Daily ' + pad2(m[1]) + ':' + m[2]; }],
    [/^每日|^天天/, function () { return 'Daily'; }],
    [/^每周\s*([一二三四五六日天])(?:\s*(\d{1,2})[:：](\d{2}))?/, function (m) {
      return 'Weekly ' + (WEEKDAY[m[1]] || '') + (m[2] ? ' ' + pad2(m[2]) + ':' + m[3] : '');
    }],
    [/^每周/, function () { return 'Weekly'; }],
    [/^每月/, function () { return 'Monthly'; }],
    [/^每半小时/, function () { return 'Every 30 min'; }],
    [/^每小时/, function () { return 'Hourly'; }],
    [/^实时|^流式/, function () { return 'Real-time stream'; }],
    [/^不定期|^按需|^手动/, function () { return 'Ad hoc'; }]
  ];

  /** 按中文原值取英文，取不到就原样返回。kind: 'freq' | 'dept' | 'owner' */
  w.msPortalTerm = function (kind, zh) {
    if (!zh) return zh || '';
    var key = String(zh).trim();
    var hit = (w.MSPortalTerms[kind] || {})[key];
    if (hit) return hit;
    if (kind !== 'freq') return zh;
    for (var i = 0; i < FREQ_RULES.length; i++) {
      var m = FREQ_RULES[i][0].exec(key);
      if (m) return FREQ_RULES[i][1](m);
    }
    return zh;
  };

  /** 取条目上的英文字段：目录里有 *En 被填成中文原值的脏数据，
      含汉字（或为空）时回查映射表，再不行退回中文原值。 */
  w.msPortalEnOf = function (en, kind, zh) {
    if (en && !HAN.test(en)) return en;
    return w.msPortalTerm(kind, zh || en) || en || '';
  };
})(window);
