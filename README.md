# DeepCast

> 输入一个主题，自动深度研究并生成一期双人对谈播客。

## 解决什么问题

现代人面临一个矛盾：**想获取深度知识，但只有碎片化时间。**

每天有海量行研报告、前沿论文、深度文章等待阅读，但通勤、健身、做家务的时间里，眼睛被占用，耳朵却是空闲的。

DeepCast 的核心洞察：**用对话式播客替代文字阅读，让耳朵成为第二个认知通道。** 用户只需输入一个主题（如"量子计算 2024 年有哪些突破"），系统自动完成全网深度调研、生成双人对谈脚本、合成语音，输出一期 5-10 分钟的播客，同时附带完整的研究报告。

## 目标用户

| 画像 | 痛点 | 使用场景 |
|------|------|----------|
| **金融投资人 / 行业分析师** | 每天面对海量行研报告，无法全部阅读 | 开车通勤时听"固态电池产业链现状"深度对谈 |
| **科研工作者** | 需要跨界了解其他学科进展，但看论文门槛高且枯燥 | 做家务时听 AI 拆解"AlphaFold 3 的核心算法" |
| **城市白领 / 终身学习者** | 知识焦虑强，买了专栏和电子书大多"吃灰"，缺乏整块阅读时间 | 地铁 30 分钟听一期"量子计算商业化"播客 |

## 产品 Demo

<!-- TODO: 替换为实际截图/GIF -->
<!-- ![产品流程](docs/demo-flow.gif) -->

**用户旅程：**

```
输入主题 "AI Agent 的发展趋势"
  → [15s] 规划 3 个研究子任务，检索相关历史记忆
  → [45s] 并行搜索（LLM 过滤 + 权威性排序）+ 摘要，实时展示 Agent 动作
  → [60s] 迭代深度搜索：分析信息缺口 → 补充任务 → 信息饱和终止
  → [90s] 生成报告 + Self-Refine（Critic 评估 → 修改）
  → [105s] 转化为双人对谈脚本（Host 苏打 + Guest 茉莉，含情感标注）
  → [150s] 导演模式 TTS 逐句语音合成 + 拼接
  → 完成：可播放的播客 MP3 + 可阅读的 Markdown 报告 + 长期记忆持久化
```

## 竞品对比

| 维度 | DeepCast | Google NotebookLM | 喜马拉雅 / 得到 |
|------|----------|-------------------|----------------|
| **内容来源** | 用户输入任意主题，AI 自动全网深度检索 | 仅限用户手动上传的文档 | 平台 PGC/UGC，无法按需定制 |
| **交互形式** | 中文双人对谈，角色人格鲜明 | 英文对谈优秀，中文支持弱 | 人类录制，质量高但产量低 |
| **定制化** | 可控制话题、深度、音色风格 | 无法控制风格和时长 | 无，只能被动搜索已有内容 |
| **使用门槛** | 零干预：输入主题即出播客 | 需手动上传文档 | 需搜索和筛选内容 |
| **时效性** | 实时搜索，信息时效性强 | 仅基于上传文档 | 依赖人工更新频率 |

## 产品设计亮点

### 1. Terminal UI 缓解等待焦虑

**问题：** AI 生成播客需要 2-3 分钟，用户不知道系统在做什么，容易流失。

**决策：** 用 macOS 风格的 Terminal 实时展示 Agent 内部动作——"正在搜索 Tavily..."、"正在总结任务 2/3..."、"正在生成对话脚本..."。将"黑盒等待"变为"半透明过程"。

**迭代细节：** 初版进度条从 0% 起步，用户反馈"以为卡住了"。改为从 2% 起步，消除静止错觉。这 2% 不是技术细节，是产品决策。

### 2. 双输出形态：音频 + 报告

**问题：** 同一内容在不同场景下有不同的最佳消费方式。

**决策：** 每次生成同时提供两种输出——播客音频（通勤/运动时听）和 Markdown 研究报告（桌面端深读）。播放器旁并排展示报告，支持"图文对照阅读"。

### 3. 黑胶唱片播放器（情感化设计）

**问题：** "播放一个 AI 生成的音频文件"这个动作缺乏仪式感。

**决策：** 设计旋转黑胶唱片 UI，配合"DeepCast Original"标识。播放时唱片旋转，暂停时停止。成本为零，但将"播放文件"变为"收听播客"的体验跃迁。

### 4. 双主持人对话而非单人朗读

**问题：** 单人 TTS 朗读研究报告枯燥且信息密度低。

**决策：** 设计 Host（苏打，好奇幽默的主持人）+ Guest（茉莉，专业严谨的嘉宾）双角色，通过提问-解答的对话结构组织内容。双人对话天然具备"捧哏/逗哏"节奏，大脑更易吸收。

### 5. Plan-and-Solve 多智能体工作流

**问题：** 复杂主题无法一步到位生成高质量内容。

**决策：** 将任务拆解为 5 个专业 Agent 协同：PlannerAgent（拆解子任务 + 信息增益分析）→ ResearcherAgent（混合搜索 + LLM 过滤 + 域名权威性排序）→ WriterAgent（报告撰写 + Self-Refine 精炼）→ ScriptGenerationService（对话脚本）→ AudioGenerationService（TTS 合成）。并行执行提升效率，DirectorAgent 统一协调。

### 7. 迭代式深度搜索 + 智能终止

**问题：** 单轮搜索无法覆盖复杂主题的所有维度，信息深度不足。

**决策：** 初始任务完成后，LLM 自动分析已有信息、识别知识缺口、生成补充搜索任务，迭代至信息饱和。同时引入定量信息增益指标——基于关键词重叠度计算信息重复度，超过阈值自动终止，避免无效搜索浪费成本。

### 8. 报告 Self-Refine 质量闭环

**问题：** 单次 LLM 生成的报告质量不稳定，缺乏自我纠错能力。

**决策：** 报告初稿生成后，Critic Agent 从逻辑严谨性、数据支撑度、专业性等维度评估质量并给出结构化反馈，Writer Agent 据此修改。形成"生成 → 批判 → 修改"的质量自闭环。

### 9. 混合记忆管理

**问题：** 每次研究都是独立的，无法利用历史研究发现。

**决策：** 引入 MemoryManager，研究完成后使用 LLM 提取关键发现（实体、关键词、结论）持久化为结构化记忆。下次研究前自动检索相关记忆注入规划 prompt，避免重复搜索已知信息。

### 6. 导演模式拟人语音（情感化 TTS）

**问题：** AI 播客的语音像机器人朗读——每句台词用同样的语调、同样的节奏，缺乏情感变化和对话感，听众很快流失。

**决策：** 采用 MiMo-V2.5-TTS 的三项进阶能力：
- **导演模式**：为每句台词构建「角色/场景/指导」三维度风格指令，而非简单的一句话描述。指导部分根据台词的情绪标注动态变化。
- **文本音色设计**（VoiceDesign）：通过自然语言描述自定义音色（"一位好奇心旺盛的年轻男性，语速偏快，偶尔因兴奋而提高音量"），而非依赖预置音色。
- **音频标签**：在文本中嵌入 `(轻笑)`、`(叹气)`、`(语速加快)` 等标签，实现词级语音控制。

**效果：** 语音不再是"读稿"，而是"表演"——同一角色在不同语境下有不同的情绪表达，对话中能听到自然的停顿、语气转折和情感流动。

## 核心指标体系

**北极星指标：** WAST（Weekly Average Session Time）—— 活跃用户周均收听时长，衡量"是否真正填补了碎片化时间"。

**转化漏斗：**

```
输入主题 (100%) → 等待超 30s (90%) → 点击播放 (80%) → 完播率 >80% (35%)
```

**关键体验指标：**
- TTFA（Time to First Audio）：提交主题到首段音频可播放，目标 < 30s
- 生成失败率：大模型超时 / TTS 失败 / 脚本解析错误的比例

## 商业化模型

| 层级 | 价格 | 权益 |
|------|------|------|
| **Free** | 免费 | 3 期/月，5 分钟短播客，浅层搜索，默认音色 |
| **Pro** | $9.9/月 | 30 期/月，15-20 分钟，深度混合搜索，多种音色风格 |
| **Max** | $39/月 | 文档上传（PDF/Word/URL），API 接口，企业级集成 |

## 迭代路线图

| 版本 | 重点 | 状态 |
|------|------|------|
| v1.0 | 主题 → 播客 MVP，跑通搜索到合成全流程 | ✅ 已完成 |
| v1.5 | 迭代深度搜索、报告 Self-Refine、搜索过滤、多智能体架构、记忆管理 | ✅ 已完成 |
| v2.0 | 支持 URL / PDF / 公众号文章作为输入源 | 规划中 |
| v2.5 | 音色克隆 + 个性化主持人，打造专属"AI 知识伴游" | 规划中 |

---

## 技术架构

```
用户输入主题
  → MemoryManager → 检索相关历史研究记忆
  → PlanningService（smart LLM + XGrammar 结构化输出）→ TodoItem[] 任务列表
  → [并行] SearchTool（Tavily + SerpApi + LLM 结果过滤 + 域名权威性排序）→ SummarizationService（fast LLM）
  → RefinePhase（smart LLM）→ 分析信息缺口 → 补充搜索（迭代至饱和 + 智能终止）
  → ReportingService（smart LLM）→ Self-Refine：初稿 → Critic 评估 → 修改 → 结构化 Markdown 报告
  → MemoryManager → 提取关键发现持久化
  → ScriptGenerationService（fast LLM）→ 双人对话 JSON 脚本（含 emotion + audio_tag）
  → AudioGenerationService（MiMo TTS 导演模式 + VoiceDesign）→ PodcastSynthesisService（FFmpeg）→ podcast.mp3
```

**技术栈：**
- **智能体编排：** 自研多智能体工作流（DirectorAgent + PlannerAgent/ResearcherAgent/CriticAgent/WriterAgent），基于 OpenAI SDK + XGrammar 结构化输出
- **大语言模型：** `ecnu-reasoner`（深度推理）、`ecnu-max`（快速响应）
- **语音合成：** MiMo-V2.5-TTS（导演模式 + VoiceDesign 文本音色设计 + 音频标签）
- **后端：** Python 3.10+, FastAPI, Pydantic
- **前端：** Vue 3, Vite, TypeScript, Tailwind CSS 4 + DaisyUI 5
- **搜索增强：** Tavily API + SerpApi 混合搜索 + LLM 结果过滤 + 域名权威性排序
- **音频处理：** FFmpeg

## 快速开始

### 环境要求

- Python 3.10+
- Node.js 18+
- FFmpeg（必须安装，Windows 需在 `.env` 中配置 `FFMPEG_PATH`）

### 安装与运行

```bash
# 后端
cd backend
uv sync                          # 或 pip install -r requirements.txt
cp env.example .env               # 填入 API Keys
uv run src/main.py                # 启动服务 http://localhost:8000

# 前端
cd frontend
npm install
npm run dev                       # 访问 http://localhost:5174
```

**关键环境变量：**
- `LLM_API_KEY` / `LLM_BASE_URL`：大语言模型 API
- `TTS_API_KEY` / `TTS_BASE_URL`：语音合成 API
- `TAVILY_API_KEY` / `SERPAPI_API_KEY`：搜索 API（至少配一项）
- `FFMPEG_PATH`：FFmpeg 可执行文件路径

### 验证脚本

```bash
cd backend
python scripts/verify_ecnu_llm.py       # 验证 LLM 连通性
python scripts/verify_mimo_tts.py       # 验证 TTS 服务
python scripts/verify_ffmpeg.py         # 检查 FFmpeg
python scripts/verify_search.py         # 测试搜索 API
```

## 项目结构

```
backend/
  src/
    agent.py               # DeepResearchAgent 核心编排器（集成 Director）
    config.py              # 配置中心（环境变量加载）
    models.py              # 数据模型（TodoItem, SummaryState）
    prompts.py             # Agent 系统提示词模板
    utils.py               # 工具函数（格式化、去重）
    agents/                # 多智能体抽象层
      base.py              # BaseAgent 抽象基类 + AgentResult
      planner.py           # PlannerAgent（任务分解、信息增益分析）
      researcher.py        # ResearcherAgent（搜索、过滤、权威性排序、摘要）
      critic.py            # CriticAgent（报告质量评估）
      writer.py            # WriterAgent（报告撰写、脚本生成）
      director.py          # DirectorAgent（协调器、Agent 注册表）
    services/              # 服务层（Agent 的底层实现）
      planner.py           # 任务拆解 + 迭代精炼分析
      search.py            # 混合搜索 + LLM 结果过滤 + 域名权威性排序
      summarizer.py        # 逐任务摘要
      reporter.py          # 报告生成 + Self-Refine 精炼
      script_generator.py  # 对话脚本生成
      audio_generator.py   # TTS 语音合成（导演模式 + VoiceDesign）
      audio_synthesizer.py # 音频拼接
      memory_manager.py    # 长期记忆管理（提取、持久化、检索）
      llm.py               # LLM 调用封装（JSON 结构化输出）
  scripts/                 # 验证 & 测试脚本
frontend/
  src/
    components/
      SetupView.vue        # 主题输入
      ProductionView.vue   # 制作流程（进度 + Terminal 日志）
      PlayerView.vue       # 黑胶播放器 + 报告阅读器
    services/
      api.ts               # SSE 流式通信
```

## 许可证

MIT License

## 致谢

感谢 [Datawhale](https://github.com/datawhalechina) 社区和 [Hello-Agents](https://github.com/datawhalechina/Hello-Agents) 项目。
