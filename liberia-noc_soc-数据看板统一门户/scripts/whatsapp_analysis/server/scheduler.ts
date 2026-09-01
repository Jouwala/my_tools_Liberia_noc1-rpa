import cron from "node-cron";

export function startScheduler(generate: () => unknown) {
  const expr = process.env.REPORT_CRON || "0 8 * * *";
  if (!cron.validate(expr)) {
    console.warn(`[scheduler] invalid REPORT_CRON "${expr}", fallback to "0 8 * * *"`);
  }
  const valid = cron.validate(expr) ? expr : "0 8 * * *";
  cron.schedule(valid, () => {
    console.log(`[scheduler] generating daily report at ${new Date().toLocaleString()}`);
    try {
      generate();
    } catch (e) {
      console.error("[scheduler] report generation failed:", e);
    }
  });
  console.log(`[scheduler] daily report scheduled: "${valid}"`);
}
