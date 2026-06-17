<template>
  <div class="min-h-screen flex items-center justify-center p-6 relative overflow-hidden">
    <!-- Background decorations -->
    <div class="setup-bg-orb setup-bg-orb-1"></div>
    <div class="setup-bg-orb setup-bg-orb-2"></div>
    <div class="setup-bg-orb setup-bg-orb-3"></div>
    <div class="setup-bg-grid"></div>

    <div class="w-full max-w-xl relative z-10">
      <!-- Brand -->
      <div class="text-center mb-7">
        <div class="inline-flex items-center justify-center w-16 h-16 rounded-[18px] bg-gradient-to-br from-blue-500 via-indigo-500 to-purple-600 shadow-2xl shadow-blue-500/20 mb-4 ring-1 ring-white/10">
          <span class="text-3xl">🎙️</span>
        </div>
        <h1 class="text-4xl font-bold mb-2 text-transparent bg-clip-text bg-gradient-to-r from-blue-400 via-indigo-400 to-purple-400 tracking-tight">DeepCast</h1>
        <p class="text-base text-gray-400 font-light">进行深度研究并转化为引人入胜的播客</p>
      </div>

      <!-- Main Card -->
      <div class="setup-card rounded-2xl">
        <form @submit.prevent="submitForm" class="p-5 md:p-6">
          <!-- Health check -->
          <div class="health-card mb-5" :class="healthCardClass">
            <div class="health-card-head">
              <span class="health-status-mark" :class="`health-status-mark--${healthStatus}`">
                {{ healthStatusMark }}
              </span>
              <div class="min-w-0 flex-1">
                <p class="health-title">{{ healthTitle }}</p>
                <p class="health-subtitle">{{ healthSubtitle }}</p>
              </div>
              <div class="health-actions">
                <button
                  type="button"
                  class="health-refresh"
                  :disabled="healthLoading"
                  @click="$emit('refreshHealth')"
                >
                  {{ healthLoading ? "检查中" : "重新检查" }}
                </button>
                <button
                  type="button"
                  class="health-detail-toggle"
                  :aria-expanded="showHealthDetails"
                  @click="showHealthDetails = !showHealthDetails"
                >
                  {{ showHealthDetails ? "收起" : "详情" }}
                </button>
              </div>
            </div>

            <ul v-if="showHealthDetails && visibleChecks.length > 0" class="health-list" aria-label="运行环境检查结果">
              <li
                v-for="item in visibleChecks"
                :key="item.id"
                class="health-item"
                :class="`health-item--${item.status}`"
              >
                <span class="health-item-dot"></span>
                <span class="health-item-label">{{ item.label }}</span>
                <span class="health-item-message" :title="item.message">{{ formatHealthMessage(item.message) }}</span>
              </li>
            </ul>
          </div>

          <!-- Input area -->
          <div class="mb-5">
            <label for="topic-input" class="block text-sm font-medium text-gray-300 mb-2.5 flex items-center gap-2">
              <svg class="w-4 h-4 text-blue-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z"/></svg>
              播客主题
            </label>
            <textarea
              id="topic-input"
              v-model="topic"
              class="setup-textarea"
              placeholder="请输入播客主题（例如：AI Agent 的发展趋势）"
              required
              rows="3"
              aria-label="播客主题输入"
              @keydown.enter.prevent="submitForm"
            ></textarea>
          </div>

          <!-- Generation controls -->
          <div class="control-panel mb-5">
            <div class="control-group">
              <div class="control-group-head">
                <span class="control-title">搜索深度</span>
                <span class="control-desc">深度搜索会在报告大纲处暂停确认</span>
              </div>
              <div class="setup-segmented" role="radiogroup" aria-label="搜索深度">
                <button type="button" class="setup-segment" :class="{ active: searchDepth === 'quick' }" @click="searchDepth = 'quick'">
                  快速
                </button>
                <button type="button" class="setup-segment" :class="{ active: searchDepth === 'deep' }" @click="searchDepth = 'deep'">
                  深度
                </button>
              </div>
            </div>

            <div class="control-group">
              <div class="control-group-head">
                <span class="control-title">播客时长</span>
                <span class="control-desc">控制脚本目标轮次</span>
              </div>
              <div class="setup-segmented setup-segmented--three" role="radiogroup" aria-label="播客时长">
                <button type="button" class="setup-segment" :class="{ active: podcastDuration === 'short' }" @click="podcastDuration = 'short'">
                  短
                </button>
                <button type="button" class="setup-segment" :class="{ active: podcastDuration === 'standard' }" @click="podcastDuration = 'standard'">
                  标准
                </button>
                <button type="button" class="setup-segment" :class="{ active: podcastDuration === 'deep' }" @click="podcastDuration = 'deep'">
                  深度
                </button>
              </div>
            </div>

            <div class="control-group">
              <div class="control-group-head">
                <span class="control-title">播客风格</span>
                <span class="control-desc">影响讲述方式和信息密度</span>
              </div>
              <div class="setup-segmented setup-segmented--three" role="radiogroup" aria-label="播客风格">
                <button type="button" class="setup-segment" :class="{ active: podcastStyle === 'plain' }" @click="podcastStyle = 'plain'">
                  通俗解释
                </button>
                <button type="button" class="setup-segment" :class="{ active: podcastStyle === 'professional' }" @click="podcastStyle = 'professional'">
                  专业分析
                </button>
                <button type="button" class="setup-segment" :class="{ active: podcastStyle === 'news' }" @click="podcastStyle = 'news'">
                  新闻播报
                </button>
              </div>
            </div>

            <label class="bgm-switch-row">
              <span>
                <strong>片头 BGM</strong>
                <small>只在开头短暂进入，随后淡出到人声。</small>
              </span>
              <span class="bgm-switch" :class="{ active: enableIntroBgm }">
                <input v-model="enableIntroBgm" type="checkbox" aria-label="启用片头 BGM" />
                <span class="bgm-switch-thumb"></span>
              </span>
            </label>
          </div>

          <!-- Feature badges -->
          <div class="flex flex-wrap gap-2 mb-6">
            <div class="setup-badge">
              <svg class="w-3.5 h-3.5 text-blue-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"/></svg>
              <span>混合搜索引擎</span>
            </div>
            <div class="setup-badge">
              <svg class="w-3.5 h-3.5 text-purple-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"/></svg>
              <span>深度 AI 研究</span>
            </div>
            <div class="setup-badge">
              <svg class="w-3.5 h-3.5 text-emerald-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z"/></svg>
              <span>自然语音合成</span>
            </div>
          </div>

          <!-- Submit button -->
          <button
            class="setup-btn w-full"
            :disabled="!canSubmit"
            aria-label="开始制作播客"
          >
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z"/><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>
            开始制作播客
          </button>
        </form>
      </div>

      <!-- Footer hint -->
      <p class="text-center text-xs text-gray-600 mt-5">自动化深度研究 → 播客生成</p>
    </div>
  </div>
</template>

<script lang="ts" setup>
import { computed, ref, watch } from "vue";
import type { HealthCheckItem, HealthCheckResponse, HealthStatus } from "../services/api";

const topic = defineModel<string>("topic", { required: true });
const searchDepth = defineModel<"quick" | "deep">("searchDepth", { required: true });
const podcastDuration = defineModel<"short" | "standard" | "deep">("podcastDuration", { required: true });
const podcastStyle = defineModel<"plain" | "professional" | "news">("podcastStyle", { required: true });
const enableIntroBgm = defineModel<boolean>("enableIntroBgm", { required: true });

const props = defineProps<{
  healthCheck: HealthCheckResponse | null;
  healthLoading: boolean;
}>();

const emit = defineEmits<{
  start: [topic: string];
  refreshHealth: [];
}>();

const showHealthDetails = ref(false);

watch(
  () => props.healthCheck,
  health => {
    if (health?.blocking || health?.status === "error") {
      showHealthDetails.value = true;
    }
  },
  { immediate: true }
);

const healthStatus = computed<HealthStatus>(() => {
  if (props.healthLoading) return "warning";
  return props.healthCheck?.status || "error";
});

const healthStatusMark = computed(() => {
  if (props.healthLoading) return "...";
  if (props.healthCheck?.status === "ok") return "✓";
  if (props.healthCheck?.status === "warning") return "!";
  return "×";
});

const healthTitle = computed(() => {
  if (props.healthLoading) return "正在检查运行环境...";
  if (!props.healthCheck) return "运行环境尚未检查";
  if (props.healthCheck.status === "ok") return "运行环境正常";
  if (props.healthCheck.status === "warning") return "运行环境有提示";
  return "运行环境需要处理";
});

const healthSubtitle = computed(() => {
  if (props.healthLoading) return "正在确认后端、密钥、FFmpeg 和输出目录";
  if (!props.healthCheck) return "请先完成健康检查，再开始制作播客";
  if (props.healthCheck.blocking) return "存在会导致制作失败的问题，请修复后重新检查";
  if (props.healthCheck.status === "warning") return "可以继续制作，但部分能力可能降级";
  return "可以输入主题并开始制作";
});

const visibleChecks = computed<HealthCheckItem[]>(() => {
  if (props.healthLoading) return [];
  return props.healthCheck?.checks || [];
});

const healthCardClass = computed(() => ({
  "health-card--ok": healthStatus.value === "ok",
  "health-card--warning": healthStatus.value === "warning",
  "health-card--error": healthStatus.value === "error",
}));

const canSubmit = computed(() => {
  const health = props.healthCheck;
  if (!topic.value.trim() || props.healthLoading || !health) return false;
  return !health.blocking;
});

function submitForm() {
  if (!canSubmit.value) return;
  emit("start", topic.value);
}

function formatHealthMessage(message: string) {
  if (message.length <= 56) return message;
  return `${message.slice(0, 53)}...`;
}
</script>

<style scoped>
/* ── Background Decorations ── */
.setup-bg-orb {
  position: absolute;
  border-radius: 50%;
  filter: blur(80px);
  pointer-events: none;
  opacity: 0.35;
}
.setup-bg-orb-1 {
  top: 10%;
  left: 15%;
  width: 300px;
  height: 300px;
  background: radial-gradient(circle, rgba(59, 130, 246, 0.4), transparent 70%);
  animation: float-slow 8s ease-in-out infinite;
}
.setup-bg-orb-2 {
  bottom: 15%;
  right: 10%;
  width: 250px;
  height: 250px;
  background: radial-gradient(circle, rgba(139, 92, 246, 0.35), transparent 70%);
  animation: float-slow 10s ease-in-out infinite reverse;
}
.setup-bg-orb-3 {
  top: 50%;
  left: 60%;
  width: 200px;
  height: 200px;
  background: radial-gradient(circle, rgba(6, 182, 212, 0.25), transparent 70%);
  animation: float-slow 12s ease-in-out infinite 2s;
}
.setup-bg-grid {
  position: absolute;
  inset: 0;
  background-image:
    linear-gradient(rgba(255, 255, 255, 0.02) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255, 255, 255, 0.02) 1px, transparent 1px);
  background-size: 60px 60px;
  pointer-events: none;
}

/* ── Main Card ── */
.setup-card {
  background: rgba(22, 24, 30, 0.8);
  backdrop-filter: blur(30px);
  -webkit-backdrop-filter: blur(30px);
  border: 1px solid rgba(255, 255, 255, 0.06);
  box-shadow:
    0 25px 60px rgba(0, 0, 0, 0.4),
    inset 0 1px 0 rgba(255, 255, 255, 0.05);
}

/* ── Textarea ── */
.setup-textarea {
  width: 100%;
  min-height: 94px;
  padding: 13px 15px;
  border-radius: 12px;
  font-size: 15px;
  line-height: 1.6;
  resize: none;
  color: #e5e7eb;
  background: rgba(0, 0, 0, 0.25);
  border: 1px solid rgba(255, 255, 255, 0.08);
  transition: all 0.25s ease;
  outline: none;
  font-family: inherit;
}
.setup-textarea::placeholder {
  color: rgba(156, 163, 175, 0.5);
}
.setup-textarea:focus {
  background: rgba(0, 0, 0, 0.35);
  border-color: rgba(59, 130, 246, 0.5);
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.12), 0 2px 8px rgba(0, 0, 0, 0.2);
}

/* ── Health Check ── */
.health-card {
  padding: 11px 12px;
  border-radius: 12px;
  background: rgba(0, 0, 0, 0.22);
  border: 1px solid rgba(255, 255, 255, 0.08);
}
.health-card--ok {
  border-color: rgba(16, 185, 129, 0.26);
  background: rgba(6, 78, 59, 0.16);
}
.health-card--warning {
  border-color: rgba(245, 158, 11, 0.26);
  background: rgba(120, 53, 15, 0.16);
}
.health-card--error {
  border-color: rgba(248, 113, 113, 0.28);
  background: rgba(127, 29, 29, 0.16);
}
.health-card-head {
  display: flex;
  align-items: center;
  gap: 10px;
}
.health-status-mark {
  width: 30px;
  height: 30px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: 0 0 auto;
  border-radius: 999px;
  font-size: 14px;
  font-weight: 800;
}
.health-status-mark--ok {
  color: #34d399;
  background: rgba(16, 185, 129, 0.13);
}
.health-status-mark--warning {
  color: #fbbf24;
  background: rgba(245, 158, 11, 0.13);
}
.health-status-mark--error {
  color: #f87171;
  background: rgba(248, 113, 113, 0.13);
}
.health-title {
  margin: 0;
  font-size: 13px;
  line-height: 1.35;
  font-weight: 700;
  color: #e5e7eb;
}
.health-subtitle {
  margin: 2px 0 0;
  font-size: 12px;
  line-height: 1.35;
  color: #9ca3af;
}
.health-actions {
  display: flex;
  align-items: center;
  gap: 7px;
  flex: 0 0 auto;
}
.health-refresh,
.health-detail-toggle {
  min-height: 30px;
  padding: 0 10px;
  border-radius: 8px;
  border: 1px solid rgba(255, 255, 255, 0.08);
  color: #d1d5db;
  background: rgba(255, 255, 255, 0.05);
  font-size: 12px;
  font-weight: 700;
  cursor: pointer;
  transition: all 0.2s ease;
}
.health-detail-toggle {
  color: #93c5fd;
  border-color: rgba(59, 130, 246, 0.18);
  background: rgba(59, 130, 246, 0.08);
}
.health-refresh:hover:not(:disabled),
.health-detail-toggle:hover {
  color: #ffffff;
  background: rgba(255, 255, 255, 0.09);
}
.health-refresh:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.health-list {
  display: grid;
  gap: 5px;
  margin: 10px 0 0;
  padding: 0;
  list-style: none;
}
.health-item {
  display: grid;
  grid-template-columns: 8px minmax(70px, 0.55fr) minmax(0, 1.45fr);
  align-items: center;
  gap: 8px;
  min-height: 22px;
  font-size: 12px;
  color: #9ca3af;
}
.health-item-dot {
  width: 7px;
  height: 7px;
  border-radius: 999px;
  background: #6b7280;
}
.health-item--ok .health-item-dot {
  background: #34d399;
}
.health-item--warning .health-item-dot {
  background: #fbbf24;
}
.health-item--error .health-item-dot {
  background: #f87171;
}
.health-item-label {
  color: #d1d5db;
  font-weight: 700;
}
.health-item-message {
  min-width: 0;
  overflow-wrap: anywhere;
}

/* ── Generation Controls ── */
.control-panel {
  display: grid;
  gap: 9px;
}
.control-group,
.bgm-switch-row {
  padding: 11px 12px;
  border-radius: 12px;
  background: rgba(0, 0, 0, 0.2);
  border: 1px solid rgba(255, 255, 255, 0.08);
}
.control-group {
  display: grid;
  grid-template-columns: minmax(112px, 0.8fr) minmax(0, 1.2fr);
  align-items: center;
  gap: 12px;
}
.control-group-head {
  min-width: 0;
}
.control-title {
  display: block;
  color: #e5e7eb;
  font-size: 13px;
  line-height: 1.3;
  font-weight: 800;
}
.control-desc {
  display: block;
  margin-top: 3px;
  color: #7d8796;
  font-size: 11px;
  line-height: 1.35;
}
.bgm-switch-row {
  min-height: 60px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.bgm-switch-row strong {
  display: block;
  color: #e5e7eb;
  font-size: 13px;
  line-height: 1.3;
}
.bgm-switch-row small {
  display: block;
  color: #9ca3af;
  font-size: 12px;
  line-height: 1.4;
  margin-top: 3px;
}
.bgm-switch {
  position: relative;
  width: 48px;
  height: 28px;
  border-radius: 999px;
  background: rgba(15, 23, 42, 0.95);
  border: 1px solid rgba(148, 163, 184, 0.24);
  box-shadow: inset 0 1px 4px rgba(0, 0, 0, 0.35);
  flex: 0 0 auto;
  cursor: pointer;
  transition: all 0.2s ease;
}
.bgm-switch.active {
  background: linear-gradient(135deg, rgba(37, 99, 235, 0.95), rgba(124, 58, 237, 0.95));
  border-color: rgba(147, 197, 253, 0.45);
  box-shadow: 0 8px 20px rgba(59, 130, 246, 0.22);
}
.bgm-switch input {
  position: absolute;
  inset: 0;
  opacity: 0;
  cursor: pointer;
}
.bgm-switch-thumb {
  position: absolute;
  top: 3px;
  left: 3px;
  width: 22px;
  height: 22px;
  border-radius: 999px;
  background: #e5e7eb;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.35);
  transition: transform 0.2s ease;
}
.bgm-switch.active .bgm-switch-thumb {
  transform: translateX(20px);
}
.setup-segmented {
  display: grid;
  grid-template-columns: repeat(2, minmax(82px, 1fr));
  gap: 3px;
  padding: 3px;
  border-radius: 10px;
  background: rgba(0, 0, 0, 0.22);
  border: 1px solid rgba(255, 255, 255, 0.07);
}
.setup-segmented--three {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}
.setup-segment {
  min-height: 32px;
  padding: 0 10px;
  border: 0;
  border-radius: 7px;
  font-size: 13px;
  font-weight: 600;
  color: #9ca3af;
  background: transparent;
  cursor: pointer;
  transition: all 0.2s ease;
}
.setup-segment:hover {
  color: #e5e7eb;
}
.setup-segment.active {
  color: #ffffff;
  background: rgba(59, 130, 246, 0.7);
  box-shadow: 0 4px 14px rgba(59, 130, 246, 0.2);
}

/* ── Feature Badge ── */
.setup-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 12px;
  border-radius: 8px;
  font-size: 12px;
  font-weight: 500;
  color: #9ca3af;
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(255, 255, 255, 0.06);
}

/* ── Submit Button ── */
.setup-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 14px 24px;
  border-radius: 12px;
  font-size: 16px;
  font-weight: 600;
  color: white;
  background: linear-gradient(135deg, #3b82f6 0%, #6366f1 50%, #8b5cf6 100%);
  border: 1px solid rgba(255, 255, 255, 0.1);
  box-shadow:
    0 4px 14px rgba(59, 130, 246, 0.3),
    inset 0 1px 1px rgba(255, 255, 255, 0.15);
  cursor: pointer;
  transition: all 0.25s ease;
}
.setup-btn:hover:not(:disabled) {
  transform: translateY(-1px);
  box-shadow:
    0 8px 25px rgba(59, 130, 246, 0.35),
    inset 0 1px 1px rgba(255, 255, 255, 0.15);
  filter: brightness(1.05);
}
.setup-btn:active:not(:disabled) {
  transform: translateY(0.5px);
  filter: brightness(0.95);
}
.setup-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
  filter: grayscale(0.4);
}

/* ── Animations ── */
@keyframes float-slow {
  0%, 100% { transform: translate(0, 0); }
  50% { transform: translate(20px, -15px); }
}

@media (max-width: 640px) {
  .control-group {
    grid-template-columns: 1fr;
  }
  .health-card-head,
  .health-actions {
    align-items: flex-start;
  }
  .health-actions {
    flex-direction: column;
  }
}
</style>
