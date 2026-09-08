# Kimi 能力测试集 Plan

## 架构概览

新增独立的 Kimi Suite API、执行器和前端页面。Suite 使用现有任务与结果存储模型，通过 `task_kind=kimi_suite` 与普通压测和缓存专项区分；不新增数据库表。

执行链为：配置页提交 Suite -> API 校验连接与 Case -> 任务管理器创建后台任务 -> Suite Runner 串行执行选中的 Case -> 每个 Case 内串行执行子场景 -> 保存 JSON、JSONL、Markdown、HTML -> 结果页通过轮询和现有 WebSocket 展示进度与最终结果。

## 核心数据结构

### KimiSuiteCreate

- `name`：测试集名称，默认“Kimi 能力测试集”。
- `base_url`、`api_key`、`model`、`endpoint`：连接配置；模型默认 `kimi-k3`，Endpoint 默认 `/v1/chat/completions`。
- `enable_stream`、`timeout_sec`、`connect_timeout_sec`、`max_retries`、`retry_backoff_base`、`retry_backoff_max`：共享执行参数。
- `case_ids`：选择的内置 Case ID，默认全部 9 项；去重后必须为已知非空列表。
- `task_kind`：固定为 `kimi_suite`。

内置 Case ID 固定为：

- `cache_repeat`
- `cache_multiturn`
- `cache_variable_suffix`
- `thinking`
- `json_output`
- `stop`
- `sampling`
- `tool_call`
- `output_tokens`

### KimiCaseDefinition

- `case_id`、`case_name`、`description`：稳定标识和展示信息。
- `scenarios`：该 Case 的子场景列表。
- `kind`：`capability` 或 `cache`。

### KimiScenarioDefinition

- `scenario_id`、`scenario_name`、`prompt`。
- `messages`：需要多轮上下文时使用；与 `prompt` 二选一。
- `request_overrides`：该场景独有的 thinking、`response_format`、`stop`、`temperature`、`top_p`、`tools`、`tool_choice`、`max_tokens`。
- `assertion_kind`：选择对应断言器。

### KimiScenarioResult

- 请求证据：场景标识、脱敏参数摘要、请求次数、HTTP 状态、耗时、TTFT、重试次数。
- 响应证据：`finish_reason`、content 摘要、tool calls 摘要、thinking 证据、原始 usage 的脱敏副本。
- 判定：`passed`、`assertion_failed`、`unsupported`、`unverifiable`、`request_failed`、`cache_hit` 或 `cache_miss`。
- 错误：失败阶段、错误类型、脱敏错误信息和断言详情。

### KimiCaseResult

- Case 元数据和全部场景结果。
- 聚合状态：`passed`、`failed`、`unsupported`、`unverifiable` 或 `cancelled`。
- 总耗时、首个有效 TTFT、累计重试次数、失败原因。
- `manual_rerun_count`：人工重跑次数，初始为 0。

聚合规则：任一场景执行失败或断言失败则 Case 为 `failed`；否则存在 `unsupported` 时为 `unsupported`；否则存在 `unverifiable` 时为 `unverifiable`；其余为 `passed`。缓存 Case 只有验证请求明确返回大于零缓存 Token 时通过，明确返回零时失败，字段缺失时无法判定。

### KimiSuiteSummary

- `config`：不包含 API Key 的配置快照及脱敏 Key。
- `results`：总 Case 数和通过、失败、不支持、无法判定、取消数量。
- `cases`：按提交顺序保存的 `KimiCaseResult`。
- `status`：`completed` 或 `cancelled`。部分 Case 失败不使后台任务本身失败。

## 核心接口

### `POST /api/kimi-suite`

创建 Suite。执行现有 Base URL 权限校验和一次最小预检，成功后返回现有 `StartTestOut` 结构。预检错误必须使用 API Key 脱敏后再返回或记录。

### `GET /api/kimi-suite/{task_id}`

返回任务状态、脱敏配置、实时进度、Suite Summary、事件和时间字段。只有 `task_kind=kimi_suite` 的任务可以通过该接口读取。

### `POST /api/kimi-suite/{task_id}/cases/{case_id}/rerun`

仅允许已结束的 Kimi Suite 重跑原任务中已选择的单个 Case。请求体只接收 API Key，连接配置沿用原任务；新结果替换该 Case 的旧结果，`manual_rerun_count` 加一，重新计算总体计数并覆盖结果文件。运行中的 Suite 或未知 Case 返回明确错误。同一任务的重跑通过任务管理器注册为活动任务，因此继续受停止机制和全局任务数限制。

### 停止与报告接口

- 停止继续复用 `POST /api/tests/{task_id}/stop`。
- 历史列表继续复用现有任务查询接口，通过 `task_kind` 路由到 Kimi 结果页。
- Markdown、HTML 和已有通用下载能力继续使用结果表中的文件路径；首版不新增专用 PDF 模板。

## 模块设计

### Kimi Suite API

**职责：** 请求校验、权限控制、创建/读取任务、单 Case 重跑。

**对外接口：** `/api/kimi-suite` 路由组。

**依赖：** 现有认证、Base URL 策略、Repository、TaskManager 和 ProgressHub。

### Kimi Case Catalog

**职责：** 定义 9 个 Case、子场景、请求参数和断言类型。定义为不可变数据，后端是唯一事实源；前端通过静态同名清单展示选择卡片，不允许用户编辑内置请求体。

具体场景：

- 思考控制：`thinking.type=enabled` 与 `thinking.type=disabled`。开启场景要求观察到 reasoning/thinking 内容；关闭场景要求请求成功且未观察到 reasoning/thinking 内容。上游明确拒绝参数为 `unsupported`，成功但缺少足够证据为 `unverifiable`。
- JSON 输出：发送 `response_format={"type":"json_object"}`，要求 content 可解析为 JSON 对象并包含 Prompt 指定键。
- stop：数字停止符和中文停止符两个场景，要求停止符之后的禁止内容不出现；同时记录 `finish_reason`，但不单独依赖其取值通过。
- 采样：低温度和 `top_p` 两个场景，只验证参数被接口接受并返回非空有效响应，不以两次文本是否不同证明采样效果。
- 工具调用：关闭 thinking，提供单个天气函数并强制该工具，要求返回对应函数名及可解析、字段正确的 JSON 参数。
- 输出 Token：使用 5、20、80 三个上限，要求 usage 中存在输出 Token 且不超过上限；usage 缺失为 `unverifiable`。
- 三个缓存 Case：复用现有公共前缀生成、消息关系、usage 解析和缓存分类口径；每项执行一次建立请求和一次验证请求。

### Kimi HTTP Executor

**职责：** 构建 OpenAI Chat Completions 请求，处理流式/非流式响应、重试、TTFT、content、thinking、tool calls、finish reason 和 usage 证据。

流式解析扩展现有 SSE 解析能力，累计 `delta.content`、reasoning/thinking 字段和增量 tool calls；非流式从 `choices[0].message` 提取同样的统一证据。参数不支持只在上游返回明确的参数/字段拒绝时分类为 `unsupported`；认证、限流、超时和服务错误均为 `request_failed`。

### Assertion Engine

**职责：** 对统一响应证据运行纯函数断言，返回状态、断言项和失败原因。断言器不访问网络，便于用固定响应进行单元测试。

### Kimi Suite Runner

**职责：** 串行调度 Case 和场景、响应停止事件、发布进度、聚合状态并写结果文件。单个场景失败只结束当前 Case 的剩余必要步骤，不阻断后续 Case；工具、JSON 等聚合 Case 会保留已完成的所有子场景证据。

进度字段包括 `current_case`、`current_case_id`、`current_scenario`、`completed_cases`、`total_cases` 和五类 Case 计数。

### 前端配置与结果页

**配置页职责：** 展示连接参数、9 个 Case 选择卡片、预计 Case/场景请求数和启动按钮。API Key 只保存在当前表单内。

**结果页职责：** 展示实时进度、总体计数和设计截图风格的 Case 表格；每行可展开查看子场景参数、断言和 usage；已结束 Case 提供重跑按钮，点击时要求重新输入 API Key。状态颜色区分通过、失败、不支持和无法判定，避免全部异常都显示为测试失败。

## 模块交互

1. 配置页提交 `KimiSuiteCreate`。
2. API 完成权限和预检后，TaskManager 以 `kimi_suite` 创建通用任务记录。
3. Runner 从 Catalog 取出用户选择的 Case，按顺序调用 Executor。
4. Executor 返回统一响应证据，Assertion Engine 给出场景结论。
5. Runner 聚合 Case 与 Suite 状态，持续发布进度和事件。
6. Runner 写入 `summary.json`、`details.jsonl`、Markdown 和 HTML，并由 Repository 保存路径和汇总 JSON。
7. 结果页读取历史数据并订阅现有进度 WebSocket。
8. 单 Case 重跑时，TaskManager 读取旧 Summary，只执行目标 Case，替换结果后原子覆盖四类文件和数据库汇总。

## 文件组织

```text
backend/app/api/kimi_suite.py          # Suite 创建、读取和 Case 重跑 API
backend/app/core/kimi_suite.py         # Catalog、Executor、断言、Runner 和报告输出
backend/app/models/schemas.py          # Kimi Suite 请求与响应模型
backend/app/core/task_manager.py       # Suite 启动、重跑和后台生命周期
backend/app/main.py                    # 注册 Kimi Suite 路由
frontend/src/views/KimiSuite.vue       # 配置页
frontend/src/views/KimiSuiteResult.vue # 运行及结果页
frontend/src/api/client.js             # Suite API 客户端
frontend/src/router/index.js           # 页面路由
frontend/src/App.vue                   # 导航和标题
frontend/src/views/History.vue         # Kimi 任务历史跳转
tests/test_kimi_suite.py               # 后端单元与 API 测试
```

## 技术决策

| 决策点 | 选择 | 理由 |
|---|---|---|
| 任务存储 | 复用现有任务、事件和结果表 | 避免数据库迁移，并保持历史、停止和下载能力一致 |
| 执行方式 | Suite 和 Case 串行，Case 内子场景串行 | 能准确归因参数行为，并避免缓存请求被并发干扰 |
| 请求实现 | 独立 Kimi Executor，复用现有协议/usage/SSE 基础函数 | 普通压测执行器不保留文本、工具和 thinking 证据，直接扩展会扩大回归范围 |
| 缓存判定 | 复用现有缓存消息关系和 usage 口径 | 保持“只依据上游字段”的既有严格规则 |
| 采样判定 | 验证兼容性，不验证随机性 | 少量请求无法可靠证明概率分布是否生效 |
| 不支持判定 | 仅依据明确的上游参数拒绝 | 防止把认证、网关或服务异常错误归类为能力不支持 |
| Case 重跑 | 更新同一任务的目标 Case | 符合结果表操作语义，且保留完整 Suite 上下文 |
| API Key | 不持久化；创建和重跑时单独提供 | 满足现有安全边界，历史任务不能自动携带凭据重跑 |
| 报告范围 | JSON、JSONL、Markdown、HTML | 满足可复核和现有下载能力，首版不扩展 PDF 模板 |
