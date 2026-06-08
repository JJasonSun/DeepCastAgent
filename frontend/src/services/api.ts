const baseURL =
  import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

export interface ResearchRequest {
  topic: string;
  llm_model_id?: "deepseek-v4-flash" | "deepseek-v4-pro";
  llm_reasoning_effort?: "high" | "max";
}

export type HealthStatus = "ok" | "warning" | "error";

export interface HealthCheckItem {
  id: "backend" | "llm" | "tts" | "search" | "ffmpeg" | "audio_output";
  label: string;
  status: HealthStatus;
  message: string;
}

export interface HealthCheckResponse {
  status: HealthStatus;
  blocking: boolean;
  checks: HealthCheckItem[];
}

export type ResearchStreamEvent =
  | { type: "status"; message?: string }
  | { type: "log"; message?: string }
  | { type: "heartbeat"; message?: string }
  | { type: "client_retry"; attempt: number; max_retries: number; message: string }
  | { type: "error"; detail?: string; message?: string }
  | { type: "stage_change"; stage: "report" | "script" | "audio" | "synthesis"; message?: string }
  | { type: "todo_list"; tasks: unknown[]; step?: number; is_refine?: boolean; round?: number }
  | { type: "task_status"; task_id: number; status: "in_progress" | "completed" | "failed" | "skipped"; title?: string; intent?: string; query?: string; detail?: string }
  | { type: "search_query"; task_id?: number; query: string; title?: string }
  | { type: "sources"; task_id?: number; result_count?: number; latest_sources?: string; raw_context?: string; backend?: string }
  | { type: "task_summary_chunk"; task_id?: number; content: string; note_id?: string; step?: number }
  | { type: "task_findings"; task_id?: number; title?: string; findings: string[] }
  | { type: "refine_round"; round: number; max_rounds: number; message?: string }
  | { type: "refine_saturation"; round?: number; reason?: string; message?: string }
  | { type: "report_refine"; phase: "critique" | "result"; round?: number; max_rounds?: number; score?: number; verdict?: string; issue_count?: number; message?: string }
  | { type: "report_note"; note_id: string; title?: string; note_path?: string; content?: string }
  | { type: "tool_call"; event_id?: number; agent?: string; tool?: string; parameters?: unknown; result?: string; task_id?: number; note_id?: string; note_path?: string }
  | { type: "podcast_blueprint"; blueprint?: unknown; section_count?: number }
  | { type: "final_report"; report: string; note_id?: string; note_path?: string }
  | { type: "podcast_script"; script?: unknown; turns?: number }
  | { type: "audio_start"; total?: number; message?: string }
  | { type: "audio_progress"; current: number; total: number; role?: string; preview?: string; message?: string }
  | { type: "audio_generated"; files?: string[]; count?: number }
  | { type: "podcast_ready"; file: string }
  | { type: "cancelled"; message?: string }
  | { type: "done" };

export interface StreamOptions {
  signal?: AbortSignal;
  maxConnectRetries?: number;
  connectRetryDelayMs?: number;
  idleTimeoutMs?: number;
}

const RETRYABLE_HTTP_STATUS = new Set([408, 409, 425, 429, 500, 502, 503, 504]);

function sleep(ms: number): Promise<void> {
  return new Promise(resolve => window.setTimeout(resolve, ms));
}

function isAbortError(error: unknown): boolean {
  return (
    (error instanceof DOMException && error.name === "AbortError") ||
    (error instanceof Error && error.name === "AbortError")
  );
}

function shouldRetryConnection(error: unknown): boolean {
  if (isAbortError(error)) return false;
  if (error instanceof TypeError) return true;
  if (error instanceof Error) {
    const status = Number((error as Error & { status?: number }).status);
    if (RETRYABLE_HTTP_STATUS.has(status)) return true;
  }
  return false;
}

async function readWithIdleTimeout(
  reader: ReadableStreamDefaultReader<Uint8Array>,
  timeoutMs: number
): Promise<ReadableStreamReadResult<Uint8Array>> {
  let timer: ReturnType<typeof window.setTimeout> | null = null;
  try {
    return await Promise.race([
      reader.read(),
      new Promise<never>((_, reject) => {
        timer = window.setTimeout(() => {
          reject(new Error(`长时间未收到后端进度事件（超过 ${Math.round(timeoutMs / 1000)} 秒）`));
        }, timeoutMs);
      })
    ]);
  } finally {
    if (timer !== null) {
      window.clearTimeout(timer);
    }
  }
}

/**
 * 主动取消后端正在执行的研究任务。
 */
export async function cancelResearch(): Promise<void> {
  try {
    await fetch(`${baseURL}/research/cancel`, { method: "POST" });
  } catch (err) {
    console.warn("Failed to send cancel request:", err);
  }
}

export async function getHealthCheck(): Promise<HealthCheckResponse> {
  const response = await fetch(`${baseURL}/api/health`, {
    headers: {
      Accept: "application/json"
    }
  });

  if (!response.ok) {
    throw new Error(`健康检查失败，状态码：${response.status}`);
  }

  return response.json() as Promise<HealthCheckResponse>;
}

export async function runResearchStream(
  payload: ResearchRequest,
  onEvent: (event: ResearchStreamEvent) => void,
  options: StreamOptions = {}
): Promise<void> {
  const maxConnectRetries = options.maxConnectRetries ?? 2;
  const connectRetryDelayMs = options.connectRetryDelayMs ?? 1200;
  const idleTimeoutMs = options.idleTimeoutMs ?? 180000;

  let response: Response | null = null;
  let lastError: unknown = null;

  for (let attempt = 0; attempt <= maxConnectRetries; attempt++) {
    try {
      response = await fetch(`${baseURL}/research/stream`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Accept: "text/event-stream"
        },
        body: JSON.stringify(payload),
        signal: options.signal
      });

      if (!response.ok) {
        const errorText = await response.text().catch(() => "");
        const error = new Error(errorText || `研究请求失败，状态码：${response.status}`) as Error & { status?: number };
        error.status = response.status;
        throw error;
      }

      break;
    } catch (error) {
      lastError = error;
      if (attempt >= maxConnectRetries || !shouldRetryConnection(error)) {
        throw error;
      }
      const nextAttempt = attempt + 1;
      onEvent({
        type: "client_retry",
        attempt: nextAttempt,
        max_retries: maxConnectRetries,
        message: `连接后端失败，正在重试 ${nextAttempt}/${maxConnectRetries}`
      });
      await sleep(connectRetryDelayMs * nextAttempt);
    }
  }

  if (!response) {
    throw lastError instanceof Error ? lastError : new Error("无法连接后端研究服务");
  }

  const body = response.body;
  if (!body) {
    throw new Error("浏览器不支持流式响应，无法获取研究进度");
  }

  const reader = body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";
  let reachedTerminalEvent = false;

  try {
    while (true) {
      const { value, done } = await readWithIdleTimeout(reader, idleTimeoutMs);
      buffer += decoder.decode(value || new Uint8Array(), { stream: !done });

      let boundary = buffer.indexOf("\n\n");
      while (boundary !== -1) {
        const rawEvent = buffer.slice(0, boundary).trim();
        buffer = buffer.slice(boundary + 2);

        if (rawEvent.startsWith("data:")) {
          const dataPayload = rawEvent.slice(5).trim();
          if (dataPayload) {
            try {
              const event = JSON.parse(dataPayload) as ResearchStreamEvent;
              onEvent(event);

              if (event.type === "error" || event.type === "done") {
                reachedTerminalEvent = true;
                return;
              }
            } catch (error) {
              console.error("解析流式事件失败：", error, dataPayload);
            }
          }
        }

        boundary = buffer.indexOf("\n\n");
      }

      if (done) {
        // 处理可能的尾巴事件
        if (buffer.trim()) {
          const rawEvent = buffer.trim();
          if (rawEvent.startsWith("data:")) {
            const dataPayload = rawEvent.slice(5).trim();
            if (dataPayload) {
              try {
                const event = JSON.parse(dataPayload) as ResearchStreamEvent;
                onEvent(event);
                if (event.type === "error" || event.type === "done") {
                  reachedTerminalEvent = true;
                }
              } catch (error) {
                console.error("解析流式事件失败：", error, dataPayload);
              }
            }
          }
        }
        break;
      }
    }
  } catch (error) {
    await reader.cancel().catch(() => {});
    throw error;
  }

  if (!reachedTerminalEvent) {
    throw new Error("流式连接提前结束，任务可能因网络波动中断");
  }
}
