<template>
  <div class="app-root min-h-screen">
    <!-- View 1: Setup -->
    <SetupView
      v-if="currentView === 'setup'"
      v-model:topic="form.topic"
      v-model:search-depth="form.searchDepth"
      v-model:podcast-duration="form.podcastDuration"
      v-model:podcast-style="form.podcastStyle"
      v-model:enable-intro-bgm="form.enableIntroBgm"
      :health-check="healthCheck"
      :health-loading="healthLoading"
      @start="startProduction"
      @refresh-health="refreshHealthCheck"
    />

    <!-- View 2: Production -->
    <ProductionView
      v-else-if="currentView === 'producing'"
      ref="productionRef"
      :logs="logs"
      :is-waiting="isWaiting"
      :waiting-dots="waitingDots"
      :production-stage="productionStage"
      :progress-percent="progressPercent"
      :report-ready="reportReady"
      :podcast-ready="podcastReady"
      :podcast-blueprint="podcastBlueprint"
      :report-outline-review="reportOutlineReview"
      :outline-action-loading="outlineActionLoading"
      :audio-url="audioUrl"
      @cancel="cancelProduction"
      @download-report="downloadReport"
      @go-player="currentView = 'player'"
      @confirm-outline="confirmOutline"
      @regenerate-outline="regenerateOutline"
    />

    <!-- View 3: Player -->
    <PlayerView
      v-else-if="currentView === 'player'"
      :topic="form.topic"
      :audio-url="audioUrl"
      :report-markdown="reportMarkdown"
      @reset="resetApp"
      @download-report="downloadReport"
    />
  </div>
</template>

<script lang="ts" setup>
import { reactive, ref, nextTick, onMounted } from "vue";
import {
  runResearchStream,
  cancelResearch,
  continueReportOutline,
  getHealthCheck,
  type HealthCheckResponse,
  type ReportOutline,
  type ResearchStreamEvent
} from "./services/api";

import SetupView from "./components/SetupView.vue";
import ProductionView from "./components/ProductionView.vue";
import PlayerView from "./components/PlayerView.vue";
import type { LogEntry } from "./components/TerminalLog.vue";
import type { PodcastBlueprint, ProductionStage } from "./components/ProductionView.vue";

// --- Types ---
type ViewState = "setup" | "producing" | "player";
type SearchDepth = "quick" | "deep";
type PodcastDuration = "short" | "standard" | "deep";
type PodcastStyle = "plain" | "professional" | "news";

interface ReportOutlineReview {
  outline: ReportOutline;
  attempt: number;
  maxAttempts: number;
  message?: string;
}

// --- State ---
const currentView = ref<ViewState>("setup");
const productionStage = ref<ProductionStage>("research");
const form = reactive({
  topic: "",
  searchDepth: "quick" as SearchDepth,
  podcastDuration: "standard" as PodcastDuration,
  podcastStyle: "plain" as PodcastStyle,
  enableIntroBgm: true
});

const logs = ref<LogEntry[]>([]);
const reportReady = ref(false);
const podcastReady = ref(false);

const audioProgress = reactive({ current: 0, total: 0 });
const taskProgress = reactive({ completed: 0, total: 0 });
const progressPercent = ref(0);
const isWaiting = ref(false);
const waitingDots = ref(".");
let waitingInterval: ReturnType<typeof setInterval> | null = null;

const reportMarkdown = ref("");
const audioUrl = ref("");
const podcastBlueprint = ref<PodcastBlueprint | null>(null);
const reportOutlineReview = ref<ReportOutlineReview | null>(null);
const outlineActionLoading = ref<"approve" | "regenerate" | null>(null);
const healthCheck = ref<HealthCheckResponse | null>(null);
const healthLoading = ref(false);

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";
let abortController: AbortController | null = null;

const productionRef = ref<InstanceType<typeof ProductionView> | null>(null);

// --- Helpers ---

function startWaitingAnimation() {
  stopWaitingAnimation();
  isWaiting.value = true;
  waitingDots.value = ".";
  waitingInterval = setInterval(() => {
    waitingDots.value = waitingDots.value.length >= 3 ? "." : waitingDots.value + ".";
  }, 500);
}

function stopWaitingAnimation() {
  isWaiting.value = false;
  if (waitingInterval) {
    clearInterval(waitingInterval);
    waitingInterval = null;
  }
}

function addLog(message: string) {
  const time = new Date().toLocaleTimeString([], { hour12: false, hour: "2-digit", minute: "2-digit", second: "2-digit" });
  logs.value.push({ time, message });
  nextTick(() => {
    productionRef.value?.scrollTerminal();
  });
}

function buildBackendUnavailableHealth(message: string): HealthCheckResponse {
  return {
    status: "error",
    blocking: true,
    checks: [
      {
        id: "backend",
        label: "后端服务",
        status: "error",
        message
      }
    ]
  };
}

async function refreshHealthCheck() {
  healthLoading.value = true;
  try {
    healthCheck.value = await getHealthCheck();
  } catch (err: any) {
    healthCheck.value = buildBackendUnavailableHealth(err.message || "无法连接后端服务");
  } finally {
    healthLoading.value = false;
  }
}

// --- Actions ---

async function startProduction() {
  if (!form.topic.trim()) return;
  if (healthLoading.value || !healthCheck.value || healthCheck.value.blocking) return;

  currentView.value = "producing";
  productionStage.value = "research";
  logs.value = [];
  reportMarkdown.value = "";
  audioUrl.value = "";
  podcastBlueprint.value = null;
  reportOutlineReview.value = null;
  outlineActionLoading.value = null;
  audioProgress.current = 0;
  audioProgress.total = 0;
  taskProgress.completed = 0;
  taskProgress.total = 0;
  progressPercent.value = 2;
  reportReady.value = false;
  podcastReady.value = false;

  abortController = new AbortController();
  startWaitingAnimation();

  addLog("🚀 启动 DeepCast 制作流程...");
  addLog(`📌 主题: ${form.topic}`);
  addLog(
    `⚙️ 搜索: ${form.searchDepth === "quick" ? "快速" : "深度"} / 时长: ${durationLabel(form.podcastDuration)} / 风格: ${styleLabel(form.podcastStyle)} / 片头 BGM: ${form.enableIntroBgm ? "开启" : "关闭"}`
  );

  try {
    await runResearchStream(
      {
        topic: form.topic,
        search_depth: form.searchDepth,
        podcast_duration: form.podcastDuration,
        podcast_style: form.podcastStyle,
        enable_intro_bgm: form.enableIntroBgm
      },
      handleStreamEvent,
      { signal: abortController.signal }
    );
  } catch (err: any) {
    if (err.name === "AbortError" || err.message?.includes("aborted")) {
      addLog("🛑 制作已取消。");
    } else {
      addLog(`❌ 错误: ${err.message || err}`);
      console.error(err);
      productionStage.value = "error";
      cancelResearch().catch(() => {});
    }
  } finally {
    stopWaitingAnimation();
    abortController = null;
  }
}

function durationLabel(duration: PodcastDuration) {
  const labels: Record<PodcastDuration, string> = {
    short: "短",
    standard: "标准",
    deep: "深度"
  };
  return labels[duration];
}

function styleLabel(style: PodcastStyle) {
  const labels: Record<PodcastStyle, string> = {
    plain: "通俗解释",
    professional: "专业分析",
    news: "新闻播报"
  };
  return labels[style];
}

function handleStreamEvent(event: ResearchStreamEvent) {
  if (event.type === "heartbeat") {
    return;
  }

  if (event.type === "client_retry") {
    addLog(`🔁 [RETRY] ${event.message || "连接波动，正在重试"}`);
    return;
  }

  if (event.type === "error") {
    const detail = String(event.detail || event.message || "后端任务失败");
    addLog(`❌ [ERROR] ${detail}`);
    stopWaitingAnimation();
    productionStage.value = "error";
    return;
  }

  if (event.type === "log") {
    const msg = String(event.message || "");
    const cleanMsg = msg.replace(/\u001b\[\d+m/g, "");
    addLog(`INFO: ${cleanMsg}`);

    const ttsMatch = cleanMsg.match(/\[TTS (\d+)\/(\d+)\]/);
    if (ttsMatch) {
      audioProgress.current = parseInt(ttsMatch[1], 10);
      audioProgress.total = parseInt(ttsMatch[2], 10);
    }
    return;
  }

  if (event.type === "stage_change") {
    const stage = event.stage;
    const message = event.message || "";

    addLog("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━");
    addLog(`📌 [STAGE] ${stage.toUpperCase()} - ${message}`);
    addLog("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━");

    if (stage === "report") {
      productionStage.value = "research";
      progressPercent.value = 40;
    } else if (stage === "script") {
      productionStage.value = "script";
      progressPercent.value = 55;
    } else if (stage === "audio") {
      productionStage.value = "audio";
      progressPercent.value = 70;
    } else if (stage === "synthesis") {
      productionStage.value = "audio";
      progressPercent.value = 95;
    }
  }

  if (event.type === "tool_call") {
    addLog(`🔧 [TOOL] ${event.tool || "unknown"} - ${event.agent || "Agent"}`);
  }

  if (event.type === "todo_list") {
    const tasks = event.tasks || [];
    taskProgress.total = tasks.length;
    taskProgress.completed = 0;
  }

  if (event.type === "task_status") {
    if (event.status === "completed") {
      taskProgress.completed++;
      if (taskProgress.total > 0) {
        progressPercent.value = Math.round((taskProgress.completed / taskProgress.total) * 40);
      }
      addLog(`✅ [TASK ${event.task_id}] ${event.title || "未命名任务"}`);
    } else if (event.status === "in_progress") {
      addLog(`🚀 [TASK ${event.task_id}] ${event.title || "未命名任务"} (In Progress)`);
    } else if (event.status === "failed") {
      addLog(`❌ [TASK ${event.task_id}] Failed: ${event.title || "未命名任务"}`);
    }
  }

  if (event.type === "search_query") {
    addLog(`🔎 [SEARCH] 正在搜索: "${event.query}"`);
  }

  if (event.type === "sources") {
    const count = event.result_count;
    if (count !== undefined) {
      addLog(`📊 [SEARCH] 获取到 ${count} 条搜索结果`);
    }
  }

  if (event.type === "task_findings") {
    const findings = event.findings || [];
    if (findings.length > 0) {
      addLog(`💡 [FINDINGS] ${event.title || "任务"} 关键发现:`);
      for (const finding of findings) {
        addLog(`   · ${finding}`);
      }
    }
  }

  if (event.type === "refine_round") {
    addLog(`🔍 [DEEP SEARCH] ${event.message || `深度搜索分析第 ${event.round}/${event.max_rounds} 轮...`}`);
  }

  if (event.type === "refine_saturation") {
    addLog(`✅ [DEEP SEARCH] ${event.message || `信息饱和: ${event.reason || "无新增信息"}`}`);
  }

  if (event.type === "report_refine") {
    if (event.phase === "critique") {
      addLog(`🔍 [REPORT] ${event.message || "正在评估报告质量"}`);
    } else if (event.phase === "result") {
      const icon = event.verdict === "pass" ? "✅" : "🔄";
      addLog(`${icon} [REPORT] ${event.message || "报告评估完成"}`);
    }
  }

  if (event.type === "report_outline_review") {
    reportOutlineReview.value = {
      outline: event.outline,
      attempt: event.attempt,
      maxAttempts: event.max_attempts,
      message: event.message
    };
    outlineActionLoading.value = null;
    productionStage.value = "outline_review";
    progressPercent.value = 45;
    addLog(`🧭 [OUTLINE] 报告大纲待确认（第 ${event.attempt}/${event.max_attempts} 次）`);
    return;
  }

  if (event.type === "podcast_blueprint") {
    podcastBlueprint.value = (event.blueprint || null) as PodcastBlueprint | null;
    const title = podcastBlueprint.value?.title || "未命名节目";
    const sectionCount = podcastBlueprint.value?.sections?.length || event.section_count || 0;
    addLog(`🧩 [BLUEPRINT] 节目蓝图已生成: ${title}（${sectionCount} 个段落）`);
  }

  if (event.type === "final_report") {
    reportMarkdown.value = String(event.report);
    reportReady.value = true;
    reportOutlineReview.value = null;
    outlineActionLoading.value = null;
    addLog("📄 [REPORT] 报告已生成");
  }

  if (event.type === "podcast_script") {
    productionStage.value = "audio";
    addLog("🎙️ [SCRIPT] 剧本已生成");
  }

  if (event.type === "audio_start") {
    audioProgress.total = event.total || 0;
    addLog(`🎵 [AUDIO] 开始生成音频, 共 ${audioProgress.total} 段`);
  }

  if (event.type === "audio_progress") {
    audioProgress.current = event.current;
    audioProgress.total = event.total;
    if (event.total > 0) {
      progressPercent.value = 70 + Math.round((event.current / event.total) * 25);
    }
  }

  if (event.type === "podcast_ready") {
    const filename = String(event.file).split(/[\\/]/).pop();
    if (filename) {
      audioUrl.value = `${apiBaseUrl}/output/audio/${filename}`;
      podcastReady.value = true;
      productionStage.value = "done";
      progressPercent.value = 100;
      stopWaitingAnimation();
      addLog(`🎉 [PODCAST] 制作完成: ${filename}`);
    }
  }

  if (event.type === "cancelled") {
    const msg = event.message || "研究任务已取消";
    addLog(`🛑 [CANCELLED] ${msg}`);
    stopWaitingAnimation();
    productionStage.value = "cancelled";
    return;
  }

  if (event.type === "done") {
    addLog("✅ [DONE] 所有任务结束");
    stopWaitingAnimation();
    progressPercent.value = 100;

    if (!podcastReady.value && audioProgress.total > 0) {
      productionStage.value = "error";
      addLog("❌ [PODCAST] 播客合成未完成，未收到可播放音频文件");
      return;
    }

    productionStage.value = "done";
  }
}

async function submitOutlineAction(action: "approve" | "regenerate") {
  if (!reportOutlineReview.value || outlineActionLoading.value) return;
  outlineActionLoading.value = action;
  try {
    const result = await continueReportOutline(action);
    if (result.status !== "accepted") {
      addLog("⚠️ [OUTLINE] 当前没有等待确认的大纲任务");
      outlineActionLoading.value = null;
      return;
    }
    if (action === "approve") {
      addLog("✅ [OUTLINE] 已确认报告大纲，继续生成报告");
      reportOutlineReview.value = null;
      productionStage.value = "research";
    } else {
      addLog("🔄 [OUTLINE] 正在重新生成报告大纲");
    }
  } catch (err: any) {
    addLog(`❌ [OUTLINE] 操作失败: ${err.message || err}`);
    outlineActionLoading.value = null;
  }
}

function confirmOutline() {
  submitOutlineAction("approve");
}

function regenerateOutline() {
  submitOutlineAction("regenerate");
}

function cancelProduction() {
  if (confirm("确定要取消制作吗？")) {
    addLog("🛑 用户请求取消制作...");

    // 1. 先显式通知后端取消，减少仅依赖断连检测的延迟
    cancelResearch().catch(() => {});

    // 2. 再中断 SSE 连接 — 后端 monitor_disconnect 仍作为后备
    if (abortController) {
      abortController.abort();
      abortController = null;
    }

    stopWaitingAnimation();
    productionStage.value = "cancelled";
    addLog("🛑 已取消制作");

    setTimeout(() => {
      currentView.value = "setup";
    }, 1000);
  }
}

function resetApp() {
  currentView.value = "setup";
  form.topic = "";
  reportReady.value = false;
  podcastReady.value = false;
  podcastBlueprint.value = null;
  reportOutlineReview.value = null;
  outlineActionLoading.value = null;
  audioUrl.value = "";
  stopWaitingAnimation();
}

function downloadReport() {
  if (!reportMarkdown.value) return;
  const blob = new Blob([reportMarkdown.value], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "DeepCast深度研究报告.md";
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

onMounted(() => {
  refreshHealthCheck();
});
</script>

<style scoped>
.app-root {
  background: linear-gradient(145deg, #0c0e14 0%, #111420 30%, #0e1018 60%, #0a0c12 100%);
  background-attachment: fixed;
}
</style>
