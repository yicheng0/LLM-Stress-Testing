# 缓存专项测试 Plan

## 架构概览

缓存专项测试采用“独立入口、独立接口、独立执行器、复用任务基础设施”的结构：

1. 前端新增独立配置页 `/tests/cache-diagnostics`，提交三个内置 Case 的选择和连接配置。
2. 后端提供独立的缓存专项接口，创建带有 `task_kind=cache_diagnostics` 标识的任务。
3. 专项执行器按 Case 顺序执行准备请求和验证请求，并在每个 Case 内严格串行。
4. 协议请求层构造具有稳定公共前缀的 OpenAI、Anthropic、Gemini 请求，并保留缓存字段“是否出现”的证据。
5. 结果写入现有任务与结果存储，使用独立 Summary 结构和请求证据 JSONL，不新增数据库表或字段。
6. 独立结果页展示进度、摘要和逐 Case 证据；历史记录依据任务类型跳转到该结果页。
7. PDF 下载识别缓存专项 Summary，使用专项模板重新生成报告。

普通压测仍沿用现有执行器、报告页和 PDF 模板，两种任务只共享认证、任务生命周期、存储、事件、停止与下载基础能力。

## 核心数据结构

### CacheDiagnosticsCreate

缓存专项创建请求：

- `name`：任务名称，默认“缓存专项测试”。
- `api_protocol`：`openai`、`anthropic` 或 `gemini`。
- `anthropic_version`：Anthropic 协议版本。
- `base_url`、`endpoint`、`api_key`、`model`：目标接口配置。
- `max_output_tokens`、`temperature`：输出参数。
- `timeout_sec`、`connect_timeout_sec`：网络超时配置。
- `max_retries`、`retry_backoff_base`、`retry_backoff_max`：失败重试配置。
- `enable_stream`：是否使用流式响应。
- `case_ids`：用户选择的内置 Case，限定为 `repeat`、`multiturn`、`variable_suffix`，至少选择一个，去重后最多三个。

持久化前补充固定任务元数据：

- `task_kind`：固定为 `cache_diagnostics`。
- `concurrency`：固定为 `1`。
- `matrix_mode`：固定为 `false`。
- `cache_test_enabled`：固定为 `true`。
- `input_tokens`：记录内置公共前缀的目标 Token 数，不由用户调整。

### CacheUsageEvidence

缓存判定证据：

- `observed`：上游响应是否出现受支持的缓存用量字段。
- `cached_input_tokens`：缓存读取或命中 Token。
- `cache_creation_input_tokens`：缓存创建或写入 Token。
- `cache_inclusive_total_tokens`：包含缓存读写口径的总 Token。
- `cache_hit_rate`：`cached_input_tokens / max(input_tokens, cached_input_tokens + cache_creation_input_tokens)`；分母无效时为空。

`observed` 必须独立保存，不能用 Token 数值是否为零替代。这样才能区分“明确返回零”和“完全没有字段”。

### CacheRequestEvidence

单阶段请求证据：

- `case_id`、`phase`：Case 标识以及 `prepare` 或 `validate` 阶段。
- `ok`、`status`：请求结果和 HTTP 状态。
- `latency_sec`、`ttft_sec`：总延迟和 TTFT。
- `input_tokens`、`output_tokens`、`total_tokens`：Token 用量。
- `cache`：`CacheUsageEvidence`。
- `error_type`、`error_message`：失败信息。

请求正文、完整模型回答、Header 和 API Key 不进入证据文件。

### CacheCaseResult

逐 Case 结果：

- `case_id`、`case_name`、`description`。
- `status`：`cache_hit`、`cache_miss`、`unverifiable` 或 `failed`。
- `failure_phase`：失败时标记 `prepare` 或 `validate`。
- `prepare`、`validate`：两阶段 `CacheRequestEvidence`。
- `error_type`、`error_message`：Case 级失败摘要。

判定顺序：

1. 准备或验证请求失败，结果为 `failed`。
2. 验证请求成功且 `cache.observed=false`，结果为 `unverifiable`。
3. 验证请求成功、`cache.observed=true` 且 `cached_input_tokens>0`，结果为 `cache_hit`。
4. 验证请求成功、`cache.observed=true` 且 `cached_input_tokens=0`，结果为 `cache_miss`。

### CacheDiagnosticsSummary

专项任务 Summary：

- `task_kind`：`cache_diagnostics`。
- `config`：已脱敏的连接配置、流式配置、Case 列表和公共前缀实际 Token 数。
- `results`：总 Case 数、命中数、未命中数、无法判定数、失败数和已执行请求数。
- `cases`：按用户选择顺序保存的 `CacheCaseResult`。
- `generated_at`：报告生成时间。

## 核心接口

### 创建缓存专项任务

`POST /api/cache-diagnostics`

- 输入：`CacheDiagnosticsCreate`。
- 行为：执行角色对应的接入域名限制、连接预检、运行数量限制和敏感字段脱敏，然后异步启动任务。
- 输出：任务 ID、初始状态和创建时间。

### 获取缓存专项任务

`GET /api/cache-diagnostics/{task_id}`

- 返回任务状态、脱敏配置、实时进度、事件和已完成的 Summary。
- 非缓存专项任务访问该接口时返回“任务类型不匹配”。

### 停止缓存专项任务

沿用 `POST /api/tests/{task_id}/stop`。

- 复用现有停止事件和状态机。
- 执行器在请求前后检查停止标记；停止后不再启动后续 Case。

### 下载缓存专项 PDF

沿用 `GET /api/tests/{task_id}/download/pdf`。

- 下载层根据 Summary 的 `task_kind` 选择缓存专项 PDF 模板。
- 每次下载仍使用临时文件生成并原子替换旧 PDF。

### 历史列表

沿用 `GET /api/tests`，任务输出增加 `task_kind`。

- 普通任务缺失该字段时兼容为 `load_test`。
- 前端根据 `task_kind` 显示任务类型并决定结果页路由。

## 模块设计

### 缓存 Case 定义模块

**职责：**

- 提供三个固定 Case 的名称、说明和请求序列。
- 生成可重复、无敏感信息且达到缓存最低规模的公共前缀。
- 保证重复请求完全一致；多轮请求保留首轮上下文并追加一轮；尾部变化请求只改变公共前缀后的尾部。

**对外接口：**

- 根据 `case_id` 和协议生成准备、验证两个请求描述。
- 返回实际公共前缀 Token 数和不含正文的结构摘要，用于结果解释。

**依赖：** Token 估算和现有 Prompt 生成能力。

公共前缀目标采用固定 `4096 Token`。该值能覆盖常见服务的最低缓存门槛，同时避免开放任意规模导致专项诊断变成高成本压测。

### 协议请求与证据模块

**职责：**

- 把通用消息序列转换为 OpenAI Chat/Responses、Anthropic Messages 和 Gemini Contents 请求。
- Anthropic 在稳定前缀内容块上添加 `ephemeral` 缓存控制；OpenAI 和 Gemini 不注入未声明的私有字段。
- 支持流式与非流式响应，采集状态、延迟、TTFT、Token、缓存字段和错误。
- 记录原始 usage 中是否出现任一受支持缓存字段。

**对外接口：**

- 发送单个诊断请求并返回 `CacheRequestEvidence`。

**依赖：** 现有 URL、Header、重试、协议错误和流式解析能力。

缓存字段识别范围保持与普通压测一致：

- OpenAI 风格：`prompt_tokens_details.cached_tokens`、`input_tokens_details.cached_tokens`。
- Anthropic 风格：`cache_read_input_tokens`、`cache_creation_input_tokens`、`cache_write_tokens`。
- Gemini 风格：`cachedContentTokenCount`。
- 网关风格：`cached_input_tokens`、`prompt_cache_hit_tokens`、`prompt_cache_miss_tokens`、`cache_miss_input_tokens` 及现有别名。

### 缓存专项执行器

**职责：**

- 按用户选择顺序执行 Case。
- 每个 Case 内严格执行 `prepare -> validate -> 判定`。
- 一个 Case 失败后记录证据并继续下一个 Case。
- 发布 `current_case`、`completed_cases`、`total_cases` 和四类结果计数。
- 响应停止事件，不再启动后续请求。
- 汇总并返回 `CacheDiagnosticsSummary`。

**对外接口：**

- 运行一次缓存专项任务并产生 Summary 与证据列表。

**依赖：** Case 定义模块、协议请求模块和进度/日志回调。

### 任务编排与存储适配

**职责：**

- 提供缓存专项任务启动分支，并复用运行数量限制、预检、状态、事件和停止机制。
- 使用现有 `test_tasks`、`test_results` 保存任务，不改变数据库结构。
- Summary 写入 `summary_json` 和 `summary_*.json`；阶段证据写入 `details_*.jsonl`。
- 写入轻量 HTML/Markdown 结果，保持现有下载文件体系完整。

**对外接口：** 独立 API 路由调用任务管理器启动专项任务。

**依赖：** Repository、TaskManager、ProgressHub 和结果目录配置。

`task_kind` 只写入脱敏后的 `config_json` 与 Summary。历史数据没有该字段时按普通压测处理，因此不需要迁移。

### 前端缓存专项配置页

**职责：**

- 独立显示连接配置和三个 Case 选择卡片，默认全部选中。
- 说明命中判定依赖上游缓存 usage，不以延迟猜测。
- 校验至少选择一个 Case，提交后进入独立结果路由。

**路由：**

- 路径：`/tests/cache-diagnostics`
- 名称：`cache-diagnostics`

**依赖：** 认证状态、协议默认值和缓存专项创建 API。

### 前端缓存专项结果页

**职责：**

- 显示任务状态、总体进度、当前 Case 和事件日志。
- 完成后显示四类摘要卡片和逐 Case 展开表。
- 每个 Case 同时展示准备与验证请求的状态、延迟、TTFT、Token、缓存证据和错误。
- 支持停止、返回配置页和下载 PDF。

**路由：**

- 路径：`/tests/cache-diagnostics/:id`
- 名称：`cache-diagnostics-result`

**依赖：** 缓存专项查询 API、现有 WebSocket 进度通道和 PDF 下载能力。

### 历史记录适配

**职责：**

- 增加“任务类型”展示，缓存专项任务标记为“缓存专项”。
- 缓存专项任务的“结果”与“运行页”操作都跳转到独立结果路由。
- 缓存专项任务不参加普通压测对比，也不提供普通压测“复制配置/续跑矩阵”操作。
- 历史页 PDF 导出继续复用现有下载入口。

### 缓存专项 PDF 模板

**职责：**

- 显示脱敏配置、Case 摘要和判定说明。
- 为每个 Case 展示准备/验证请求证据，错误长文本自动换行。
- TTFT 缺失显示“不可用”，真实零值显示 `0.0000s`。
- 不渲染普通压测的 RPM、TPM、容量推荐和矩阵图表。

**依赖：** 现有 Playwright PDF 渲染和临时文件原子替换流程。

## 模块交互

```text
侧边栏“缓存专项测试”
  -> /tests/cache-diagnostics
  -> POST /api/cache-diagnostics
  -> 域名策略与连接预检
  -> 创建 task_kind=cache_diagnostics 的任务
  -> CacheDiagnosticsRunner
       -> Case 1 prepare -> validate -> 判定 -> 发布进度
       -> Case 2 prepare -> validate -> 判定 -> 发布进度
       -> Case 3 prepare -> validate -> 判定 -> 发布进度
  -> 保存 Summary + JSONL 证据 + HTML/Markdown
  -> /tests/cache-diagnostics/:id 展示结果
  -> 历史记录按 task_kind 回到同一结果页
  -> 下载 PDF 时选择缓存专项模板并原子替换
```

失败隔离：单个请求失败只结束当前 Case；执行器继续后续 Case。任务创建、预检、存储或执行器级异常才使整个任务进入 `failed`。

## 文件组织

```text
backend/app/
├── api/
│   ├── cache_diagnostics.py        # 专项创建与查询接口
│   └── tests.py                    # 通用历史、停止和 PDF 下载类型分发
├── core/
│   ├── cache_diagnostics.py        # Case 定义、执行、判定和结果写入
│   ├── task_manager.py             # 专项任务生命周期编排
│   ├── repository.py               # 接受专项任务并持久化脱敏配置
│   └── pdf_report.py               # 缓存专项 PDF 模板分发
├── models/
│   └── schemas.py                  # 专项请求/响应及 task_kind 字段
└── main.py                         # 注册专项 API 路由
loadtest/
├── protocols.py                    # 消息型专项 payload 与缓存字段观测
├── streaming.py                    # 流式缓存 usage 观测保留
└── models.py                       # TokenUsage 增加缓存字段是否出现
frontend/src/
├── api/client.js                   # 缓存专项创建与查询 API
├── router/index.js                 # 两条独立缓存专项路由
├── App.vue                         # 独立侧边栏入口和标题
├── views/
│   ├── CacheDiagnostics.vue        # 专项配置页
│   ├── CacheDiagnosticsResult.vue  # 运行与结果页
│   └── History.vue                 # 按 task_kind 分流跳转和对比限制
└── components/
    └── HistoryTable.vue            # 任务类型及专项操作适配
tests/
└── test_core_refactors.py          # 后端专项执行、判定、接口与 PDF 简单回归
docs/specs/cache-diagnostics/
├── spec.md
├── plan.md
├── task.md
└── checklist.md
```

若前端专项页面样式可以直接使用现有全局 section、表格和卡片样式，不新增独立样式文件。

## 需求映射

| 功能需求 | 设计归属 |
|---|---|
| F1 | 独立前端配置页、路由和侧边栏入口 |
| F2 | `CacheDiagnosticsCreate` 与配置页 |
| F3 | 缓存 Case 定义模块和 Case 选择卡片 |
| F4 | 缓存专项执行器的串行阶段模型 |
| F5 | `CacheRequestEvidence`、结果页和 PDF 模板 |
| F6 | `CacheUsageEvidence.observed` 与固定判定顺序 |
| F7 | 执行器进度数据和结果摘要 |
| F8 | `task_kind`、现有任务存储和历史记录适配 |
| F9 | PDF 类型分发和缓存专项模板 |

## 技术决策

| 决策点 | 选择 | 理由 |
|---|---|---|
| 页面入口 | 独立菜单与独立路由 | 满足用户明确要求，避免与容量压测配置混淆 |
| 结果路由 | `/tests/cache-diagnostics/:id` | 创建、运行、历史回看均使用同一专项命名空间 |
| 后端接口 | 独立 `/api/cache-diagnostics` | 避免普通 `TestCreate` 承担两种不同语义 |
| 数据库存储 | 复用现有任务表，`config_json` 保存 `task_kind` | 不新增迁移，同时复用权限、历史、事件和保留策略 |
| 公共前缀 | 内置固定 4096 Token | 覆盖常见缓存门槛，并限制成本和范围 |
| Case 并发 | 全部顺序执行 | 保证缓存前置关系确定，避免负载竞争影响诊断 |
| 缓存判定 | 只依据响应缓存字段及其存在性 | 防止把低延迟或重复文本误判为缓存命中 |
| 缺失字段 | `observed=false`，结果“无法判定” | 与明确返回零的“未命中缓存”区分 |
| Anthropic 缓存 | 稳定内容块加 `ephemeral` | 使用协议支持的显式缓存控制 |
| OpenAI/Gemini 缓存 | 不注入私有缓存参数 | 依赖目标服务原生/网关缓存，避免协议校验失败 |
| 单 Case 失败 | 记录失败并继续 | 让一次执行尽可能获得其余场景结果 |
| 整体任务状态 | 执行流程完成即 `completed`，Case 失败由 Summary 表达 | 避免部分失败遮蔽已获得的诊断证据；执行器级异常仍为 `failed` |
| PDF | 专项模板，复用原子替换 | 保持历史下载可靠性且不展示无意义的吞吐指标 |
| 测试策略 | 聚焦判定、协议结构、接口和 HTML/PDF 字段的简单回归 | 遵循用户要求的 SDD 与简单测试，不扩展为复杂 TDD 套件 |
