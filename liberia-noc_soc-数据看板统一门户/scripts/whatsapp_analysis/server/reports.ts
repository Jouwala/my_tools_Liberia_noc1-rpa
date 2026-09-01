import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { listTasks, saveReport, type Task } from "./storage";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const REPORTS_DIR = path.join(ROOT, "reports");

const PRIORITY_HEAD: Record<string, string> = {
  urgent: "🔴 HIGH PRIORITY",
  followup: "🟡 FOLLOW UP / WAITING",
  fyi: "🟢 FYI",
};

// 固定输出格式：9 个字段、顺序不变；未找到的照常输出标签、值留空
function fmtTask(t: Task, idx: number): string {
  const f = (v: string | null | undefined) => String(v ?? "").trim();
  return [
    `${idx}. Requester: ${f(t.requester)}`,
    `   MessageTime: ${f(t.message_time)}`,
    `   SiteID: ${f(t.site_id)}`,
    `   SiteName: ${f(t.site_name)}`,
    `   TT_ID: ${f(t.tt_id)}`,
    `   Alarm_Name: ${f(t.alarm_name)}`,
    `   Group: ${f(t.group_name)}`,
    `   Issue: ${f(t.issue)}`,
    `   Deadline: ${f(t.deadline)}`,
  ].join("\n");
}

function section(priority: string, tasks: Task[]): string {
  if (!tasks.length) return "";
  const body = tasks.map((t, i) => fmtTask(t, i + 1)).join("\n\n");
  return `### ${PRIORITY_HEAD[priority]} (${tasks.length})\n\n${body}\n\n`;
}

export function generateDailyReport(): { report_date: string; markdown: string } {
  mkdirSync(REPORTS_DIR, { recursive: true });

  // 过去 24 小时新增或被更新的任务（不含已被合并走的）
  const since = new Date(Date.now() - 24 * 3600 * 1000).toISOString();
  const tasks = listTasks({ since });
  const byPriority = (p: string) => tasks.filter((t) => t.priority === p);

  const urgent = byPriority("urgent");
  const followup = byPriority("followup");
  const fyi = byPriority("fyi");
  const pendingCount = tasks.filter((t) => t.status === "pending").length;

  const today = new Date().toISOString().slice(0, 10);
  const parts: string[] = [];
  parts.push(`# 📋 WhatsApp Daily Action Report\n`);
  parts.push(`**日期**: ${today}\n`);
  parts.push(`**@我的待办**: ${tasks.length} 项（待处理 ${pendingCount}）\n`);
  parts.push(`---\n`);

  if (!tasks.length) {
    parts.push(`\n过去 24 小时没有 @我 的待办事项。\n`);
  } else {
    parts.push(section("urgent", urgent));
    parts.push(section("followup", followup));
    parts.push(section("fyi", fyi));
  }

  parts.push(`### 📊 Summary\n`);
  parts.push(`- 总事项: ${tasks.length}`);
  parts.push(`- 高优先级: ${urgent.length}`);
  parts.push(`- 待跟进: ${followup.length}`);
  parts.push(`- FYI: ${fyi.length}\n`);

  const markdown = parts.filter(Boolean).join("\n");
  saveReport(today, markdown);

  const filePath = path.join(REPORTS_DIR, `${today}.md`);
  writeFileSync(filePath, markdown, "utf-8");
  console.log(`[report] written: ${filePath}`);

  return { report_date: today, markdown };
}
