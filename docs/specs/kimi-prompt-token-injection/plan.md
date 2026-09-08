# Kimi Prompt Token 注入检测 Plan

## 架构概览

在现有 Kimi Suite Runner 上增加一个独立的 Prompt Token 注入检测 Case。Runner 为该 Case 生成固定测试提示词，按当前协议构造请求，采集协议响应中的输入 Token usage，并调用独立判定逻辑计算 Token 差值、比例和结论。判定结果写入现有 scenario/case 结果结构，同时通过已有 ProgressHub 实时推送到结果页。

前端复用现有 Kimi Suite 配置页的 Case 选择表和结果页的 Ant Design 表格、详情抽屉。新增 Case 自动出现在配置表中；结果页沿用现有状态轮询，仅补充 Token 检测证据字段展示。现有 9 个 Case 的请求和断言逻辑不改。

## 核心数据结构

### PromptTokenEvidence

- `local_prompt_tokens`：本地估算 Token 数量；无法估算时为 `null`
- `estimation_method`：估算方法标识，例如 `tiktoken` 或 `char_fallback`
- `upstream_input_tokens`：上游 usage 中提取的输入 Token；缺失时为 `null`
- `delta_tokens`：上游值减本地值；不可比较时为 `null`
- `delta_ratio`：差值相对本地值的比例；不可比较时为 `null`
- `tolerance_tokens`：本次判定使用的绝对容差
- `tolerance_ratio`：本次判定使用的相对容差
- `status`：`passed`、`suspected_injection`、`unverifiable`、`unsupported` 或 `request_failed`
- `detail`：面向用户的简短判定说明

### Kimi Prompt Token Scenario

- `id`：固定为 `prompt_token_injection`
- `name`：Prompt Token 注入检测
- `prompt`：固定、短且可审计的测试提示词
- `overrides`：不额外注入 thinking、tools、stop 等其他能力参数
- `assertion`：`prompt_tokens`

### Progress Case Row

沿用现有实时 Case 行结构，并在该 Case 完成后增加：

- `token_evidence`：脱敏后的 PromptTokenEvidence
- `elapsed_sec`、`retry_count`、`manual_rerun_count`
- `status`：实时状态或最终判定状态

## 核心接口

### `estimate_prompt_tokens`

接收协议和待发送消息，返回本地 Token 数与估算方法。优先使用项目现有 Token 计算能力；不可用时使用明确标识的字符回退估算，不伪装成精确值。

### `extract_input_tokens`

从 OpenAI-compatible、Anthropic 和 Gemini 的响应 usage 结构提取输入 Token。字段不存在时返回不可比较结果，不使用 0 代替缺失值。

### `assert_prompt_token_evidence`

接收本地估算值、上游输入 Token、绝对/相对容差和协议能力，返回统一 PromptTokenEvidence。判定顺序为请求失败、协议不支持、usage 缺失、本地估算不可用、容差内通过、超出容差疑似注入。

### `build_protocol_request`

扩展现有协议请求构造，使新增 Case 与 OpenAI-compatible、Anthropic、Gemini 请求格式和鉴权方式一致；不把检测专用字段发送给上游。

## 模块设计

### Kimi Suite Runner

**职责：** 注册第 10 个 Case，生成请求，提取输入 Token，执行判定，写入结果和实时进度。

**位置：** `backend/app/core/kimi_suite.py`。

**依赖：** 现有协议 URL/Header 构造、Token usage 解析、ProgressHub 回调。

### Kimi Suite Schema

**职责：** 将默认 Case 数量上限从 9 扩展到 10，并允许可选 Token 检测容差配置；保留未知 Case、空 Case 和重复 Case 校验。

**位置：** `backend/app/models/schemas.py`。

**依赖：** 现有 Pydantic 校验模型。

### Kimi 配置页

**职责：** 显示并选择第 10 个 Case，默认选中；展示 Case 描述和数量上限。

**位置：** `frontend/src/views/KimiSuite.vue`。

**依赖：** 现有 Ant Design `a-table`、`a-checkbox`、`a-tag`。

### Kimi 结果页

**职责：** 在实时结果表中显示 Prompt Token 检测状态和摘要；在详情抽屉中展示本地估算、上游 usage、差值、比例、容差和判定说明。

**位置：** `frontend/src/views/KimiSuiteResult.vue`。

**依赖：** 现有 Ant Design `a-table`、`a-drawer`、`a-descriptions`、`a-tag`、轮询数据结构。

### 回归测试

**职责：** 覆盖 Case 注册、请求参数隔离、协议 usage 提取、四种判定结果、脱敏结果和旧 Case 兼容。

**位置：** `tests/test_kimi_suite.py`。

**依赖：** 本地可控字典响应，不访问真实供应商接口。

## 模块交互

```text
Kimi 配置页选择第 10 个 Case
  -> POST /api/kimi-suite
  -> TaskManager 启动 Kimi Suite
  -> Runner 生成固定 Prompt
  -> 协议请求构造器生成 URL/Header/Body
  -> 上游响应
  -> 提取 input tokens + 本地估算 tokens
  -> Prompt Token 判定器
  -> ProgressHub 推送实时 Case 行
  -> 结果页表格与详情抽屉刷新
  -> summary/details/report 保存脱敏证据
```

## 文件组织

```text
docs/specs/kimi-prompt-token-injection/
└── plan.md                         # 本技术设计

backend/app/core/kimi_suite.py     # Case、Token 估算、判定和实时结果
backend/app/models/schemas.py      # Case 数量和配置校验
frontend/src/views/KimiSuite.vue   # 第 10 个 Case 选择
frontend/src/views/KimiSuiteResult.vue # Token 证据展示
tests/test_kimi_suite.py           # 单元与回归测试
```

## 技术决策

| 决策点 | 选择 | 理由 |
|---|---|---|
| Token 估算 | 优先复用现有 Token 能力，必要时显式字符回退 | 保证本地环境缺少 tokenizer 时仍能运行，但不虚构精度 |
| 注入判定 | 绝对容差与相对容差同时满足才算通过 | 同时覆盖短 Prompt 的固定开销和长 Prompt 的比例偏差 |
| 缺失 usage | `unverifiable` / `unsupported` | 缺少证据不能推断通过，也不把缺失值当 0 |
| 结果同步 | 复用现有 ProgressHub + 1.5 秒轮询 | 不新增接口，不改变现有任务生命周期 |
| 敏感信息 | 只保存数值、方法和摘要，不保存完整 Prompt/响应 | 满足现有结果脱敏约束 |
| 旧 Case 兼容 | 新增 ID，保持原 ID 与顺序不变 | 避免历史配置和回归测试失效 |
