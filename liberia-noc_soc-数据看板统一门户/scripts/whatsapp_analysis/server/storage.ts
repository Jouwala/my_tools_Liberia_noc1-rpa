import { DatabaseSync } from "node:sqlite";
import { mkdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const DATA_DIR = path.join(ROOT, "data");
mkdirSync(DATA_DIR, { recursive: true });

const db = new DatabaseSync(path.join(DATA_DIR, "assistant.db"));

db.exec(`
  PRAGMA journal_mode = WAL;

  CREATE TABLE IF NOT EXISTS raw_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_key TEXT UNIQUE NOT NULL,
    group_name TEXT NOT NULL,
    sender TEXT,
    timestamp TEXT,
    text TEXT,
    is_from_me INTEGER DEFAULT 0,
    mentioned_me INTEGER DEFAULT 0,
    received_at TEXT NOT NULL
  );

  CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    merge_key TEXT,
    group_name TEXT,
    requester TEXT,
    site_name TEXT,
    site_id TEXT,
    issue TEXT,
    action_required TEXT,
    deadline TEXT,
    priority TEXT NOT NULL DEFAULT 'fyi' CHECK(priority IN ('urgent','followup','fyi')),
    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','done','dismissed')),
    source TEXT NOT NULL DEFAULT 'ai',
    raw_message_keys TEXT DEFAULT '[]',
    merged_into INTEGER REFERENCES tasks(id),
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
  );

  CREATE TABLE IF NOT EXISTS reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    report_date TEXT NOT NULL,
    markdown TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
  );

  CREATE TABLE IF NOT EXISTS attachments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    filename TEXT NOT NULL,
    mime TEXT NOT NULL DEFAULT 'application/octet-stream',
    size INTEGER NOT NULL DEFAULT 0,
    stored_name TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
  );
`);

try {
  db.exec(`ALTER TABLE tasks ADD COLUMN my_result TEXT DEFAULT ''`);
} catch {
  // 旧库已存在该列时忽略
}

// 固定输出格式新增列：MessageTime / TT_ID / Alarm_Name（旧库自动补列）
for (const ddl of [
  `ALTER TABLE tasks ADD COLUMN message_time TEXT DEFAULT ''`,
  `ALTER TABLE tasks ADD COLUMN tt_id TEXT DEFAULT ''`,
  `ALTER TABLE tasks ADD COLUMN alarm_name TEXT DEFAULT ''`,
]) {
  try {
    db.exec(ddl);
  } catch {
    // 列已存在时忽略
  }
}

export const ATTACH_DIR = path.join(DATA_DIR, "attachments");
mkdirSync(ATTACH_DIR, { recursive: true });

export interface RawMessage {
  group_name: string;
  sender: string;
  timestamp: string;
  text: string;
  is_from_me: boolean;
  mentioned_me: boolean;
}

export interface Task {
  id: number;
  merge_key: string | null;
  group_name: string | null;
  requester: string | null;
  message_time: string | null;
  site_name: string | null;
  site_id: string | null;
  tt_id: string | null;
  alarm_name: string | null;
  issue: string | null;
  action_required: string | null;
  deadline: string | null;
  priority: "urgent" | "followup" | "fyi";
  status: "pending" | "done" | "dismissed";
  source: string;
  raw_message_keys: string;
  merged_into: number | null;
  my_result: string;
  created_at: string;
  updated_at: string;
}

export function messageKey(groupName: string, m: { sender: string; timestamp: string; text: string }) {
  return `${groupName}|${m.sender}|${m.timestamp}|${(m.text || "").slice(0, 200)}`;
}

const insertMessageStmt = db.prepare(`
  INSERT OR IGNORE INTO raw_messages
    (message_key, group_name, sender, timestamp, text, is_from_me, mentioned_me, received_at)
  VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now','localtime'))
`);

export function storeRawMessages(groupName: string, messages: RawMessage[]) {
  for (const m of messages) {
    insertMessageStmt.run(
      messageKey(groupName, m),
      groupName,
      m.sender,
      m.timestamp,
      m.text,
      m.is_from_me ? 1 : 0,
      m.mentioned_me ? 1 : 0
    );
  }
}

const insertTaskStmt = db.prepare(`
  INSERT INTO tasks
    (merge_key, group_name, requester, message_time, site_name, site_id, tt_id, alarm_name, issue, action_required, deadline, priority, status, source, raw_message_keys)
  VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)
`);

const updateTaskStmt = db.prepare(`
  UPDATE tasks SET
    group_name = ?, requester = ?, message_time = ?, site_name = ?, site_id = ?, tt_id = ?, alarm_name = ?, issue = ?,
    action_required = ?, deadline = ?, priority = ?, raw_message_keys = ?,
    updated_at = datetime('now','localtime')
  WHERE id = ?
`);

export function findMergeTarget(mergeKey: string, groupName: string, windowHours: number) {
  if (!mergeKey) return undefined;
  const stmt = db.prepare(`
    SELECT * FROM tasks
    WHERE merge_key = ? AND group_name = ? AND status = 'pending' AND merged_into IS NULL
      AND datetime(created_at) >= datetime('now','localtime', ?)
    ORDER BY id DESC LIMIT 1
  `);
  return stmt.get(mergeKey, groupName, `-${windowHours} hours`) as Task | undefined;
}

export interface TaskInput {
  merge_key?: string | null;
  group_name?: string | null;
  requester?: string | null;
  message_time?: string | null;
  site_name?: string | null;
  site_id?: string | null;
  tt_id?: string | null;
  alarm_name?: string | null;
  issue?: string | null;
  action_required?: string | null;
  deadline?: string | null;
  priority: "urgent" | "followup" | "fyi";
  source: string;
  raw_message_keys: string[];
}

const PRIORITY_RANK = { fyi: 0, followup: 1, urgent: 2 } as const;

export function upsertTask(input: TaskInput, mergeWindowHours = 24): Task {
  const existing = input.merge_key
    ? findMergeTarget(input.merge_key, input.group_name || "", mergeWindowHours)
    : undefined;

  if (existing) {
    const keys: string[] = JSON.parse(existing.raw_message_keys || "[]");
    for (const k of input.raw_message_keys) if (!keys.includes(k)) keys.push(k);
    const actions = [existing.action_required, input.action_required]
      .filter(Boolean)
      .filter((v, i, arr) => arr.indexOf(v) === i);
    const merged = {
      ...existing,
      requester: existing.requester || input.requester,
      message_time: existing.message_time || input.message_time,
      site_name: existing.site_name || input.site_name,
      site_id: existing.site_id || input.site_id,
      tt_id: existing.tt_id || input.tt_id,
      alarm_name: existing.alarm_name || input.alarm_name,
      issue: existing.issue || input.issue,
      action_required: actions.join("；"),
      deadline:
        existing.deadline && input.deadline
          ? existing.deadline <= input.deadline
            ? existing.deadline
            : input.deadline
          : existing.deadline || input.deadline,
      priority:
        PRIORITY_RANK[input.priority] > PRIORITY_RANK[existing.priority]
          ? input.priority
          : existing.priority,
      raw_message_keys: JSON.stringify(keys),
    };
    updateTaskStmt.run(
      merged.group_name ?? null,
      merged.requester ?? null,
      merged.message_time ?? null,
      merged.site_name ?? null,
      merged.site_id ?? null,
      merged.tt_id ?? null,
      merged.alarm_name ?? null,
      merged.issue ?? null,
      merged.action_required ?? null,
      merged.deadline ?? null,
      merged.priority,
      merged.raw_message_keys,
      existing.id
    );
    return { ...merged, id: existing.id } as Task;
  }

  const res = insertTaskStmt.run(
    input.merge_key ?? null,
    input.group_name ?? null,
    input.requester ?? null,
    input.message_time ?? null,
    input.site_name ?? null,
    input.site_id ?? null,
    input.tt_id ?? null,
    input.alarm_name ?? null,
    input.issue ?? null,
    input.action_required ?? null,
    input.deadline ?? null,
    input.priority,
    input.source,
    JSON.stringify(input.raw_message_keys)
  );
  return getTask(Number(res.lastInsertRowid))!;
}

export function getTask(id: number) {
  return db.prepare("SELECT * FROM tasks WHERE id = ?").get(id) as Task | undefined;
}

export function listTasks(opts: { status?: string; since?: string; limit?: number } = {}) {
  const where: string[] = ["merged_into IS NULL"];
  const params: (string | number)[] = [];
  if (opts.status) {
    where.push("status = ?");
    params.push(opts.status);
  }
  if (opts.since) {
    where.push("datetime(created_at) >= datetime(?)");
    params.push(opts.since);
  }
  const limit = Math.min(opts.limit ?? 200, 1000);
  const stmt = db.prepare(
    `SELECT * FROM tasks WHERE ${where.join(" AND ")} ORDER BY
       CASE priority WHEN 'urgent' THEN 0 WHEN 'followup' THEN 1 ELSE 2 END,
       datetime(created_at) DESC
     LIMIT ?`
  );
  return stmt.all(...params, limit) as unknown as Task[];
}

export function setTaskStatus(id: number, status: "pending" | "done" | "dismissed") {
  db.prepare(
    "UPDATE tasks SET status = ?, updated_at = datetime('now','localtime') WHERE id = ?"
  ).run(status, id);
  return getTask(id);
}

export function saveReport(reportDate: string, markdown: string) {
  db.prepare("INSERT INTO reports (report_date, markdown) VALUES (?, ?)").run(
    reportDate,
    markdown
  );
}

export function latestReport() {
  return db.prepare(
    "SELECT * FROM reports ORDER BY datetime(created_at) DESC LIMIT 1"
  ).get() as { id: number; report_date: string; markdown: string; created_at: string } | undefined;
}

export function updateTaskResult(id: number, myResult: string) {
  db.prepare(
    "UPDATE tasks SET my_result = ?, updated_at = datetime('now','localtime') WHERE id = ?"
  ).run(myResult, id);
  return getTask(id);
}

export interface Attachment {
  id: number;
  task_id: number;
  filename: string;
  mime: string;
  size: number;
  stored_name: string;
  created_at: string;
}

export function addAttachment(
  taskId: number,
  filename: string,
  mime: string,
  size: number,
  storedName: string
) {
  const res = db.prepare(
    "INSERT INTO attachments (task_id, filename, mime, size, stored_name) VALUES (?, ?, ?, ?, ?)"
  ).run(taskId, filename, mime, size, storedName);
  return db.prepare("SELECT * FROM attachments WHERE id = ?").get(
    Number(res.lastInsertRowid)
  ) as unknown as Attachment;
}

export function listAttachments(taskId: number) {
  return db.prepare(
    "SELECT * FROM attachments WHERE task_id = ? ORDER BY id"
  ).all(taskId) as unknown as Attachment[];
}

export function getAttachment(id: number) {
  return db.prepare("SELECT * FROM attachments WHERE id = ?").get(id) as unknown as
    | Attachment
    | undefined;
}

export function deleteAttachment(id: number) {
  db.prepare("DELETE FROM attachments WHERE id = ?").run(id);
}
