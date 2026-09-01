import type { AIAdapter, AiAnalysis, ContextImage } from "./types";

function extractJson(text: string): AiAnalysis {
  const cleaned = text.replace(/```(?:json)?/gi, "").trim();
  const start = cleaned.indexOf("{");
  const end = cleaned.lastIndexOf("}");
  if (start === -1 || end === -1) throw new Error("AI 响应中未找到 JSON");
  const parsed = JSON.parse(cleaned.slice(start, end + 1));
  const tasks = Array.isArray(parsed.tasks) ? parsed.tasks : [];
  return {
    tasks: tasks
      .filter((t: unknown) => t && typeof t === "object")
      .map((t: Record<string, unknown>) => ({
        requester: str(t.requester),
        message_time: str(t.message_time),
        site_id: str(t.site_id),
        site_name: str(t.site_name),
        tt_id: str(t.tt_id),
        alarm_name: str(t.alarm_name),
        issue: str(t.issue),
        action: str(t.action),
        deadline: str(t.deadline),
        block: str(t.block),
        priority:
          t.priority === "urgent" || t.priority === "followup"
            ? (t.priority as "urgent" | "followup")
            : "fyi",
      })),
    summary: str(parsed.summary),
  };
}

function str(v: unknown): string {
  return typeof v === "string" ? v.trim() : v == null ? "" : String(v);
}

// 图片请求失败（模型不支持视觉 / 图片被拒）时的降级开关：
// 有图失败 → 自动去图重试一次，保证分析链路不断
const dataUrl = (img: ContextImage) => `data:${img.mime || "image/jpeg"};base64,${img.dataBase64}`;

class OpenAICompatibleAdapter implements AIAdapter {
  readonly name = "openai-compatible";
  private baseUrl: string;
  private apiKey: string;
  private model: string;

  constructor() {
    this.baseUrl = (process.env.AI_BASE_URL || "").replace(/\/+$/, "");
    this.apiKey = process.env.AI_API_KEY || "";
    this.model = process.env.AI_MODEL || "gpt-4o-mini";
  }

  get configured() {
    return !!this.baseUrl && !!this.apiKey;
  }

  private requestBody(systemPrompt: string, userPrompt: string, images: ContextImage[]) {
    const userContent = images.length
      ? [
          { type: "text", text: userPrompt },
          ...images.map((img) => ({
            type: "image_url",
            image_url: { url: dataUrl(img) },
          })),
        ]
      : userPrompt;
    return {
      model: this.model,
      temperature: 0.2,
      messages: [
        { role: "system", content: systemPrompt },
        { role: "user", content: userContent },
      ],
    };
  }

  async analyze(systemPrompt: string, userPrompt: string, images: ContextImage[] = []): Promise<AiAnalysis> {
    const call = async (imgs: ContextImage[]) => {
      const res = await fetch(`${this.baseUrl}/chat/completions`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${this.apiKey}`,
        },
        signal: AbortSignal.timeout(120_000),
        body: JSON.stringify(this.requestBody(systemPrompt, userPrompt, imgs)),
      });
      if (!res.ok) {
        throw new Error(`OpenAI 兼容接口错误 ${res.status}: ${(await res.text()).slice(0, 300)}`);
      }
      const data = (await res.json()) as {
        choices?: { message?: { content?: string } }[];
      };
      return extractJson(data.choices?.[0]?.message?.content || "");
    };

    if (!images.length) return await call([]);
    try {
      return await call(images);
    } catch (e) {
      console.warn(
        `[ai] 带图请求失败（${e instanceof Error ? e.message : e}），改用纯文本重试`
      );
      return await call([]);
    }
  }
}

class GeminiAdapter implements AIAdapter {
  readonly name = "gemini";
  private apiKey: string;
  private model: string;

  constructor() {
    this.apiKey = process.env.AI_API_KEY || process.env.GEMINI_API_KEY || "";
    this.model = process.env.GEMINI_MODEL || "gemini-2.0-flash";
  }

  get configured() {
    return !!this.apiKey;
  }

  async analyze(systemPrompt: string, userPrompt: string, images: ContextImage[] = []): Promise<AiAnalysis> {
    const url = `https://generativelanguage.googleapis.com/v1beta/models/${this.model}:generateContent`;
    const call = async (imgs: ContextImage[]) => {
      const res = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json", "x-goog-api-key": this.apiKey },
        body: JSON.stringify({
          systemInstruction: { parts: [{ text: systemPrompt }] },
          contents: [
            {
              role: "user",
              parts: [
                { text: userPrompt },
                ...imgs.map((img) => ({
                  inline_data: { mime_type: img.mime || "image/jpeg", data: img.dataBase64 },
                })),
              ],
            },
          ],
          generationConfig: { temperature: 0.2 },
        }),
      });
      if (!res.ok) {
        throw new Error(`Gemini 接口错误 ${res.status}: ${(await res.text()).slice(0, 300)}`);
      }
      const data = (await res.json()) as {
        candidates?: { content?: { parts?: { text?: string }[] } }[];
      };
      const text = (data.candidates?.[0]?.content?.parts || [])
        .map((p) => p.text || "")
        .join("");
      return extractJson(text);
    };

    if (!images.length) return await call([]);
    try {
      return await call(images);
    } catch (e) {
      console.warn(
        `[ai] 带图请求失败（${e instanceof Error ? e.message : e}），改用纯文本重试`
      );
      return await call([]);
    }
  }
}

export function createAdapter(): AIAdapter {
  const type = (process.env.AI_API_TYPE || "").toLowerCase();
  if (type === "gemini") return new GeminiAdapter();
  return new OpenAICompatibleAdapter();
}
