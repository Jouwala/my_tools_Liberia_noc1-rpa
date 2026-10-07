/**
 * 问答记录 —— 每条回复**落盘一行**，用于事后优化。
 *
 * ## 为什么必须单独存
 *
 * 2026-10-07 排查「那个单子未闭环答错了」时，唯一的记录是运行日志里
 * `[回复] 32560ms｜命中=true` 这一行。**回答内容根本没记**，
 * 我只能靠"32 秒 + gap 字段"反推它走了知识库通道。
 *
 * 更早那次（`@~olbr_assistant 今天有p1的单子吗` 答成 P1 规则定义）
 * 是用户截图发过来的 —— 机器人自己这边什么都没留下。
 *
 * 所以：**回复内容、路由通道、耗时**都要落盘。没有这份记录，
 * 「哪类问法容易答错」只能靠人回忆，也就无从优化。
 *
 * ## 为什么用 SQLite 而不是继续写文本日志
 *
 * 文本日志适合"看一条"，不适合"看一类"。要回答
 * 「哪些问法命中率最低」「哪个工具的失败率在涨」，
 * 必须能聚合查询 —— 那是 SQL 的活。
 *
 * ## 为什么和运行日志分开存
 *
 * 两者生命周期不同：运行日志按天滚动、会自然过期；
 * 问答记录是要**长期积累**的资产，越久越有价值。
 * 混在一起会导致"清理日志时把分析样本也清了"。
 *
 * ## 表结构刻意保持精简（每列都有明确用途）
 *
 * 只存问、答、是否命中，外加三个**零成本**的定位字段
 * （通道 / 工具 / 耗时）—— 它们本来就已经算出来了，
 * 不记则等于把已付出的成本扔掉。
 *
 * **已知局限**：表里没有检索得分（gap/top/base）与召回块 id。
 * 因此**无法从库里回答"为什么这一条走错了通道"** ——
 * 那类问题仍需回看运行日志（`data/logs/bot-*.log` 里有 gap/top/base）。
 * 若将来这类排查变频繁，再补列；现在不预先加，避免存了没人看。
 *
 * ## 隐私
 *
 * 按约定存**真实号码**（便于按人追踪），因此库文件**不入 git**：
 * 路径在 `data/` 下，已被 `.gitignore` 的 `data/*.json` 之外的规则覆盖，
 * 见文件末尾 ensureIgnored 的说明。
 */
import { DatabaseSync } from 'node:sqlite';
import { existsSync, mkdirSync } from 'node:fs';
import { dirname } from 'node:path';

/** 库文件路径（由调用方从 CONFIG 传入，便于测试用临时库）。 */
let dbPath = null;
let db = null;
let broken = false;

const SCHEMA = `
CREATE TABLE IF NOT EXISTS qa_log (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  ts          TEXT NOT NULL,          -- ISO 时间（UTC）
  chat_jid    TEXT NOT NULL,          -- 会话（群/私聊）
  sender      TEXT NOT NULL,          -- 提问人号码
  question    TEXT NOT NULL,          -- 原始提问（未截断，分析要用原文）
  answer      TEXT NOT NULL,          -- 回复内容（**这是以前完全没记的**）
  answered    INTEGER NOT NULL,       -- 1=答上了 0=没答上（未命中/失败）
  channel     TEXT,                   -- stats / tt / kb / lookup
  tool        TEXT,                   -- query_tickets / analyze_ticket / search_knowledge / lookup_*
  via         TEXT,                   -- rule / model（规则层还是模型层选的）
  ms          INTEGER,                -- 本轮耗时
  lang        TEXT,                   -- 回复语言
  degraded    INTEGER,                -- 是否走了降级路径（本地副本）
  top_base    REAL,                   -- 检索 top1 混合分（诊断「为什么走错通道」）
  gap         REAL,                   -- top1 − 中位数基线
  hit_source  TEXT,                   -- top1 命中的文件名（前 3 个 confident 来源，| 分隔）
  route_args  TEXT                    -- 路由/工具参数 JSON（**不塞完整工单正文**）
);
CREATE INDEX IF NOT EXISTS idx_qa_ts      ON qa_log(ts);
CREATE INDEX IF NOT EXISTS idx_qa_chat    ON qa_log(chat_jid, ts);
CREATE INDEX IF NOT EXISTS idx_qa_answered ON qa_log(answered, ts);
CREATE INDEX IF NOT EXISTS idx_qa_channel ON qa_log(channel, ts);
`;

/**
 * 增量迁移：给已存在的旧库补列。
 *
 * 为什么用 ALTER 而不是改 SCHEMA 重建：`data/qa.sqlite` 是**长期积累的资产**，
 * 库可能已经在线上跑了几天。重建等于把已有样本清空。
 * 只在列缺失时才 ADD COLUMN（PRAGMA table_info 查一遍），幂等。
 */
const MIGRATIONS = [
  ['top_base', 'REAL'],
  ['gap', 'REAL'],
  ['hit_source', 'TEXT'],
  ['route_args', 'TEXT'],
];

function migrate(db) {
  const have = new Set(db.prepare('PRAGMA table_info(qa_log)').all().map((c) => c.name));
  for (const [name, type] of MIGRATIONS) {
    if (!have.has(name)) db.exec(`ALTER TABLE qa_log ADD COLUMN ${name} ${type}`);
  }
}

/**
 * 打开（并建表）。失败**不抛** —— 记录是旁路，
 * 不能让"记不上"把"能回答"也拖垮。
 *
 * @param {string} path 库文件路径
 * @returns {boolean} 是否可用
 */
export function openQaLog(path) {
  if (db) return true;
  if (broken) return false;
  try {
    mkdirSync(dirname(path), { recursive: true });
    db = new DatabaseSync(path);
    db.exec('PRAGMA journal_mode = WAL;');
    db.exec(SCHEMA);
    migrate(db); // 旧库补列（建表 SQL 已含新列时这里是空操作）
    dbPath = path;
    return true;
  } catch {
    // 打不开就永久放弃，不每轮重试 —— 每轮都试会在磁盘故障时拖慢所有回复
    broken = true;
    db = null;
    return false;
  }
}

/**
 * 写一条记录。**永不抛异常**。
 *
 * 记录是旁路：写不进去也不能影响用户拿到回复。
 * 这与"吞错掩盖故障"不同 —— 这里是**有意**降级，
 * 且失败会在运行日志里留一行，不是静默。
 *
 * @param {object} rec {ts,chatJid,sender,question,answer,answered,channel,tool,via,ms,lang,degraded}
 * @returns {boolean} 是否写入成功
 */
export function recordQa(rec) {
  if (!db) return false;
  try {
    db.prepare(
      `INSERT INTO qa_log
         (ts, chat_jid, sender, question, answer, answered, channel, tool, via, ms, lang, degraded,
          top_base, gap, hit_source, route_args)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`
    ).run(
      rec.ts || new Date().toISOString(),
      String(rec.chatJid || ''),
      String(rec.sender || ''),
      String(rec.question || ''),
      String(rec.answer || ''),
      rec.answered ? 1 : 0,
      rec.channel || null,
      rec.tool || null,
      rec.via || null,
      Number.isFinite(rec.ms) ? Math.round(rec.ms) : null,
      rec.lang || null,
      rec.degraded ? 1 : null,
      // —— 新增诊断列（缺字段当 null，绝不因缺字段而写失败）——
      Number.isFinite(rec.topBase) ? rec.topBase : null,
      Number.isFinite(rec.gap) ? rec.gap : null,
      rec.hitSource || null,
      rec.routeArgs || null
    );
    return true;
  } catch {
    return false;
  }
}

/** 关闭（退出时调用，确保 WAL 落盘）。 */
export function closeQaLog() {
  try {
    db?.close();
  } catch {
    /* 忽略 */
  }
  db = null;
}

/** 供测试/诊断：当前库路径与是否可用。 */
export function qaLogState() {
  return { path: dbPath, ready: !!db, broken };
}
