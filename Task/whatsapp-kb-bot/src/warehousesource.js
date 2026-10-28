/**
 * 库房（SP 备件库房）查询的**取数层** —— HTTP 优先，SQLite 降级。
 *
 * ## 为什么库房数据要单独一层
 *
 * 库房数据是**实时事实**（库存数量、单据状态每小时都在变），
 * 不是叙述性知识。塞进向量知识库只会变成过期快照 ——
 * 这正是本项目 README 里反复强调的坑（工单实时数据同理）。
 * 所以库房事实走**工具通道**，与工单统计（src/ttsource.js）同一套纪律：
 * 数字由脚本渲染，模型一个数字都不碰。
 *
 * ## 两条数据源
 *
 *   ① HTTP：my_app 的 /api/data（库房看板聚合）—— 生产库 PostgreSQL，实时；
 *   ② SQLite：node:sqlite 直读 my_app/db/app.db —— 同步副本，**有延迟**。
 *
 * 降级时**必须如实标注口径**（渲染层打「本地副本」那句），
 * 跟 ttsource.js 的做法一致 —— 同一个问题两条通道给出不同数字，
 * 是最难排查的一类故障。
 *
 * ## ⚠️ 库存口径陷阱（本模块最重要的一段）
 *
 * `inventory_details` 是**按日快照表**，不是当前库存表。
 * 每个 update_date 各存一份当日快照，全表累积 21 万行以上；
 * **只有 update_date = max(update_date) 的那一份才是当前库存**（约 2100 行）。
 *
 * 直接 SUM 全表会得到 90 万这种离谱数字（把所有历史快照加了一遍）。
 * my_app 的 backend/services/native_catalog.py:1952 用的是同一口径，
 * 两边若不一致，对账结果就会对不上。
 *
 * ## ⚠️ 列名有坑：单位列一会儿带空格一会儿不带
 *
 * `inventory_details` 的单位列叫 **`Unit `**（**带一个尾随空格**），
 * 而 `inband_details` / `outband_details` 的叫 **`Unit`**（没有空格）。
 * 两张表都是 Excel 直接导进来的，表头原样保留，连空格都保留下来了。
 *
 * 写 SQL 时必须分别照抄：inventory 用 `"Unit "`，明细表用 `"Unit"`。
 * 写成 `"Unit"` 查 inventory 会报 `no such column: "Unit "`，
 * 反之报 `no such column: "Unit"` —— 报错信息里那个空格是唯一的线索。
 */
import { existsSync } from 'node:fs';
import { resolve } from 'node:path';
import { CONFIG, ROOT } from './config.js';

/** HTTP 超时。库房聚合要扫全表，比单票查询慢；超时即降级，不重试。 */
const HTTP_TIMEOUT_MS = Number(process.env.WAREHOUSE_TIMEOUT_MS || 20000);

/** SQLite 降级超时。1.5GB 的库首次全表扫描实测要数秒。 */
const SQLITE_TIMEOUT_MS = Number(process.env.WAREHOUSE_SQLITE_TIMEOUT_MS || 30000);

/** 库房库路径。可用环境变量 MY_APP_DB 覆盖。 */
const DB_PATH = resolve(
  process.env.MY_APP_DB || resolve(ROOT, '..', 'my_app', 'db', 'app.db')
);

/**
 * 库房主单表前缀。SPIB=入库单，SPOB=出库单。
 *
 * ⚠️ 这里**不能**用 `\b` 界定：`\b` 是「单词边界」，
 * 而 `B` 与后面的数字**都是单词字符**，两者之间不存在边界 ——
 * 写成 `\b(SPIB|SPOB)\d{8,}\b` 实测只能匹配到 `SPIB` 就断了
 * （前缀被截断，票号全丢）。所以直接用「前缀 + 8 位以上数字」，
 * 尾部再用一个「非数字」来收口。
 */
const SP_TICKET_RE = /(SPIB|SPOB)\d{8,}(?!\d)/gi;

/* ------------------------------- HTTP 通道 ------------------------------- */

/** my_app 后端基址（去掉尾部斜杠）。 */
function apiBase() {
  const base = String(CONFIG.myAppApiBase || '').replace(/\/+$/, '');
  if (!base) throw new Error('未配置 myAppApiBase');
  return base;
}

/** 带超时地 fetch 一个 JSON 接口；失败一律抛，由调用方决定是否降级。 */
async function fetchJson(url) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), HTTP_TIMEOUT_MS);
  let res;
  try {
    res = await fetch(url, { signal: ctrl.signal });
  } catch (err) {
    if (err.name === 'AbortError') throw new Error(`HTTP 超时（${HTTP_TIMEOUT_MS}ms）`);
    throw new Error(`连不上 my_app：${err.cause?.code || err.message}`);
  } finally {
    clearTimeout(timer);
  }
  if (!res.ok) throw new Error(`my_app 返回 ${res.status}`);
  return res.json();
}

/* ------------------------------ SQLite 通道 ------------------------------ */

let sqliteModule;
let sqliteChecked = false;

/**
 * 懒加载 node:sqlite。
 *
 * Node 22+ 内置（node:sqlite），不需要装依赖 —— 本项目原则是不引新依赖。
 * 首次 import 会打 ExperimentalWarning，那只是警告，不影响功能。
 */
async function loadSqlite() {
  if (sqliteChecked) return sqliteModule;
  sqliteChecked = true;
  try {
    const mod = await import('node:sqlite');
    sqliteModule = mod.DatabaseSync;
  } catch {
    sqliteModule = null;
  }
  return sqliteModule;
}

/** 打开只读连接。immutable=1 避免在 1.5GB 库上建 -wal/-shm 旁路文件。 */
async function openDb() {
  const DatabaseSync = await loadSqlite();
  if (!DatabaseSync) throw new Error('当前 Node 不支持 node:sqlite');
  if (!existsSync(DB_PATH)) throw new Error(`找不到库房数据库：${DB_PATH}`);
  return new DatabaseSync(DB_PATH, { readOnly: true });
}

/** 把 node:sqlite 的行对象转成普通对象（它返回 null-prototype 对象）。 */
function plain(row) {
  return row ? { ...row } : row;
}

/* ------------------------------ 取数入口 ------------------------------ */

/**
 * 库房总览：各仓库存 + 入出库单据统计。
 *
 * @returns {Promise<{ok:boolean, source:'http'|'sqlite', data?:object, error?:string}>}
 */
export async function queryWarehouseOverview() {
  // ① HTTP（单据统计，实时）
  let httpData = null;
  let httpErr = null;
  try {
    const payload = await fetchJson(`${apiBase()}/api/data`);
    if (!payload?.status || !payload?.data) throw new Error('my_app 返回结构不符合预期');
    httpData = normalizeHttp(payload);
  } catch (err) {
    httpErr = err;
  }

  // ② 分仓库存**必须**走 SQLite —— my_app 的 /api/data 只有总量聚合，
  //    没有分仓明细。取不到就让库存一节为空，但单据统计仍可用。
  let inventory = [];
  let snapDate = '';
  try {
    const r = await inventoryFromSqlite();
    inventory = r.inventory;
    snapDate = r.snapshotDate;
  } catch {
    /* 库存取不到不阻断整体 */
  }

  if (httpData) {
    httpData.inventory = inventory;
    httpData.snapshotDate = snapDate;
    return { ok: true, source: 'http', data: httpData };
  }

  // HTTP 不可用 → SQLite 全量降级
  try {
    const data = await overviewFromSqlite();
    data.inventory = inventory;
    data.snapshotDate = snapDate;
    return { ok: true, source: 'sqlite', data, degradedReason: httpErr?.message };
  } catch (err2) {
    return {
      ok: false,
      error: `HTTP：${httpErr?.message || '未知错误'}；本地副本：${err2.message}`,
    };
  }
}

/**
 * 分仓当前库存（只取最新快照）。
 *
 * 口径关键：inventory_details 是按日快照表，
 * **只有 update_date = max(update_date) 的那一份才是当前库存**。
 */
async function inventoryFromSqlite() {
  const db = await openDb();
  try {
    const maxDate =
      plain(db.prepare('SELECT MAX(update_date) AS d FROM inventory_details').get())?.d || '';
    const rows = maxDate
      ? db
          .prepare(
            `SELECT "Warehouse Name" AS warehouse, COUNT(*) AS items,
                    COALESCE(SUM("Stock Qty"),0) AS qty
             FROM inventory_details WHERE update_date = ? GROUP BY 1 ORDER BY 3 DESC`
          )
          .all(maxDate)
          .map(plain)
      : [];
    return { inventory: rows, snapshotDate: maxDate };
  } finally {
    db.close();
  }
}

/**
 * 把 my_app 的 /api/data 响应整理成统一结构。
 *
 * ⚠️ 字段对不上的坑（2026-10-27 实测）：
 *   · my_app 返回的 `Inventory` 是**总量聚合**（{Total, Consumables_QTY, SpareParts_QTY}），
 *     **没有分仓明细** —— 分仓库存只存在于 SQLite 副本的 inventory_details。
 *   · `Inbound`/`Outbound` 数组的元素用**带空格的键名**（'Inbound Type'/'Inbound Qty'），
 *     不是驼峰键。
 *   · my_app 没有 'Warehouse' 键，不要凭空造。
 * 所以 HTTP 通道拿单据统计，**分仓库存一律走 SQLite**（inventoryFromSqlite）。
 */
function normalizeHttp(payload) {
  const d = payload.data || {};
  return {
    lastSync: d.Time?.[0]?.update_time || '',
    warehouses: [],
    inboundTickets: d['Inbound Ticket']?.[0] || { Total: 0, Closed: 0, Unclosed: 0 },
    outboundTickets: d['Outbound Ticket']?.[0] || { Total: 0, Closed: 0, Unclosed: 0 },
    inboundByType: (d.Inbound || []).map((r) => ({
      type: r['Inbound Type'],
      total: r.Total,
      qty: r['Inbound Qty'],
      closed: r.Closed,
      unclosed: r.Unclosed,
    })),
    outboundByType: (d.Outbound || []).map((r) => ({
      type: r['Outbound Type'],
      total: r.Total,
      qty: r['Stock Qty'],
      closed: r.Closed,
      unclosed: r.Unclosed,
    })),
    inventoryTotal: d.Inventory?.[0] || null,
    inventory: [],
    warehouseRows: [],
  };
}

/** SQLite 通道的库房总览（单据统计部分；分仓库存由 inventoryFromSqlite 负责）。 */
async function overviewFromSqlite() {
  const db = await openDb();
  try {
    const one = (sql, ...p) => plain(db.prepare(sql).get(...p));
    const all = (sql, ...p) => db.prepare(sql).all(...p).map(plain);

    const lastSync = one(
      'SELECT synced_at FROM sp_sync_log ORDER BY id DESC LIMIT 1'
    )?.synced_at || '';

    const ticketStat = (table) => {
      const r = one(
        `SELECT COUNT(*) AS total,
                SUM(CASE WHEN status LIKE 'Closed%' THEN 1 ELSE 0 END) AS closed
         FROM "${table}"`
      );
      return {
        Total: Number(r?.total || 0),
        Closed: Number(r?.closed || 0),
        Unclosed: Number(r?.total || 0) - Number(r?.closed || 0),
      };
    };

    const byType = (table, col, qtyCol) =>
      all(
        `SELECT "${col}" AS type, COUNT(*) AS total,
                COALESCE(SUM("${qtyCol}"), 0) AS qty
         FROM "${table}" GROUP BY 1 ORDER BY 2 DESC`
      );

    return {
      lastSync,
      snapshotDate: '',
      warehouses: [],
      inboundTickets: ticketStat('sp_inbound'),
      outboundTickets: ticketStat('sp_outbound'),
      inboundByType: byType('inband_details', 'Inbound Type', 'Inbound Qty'),
      outboundByType: byType('outband_details', 'Outbound Type', 'Outbound Qty'),
      inventory: [],
      inventoryTotal: null,
      warehouseRows: [],
    };
  } finally {
    db.close();
  }
}

/**
 * 按物料编码/名称查库存。
 *
 * @param {string} keyword 物料编码或名称关键字
 */
export async function queryWarehouseMaterial(keyword) {
  const kw = String(keyword || '').trim();
  if (!kw) return { ok: false, error: '没给物料编码或名称' };

  const db = await openDb();
  try {
    const like = `%${kw}%`;
    const rows = db
      .prepare(
        `SELECT "Material No." AS materialNo, "Material Name" AS materialName,
                "Material Type" AS materialType, "Warehouse Name" AS warehouse,
                COALESCE(SUM("Stock Qty"),0) AS qty, "Unit " AS unit,
                "Material Status" AS materialStatus
         FROM inventory_details
         WHERE update_date = (SELECT MAX(update_date) FROM inventory_details)
           AND ("Material No." LIKE ? OR "Material Name" LIKE ?)
         GROUP BY 1,2,3,4,6,7
         ORDER BY qty DESC
         LIMIT 30`
      )
      .all(like, like)
      .map(plain);

    const lastSync =
      plain(db.prepare('SELECT synced_at FROM sp_sync_log ORDER BY id DESC LIMIT 1').get())
        ?.synced_at || '';

    return { ok: true, source: 'sqlite', data: { rows, lastSync } };
  } catch (err) {
    return { ok: false, error: err.message };
  } finally {
    db.close();
  }
}

/**
 * 按单号查库房单据（入库单/出库单）。
 *
 * @param {string} ticketNo 单号，如 SPIB202610220006
 */
export async function queryWarehouseTicket(ticketNo) {
  const no = String(ticketNo || '').trim().toUpperCase();
  if (!no) return { ok: false, error: '没给单号' };

  const db = await openDb();
  try {
    const isInbound = no.startsWith('SPIB');
    const isOutbound = no.startsWith('SPOB');

    const ticket = isInbound
      ? plain(db.prepare('SELECT * FROM sp_inbound WHERE woNum = ? LIMIT 1').get(no))
      : isOutbound
        ? plain(db.prepare('SELECT * FROM sp_outbound WHERE woNum = ? LIMIT 1').get(no))
        : plain(
            db
              .prepare(
                'SELECT * FROM sp_inbound WHERE woNum = ? LIMIT 1'
              )
              .get(no)
          );

    if (!ticket) {
      // 出库单也可能是调拨单，再查一次 transfer_details
      const transfer = plain(
        db.prepare('SELECT * FROM transfer_details WHERE "Warehouse Transfer No." = ? LIMIT 1').get(no)
      );
      if (transfer) {
        return { ok: true, source: 'sqlite', data: { kind: 'transfer', ticket: transfer, lines: [] } };
      }
      return { ok: true, source: 'sqlite', data: { kind: 'none', ticket: null, lines: [] } };
    }

    const kind = isInbound ? 'inbound' : 'outbound';
    const lines = isInbound
      ? db
          .prepare(
            `SELECT "Material No." AS materialNo, "Material Name" AS materialName,
                    "Serial No." AS serialNo, "Inbound Qty" AS qty, "Unit" AS unit,
                    "Warehouse Name" AS warehouse, "Location Name" AS location,
                    "Scan Status" AS scanStatus
             FROM inband_details WHERE "Inbound No." = ? ORDER BY 3 LIMIT 40`
          )
          .all(no)
          .map(plain)
      : db
          .prepare(
            `SELECT "Material No." AS materialNo, "Material Name" AS materialName,
                    "Serial No." AS serialNo, "Outbound Qty" AS qty, "Unit" AS unit,
                    "Warehouse Name" AS warehouse, "Location Name" AS location,
                    "Recipient" AS recipient, "Related Ticket No." AS relatedTicket,
                    "Scan Status" AS scanStatus
             FROM outband_details WHERE "Outbound No." = ? ORDER BY 3 LIMIT 40`
          )
          .all(no)
          .map(plain);

    return { ok: true, source: 'sqlite', data: { kind, ticket, lines } };
  } catch (err) {
    return { ok: false, error: err.message };
  } finally {
    db.close();
  }
}

/** 从提问里抽库房单号（SPIB/SPOB 开头）。 */
export function extractSpTicketNos(q) {
  const s = String(q || '');
  const out = [];
  const re = new RegExp(SP_TICKET_RE.source, 'gi');
  let m;
  while ((m = re.exec(s))) {
    const v = m[0].toUpperCase();
    if (!out.includes(v)) out.push(v);
  }
  return out;
}

export { DB_PATH, HTTP_TIMEOUT_MS, SQLITE_TIMEOUT_MS };
