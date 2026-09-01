// AI 分析输入输出结构
export interface ContextMessage {
  id?: string;
  sender: string;
  timestamp: string;
  text: string;
  isFromMe?: boolean;
}

// 随消息片段附带的聊天截图（扩展端已降采样为 JPEG base64）
export interface ContextImage {
  mime: string;
  dataBase64: string;
}

export interface MentionContext {
  mentionIndex: number;
  messages: ContextMessage[];
  images?: ContextImage[];
}

export interface ConversationScan {
  groupName: string;
  messageCount: number;
  mentionContexts: MentionContext[];
  allMessages?: ContextMessage[];
}

export interface ScanResult {
  selfName: string;
  mode: string;
  scannedAt: string;
  conversations: ConversationScan[];
  diagnostics?: Record<string, unknown>;
}

// 固定输出字段（顺序即展示顺序，全部必填、找不到填空字符串）：
// Requester / MessageTime / SiteID / SiteName / TT_ID / Alarm_Name / Issue / Deadline
// Group 不由 AI 提供：服务器端已知群名，直接回填，避免 AI 抄错。
export interface AiTask {
  requester?: string;
  message_time?: string;
  site_id?: string;
  site_name?: string;
  tt_id?: string;
  alarm_name?: string;
  issue?: string;
  action?: string;
  deadline?: string;
  priority: "urgent" | "followup" | "fyi";
  block?: string; // 任务来自哪个片段（如 "片段 2"），用于服务端归属
}

export interface AiAnalysis {
  tasks: AiTask[];
  summary?: string;
}

export interface AIAdapter {
  readonly name: string;
  readonly configured: boolean;
  analyze(systemPrompt: string, userPrompt: string, images?: ContextImage[]): Promise<AiAnalysis>;
}
