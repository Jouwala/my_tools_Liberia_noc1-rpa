// ============================================================================
// 团队门户可见性矩阵的持久化层（server/teamScopeDb.ts）
// ----------------------------------------------------------------------------
// 需求：管理员能在门户界面上直接勾选「哪个团队能看到哪些内容」，
// 勾选结果**必须落盘**，且门户运行时读到的就是它（而不是编译期写死的那份）。
//
// 为什么需要这一层（2026-10-30 加）
// ------------------------------
// 此前矩阵的唯一来源是 `v3/team_portal/scope-map.json` —— 一个**仓库里的静态文件**。
// 改一次矩阵要走「改 JSON → 跑脚本 → 生成 team-matrix.js → 提交」，
// 而且**必须改到服务器的文件系统上**才能生效（nginx 直接发静态文件）。
// 于是：
//   · 管理员（非开发者）改不了；
//   · 生产机上改了文件，但下次谁跑一次生成脚本就把手改覆盖掉；
//   · 「谁在什么时候改了哪个团队的可见范围」无迹可查。
//
// 现在改成：**数据库是运行时的真相源**，scope-map.json 退化为**仓库里的默认模板**。
//   · 运行时：门户向 /api/auth/team-scope 拿矩阵（该端点读数据库）；
//   · 管理界面：管理员勾选 → POST /api/auth/team-scope → 落库；
//   · 首次启动：数据库为空时，从 scope-map.json 播种一份默认矩阵；
//   · 静态文件 team-matrix.js 保留为**离线兜底**（数据库不可用时用），
//     但它不再是运行时的首选真相源。
//
// 存储位置：与账号数据同一个 SQLite 库（<dataDir>/portal-auth.db）的
//   team_scope 表 —— 同库便于一起备份/恢复，不会出现「账号在一个库、矩阵在另一个库」。
//
// 失败策略：**fail-open 到静态兜底，但绝不 fail-open 到「全显」**。
//   矩阵取不到时，team-scope.js 的 ok() 对所有域返回 false（什么都不显示），
//   这一点由 team-scope.js 的实现保证 —— 详见那里的注释。
// ============================================================================

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import type { TeamId } from './auth/types';

/** 域键 → 子键 → 团队 id 列表 */
export type TeamScopeMatrix = Record<string, Record<string, TeamId[]>>;

/** 一份可编辑的矩阵：矩阵 + 目录（域/项的中英文名，供界面显示） */
export interface TeamScopeDoc {
  matrix: TeamScopeMatrix;
  /** 域的展示信息（key / zh / en） */
  domains: { key: string; zh: string; en: string }[];
  /** 每个域下的项（key / zh / en） */
  items: Record<string, { key: string; zh: string; en: string }[]>;
}

// ---------------------------------------------------------------------------
// scope-map.json 的读取（默认模板）
// ---------------------------------------------------------------------------

/** 团队门户的 scope-map.json 所在目录（v3/team_portal/） */
function scopeMapCandidates(): string[] {
  // ⚠️ 用 fileURLToPath 而不是 import.meta.url.pathname ——
  //   后者在 Windows 上是 "/D:/01_RPA/..."，前导斜杠会让 path.resolve 把盘符
  //   当成相对路径的一部分，结果落到 "D:\D:\01_RPA\..."，文件永远读不到。
  const here = path.dirname(fileURLToPath(import.meta.url));
  const root = path.resolve(here, '..');
  return [
    path.resolve(root, 'v3', 'team_portal', 'scope-map.json'),
    // 生产构建（dist/）里的相对路径
    path.resolve(root, '..', 'v3', 'team_portal', 'scope-map.json'),
  ];
}

interface ScopeMapFile {
  teams?: { id: string; zh?: string; en?: string }[];
  domains?: { key: string; zh?: string; en?: string; items?: { key: string; zh?: string; en?: string }[] }[];
  extra_domains?: {
    key: string;
    zh?: string;
    en?: string;
    items?: { key: string; zh?: string; en?: string }[];
  }[];
  matrix?: Record<string, Record<string, string[]>>;
}

/**
 * 读取 scope-map.json（默认模板）。
 * 找不到 / 解析失败 → 返回 null（调用方据此决定回落策略，**不静默当成空矩阵**）。
 */
export function readScopeMapTemplate(): TeamScopeDoc | null {
  for (const file of scopeMapCandidates()) {
    try {
      if (!fs.existsSync(file)) continue;
      const raw = fs.readFileSync(file, 'utf-8');
      const data = JSON.parse(raw) as ScopeMapFile;
      const domains = [...(data.domains ?? []), ...(data.extra_domains ?? [])];
      const items: TeamScopeDoc['items'] = {};
      const domainMeta: TeamScopeDoc['domains'] = [];
      for (const d of domains) {
        domainMeta.push({ key: d.key, zh: d.zh ?? d.key, en: d.en ?? d.key });
        items[d.key] = (d.items ?? []).map((i) => ({
          key: i.key,
          zh: i.zh ?? i.key,
          en: i.en ?? i.key,
        }));
      }
      const matrix: TeamScopeMatrix = {};
      for (const [dk, subs] of Object.entries(data.matrix ?? {})) {
        matrix[dk] = {};
        for (const [sk, teams] of Object.entries(subs ?? {})) {
          matrix[dk][sk] = (teams ?? []).filter((t): t is TeamId =>
            typeof t === 'string'
          );
        }
      }
      return { matrix, domains: domainMeta, items };
    } catch (e) {
      console.error('[team-scope-db] 读取 scope-map.json 失败：', e);
      return null;
    }
  }
  console.warn('[team-scope-db] 找不到 scope-map.json（默认模板）');
  return null;
}

// ---------------------------------------------------------------------------
// 矩阵清洗（写库前必须过）
// ---------------------------------------------------------------------------

/**
 * 把外部输入（管理员在界面上的勾选）清洗成合法矩阵。
 *
 * 规则：
 *   · 域键 / 子键必须存在于 scope-map.json 的目录里 —— 认不得的一律丢弃；
 *   · 团队 id 必须在白名单里；
 *   · 去掉重复；
 *   · 子键勾选为空 = 不显示（保留空数组，不删键）——
 *     删键与空数组在运行时等价，但保留空数组能让界面回显「这一项是显式取消的」。
 */
export function sanitizeMatrix(
  input: unknown,
  template: TeamScopeDoc | null
): TeamScopeMatrix {
  const out: TeamScopeMatrix = {};
  if (!input || typeof input !== 'object' || Array.isArray(input)) return out;
  /* ⚠️ **没有模板就什么都不放行**（fail-closed）。
     模板的作用是「认得出哪些域/项是合法的」。模板读不到时若照单全收，
     就会把任意域键/项键写进库 —— 而运行时只按已知键过滤，
     那些垃圾键永远不生效，却会让「我明明勾了却没生效」变成查不出原因的问题。
     宁可这一次保存失败（管理员会看到报错并去修 scope-map.json），
     也不要写进一份「看着存下来了、实际不生效」的矩阵。 */
  if (!template) return out;
  const src = input as Record<string, unknown>;
  const validTeams = new Set(['fo', 'bo', 'flm', 'smc', 'cxo']);
  for (const [domKey, subsRaw] of Object.entries(src)) {
    if (!subsRaw || typeof subsRaw !== 'object' || Array.isArray(subsRaw)) continue;
    if (!template.items[domKey]) continue;
    const subs = subsRaw as Record<string, unknown>;
    const domOut: Record<string, TeamId[]> = {};
    for (const [subKey, teamsRaw] of Object.entries(subs)) {
      if (!template.items[domKey].some((i) => i.key === subKey)) continue;
      const teams: TeamId[] = [];
      if (Array.isArray(teamsRaw)) {
        for (const t of teamsRaw) {
          const v = String(t);
          if (validTeams.has(v) && !teams.includes(v as TeamId)) teams.push(v as TeamId);
        }
      }
      domOut[subKey] = teams;
    }
    out[domKey] = domOut;
  }
  return out;
}

/** 矩阵是否为空（空 = 数据库里还没有播种过） */
export function isMatrixEmpty(matrix: TeamScopeMatrix): boolean {
  return Object.values(matrix).every((subs) => Object.values(subs).every((t) => t.length === 0));
}

// ---------------------------------------------------------------------------
// SQLite 存取
// ---------------------------------------------------------------------------

interface StatementLike {
  run(...params: (string | number | bigint | null)[]): { changes: number | bigint };
  all(...params: (string | number | bigint | null)[]): unknown[];
}

interface DatabaseSyncLike {
  exec(sql: string): void;
  prepare(sql: string): StatementLike;
  close(): void;
}

interface SqliteModule {
  DatabaseSync: new (location: string) => DatabaseSyncLike;
}

/**
 * 矩阵在数据库里的存取。
 *
 * ⚠️ 为什么不复用 authDb.ts 的连接：
 *   authDb 有自己的备份/恢复/JSON 兜底逻辑，它把数据库**实例**封在自己的类里，
 *   不对外暴露连接句柄。本模块要独立地「能连上同一个库」，
 *   与其去撬 authDb 的私有字段，不如自己开一个连接 ——
 *   SQLite 支持多连接（同进程同文件），WAL 模式下并发读写没问题。
 *   代价是两条 WAL 连接，故这里开 busy_timeout。
 */
export class TeamScopeStore {
  private db: DatabaseSyncLike | null = null;
  private readonly dbFile: string;
  private template: TeamScopeDoc | null = null;
  private templateLoaded = false;

  constructor(
    private readonly sqliteModule: SqliteModule | null,
    dbFile: string
  ) {
    this.dbFile = dbFile;
  }

  private connect(): DatabaseSyncLike | null {
    if (!this.sqliteModule) return null;
    try {
      const db = new this.sqliteModule.DatabaseSync(this.dbFile);
      db.exec('PRAGMA journal_mode = WAL');
      db.exec('PRAGMA busy_timeout = 5000');
      db.exec(`CREATE TABLE IF NOT EXISTS team_scope (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        matrix TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        updated_by TEXT
      )`);
      return db;
    } catch (e) {
      console.error('[team-scope-db] 打开数据库失败：', e);
      return null;
    }
  }

  private getDb(): DatabaseSyncLike | null {
    if (!this.db) this.db = this.connect();
    return this.db;
  }

  /** 默认模板（scope-map.json），缓存一次。 */
  getTemplate(): TeamScopeDoc | null {
    if (!this.templateLoaded) {
      this.template = readScopeMapTemplate();
      this.templateLoaded = true;
    }
    return this.template;
  }

  /** 读当前矩阵；库里没有就用 scope-map.json 播种一份。 */
  load(): TeamScopeMatrix {
    const template = this.getTemplate();
    const db = this.getDb();
    if (!db) {
      // 没有 SQLite（如 Node < 22.5）：退回到静态模板。
      // ⚠️ 此时矩阵**不可编辑**（存不住），但运行时的可见性仍然正确 ——
      //   团队门户读的是静态 team-matrix.js，那份由 scope-map.json 生成。
      console.warn('[team-scope-db] 无 SQLite，矩阵回落为静态模板（不可编辑）');
      return template?.matrix ?? {};
    }
    try {
      const rows = db.prepare('SELECT matrix FROM team_scope WHERE id = 1').all() as unknown as {
        matrix: string;
      }[];
      if (rows.length && rows[0].matrix) {
        const parsed = JSON.parse(rows[0].matrix) as TeamScopeMatrix;
        return parsed;
      }
    } catch (e) {
      console.error('[team-scope-db] 读取矩阵失败：', e);
    }
    // 库里没有 → 用模板播种（第一次启动）
    if (template) {
      this.save(template.matrix, 'system');
      console.log('[team-scope-db] 已用 scope-map.json 播种团队可见性矩阵');
    }
    return template?.matrix ?? {};
  }

  /** 写矩阵（管理员改动后调用）。 */
  save(matrix: TeamScopeMatrix, byUsername: string): boolean {
    const db = this.getDb();
    if (!db) {
      console.error('[team-scope-db] 无 SQLite，无法保存矩阵');
      return false;
    }
    try {
      db.exec('BEGIN IMMEDIATE');
      try {
        db.prepare(
          `INSERT INTO team_scope (id, matrix, updated_at, updated_by)
           VALUES (1, ?, ?, ?)
           ON CONFLICT(id) DO UPDATE SET
             matrix = excluded.matrix,
             updated_at = excluded.updated_at,
             updated_by = excluded.updated_by`
        ).run(JSON.stringify(matrix), new Date().toISOString(), byUsername);
        db.exec('COMMIT');
        return true;
      } catch (e) {
        try {
          db.exec('ROLLBACK');
        } catch {
          /* 回滚失败无补救 */
        }
        throw e;
      }
    } catch (e) {
      console.error('[team-scope-db] 保存矩阵失败：', e);
      return false;
    }
  }

  /** 最后一次修改的时间与操作人（管理界面显示）。 */
  info(): { updatedAt: string | null; updatedBy: string | null; editable: boolean } {
    const db = this.getDb();
    if (!db) return { updatedAt: null, updatedBy: null, editable: false };
    try {
      const rows = db
        .prepare('SELECT updated_at, updated_by FROM team_scope WHERE id = 1')
        .all() as unknown as { updated_at: string; updated_by: string | null }[];
      if (!rows.length) return { updatedAt: null, updatedBy: null, editable: true };
      return {
        updatedAt: rows[0].updated_at ?? null,
        updatedBy: rows[0].updated_by ?? null,
        editable: true,
      };
    } catch (e) {
      console.error('[team-scope-db] 读取矩阵元信息失败：', e);
      return { updatedAt: null, updatedBy: null, editable: false };
    }
  }
}
