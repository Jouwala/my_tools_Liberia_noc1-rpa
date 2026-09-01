// 手动触发一次报告生成：npm run report
import "dotenv/config";
import { generateDailyReport } from "./reports";

const { markdown } = generateDailyReport();
console.log("\n" + markdown);
