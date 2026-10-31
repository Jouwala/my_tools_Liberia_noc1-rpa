// ============================================================================
// 门户鉴权数据的持久化层（server/authDb.ts）
// ----------------------------------------------------------------------------
// 目标：账号、密码哈希、以及每个账号的「看板权限（landing / allowedGroups /
// allowedCards）」必须落盘且不可静默丢失。
//
// 首选后端：SQLite（Node 内置模块 node:sqlite，零 npm 依赖）
//   · 文件：<dataDir>/portal-auth.db（<dataDir> 默认 <项目根>/auth-data）
//   · journal_mode=WAL + synchronous=FULL + busy_timeout=5000
//     → 每次写入在单个事务里提交，进程崩溃/断电不会写坏半个文件
//   · 自动滚动备份：<dataDir>/backups/portal-auth-<时间戳>.db，默认保留最近 30 份
//   · 首次启动自动从 users.json / requests.json 迁移，旧 JSON 改名为
//     users.json.imported-<时间戳> 保留，不删除、不留歧义（避免双份真相源）
//   · 数据库损坏时自动用最新备份恢复，坏文件改名 .corrupt-<时间戳> 留证
//
// 兜底后端：JSON（PORTAL_AUTH_BACKEND=json，或运行时没有 node:sqlite，Node < 22.5）
//   · 原子写（临时文件 + rename）
//   · 每次覆盖前先按时间戳复制一份快照到 backups/ 并轮转保留
//   · 修复原实现的致命行为：JSON 解析失败时会「当作空用户表 → 播种新 admin →
//     覆盖写回」，等于一次损坏就把所有账号清空。现在改为先把坏文件改名留证，
//     并尝试用最新备份恢复。
// ============================================================================

import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
// 直接指向 auth/types，不经 auth 的 barrel（index.ts）：
// store.ts → authDb.ts → auth/index.ts → store.ts 会构成循环依赖，
// 故持久化层只依赖纯类型文件（2026-09-25 鉴权模块拆分时修正）。
import type { RegistrationRequest, StoredUser } from './auth/types';
// sanitizeTeam 是**值**导入（不是纯类型）：读库时要把 team 列归一成合法团队 id。
// ⚠️ types.ts 只 import node:http 的类型、不 import 任何本项目的模块，
//   故这里不会构成循环依赖（循环的根因是经 auth/index.ts 绕回 store.ts）。
import { sanitizeTeam } from './auth/types';

const require_ = createRequire(import.meta.url);

/** 一次加载读到的全部数据；fresh=true 表示此前不存在任何已有数据文件 */
export interface AuthSnapshot {
  users: StoredUser[];
  requests: RegistrationRequest[];
  fresh: boolean;
}

export interface BackupEntry {
  name: string;
  size: number;
  mtime: string;
}

/** 供前端「用户管理」展示的存储位置信息 */
export interface StorageInfo {
  backend: 'sqlite' | 'json';
  location: string;
  /** 本次升级是否已从旧 JSON 迁移历史数据 */
  migratedFromJson: boolean;
  writeCount: number;
  lastWriteAt: string | null;
  backups: BackupEntry[];
  maxBackups: number;
  backupDir: string;
}

export interface AuthPersistence {
  readonly backend: 'sqlite' | 'json';
  readonly location: string;
  load(): AuthSnapshot;
  saveUsers(users: StoredUser[]): void;
  saveRequests(requests: RegistrationRequest[]): void;
  info(): StorageInfo;
}

// —— 可配置项（环境变量覆盖）——

const DB_FILE_NAME = 'portal-auth.db';
const USERS_FILE = 'users.json';
const REQUESTS_FILE = 'requests.json';
const BACKUP_DIR_NAME = 'backups';
const BACKUP_PREFIX = 'portal-auth-';
const MAX_BACKUPS = clampInt(process.env.PORTAL_AUTH_MAX_BACKUPS, 30, 1, 500);
/** 两次自动备份的最小间隔（毫秒），默认 6 小时 */
const BACKUP_MIN_INTERVAL_MS = 6 * 60 * 60 * 1000;
/** 距上次备份写满这么多次也强制备份一次，避免高频改动长时间无快照 */
const BACKUP_MAX_WRITES = 20;

function clampInt(raw: string | undefined, fallback: number, min: number, max: number): number {
  const n = Number.parseInt(String(raw ?? ''), 10);
  if (!Number.isFinite(n)) return fallback;
  return Math.min(max, Math.max(min, n));
}

/** 时间戳后缀：20260912-093015 */
function stamp(d: Date = new Date()): string {
  const p = (n: number) => String(n).padStart(2, '0');
  return (
    `${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}` +
    `-${p(d.getHours())}${p(d.getMinutes())}${p(d.getSeconds())}`
  );
}

function safeJson<T>(raw: string | null, fallback: T): T {
  if (!raw) return fallback;
  try {
    return JSON.parse(raw) as T;
  } catch {
    return fallback;
  }
}

/** 备份文件只认 <prefix><时间戳><ext> 这种格式，避免把用户的其它文件当快照删掉 */
function listBackups(dir: string, prefix: string, ext: string): { file: string; mtime: number }[] {
  if (!fs.existsSync(dir)) return [];
  const out: { file: string; mtime: number }[] = [];
  for (const name of fs.readdirSync(dir)) {
    if (!name.startsWith(prefix) || !name.endsWith(ext)) continue;
    try {
      out.push({ file: name, mtime: fs.statSync(path.join(dir, name)).mtimeMs });
    } catch {
      /* 读不到就跳过 */
    }
  }
  // 文件名里的时间戳本身可字典序排序，新→旧
  return out.sort((a, b) => (a.file < b.file ? 1 : a.file > b.file ? -1 : 0));
}

function rotateBackups(dir: string, prefix: string, ext: string, max: number): void {
  const all = listBackups(dir, prefix, ext);
  for (const item of all.slice(max)) {
    try {
      fs.rmSync(path.join(dir, item.file), { force: true });
    } catch {
      /* 删不掉不影响主流程 */
    }
  }
}

function readJsonArray<T>(file: string): { items: T[] | null; error: string | null } {
  if (!fs.existsSync(file)) return { items: null, error: null };
  try {
    const parsed = JSON.parse(fs.readFileSync(file, 'utf-8')) as unknown;
    if (!Array.isArray(parsed)) return { items: null, error: 'not an array' };
    return { items: parsed as T[], error: null };
  } catch (e) {
    return { items: null, error: String(e) };
  }
}

// ============================================================================
// SQLite 后端
// ============================================================================

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
  backup: (source: DatabaseSyncLike, destination: string) => Promise<number>;
}

/**
 * 对外的最小 SQLite 接口形状（只含 DatabaseSync）。
 * 供需要**单独开一条连接**的模块（如 teamScopeDb）复用同一套类型。
 */
export type SqliteModuleLike = { DatabaseSync: new (location: string) => DatabaseSyncLike };

interface UserRow {
  id: string;
  username: string;
  role: string;
  password_hash: string;
  must_change_password: number;
  created_at: string;
  landing: string | null;
  allowed_groups: string | null;
  allowed_cards: string | null;
  /** 团队归属（2026-10-29 加）：NULL = 未指派。老库可能没有这一列，读时按缺列处理。 */
  team?: string | null;
}

interface RequestRow {
  id: string;
  username: string;
  password_hash: string;
  note: string;
  status: string;
  created_at: string;
  ip: string;
  decided_at: string | null;
  decided_by: string | null;
}

const SCHEMA_STATEMENTS = [
  `CREATE TABLE IF NOT EXISTS users (
      id TEXT PRIMARY KEY,
      username TEXT NOT NULL UNIQUE,
      role TEXT NOT NULL,
      password_hash TEXT NOT NULL,
      must_change_password INTEGER NOT NULL DEFAULT 1,
      created_at TEXT NOT NULL,
      landing TEXT,
      allowed_groups TEXT,
      allowed_cards TEXT,
      team TEXT
    )`,
  `CREATE TABLE IF NOT EXISTS registration_requests (
      id TEXT PRIMARY KEY,
      username TEXT NOT NULL,
      password_hash TEXT NOT NULL,
      note TEXT NOT NULL DEFAULT '',
      status TEXT NOT NULL,
      created_at TEXT NOT NULL,
      ip TEXT NOT NULL DEFAULT '',
      decided_at TEXT,
      decided_by TEXT
    )`,
  `CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)`,
];

class SqlitePersistence implements AuthPersistence {
  readonly backend = 'sqlite' as const;
  readonly location: string;
  private db: DatabaseSyncLike;
  private readonly backupDir: string;
  private migratedFromJson = false;
  private writeCount = 0;
  private lastWriteAt: string | null = null;
  private lastBackupAt = 0;
  private writesSinceBackup = 0;
  private backupInFlight = false;

  constructor(
    private readonly sqliteModule: SqliteModule,
    private readonly dbFile: string,
    dataDir: string,
    private readonly fresh: boolean
  ) {
    this.location = dbFile;
    this.backupDir = path.join(dataDir, BACKUP_DIR_NAME);
    fs.mkdirSync(dataDir, { recursive: true });
    fs.mkdirSync(this.backupDir, { recursive: true });
    this.db = this.openWithRecovery();
    this.execStatements(SCHEMA_STATEMENTS);
    this.migrateSchema();
  }

  /**
   * 补齐后加的列（2026-10-29：users.team —— 账号归属团队）。
   *
   * 为什么不能只靠 CREATE TABLE IF NOT EXISTS：
   *   那条语句对**已存在的表**是空操作。本机 auth-data/portal-auth.db 早在
   *   2026-09 就建好了，users 表里没有 team 列 —— 只改 SCHEMA_STATEMENTS
   *   的话，新库有 team、老库没有，于是 saveUsers 的 INSERT 会因
   *   "table users has no column named team" 而整批写入失败，
   *   症状是「改了团队归属，保存后刷新又变回去」，且**只在老库上复现**。
   *
   * 做法：查 PRAGMA table_info(users)，缺哪列补哪列（ADD COLUMN 是幂等的，
   *   重复执行不报错 —— 故这里可以放心每次启动都跑一遍）。
   * ⚠️ SQLite 的 ALTER TABLE ADD COLUMN 不支持带默认值以外的约束，
   *   所以这里只加可空列、不加 NOT NULL（历史行自然是 NULL = 未指派）。
   */
  private migrateSchema(): void {
    const columns = this.db.prepare('PRAGMA table_info(users)').all() as unknown as {
      name: string;
    }[];
    const names = new Set(columns.map((c) => c.name));
    if (!names.has('team')) {
      try {
        this.db.exec('ALTER TABLE users ADD COLUMN team TEXT');
        console.warn('[auth-db] 已为 users 表补加 team 列（团队归属，2026-10-29）');
      } catch (e) {
        console.error('[auth-db] 补加 users.team 列失败：', e);
      }
    }
  }

  // —— 打开 / 损坏恢复 ——

  private connect(): DatabaseSyncLike {
    let db: DatabaseSyncLike | null = null;
    try {
      db = new this.sqliteModule.DatabaseSync(this.dbFile);
      db.exec('PRAGMA journal_mode = WAL');
      db.exec('PRAGMA synchronous = FULL');
      db.exec('PRAGMA busy_timeout = 5000');
      return db;
    } catch (e) {
      // Windows 上不关句柄的话，后面给坏文件改名会因占用而失败（EBUSY），证据就留不下来
      if (db) {
        try {
          db.close();
        } catch {
          /* 关不掉也继续走恢复流程 */
        }
      }
      throw e;
    }
  }

  /** 打开失败或库损坏 → 用最新备份顶上；坏文件改名留证 */
  private openWithRecovery(): DatabaseSyncLike {
    try {
      const db = this.connect();
      db.exec('SELECT count(*) FROM sqlite_master'); // 探活
      return db;
    } catch (e) {
      console.error('[auth-db] 打开数据库失败，尝试从备份恢复：', e);
    }
    const brokenMarker = `${this.dbFile}.corrupt-${stamp()}`;
    try {
      if (fs.existsSync(this.dbFile)) fs.renameSync(this.dbFile, brokenMarker);
      for (const suffix of ['-wal', '-shm']) {
        const side = `${this.dbFile}${suffix}`;
        if (fs.existsSync(side)) fs.rmSync(side, { force: true });
      }
    } catch (e) {
      console.error('[auth-db] 隔离损坏数据库失败：', e);
    }
    const latest = listBackups(this.backupDir, BACKUP_PREFIX, '.db')[0];
    if (latest) {
      try {
        fs.copyFileSync(path.join(this.backupDir, latest.file), this.dbFile);
        console.warn(`[auth-db] 已从备份 ${latest.file} 恢复账号数据`);
      } catch (e) {
        console.error('[auth-db] 恢复备份失败：', e);
      }
    } else {
      console.warn('[auth-db] 没有可用备份，将重建空数据库（旧文件已保留为 .corrupt-*）');
    }
    return this.connect();
  }

  private execStatements(statements: string[]): void {
    for (const sql of statements) this.db.exec(sql);
  }

  // —— 读写 ——

  load(): AuthSnapshot {
    const userRows = this.db
      .prepare('SELECT * FROM users ORDER BY created_at, username')
      .all() as unknown as UserRow[];
    const requestRows = this.db
      .prepare('SELECT * FROM registration_requests ORDER BY created_at')
      .all() as unknown as RequestRow[];

    const users: StoredUser[] = userRows.map((row) => {
      const user: StoredUser = {
        id: row.id,
        username: row.username,
        role: (row.role === 'admin' ? 'admin' : 'viewer') as StoredUser['role'],
        passwordHash: row.password_hash,
        mustChangePassword: row.must_change_password !== 0,
        createdAt: row.created_at,
      };
      // landing：列为空字符串/NULL → 字段不出现，与老 JSON 语义一致
      if (row.landing) user.landing = safeJson(row.landing, undefined as never) ?? undefined;
      // allowedGroups/allowedCards：NULL = 不限制，'[]' = 一条都不给看（语义必须区分）
      if (row.allowed_groups !== null) user.allowedGroups = safeJson<string[]>(row.allowed_groups, []);
      if (row.allowed_cards !== null) user.allowedCards = safeJson<string[]>(row.allowed_cards, []);
      // team：NULL/空 = 未指派；认不得的值一律当成未指派（脏数据不该把人塞进某个团队）
      const team = sanitizeTeam(row.team);
      if (team) user.team = team;
      return user;
    });

    const requests: RegistrationRequest[] = requestRows.map((row) => {
      const record: RegistrationRequest = {
        id: row.id,
        username: row.username,
        passwordHash: row.password_hash,
        note: row.note || '',
        status: (['pending', 'approved', 'rejected'].includes(row.status)
          ? row.status
          : 'pending') as RegistrationRequest['status'],
        createdAt: row.created_at,
        ip: row.ip || '',
      };
      if (row.decided_at) record.decidedAt = row.decided_at;
      if (row.decided_by) record.decidedBy = row.decided_by;
      return record;
    });

    return { users, requests, fresh: this.fresh };
  }

  saveUsers(users: StoredUser[]): void {
    this.transact(() => {
      const upsert = this.db.prepare(
        `INSERT INTO users (id, username, role, password_hash, must_change_password, created_at, landing, allowed_groups, allowed_cards, team)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
         ON CONFLICT(id) DO UPDATE SET
           username = excluded.username,
           role = excluded.role,
           password_hash = excluded.password_hash,
           must_change_password = excluded.must_change_password,
           created_at = excluded.created_at,
           landing = excluded.landing,
           allowed_groups = excluded.allowed_groups,
           allowed_cards = excluded.allowed_cards,
           team = excluded.team`
      );
      const keep = new Set<string>();
      for (const u of users) {
        keep.add(u.id);
        upsert.run(
          u.id,
          u.username,
          u.role,
          u.passwordHash,
          u.mustChangePassword ? 1 : 0,
          u.createdAt,
          u.landing ? JSON.stringify(u.landing) : null,
          Array.isArray(u.allowedGroups) ? JSON.stringify(u.allowedGroups) : null,
          Array.isArray(u.allowedCards) ? JSON.stringify(u.allowedCards) : null,
          // team：存的是团队 id；未指派存 NULL（= 不限制跳转）
          u.team ?? null
        );
      }
      const del = this.db.prepare('DELETE FROM users WHERE id = ?');
      const existing = this.db.prepare('SELECT id FROM users').all() as unknown as { id: string }[];
      for (const row of existing) {
        if (!keep.has(row.id)) del.run(row.id);
      }
    });
    this.afterWrite();
  }

  saveRequests(requests: RegistrationRequest[]): void {
    this.transact(() => {
      const upsert = this.db.prepare(
        `INSERT INTO registration_requests (id, username, password_hash, note, status, created_at, ip, decided_at, decided_by)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
         ON CONFLICT(id) DO UPDATE SET
           username = excluded.username,
           password_hash = excluded.password_hash,
           note = excluded.note,
           status = excluded.status,
           created_at = excluded.created_at,
           ip = excluded.ip,
           decided_at = excluded.decided_at,
           decided_by = excluded.decided_by`
      );
      const keep = new Set<string>();
      for (const r of requests) {
        keep.add(r.id);
        upsert.run(
          r.id,
          r.username,
          r.passwordHash,
          r.note,
          r.status,
          r.createdAt,
          r.ip,
          r.decidedAt ?? null,
          r.decidedBy ?? null
        );
      }
      const del = this.db.prepare('DELETE FROM registration_requests WHERE id = ?');
      const existing = this.db
        .prepare('SELECT id FROM registration_requests')
        .all() as unknown as { id: string }[];
      for (const row of existing) {
        if (!keep.has(row.id)) del.run(row.id);
      }
    });
    this.afterWrite();
  }

  /** 单事务执行；失败回滚并把错误抛给调用方（调用方负责打印，绝不静默吞掉） */
  private transact(body: () => void): void {
    this.db.exec('BEGIN IMMEDIATE');
    try {
      body();
      this.db.exec('COMMIT');
      // 立刻把 WAL 合并回主库文件：保证 portal-auth.db 本身就是完整数据，
      // 单独拷走这一个文件（而不是连同 -wal）也能拿到全部已提交数据。
      try {
        this.db.exec('PRAGMA wal_checkpoint(TRUNCATE)');
      } catch {
        /* 有其它连接在读时 checkpoint 会失败，数据仍在 WAL 里，下次打开照样读得到 */
      }
    } catch (e) {
      try {
        this.db.exec('ROLLBACK');
      } catch {
        /* 回滚失败无补救 */
      }
      throw e;
    }
  }

  private afterWrite(): void {
    this.writeCount += 1;
    this.writesSinceBackup += 1;
    this.lastWriteAt = new Date().toISOString();
    const due =
      this.lastBackupAt === 0 ||
      Date.now() - this.lastBackupAt > BACKUP_MIN_INTERVAL_MS ||
      this.writesSinceBackup >= BACKUP_MAX_WRITES;
    if (due) {
      this.lastBackupAt = Date.now();
      this.writesSinceBackup = 0;
      // 延后一小拍再备份：同一批写入（比如一次请求里连改好几个账号）只快照一次，
      // 而且快照落在所有写入提交之后，不会拿到半成品状态。
      const timer = setTimeout(() => {
        this.runBackup();
      }, 50);
      timer.unref?.();
    }
  }

  /** 在线热备份（SQLite backup API），失败只记日志不影响写库主流程 */
  private runBackup(): void {
    // 同一时刻只跑一个备份任务，避免短时间写爆备份目录
    if (this.backupInFlight) return;
    this.backupInFlight = true;
    const dest = path.join(this.backupDir, `${BACKUP_PREFIX}${stamp()}.db`);
    try {
      const result = this.sqliteModule.backup(this.db, dest);
      void Promise.resolve(result)
        .then(() => {
          rotateBackups(this.backupDir, BACKUP_PREFIX, '.db', MAX_BACKUPS);
        })
        .catch((e) => console.error('[auth-db] 备份失败：', e))
        .finally(() => {
          this.backupInFlight = false;
        });
    } catch (e) {
      this.backupInFlight = false;
      console.error('[auth-db] 备份失败：', e);
    }
  }

  // runBackup 需要拿到 sqlite 模块的 backup 函数（构造函数注入，字段声明见顶部）

  /** 全新库（此前没有 db 文件）→ 从旧 JSON 一次性迁移 */
  migrateFromJson(usersFile: string, requestsFile: string): boolean {
    let migrated = false;
    for (const [file, kind] of [
      [usersFile, 'users'],
      [requestsFile, 'requests'],
    ] as const) {
      const { items, error } = readJsonArray(file) as {
        items: (StoredUser | RegistrationRequest)[] | null;
        error: string | null;
      };
      if (items === null) {
        if (error) {
          console.error(`[auth-db] ${file} 无法解析，已跳过迁移（原文件保留）：${error}`);
        }
        continue;
      }
      if (items.length === 0) continue;
      try {
        if (kind === 'users') this.saveUsers(items as StoredUser[]);
        else this.saveRequests(items as RegistrationRequest[]);
        migrated = true;
      } catch (e) {
        console.error(`[auth-db] 迁移 ${file} 失败：`, e);
        continue;
      }
      // 旧文件改名保留：避免和数据库形成两个真相源，也便于需要时人工回滚
      try {
        fs.renameSync(file, `${file}.imported-${stamp()}`);
      } catch (e) {
        console.error(`[auth-db] ${file} 迁移后改名失败（请手工处理，避免重复导入）：`, e);
      }
    }
    if (migrated) this.setMeta('migrated_from_json', new Date().toISOString());
    return migrated;
  }

  private setMeta(key: string, value: string): void {
    this.db
      .prepare('INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value')
      .run(key, value);
  }

  info(): StorageInfo {
    const backups = listBackups(this.backupDir, BACKUP_PREFIX, '.db').map((item) => {
      const stat = fs.statSync(path.join(this.backupDir, item.file));
      return { name: item.file, size: stat.size, mtime: new Date(stat.mtimeMs).toISOString() };
    });
    const metaRow = this.db.prepare("SELECT value FROM meta WHERE key = 'migrated_from_json'").all() as unknown as {
      value: string;
    }[];
    return {
      backend: 'sqlite',
      location: this.location,
      migratedFromJson: metaRow.length > 0,
      writeCount: this.writeCount,
      lastWriteAt: this.lastWriteAt,
      backups,
      maxBackups: MAX_BACKUPS,
      backupDir: this.backupDir,
    };
  }
}

// ============================================================================
// JSON 兜底后端（无 node:sqlite 时使用；行为与旧实现兼容，但不再丢数据）
// ============================================================================

class JsonPersistence implements AuthPersistence {
  readonly backend = 'json' as const;
  readonly location: string;
  private readonly backupDir: string;
  private writeCount = 0;
  private lastWriteAt: string | null = null;
  private migratedFromJson = false;

  constructor(
    private readonly dataDir: string,
    private readonly usersFile: string,
    private readonly requestsFile: string
  ) {
    this.location = usersFile;
    this.backupDir = path.join(dataDir, BACKUP_DIR_NAME);
    fs.mkdirSync(dataDir, { recursive: true });
    fs.mkdirSync(this.backupDir, { recursive: true });
  }

  load(): AuthSnapshot {
    const users = this.readUsers();
    const requests = this.readRequests();
    const fresh = !fs.existsSync(this.usersFile) && !fs.existsSync(this.requestsFile);
    return { users, requests, fresh };
  }

  private readUsers(): StoredUser[] {
    const { items, error } = readJsonArray<StoredUser>(this.usersFile);
    if (items) return items;
    if (error) {
      this.quarantine(this.usersFile, error);
      return this.restoreLatest<StoredUser>('users') ?? [];
    }
    return [];
  }

  private readRequests(): RegistrationRequest[] {
    const { items, error } = readJsonArray<RegistrationRequest>(this.requestsFile);
    if (items) return items;
    if (error) {
      this.quarantine(this.requestsFile, error);
      return this.restoreLatest<RegistrationRequest>('requests') ?? [];
    }
    return [];
  }

  /** 坏文件改名留证 + 尝试从备份恢复（旧实现是「当空表处理 → 播种 admin → 覆盖」，会丢号） */
  private quarantine(file: string, reason: string): void {
    const marker = `${file}.corrupt-${stamp()}`;
    console.error(`[auth-db] ${file} 解析失败（${reason}），已隔离为 ${path.basename(marker)}，正在尝试用备份恢复`);
    try {
      fs.renameSync(file, marker);
    } catch (e) {
      console.error('[auth-db] 隔离失败：', e);
    }
  }

  private restoreLatest<T>(kind: 'users' | 'requests'): T[] | null {
    const prefix = `${kind}-json-`;
    const latest = listBackups(this.backupDir, prefix, '.json')[0];
    if (!latest) return null;
    try {
      const parsed = JSON.parse(fs.readFileSync(path.join(this.backupDir, latest.file), 'utf-8'));
      if (!Array.isArray(parsed)) return null;
      console.warn(`[auth-db] 已从备份 ${latest.file} 恢复 ${kind}`);
      this.migratedFromJson = true;
      const target = kind === 'users' ? this.usersFile : this.requestsFile;
      fs.writeFileSync(target, JSON.stringify(parsed, null, 2), 'utf-8');
      return parsed as T[];
    } catch (e) {
      console.error('[auth-db] 备份恢复失败：', e);
      return null;
    }
  }

  /** 原子写：先留快照备份，再写临时文件 + rename */
  private write(file: string, rows: unknown[], kind: 'users' | 'requests'): void {
    try {
      if (fs.existsSync(file)) {
        try {
          fs.copyFileSync(file, path.join(this.backupDir, `${kind}-json-${stamp()}.json`));
          rotateBackups(this.backupDir, `${kind}-json-`, '.json', MAX_BACKUPS);
        } catch (e) {
          console.error('[auth-db] 写入前快照失败（不阻断写入）：', e);
        }
      }
      const tmp = `${file}.tmp`;
      fs.writeFileSync(tmp, JSON.stringify(rows, null, 2), 'utf-8');
      fs.renameSync(tmp, file);
      this.writeCount += 1;
      this.lastWriteAt = new Date().toISOString();
    } catch (e) {
      console.error(`[auth-db] 写入 ${file} 失败：`, e);
      throw e;
    }
  }

  saveUsers(users: StoredUser[]): void {
    this.write(this.usersFile, users, 'users');
  }

  saveRequests(requests: RegistrationRequest[]): void {
    this.write(this.requestsFile, requests, 'requests');
  }

  info(): StorageInfo {
    const backups = [
      ...listBackups(this.backupDir, 'users-json-', '.json'),
      ...listBackups(this.backupDir, 'requests-json-', '.json'),
    ].map((item) => {
      const stat = fs.statSync(path.join(this.backupDir, item.file));
      return { name: item.file, size: stat.size, mtime: new Date(stat.mtimeMs).toISOString() };
    });
    return {
      backend: 'json',
      location: this.location,
      migratedFromJson: this.migratedFromJson,
      writeCount: this.writeCount,
      lastWriteAt: this.lastWriteAt,
      backups,
      maxBackups: MAX_BACKUPS * 2,
      backupDir: this.backupDir,
    };
  }
}

// ============================================================================
// 工厂：选后端 + 首次迁移
// ============================================================================

function tryRequireSqlite(): SqliteModule | null {
  try {
    const mod = require_('node:sqlite') as SqliteModule;
    return typeof mod?.DatabaseSync === 'function' ? mod : null;
  } catch {
    return null;
  }
}

/**
 * 创建持久化实例。
 * 全新数据目录（既没有 db 也没有 JSON）→ fresh=true，此时 AuthStore 才会播种初始 admin；
 * 已有 users.json 但没有 db → 自动迁移后 JSON 改名归档。
 */
export function createAuthPersistence(dataDir: string): AuthPersistence {
  fs.mkdirSync(dataDir, { recursive: true });
  const dbFile = path.join(dataDir, DB_FILE_NAME);
  const usersFile = path.join(dataDir, USERS_FILE);
  const requestsFile = path.join(dataDir, REQUESTS_FILE);
  const forced = (process.env.PORTAL_AUTH_BACKEND || '').trim().toLowerCase();

  const sqlite = forced === 'json' ? null : tryRequireSqlite();
  if (!sqlite) {
    if (forced === 'json') {
      console.warn('[auth-db] PORTAL_AUTH_BACKEND=json：按配置使用 JSON 文件存储账号数据');
    } else {
      console.warn('[auth-db] 当前 Node 不支持内置 node:sqlite（需 >= 22.5），回退到 JSON 文件存储');
    }
    return new JsonPersistence(dataDir, usersFile, requestsFile);
  }

  try {
    const dbExistedBefore = fs.existsSync(dbFile);
    const persistence = new SqlitePersistence(sqlite, dbFile, dataDir, !dbExistedBefore);
    if (!dbExistedBefore) {
      const migrated = persistence.migrateFromJson(usersFile, requestsFile);
      if (migrated) {
        console.warn(`[auth-db] 已把历史 users.json / requests.json 迁入 ${DB_FILE_NAME}`);
      }
    }
    return persistence;
  } catch (e) {
    console.error('[auth-db] SQLite 初始化失败，回退到 JSON 文件存储：', e);
    return new JsonPersistence(dataDir, usersFile, requestsFile);
  }
}
