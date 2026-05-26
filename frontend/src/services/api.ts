const baseURL =
  import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

export interface ResearchRequest {
  topic: string;
  llm_model_id?: "deepseek-v4-flash" | "deepseek-v4-pro";
  llm_reasoning_effort?: "high" | "max";
}

export interface ResearchStreamEvent {
  type: string;
  [key: string]: unknown;
}

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
