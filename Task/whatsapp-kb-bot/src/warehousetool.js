/**
 * 库房查询工具 —— 意图解析 + 结果渲染（不经 LLM）。
 *
 * ## 为什么数字由脚本渲染
 *
 * 群里同事会把机器人说的话当依据去执行（去仓库领料、催归还）。
 * 模型一旦自由发挥，「0」可能被说成「没有」，也可能凭语感说成「有几个」——
 * 后者是编造。所以这里所有数字都来自 SQL 的 COUNT/SUM，
 * 模型只负责**选工具、抽参数**，一个数字都不参与。
 *
 * 与 src/ttquery.js（工单统计）同一套纪律。
 *
 * ## 三种问法
 *
 *   ① 总览：库房现在什么情况 / 各仓库存多少
 *   ② 物料：某物料还有多少库存 / 在哪些仓
 *   ③ 单据：SPIB202610220006 这张单什么情况
 *
 * ## 语言
 *
 * 英文提问走英文版。渲染是纯函数，可离线测试。
 */
import {
  queryWarehouseOverview,
  queryWarehouseMaterial,
  queryWarehouseTicket,
  extractSpTicketNos,
} from './warehousesource.js';

/* ------------------------------ 意图识别 ------------------------------ */

/**
 * 库房意图关键词。
 *
 * 为什么要这么多同义词：群里问法很杂 —— 「库房」「仓库」「库存」「备件」
 * 「领料」「出库」「入库」「调拨」「warehouse」「spare parts」「inventory」。
 * 少认一个就漏掉一类问法，漏掉的会掉进知识库通道被当成叙述题。
 *
 * ⚠️ 「在库」「哪些仓」「在哪个仓」也要算 —— 现场常说「SFP 在库多少」
 * 「这物料在哪些仓」，句子里没有「库存」「库房」两个字，
 * 只有「在库」/「哪些仓」这类说法。
 */
const WAREHOUSE_INTENT =
  /(库房|仓库|库存|存货|备件|物料仓|料仓|领料|出库|入库|调拨|盘点|在库|哪些仓|哪个仓|warehouse|inventory|stock|spare\s*parts?|material\s*(stock|warehouse))/i;

/**
 * 库房**知识问法**特征 —— 命中则该走知识库（RAG），不该走实时工具。
 *
 * ## 为什么需要这道护栏
 *
 * 库房工具一旦命中「库房/库存/入库」这些词就短路，**叙述性问题会被一起吃掉**：
 *   · 「库房有哪些单据类型」 → 答成「入库单 312 张、出库单 746 张」，
 *     用户问的是**有哪些类型**，答的是**有多少张** —— 答非所问；
 *   · 「库房库存表怎么对账 Gap 怎么算」 → 同样答成总览，
 *     而答案（Gap = 入库 − 出库 − 现存）明明白白写在知识库文档里。
 *
 * 这类问题的答案在**文档**里（库房-业务与数据字典.md），不在数据里。
 * 与 tools.js 里 KNOWLEDGE_INTENT 的分工一致：
 * 「是什么/有哪些/怎么算/含义」→ 知识库；「多少/状态/还剩」→ 实时数据。
 *
 * ⚠️ 边界：「某物料还有多少库存」里有「多少」但**没有**知识特征词，
 * 仍走工具；「库存表怎么对账」里有「怎么」但**没有**数量词，
 * 走知识库。两边靠各自的特征词区分，不靠互相排除。
 */
const WAREHOUSE_KNOWLEDGE_INTENT =
  /(是什么|有哪些|有哪几种|什么意思|啥意思|含义|怎么算|如何算|怎么对账|对账规则|口径|定义|区别|流程|怎么走|步骤|规则|标准|依据|为什么|字段|表结构|字段含义|what\s+is|what\s+are|which\s+\w+\s+types?|how\s+(is|do|does|to)\s+\w+\s+(work|calculat|comput)|meaning|defin|rule|criteria|difference|process|field|schema)/i;

/** 从提问里抽物料编码或名称关键字。 */
export function extractMaterialKeyword(q) {
  const s = String(q || '');
  // 带引导词的写法最可靠：「material no XXX」「物料编码 XXX」「part number XXX」
  const guided =
    s.match(
      /(?:material\s*(?:no\.?|number|code)?|part\s*(?:no\.?|number|code)|物料(?:编码|编号|料号)?|备件号)\s*[:：]?\s*([A-Za-z0-9][A-Za-z0-9\-_./()（）]{2,})/i
    )?.[1] || '';
  if (guided) return guided.trim();

  // 「物料 XXX 还有多少」：介词后的一串
  const after =
    s.match(/(?:物料|材料|备件|配件|material|part)\s+([A-Za-z0-9][A-Za-z0-9\-_./()（）]{2,})/i)?.[1] || '';
  if (after) return after.trim();

  // 裸名称兜底：「SFP 在库多少」「PS-M 在哪些仓」——
  // 取**第一个**连续的英文/数字型号词（不含空格）。这类写法句子里
  // 没有任何引导词，靠上面的两条规则都抽不到。
  // 限制在 2~30 字符，避免把整句英文当关键词。
  //
  // ⚠️ 必须排除**库房意图关键词本身** —— 否则
  // 「warehouse stock status」会把 warehouse 当成物料名，
  // 去物料表里 LIKE '%warehouse%'，答成「没有这个物料」。
  // 判断依据：这个词若本身就是库房话题词（warehouse/inventory/stock），
  // 说明它是问题的主语（问的是库房整体），不是被查的物料。
  const bare = s.match(/^\s*([A-Za-z0-9][A-Za-z0-9\-_./]{1,29})(?=\s|$)/)?.[1] || '';
  if (
    bare &&
    !/^(how|what|which|show|tell|check|is|are|the|please|can|do|does)$/i.test(bare) &&
    !/^(warehouse|inventory|stock|spare|material|part)s?$/i.test(bare)
  ) {
    return bare;
  }

  return '';
}

/**
 * 规则层解析库房意图。
 *
 * @returns {{tool:'query_warehouse', args:{kind:string, keyword?:string, ticket_no?:string}}|null}
 */
export function parseWarehouseIntent(q) {
  const s = String(q || '');
  if (!s) return null;

  // ① 单据：单号是**强信号**，不需要句子里同时出现「库房」二字 ——
  //    群里问「SPOB202609150003 怎么样」是常见写法，
  //    若要求先命中关键词就会漏掉，整条单号全丢。
  const nos = extractSpTicketNos(s);
  if (nos.length) {
    return { tool: 'query_warehouse', args: { kind: 'ticket', ticket_no: nos[0], keyword: '' } };
  }

  // ② 其余必须命中库房关键词。
  if (!WAREHOUSE_INTENT.test(s)) return null;

  // ②.5 知识问法护栏：「有哪些类型」「怎么算 Gap」这类问**口径**的问题，
  //     答案在知识库文档里，不在数据里 —— 交回 RAG 通道。
  //     单号查询不受影响（在上面 ① 就已经返回了）。
  if (WAREHOUSE_KNOWLEDGE_INTENT.test(s)) return null;

  // ③ 物料：问的是某个物料的库存。
  //    抽到关键词就按物料查 —— 不强制要求句子里出现「物料」二字。
  //    现场问法是「SFP 在库多少」「PS-M 在哪些仓」，没有「物料」字样，
  //    但显然问的是某个物料；若坚持要物料二字，这些会退化成总览，
  //    答成「全库有多少」而不是「这个物料有多少」。
  const keyword = extractMaterialKeyword(s);
  if (keyword) {
    return { tool: 'query_warehouse', args: { kind: 'material', keyword, ticket_no: '' } };
  }

  // ④ 其余（提到库房但没点名物料/单据）→ 总览。
  return { tool: 'query_warehouse', args: { kind: 'overview', keyword: '', ticket_no: '' } };
}

/**
 * 库房**话题词** —— 句子必须提到库房相关的概念，才算库房问法。
 *
 * 与 WAREHOUSE_INTENT 的区别：那个是「库房**事实**问法的强信号」
 * （出现即短路到工具）；这个是「这句确实在聊库房」的判定，
 * 用于知识问法的护栏，避免把工单问法（「P1 是什么级别」）也当成库房知识题。
 *
 * 比 WAREHOUSE_INTENT 更宽：库房口径问题常不带「库存」「库房」字样，
 * 但会提「单据」「物料」「仓库」「入库单」「序列号」这些概念。
 */
const WAREHOUSE_TOPIC =
  /(库房|仓库|库存|存货|备件|物料|材料|配件|料号|序列号|入库|出库|调拨|领料|盘点|单据|库存量|warehouse|inventory|stock|spare|material|serial|inbound|outbound|transfer|ticket)/i;

/**
 * 判断是不是**库房知识问法**（问口径/定义/类型，不是问实时数据）。
 *
 * 供 src/tools.js 的模型层校正使用 —— 模型可能把「有哪些单据类型」
 * 也选成 query_warehouse，这时要把它交回知识库通道。
 *
 * ⚠️ 这里**不能**只靠「有知识特征词」判定 ——
 * 「P1 是什么级别」「报销流程怎么走」同样含知识特征词，
 * 但它们与库房无关。所以还要要求句子**确实在聊库房**（WAREHOUSE_TOPIC）。
 *
 * 另外**不能**要求句子里出现 WAREHOUSE_INTENT 那些强事实信号 ——
 * 「物料管理方式 Instance 和 Category 区别」问的是库房物料口径，
 * 句子里却没有「库房」「库存」二字。若据此判「不是库房问法」，
 * 模型层一旦选了 query_warehouse，它就会被当成总览，
 * 答成「全库有多少」而不是「两种管理方式的区别」。
 */
export function isWarehouseKnowledgeQuestion(q) {
  const s = String(q || '');
  if (!s) return false;
  // 单号查询一律是事实查询，不受这道护栏影响
  if (extractSpTicketNos(s).length) return false;
  if (!WAREHOUSE_TOPIC.test(s)) return false;
  return WAREHOUSE_KNOWLEDGE_INTENT.test(s);
}

/* ------------------------------ 渲染 ------------------------------ */

const num = (v) => (v == null || v === '' ? '0' : String(v));

/**
 * 把库房库的时间字段转成可读文本。
 *
 * ⚠️ 库里有**两套**时间表示，同一行并存：
 *   · `inboundTime` / `createTime` 等 = **epoch 毫秒**（如 1792751686560）
 *   · `inboundTime_str` / `createTime_str` = **可读字符串**（如 2026-10-23 10:34:46）
 *
 * 直接把 epoch 毫秒显示给用户是错的（1792751686560 看不出是哪天），
 * 所以**优先取 _str 版本**；没有 _str 时才把 epoch 转成本地时间。
 */
function fmtTime(t, strKey) {
  const s = t?.[strKey];
  if (s != null && String(s).trim() !== '') return String(s).trim();

  const raw = t?.time;
  if (raw == null || raw === '') return '';
  const n = Number(raw);
  if (!Number.isFinite(n) || n <= 0) return String(raw);

  // epoch 毫秒 → 本地时间 YYYY-MM-DD HH:MM:SS
  const d = new Date(n);
  if (Number.isNaN(d.getTime())) return String(raw);
  const p = (x) => String(x).padStart(2, '0');
  return (
    `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ` +
    `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
  );
}

/** 渲染总览。 */
export function renderOverview(data, lang, source) {
  const degraded = source !== 'http';
  const lines = [];

  if (lang === 'en') {
    lines.push('Warehouse overview (SP spare parts):');
    if (data.lastSync) lines.push(`Data as of: ${data.lastSync}`);
    lines.push('');
    lines.push(
      `Inbound tickets: ${num(data.inboundTickets?.Total)} total, ` +
        `${num(data.inboundTickets?.Closed)} closed, ${num(data.inboundTickets?.Unclosed)} open`
    );
    lines.push(
      `Outbound tickets: ${num(data.outboundTickets?.Total)} total, ` +
        `${num(data.outboundTickets?.Closed)} closed, ${num(data.outboundTickets?.Unclosed)} open`
    );

  if (data.inventory?.length) {
    lines.push('');
    if (data.snapshotDate) {
      lines.push(
        lang === 'en'
          ? `Current stock by warehouse (snapshot ${data.snapshotDate}):`
          : `各仓当前库存（快照日期 ${data.snapshotDate}）：`
      );
    } else {
      lines.push(lang === 'en' ? 'Current stock by warehouse:' : '各仓当前库存：');
    }
    for (const r of data.inventory) {
      lines.push(`- ${r.warehouse}: ${num(r.qty)} (${num(r.items)} records)`);
    }
  }
    if (data.inboundByType?.length) {
      lines.push('');
      lines.push('Inbound by type:');
      for (const r of data.inboundByType) {
        lines.push(`- ${r.type}: ${num(r.total)} tickets, ${num(r.qty)} qty`);
      }
    }
    if (data.outboundByType?.length) {
      lines.push('');
      lines.push('Outbound by type:');
      for (const r of data.outboundByType) {
        lines.push(`- ${r.type}: ${num(r.total)} tickets, ${num(r.qty)} qty`);
      }
    }
    if (degraded) {
      lines.push('');
      lines.push('Note: read from the local SQLite snapshot (delayed) — my_app was unavailable.');
    }
    return lines.join('\n');
  }

  lines.push('库房总览（SP 备件库房）：');
  if (data.lastSync) lines.push(`数据同步时间：${data.lastSync}`);
  lines.push('');
  lines.push(
    `入库单：共 ${num(data.inboundTickets?.Total)} 张，已闭环 ${num(data.inboundTickets?.Closed)}，` +
      `未闭环 ${num(data.inboundTickets?.Unclosed)}`
  );
  lines.push(
    `出库单：共 ${num(data.outboundTickets?.Total)} 张，已闭环 ${num(data.outboundTickets?.Closed)}，` +
      `未闭环 ${num(data.outboundTickets?.Unclosed)}`
  );

  if (data.inventory?.length) {
    lines.push('');
    if (data.snapshotDate) {
      lines.push(`各仓当前库存（快照日期 ${data.snapshotDate}）：`);
    } else {
      lines.push('各仓当前库存：');
    }
    for (const r of data.inventory) {
      lines.push(`- ${r.warehouse}：${num(r.qty)}（${num(r.items)} 条明细）`);
    }
  }
  if (data.inboundByType?.length) {
    lines.push('');
    lines.push('入库按类型：');
    for (const r of data.inboundByType) {
      lines.push(`- ${r.type}：${num(r.total)} 张单，数量 ${num(r.qty)}`);
    }
  }
  if (data.outboundByType?.length) {
    lines.push('');
    lines.push('出库按类型：');
    for (const r of data.outboundByType) {
      lines.push(`- ${r.type}：${num(r.total)} 张单，数量 ${num(r.qty)}`);
    }
  }
  if (degraded) {
    lines.push('');
    lines.push('注：本次读的是本地 SQLite 副本（有延迟），my_app 当时不可用。');
  }
  return lines.join('\n');
}

/** 渲染物料库存查询。 */
export function renderMaterial(data, keyword, lang) {
  const rows = data?.rows || [];
  if (!rows.length) {
    return lang === 'en'
      ? `No stock found for material "${keyword}" in the current warehouse snapshot.`
      : `当前库存快照里没找到物料「${keyword}」的记录。`;
  }

  const lines = [];
  if (lang === 'en') {
    lines.push(`Stock for material "${keyword}":`);
    for (const r of rows) {
      lines.push(
        `- ${r.materialName || '(no name)'} [${r.materialNo}] — ${num(r.qty)} ${r.unit || ''} ` +
          `in ${r.warehouse}${r.materialStatus && r.materialStatus !== 'available' ? ` (${r.materialStatus})` : ''}`
      );
    }
  } else {
    lines.push(`物料「${keyword}」的库存：`);
    for (const r of rows) {
      lines.push(
        `- ${r.materialName || '（无名称）'} [${r.materialNo}] —— ${num(r.qty)} ${r.unit || ''}，` +
          `在 ${r.warehouse}${r.materialStatus && r.materialStatus !== 'available' ? `（${r.materialStatus}）` : ''}`
      );
    }
  }
  if (data.lastSync) {
    lines.push(lang === 'en' ? `Source: warehouse DB, synced ${data.lastSync}` : `来源：库房库，同步时间 ${data.lastSync}`);
  }
  return lines.join('\n');
}

/** 渲染单据查询。 */
export function renderTicket(data, ticketNo, lang) {
  if (!data || data.kind === 'none' || !data.ticket) {
    return lang === 'en'
      ? `No warehouse ticket found for ${ticketNo}.`
      : `库房单据里没找到 ${ticketNo}。`;
  }

  const t = data.ticket;
  const lines = [];
  const isInbound = data.kind === 'inbound';

  const pick = (...keys) => {
    for (const k of keys) {
      const v = t[k];
      if (v != null && v !== '') return String(v);
    }
    return '';
  };

  // 时间：优先 _str 可读字段，其次 epoch 毫秒转换（见 fmtTime 注释）
  const timeText = isInbound
    ? fmtTime(t, 'inboundTime_str') || fmtTime({ time: t.inboundTime }, 'time')
    : fmtTime(t, 'outboundTime_str') || fmtTime({ time: t.outboundTime }, 'time');
  const requestText = fmtTime(t, 'requestTime_str') || fmtTime({ time: t.requestTime }, 'time');
  const closeText = fmtTime(t, 'closeTime_str') || fmtTime({ time: t.closeTime }, 'time');

  if (lang === 'en') {
    lines.push(`Warehouse ticket ${ticketNo} (${isInbound ? 'Inbound' : 'Outbound'}):`);
    lines.push(`- Status: ${pick('status', 'Status') || '(empty)'}`);
    const type = pick('inboundType', 'outboundType', 'Inbound Type', 'Outbound Type');
    if (type) lines.push(`- Type: ${type}`);
    const wh = pick('warehouseName', 'Warehouse Name');
    if (wh) lines.push(`- Warehouse: ${wh}`);
    if (timeText) lines.push(`- Time: ${timeText}`);
    if (requestText) lines.push(`- Requested: ${requestText}`);
    if (closeText) lines.push(`- Closed: ${closeText}`);
  } else {
    lines.push(`库房单据 ${ticketNo}（${isInbound ? '入库单' : '出库单'}）：`);
    lines.push(`- 状态：${pick('status', 'Status') || '（空）'}`);
    const type = pick('inboundType', 'outboundType', 'Inbound Type', 'Outbound Type');
    if (type) lines.push(`- 类型：${type}`);
    const wh = pick('warehouseName', 'Warehouse Name');
    if (wh) lines.push(`- 库房：${wh}`);
    if (timeText) lines.push(`- 时间：${timeText}`);
    if (requestText) lines.push(`- 请求时间：${requestText}`);
    if (closeText) lines.push(`- 关闭时间：${closeText}`);
  }

  const lines2 = data.lines || [];
  if (lines2.length) {
    lines.push('');
    lines.push(lang === 'en' ? `Material lines (${lines2.length}):` : `物料明细（${lines2.length} 行）：`);
    for (const r of lines2.slice(0, 12)) {
      const label = r.materialName || r.materialNo || '(unknown)';
      const extra = lang === 'en' ? r.recipient || '' : r.relatedTicket ? `关联工单 ${r.relatedTicket}` : '';
      lines.push(
        `- ${label}${r.serialNo ? ` / ${r.serialNo}` : ''} — ${num(r.qty)} ${r.unit || ''}` +
          `${r.warehouse ? ` @ ${r.warehouse}` : ''}${extra ? `（${extra}）` : ''}`
      );
    }
    if (lines2.length > 12) {
      lines.push(
        lang === 'en'
          ? `... and ${lines2.length - 12} more lines`
          : `……另有 ${lines2.length - 12} 行明细未列出`
      );
    }
  }
  return lines.join('\n');
}

/* ------------------------------ 工具入口 ------------------------------ */

/**
 * 执行库房查询。
 *
 * @param {object} args {kind:'overview'|'material'|'ticket', keyword?:string, ticket_no?:string}
 * @param {'zh'|'en'} lang
 * @returns {Promise<{text:string, answered:boolean, stats:object}>}
 */
export async function runWarehouseQuery(args, lang) {
  const kind = String(args?.kind || 'overview');

  try {
    if (kind === 'ticket') {
      const r = await queryWarehouseTicket(args?.ticket_no || '');
      if (!r.ok) {
        return {
          text:
            lang === 'en'
              ? `I couldn't query the warehouse ticket: ${r.error}`
              : `库房单据没查成：${r.error}`,
          answered: false,
          stats: { kind },
        };
      }
      return {
        text: renderTicket(r.data, String(args?.ticket_no || '').toUpperCase(), lang),
        answered: true,
        stats: { kind, source: r.source },
      };
    }

    if (kind === 'material') {
      const r = await queryWarehouseMaterial(args?.keyword || '');
      if (!r.ok) {
        return {
          text:
            lang === 'en'
              ? `I couldn't query the warehouse stock: ${r.error}`
              : `库房库存没查成：${r.error}`,
          answered: false,
          stats: { kind },
        };
      }
      return {
        text: renderMaterial(r.data, args?.keyword || '', lang),
        answered: true,
        stats: { kind, source: r.source },
      };
    }

    // 总览
    const r = await queryWarehouseOverview();
    if (!r.ok) {
      return {
        text:
          lang === 'en'
            ? `I couldn't query the warehouse data: ${r.error}`
            : `库房数据没查成：${r.error}`,
        answered: false,
        stats: { kind },
      };
    }
    return {
      text: renderOverview(r.data, lang, r.source),
      answered: true,
      stats: { kind, source: r.source, degraded: r.source !== 'http' },
    };
  } catch (err) {
    // 兜底：抛错也要如实说查不了，**绝不**把「查不了」说成「没有数据」
    return {
      text:
        lang === 'en'
          ? `The warehouse query failed: ${err.message}`
          : `库房查询出错了：${err.message}`,
      answered: false,
      stats: { kind, error: true },
    };
  }
}
