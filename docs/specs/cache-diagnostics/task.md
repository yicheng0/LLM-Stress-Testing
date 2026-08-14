# 缓存专项测试 Tasks

## 文件清单

| 操作 | 文件 | 职责 |
|---|---|---|
| 修改 | `loadtest/models.py` | 缓存 usage 是否出现的证据字段 |
| 修改 | `loadtest/protocols.py` | 缓存字段识别和三协议专项请求体构造 |
| 修改 | `loadtest/streaming.py` | 流式响应保留缓存字段观测状态 |
| 新建 | `backend/app/core/cache_diagnostics.py` | 内置 Case、请求发送、判定、进度和结果文件 |
| 修改 | `backend/app/models/schemas.py` | 缓存专项创建/查询模型和任务类型输出 |
| 修改 | `backend/app/core/repository.py` | 通用任务创建适配和专项配置脱敏持久化 |
| 修改 | `backend/app/core/task_manager.py` | 缓存专项任务启动与生命周期编排 |
| 新建 | `backend/app/api/cache_diagnostics.py` | 缓存专项创建与查询 API |
| 修改 | `backend/app/api/tests.py` | 历史任务类型、停止和 PDF 下载分发兼容 |
| 修改 | `backend/app/core/pdf_report.py` | 缓存专项 PDF HTML 模板 |
| 修改 | `backend/app/main.py` | 注册缓存专项 API 路由 |
| 修改 | `frontend/src/api/client.js` | 缓存专项 API 客户端 |
| 修改 | `frontend/src/router/index.js` | 独立配置和结果路由 |
| 修改 | `frontend/src/App.vue` | 独立侧边栏入口、激活状态和页面标题 |
| 新建 | `frontend/src/views/CacheDiagnostics.vue` | 缓存专项配置页 |
| 新建 | `frontend/src/views/CacheDiagnosticsResult.vue` | 缓存专项运行与结果页 |
| 修改 | `frontend/src/views/History.vue` | 专项任务跳转、导出和对比限制 |
| 修改 | `frontend/src/components/HistoryTable.vue` | 任务类型与专项操作展示 |
| 修改 | `tests/test_core_refactors.py` | 后端专项行为的简单回归测试 |
| 已建 | `docs/specs/cache-diagnostics/spec.md` | 已批准需求 |
| 已建 | `docs/specs/cache-diagnostics/plan.md` | 已批准设计 |
| 新建 | `docs/specs/cache-diagnostics/checklist.md` | 最终验收清单 |

## T1: 保留缓存字段是否出现的证据

**文件：** `loadtest/models.py`、`loadtest/protocols.py`、`loadtest/streaming.py`

**依赖：** 无

**步骤：**

1. 在 Token usage 结果中增加 `cache_usage_observed`，默认 `false`，保证现有调用方兼容。
2. 集中维护受支持的缓存字段路径，检查原始 usage 是否实际包含其中任一字段。
3. 解析 OpenAI、Anthropic、Gemini 和网关缓存字段时，同时返回 Token 数和字段观测状态。
4. 流式解析累计最新 usage 时保留 `cache_usage_observed`，即使命中 Token 为零也不能丢失该状态。
5. 保持普通压测现有缓存 Token 计算和含缓存总量口径不变。

**验证：** 运行 `python -m py_compile loadtest/models.py loadtest/protocols.py loadtest/streaming.py`，期望无错误；运行相关现有缓存解析测试，期望全部通过。

## T2: 构造三个协议的专项消息请求

**文件：** `loadtest/protocols.py`

**依赖：** T1

**步骤：**

1. 增加接收消息序列的专项 payload 构造能力，不改变普通压测的 prompt payload 接口。
2. OpenAI Chat 使用 `messages`，OpenAI Responses 使用结构化 `input`。
3. Anthropic 将稳定公共前缀放入带 `cache_control: {type: ephemeral}` 的内容块，并保留后续多轮消息结构。
4. Gemini 将多轮消息转换为 `contents`，角色映射符合现有兼容口径。
5. 三种协议均复用现有模型、输出限制、温度和流式配置；不向 OpenAI 或 Gemini 添加未知缓存参数。

**验证：** 运行专项 payload 的简单测试，期望三个协议结构正确，Anthropic 仅稳定内容块带缓存控制，OpenAI/Gemini 不含未知缓存字段。

## T3: 定义内置 Case 和固定公共前缀

**文件：** `backend/app/core/cache_diagnostics.py`

**依赖：** T2

**步骤：**

1. 定义 `repeat`、`multiturn`、`variable_suffix` 三个 Case 的固定名称和说明。
2. 使用现有 Token 估算/Prompt 能力生成目标 4096 Token 的无敏感公共前缀，并记录实际 Token 数。
3. 为重复请求 Case 生成完全相同的准备和验证消息。
4. 为多轮 Case 生成首轮准备消息，以及保留首轮上下文并追加用户消息的验证序列。
5. 为尾部变化 Case 生成相同公共前缀、不同短尾部的两次请求。
6. 只把 Case 结构摘要和 Token 数放入结果，不保存完整公共前缀正文。

**验证：** 运行 Case 结构测试，期望重复请求完全一致，多轮验证保留准备上下文且新增一轮，尾部变化只改变公共前缀后的内容，实际公共前缀 Token 数达到目标范围。

## T4: 实现单请求证据采集

**文件：** `backend/app/core/cache_diagnostics.py`

**依赖：** T1、T2、T3

**步骤：**

1. 使用现有 URL、Header、超时、重试和协议错误解析发送单个专项请求。
2. 非流式响应读取 usage，生成状态码、总延迟、Token、缓存观测和错误证据。
3. 流式响应解析首数据时间和最终 usage，生成 TTFT 与缓存证据。
4. 对 HTTP、超时、客户端和协议错误建立一致的错误类型与错误信息。
5. 证据中不包含请求正文、完整响应、Header 或 API Key。

**验证：** 使用伪响应运行简单测试，期望流式和非流式均生成完整证据；缺失缓存字段为 `observed=false`；明确零命中为 `observed=true` 且命中 Token 为零。

## T5: 实现 Case 串行执行与判定

**文件：** `backend/app/core/cache_diagnostics.py`

**依赖：** T4

**步骤：**

1. 按用户提交的 `case_ids` 顺序逐个执行 Case。
2. 每个 Case 严格串行执行准备请求，再执行验证请求。
3. 准备请求失败时标记失败阶段且不发送该 Case 的验证请求。
4. 验证请求失败时记录验证阶段失败；随后继续下一个 Case。
5. 根据已批准的固定优先级判定 `cache_hit`、`cache_miss`、`unverifiable`、`failed`。
6. 每个阶段发布当前 Case、完成数量、总数和四类结果计数；请求前后检查停止事件。
7. 生成 Summary、逐阶段 JSONL、轻量 Markdown 和 HTML 文件。

**验证：** 运行执行器简单测试，期望调用顺序为 `prepare -> validate`，单 Case 失败不阻止下一个 Case，四种结果和摘要计数正确，停止后不再启动后续 Case。

## T6: 增加专项请求模型和任务类型字段

**文件：** `backend/app/models/schemas.py`

**依赖：** 无

**步骤：**

1. 定义 `CacheDiagnosticsCreate`，限制协议、Case ID、超时、重试和输出参数。
2. 校验至少选择一个 Case，去重后最多三个，拒绝未知 Case。
3. 定义缓存专项查询输出所需模型或复用现有输出模型的公共字段。
4. 在任务输出中增加 `task_kind`，默认兼容为 `load_test`。

**验证：** 运行模型校验测试，期望默认三个 Case 可通过；空列表、未知 Case 和重复后为空均被拒绝；普通任务默认类型不变。

## T7: 适配任务持久化与敏感信息脱敏

**文件：** `backend/app/core/repository.py`

**依赖：** T6

**步骤：**

1. 让任务创建接受普通压测和缓存专项创建模型，统一读取任务基础字段。
2. 专项配置中写入 `task_kind=cache_diagnostics` 及固定并发、矩阵和缓存模式元数据。
3. 继续使用现有敏感字段递归脱敏，确认 `api_key` 不进入 `config_json` 和 Summary。
4. 不修改数据库表、兼容列和历史任务数据。

**验证：** 创建临时专项任务后读取 `config_json`，期望包含任务类型和 Case ID，但不包含 API Key；普通任务创建测试仍通过。

## T8: 接入任务管理器生命周期

**文件：** `backend/app/core/task_manager.py`

**依赖：** T5、T7

**步骤：**

1. 增加缓存专项启动入口，复用最大运行任务数和连接预检。
2. 创建任务、事件、停止事件和异步执行任务。
3. 执行时复用 queued、running、stopping、completed、failed、cancelled 状态机。
4. 调用专项执行器并保存 Summary、JSONL、Markdown 和 HTML 文件路径。
5. Case 层失败保留在 Summary 中，执行流程完成时任务为 `completed`；执行器级异常为 `failed`。
6. 用户停止时保持现有最终状态转换和事件清理逻辑。

**验证：** 运行任务管理器简单测试，期望创建后可读取父任务与结果行；成功执行保存文件；执行器异常保存错误；停止事件能阻止后续 Case。

## T9: 提供独立缓存专项 API

**文件：** `backend/app/api/cache_diagnostics.py`、`backend/app/main.py`

**依赖：** T6、T8

**步骤：**

1. 注册前缀 `/api/cache-diagnostics` 的独立路由。
2. 创建接口执行用户认证、角色对应域名策略、参数校验和任务启动。
3. 查询接口执行任务权限校验和 `task_kind` 校验，返回配置、进度、事件和 Summary。
4. 复用现有启动响应格式；错误信息保持用户可理解且不包含敏感字段。
5. 保持停止接口走现有 `/api/tests/{task_id}/stop`。

**验证：** 运行 API 简单测试，期望创建返回任务 ID；未登录被拒绝；错误域名按角色被拒绝；普通任务访问专项查询接口被拒绝；API Key 不出现在响应。

## T10: 让历史任务识别缓存专项类型

**文件：** `backend/app/api/tests.py`、`backend/app/models/schemas.py`

**依赖：** T6、T7

**步骤：**

1. 从任务脱敏配置读取 `task_kind`，历史任务缺失时返回 `load_test`。
2. 列表和单任务输出包含 `task_kind`。
3. 普通报告数据回填和图表构建遇到缓存专项 Summary 时跳过负载测试专属计算。
4. 通用停止、删除、事件和文件下载保持可用于缓存专项任务。

**验证：** 运行历史列表简单测试，期望缓存专项任务类型正确，旧任务显示普通压测；读取专项任务不会触发普通压测图表或延迟回填错误。

## T11: 生成缓存专项 PDF

**文件：** `backend/app/core/pdf_report.py`、`backend/app/api/tests.py`

**依赖：** T5、T10

**步骤：**

1. PDF HTML 分发先识别 `task_kind=cache_diagnostics`，再处理矩阵和普通单次报告。
2. 输出脱敏配置、判定口径、Case 总数和四类摘要卡片。
3. 为每个 Case 输出判定、失败阶段以及准备/验证两阶段的状态码、总延迟、TTFT、输入/输出/总 Token、缓存命中/创建/含缓存 Token、命中率和错误。
4. 缺失 TTFT 显示“不可用”，真实零值显示 `0.0000s`；长错误自动换行，表头在分页时重复。
5. 缓存专项不构建普通吞吐图表，不展示 RPM、QPS、TPM 或容量结论。
6. 保持每次下载重新渲染、临时文件和原子替换逻辑。

**验证：** 渲染专项 HTML 并断言配置、四种判定和两阶段字段存在；生成示例 PDF 后运行 `pdfinfo`、`pdftotext` 和逐页 PNG 检查，期望 A4、无截断、无重叠且不含 API Key。

## T12: 增加前端 API 和独立路由入口

**文件：** `frontend/src/api/client.js`、`frontend/src/router/index.js`、`frontend/src/App.vue`

**依赖：** T9

**步骤：**

1. 增加创建和查询缓存专项任务的客户端方法。
2. 注册 `/tests/cache-diagnostics`，路由名固定为 `cache-diagnostics`。
3. 注册 `/tests/cache-diagnostics/:id`，路由名固定为 `cache-diagnostics-result`。
4. 侧边栏新增与“新建测试”“自定义 Case”平级的“缓存专项测试”入口。
5. 补充激活路径和两个页面标题；现有路由顺序确保动态 `:id` 不吞掉固定路径。

**验证：** 运行前端构建，期望无路由或导入错误；检查生成路由，期望路径、名称、菜单和标题准确。

## T13: 实现缓存专项配置页

**文件：** `frontend/src/views/CacheDiagnostics.vue`

**依赖：** T12

**步骤：**

1. 复用现有协议、域名权限、Endpoint 默认值和 API Key 表单交互。
2. 展示名称、协议、域名、Endpoint、API Key、模型、输出限制、温度、超时、重试和流式配置。
3. 展示三个内置 Case 选择卡片并默认全部选中，说明固定 4096 Token 公共前缀和串行执行方式。
4. 明确提示命中只依据上游缓存字段；无字段会显示“无法判定”。
5. 校验至少选一个 Case，提交成功后跳转 `/tests/cache-diagnostics/{id}`。
6. 提交期间禁用重复启动，错误通过现有消息组件展示。

**验证：** 运行前端构建；浏览器检查默认三项勾选、协议切换、域名权限、表单校验、提交跳转和窄屏布局。

## T14: 实现缓存专项运行与结果页

**文件：** `frontend/src/views/CacheDiagnosticsResult.vue`

**依赖：** T12、T9

**步骤：**

1. 查询缓存专项任务并连接现有任务 WebSocket，断线时使用轻量轮询刷新状态。
2. 运行中显示总体进度、当前 Case、四类实时计数和事件日志。
3. 提供停止按钮，调用现有停止接口；终态后停止轮询和 WebSocket。
4. 完成后显示总数、命中、未命中、无法判定和失败摘要。
5. 按 Case 展示准备和验证请求的状态码、延迟、TTFT、Token、缓存字段、命中率和错误。
6. 使用明确颜色区分四种 Case 判定；不可用值显示“不可用”，零值仍显示零。
7. 提供“再次测试”“历史记录”和“下载 PDF”操作。

**验证：** 运行前端构建；用模拟 Summary 检查四种状态、两阶段字段、停止流程、终态刷新和 PDF 下载链接。

## T15: 适配历史记录的专项分流

**文件：** `frontend/src/views/History.vue`、`frontend/src/components/HistoryTable.vue`

**依赖：** T10、T12

**步骤：**

1. 历史表增加任务类型，普通任务显示“负载测试”，专项任务显示“缓存专项”。
2. 专项任务的结果和运行操作统一跳转 `/tests/cache-diagnostics/{id}`。
3. 专项任务隐藏普通“复跑”和“续跑矩阵”操作。
4. 选择普通任务达到 2-4 条时才允许对比；选中专项任务时禁用普通对比并给出提示。
5. 单条专项任务仍可通过现有历史导出入口下载 PDF、Summary、Details、HTML 和 Markdown。

**验证：** 运行前端构建；浏览器检查普通任务行为不变，专项任务标签、跳转、操作隐藏、对比限制和导出正确。

## T16: 增加聚焦的简单回归测试

**文件：** `tests/test_core_refactors.py`

**依赖：** T1-T11

**步骤：**

1. 验证缓存字段缺失和明确为零能被区分。
2. 验证三个 Case 的消息关系和 4096 Token 公共前缀。
3. 验证四种判定及单 Case 失败后继续执行。
4. 验证任务持久化包含 `task_kind` 且不含 API Key。
5. 验证专项 PDF HTML 包含摘要和两阶段指标，不包含普通吞吐标题。
6. 保持测试为少量行为断言，不增加复杂端到端测试框架或大规模 fixture。

**验证：** 运行 `PYTHONPATH=. python -m unittest tests.test_core_refactors -q`，期望全部通过。

## T17: 完成构建与端到端验收

**文件：** 本任务全部修改文件

**依赖：** T1-T16

**步骤：**

1. 运行 Python 编译检查和后端完整现有测试。
2. 使用现有 lockfile 和依赖目录运行前端生产构建，不修改或提交 `node_modules` 与无关 lockfile。
3. 本地启动前后端，使用可控的模拟上游分别返回缓存命中、明确零命中、无缓存字段和失败响应。
4. 从独立菜单启动三个 Case，观察串行顺序、实时进度、结果页、历史回看和停止行为。
5. 下载专项 PDF，执行文本提取和逐页图片检查。
6. 运行 `git diff --check`，确认只包含本功能文件和已批准 SDD 文档。

**验证：** 后端测试退出码为 0，前端构建成功，端到端四类判定与页面/PDF一致，`git diff --check` 无错误。

## 执行顺序

```text
T1 -> T2 -> T3 -> T4 -> T5
T6 -> T7
T5 + T7 -> T8 -> T9
T6 + T7 -> T10
T5 + T10 -> T11
T9 -> T12 -> T13
T9 + T12 -> T14
T10 + T12 -> T15
T1-T11 -> T16
T1-T16 -> T17
```
