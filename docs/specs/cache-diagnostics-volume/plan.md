# 缓存专项可配置样本量 Plan

## 架构概览

本次改动在现有缓存专项入口、API、任务生命周期和 PDF 下载路径上做增量扩展，不新增路由或数据库字段：

1. 创建请求增加公共前缀 Token 长度和每个 Case 请求次数两个配置字段。
2. 公共前缀生成器按照用户目标长度构造前缀，并记录目标值与本地实际估算值。
3. 专项执行器把原有固定 `prepare -> validate` 扩展为每个 Case 的串行请求序列：第 1 次为缓存建立，第 2 次至第 N 次为缓存验证。
4. 每个业务请求独立保存证据和判定；Case 聚合器基于验证请求计算计数和命中率；任务聚合器合并全部 Case 的可判定验证样本计算总体命中率。
5. 实时进度改为请求级进度，同时保留 Case 级进度字段，兼容现有结果页和历史状态。
6. Summary 使用新的请求列表结构保存多次请求；读取层提供旧版 `prepare/validate` 到统一请求列表的兼容转换，不修改旧文件。
7. 结果页、Markdown、HTML 和 PDF 按新结构展示配置、统计和逐请求证据；PDF 依赖现有表头重复和自动分页样式。

普通压测、矩阵压测、自定义 Case、认证、停止、历史列表、文件保留和 PDF 原子替换流程保持不变。

## 核心数据结构

### CacheDiagnosticsCreate

在现有缓存专项创建配置上增加：

- `input_tokens`：公共前缀目标 Token，默认 `4096`，最小 `1`。
- `requests_per_case`：每个 Case 的业务请求次数，默认 `10`，范围 `2..100`。

`input_tokens` 继续写入现有任务基础字段，用于历史记录和配置回显；不代表每一次请求的上游实际输入 Token。计划请求总数由 `选中 Case 数 × requests_per_case` 派生，不持久化为数据库列。

### CacheRequestEvidence

在现有单请求证据上补充请求序列语义：

- `request_index`：Case 内从 1 开始的业务请求序号。
- `phase`：第 1 次固定为 `prepare`，其余固定为 `validate`，保持旧数据兼容。
- `phase_label`：展示口径分别为“缓存建立”和“缓存验证”。
- `classification`：验证请求的 `cache_hit`、`cache_miss`、`unverifiable` 或 `failed`；缓存建立请求为空。
- 现有 `ok`、HTTP 状态、延迟、TTFT、Token、缓存字段和错误字段保持不变。

请求正文和模型回复只在当前请求链内存中使用，不进入证据对象。

### CacheCaseResult

逐 Case 结果调整为：

- `case_id`、`case_name`、`description`。
- `planned_requests`、`executed_requests`。
- `validation_requests`：已执行验证请求数量，包含成功、无法判定和失败样本。
- `cache_hit_requests`、`cache_miss_requests`、`unverifiable_requests`、`failed_requests`。
- `decidable_requests`：命中数与未命中数之和。
- `cache_hit_rate`：命中数除以可判定数；可判定数为零时为空。
- `status`：Case 汇总结论。
- `failure_phase`、`error_type`、`error_message`：兼容旧版摘要字段，主要用于缓存建立失败或 Case 没有完成验证的情况。
- `requests`：按执行顺序保存全部 `CacheRequestEvidence`。

Case 汇总结论优先级：

1. 缓存建立失败，或没有任何验证请求成功执行：`failed`。
2. 可判定验证样本为零且存在成功但无缓存字段的验证请求：`unverifiable`。
3. 可判定样本中至少一个命中：`cache_hit`。
4. 可判定样本全部未命中：`cache_miss`。

部分验证请求失败不会覆盖已经取得的命中率；失败数独立展示。

### CacheDiagnosticsSummary

`config` 增加：

- `cache_prefix_target_tokens`
- `cache_prefix_actual_tokens`
- `requests_per_case`

`results` 增加：

- `planned_requests`
- `executed_requests`
- `validation_requests`
- `cache_hit_requests`
- `cache_miss_requests`
- `unverifiable_requests`
- `failed_requests`
- `decidable_requests`
- `cache_hit_rate`

现有 `total_cases`、四类 Case 数继续保留，避免已有页面和外围调用立即失效。总体命中率直接用全部 Case 的请求计数合并计算。

### CacheDiagnosticsProgress

实时进度包含：

- `current_case`、`current_case_id`
- `current_request_index`、`requests_per_case`
- `completed_cases`、`total_cases`
- `executed_requests`、`planned_requests`
- 请求级命中、未命中、无法判定、失败计数和总体命中率

进度百分比优先使用 `executed_requests / planned_requests`；旧任务或旧快照没有请求级字段时回退到 Case 进度。

## 核心接口

### 创建缓存专项任务

`POST /api/cache-diagnostics`

- 接收公共前缀 Token 长度和每个 Case 请求次数。
- 服务端校验 Token 为正整数、请求次数在 `2..100`。
- 保持响应结构、认证、域名策略和预检流程不变。

### 获取缓存专项任务

`GET /api/cache-diagnostics/{task_id}`

- 返回新增配置、请求级进度和新版 Summary。
- 读取旧版 Summary 时保持原始数据，不在数据库或文件中写回迁移结果。

### 停止和下载

- 停止仍使用 `POST /api/tests/{task_id}/stop`，执行器在每次业务请求与重试前检查停止事件。
- PDF 仍使用 `GET /api/tests/{task_id}/download/pdf`，每次根据最新 Summary 重新生成并原子替换。

## 模块设计

### 配置与校验模块

**职责：**

- 定义 Token 长度和请求次数的默认值及边界。
- 计算计划总请求数并在配置页即时展示。
- 让历史任务缺少 `requests_per_case` 时使用旧版展示策略，而不是自动假定为 10。

**对外接口：** 缓存专项创建模型和前端表单配置。

**依赖：** 现有认证与域名策略。

### 公共前缀与 Case 请求序列模块

**职责：**

- 按 `input_tokens` 生成公共前缀。
- 为每个 Case 维护下一次请求所需的内存上下文。
- 重复请求：所有请求保持相同消息结构。
- 尾部变化：第 1 次使用建立尾部，所有验证请求使用固定验证尾部，公共前缀不变。
- 多轮对话：第 1 次建立首轮上下文；每次成功回复仅保存在内存中，下一次验证追加该真实回复和新一轮用户消息。

**对外接口：** 根据 Case、请求序号和当前内存上下文产生下一次消息序列。

**依赖：** 现有 Prompt 生成、Token 估算和协议 payload 构造。

### 串行执行与请求判定模块

**职责：**

- 外层按用户选择顺序遍历 Case，内层按 `1..requests_per_case` 串行发送请求。
- 第 1 次请求只验证是否成功建立上下文，不计算缓存判定。
- 每个验证请求独立执行四类判定。
- 缓存建立失败时停止当前 Case，继续下一个 Case；验证请求失败时记录失败并继续当前 Case 的后续请求。
- 每次请求完成后发布请求级进度；停止后不再进入下一次业务请求或后续 Case。
- 只在内存中保存构造后续多轮请求所需的回复文本，并在写入结果前移除。

**对外接口：** 运行专项任务并返回请求证据、Case 统计和任务统计。

**依赖：** 单请求发送器、停止事件、进度和日志回调。

### 聚合与兼容模块

**职责：**

- 从请求判定生成 Case 统计与总体统计。
- 命中率分母只包含 `cache_hit` 和 `cache_miss` 验证请求。
- 把旧版 `prepare`、`validate` 字段投影成只读的两条请求列表，旧版验证请求可直接判定时才计算对应计数。
- 新版 Summary 同时保留兼容字段，避免历史列表和专项任务类型判断失效。

**对外接口：** 新旧 Case 的统一读取视图和统计函数。

**依赖：** 无外部服务。

### 结果页面模块

**职责：**

- 配置页增加两个数字输入框和计划请求总数提示。
- 运行页以请求数显示进度，展示当前 Case 与当前请求序号。
- 任务摘要展示计划请求、已执行请求、可判定验证样本、总体命中率、无法判定和失败数。
- 每个 Case 展示统计卡片，并用表格列出全部请求；第 1 行标记“缓存建立”，后续行标记“缓存验证 #N”。
- 对旧版 Case 使用兼容投影，仍显示原来的两条证据。

**对外接口：** 现有缓存专项配置路由和结果路由。

**依赖：** 缓存专项创建/查询 API 和现有 WebSocket。

### 报告与文件模块

**职责：**

- Summary JSON 保存新版配置、总体统计、Case 统计和请求列表。
- Details JSONL 每行保存一个请求证据，增加请求序号和单请求判定。
- Markdown/HTML 展示轻量配置、总体与 Case 统计，不写入正文或回复。
- PDF 展示配置、统计口径、总体统计、各 Case 统计及逐请求宽表。
- 逐请求表使用重复表头、禁止行内分页和长错误换行；Case 数多或请求次数大时自然跨页。
- 旧版 Summary 仍走兼容渲染；原子替换逻辑保持不变。

**对外接口：** 现有结果文件和 PDF 下载。

**依赖：** 现有 PDF HTML 渲染、详情读取和临时文件替换。

## 模块交互

```text
缓存专项配置页
  -> 输入公共前缀 Token、每个 Case 请求次数、选择 Case
  -> POST /api/cache-diagnostics
  -> 创建脱敏任务配置
  -> 专项执行器
       -> 生成目标长度公共前缀
       -> Case 1
            -> 请求 1 缓存建立
            -> 请求 2..N 串行缓存验证
            -> 请求级判定与 Case 聚合
       -> Case 2..M
       -> 总体聚合
       -> Summary / Details / Markdown / HTML
  -> WebSocket 与轮询展示请求级进度
  -> 结果页展示总体、Case、逐请求证据
  -> PDF 下载重新渲染新版或兼容旧版报告
```

## 文件组织

```text
backend/app/models/schemas.py                    # 新增配置字段和边界校验
backend/app/core/cache_diagnostics.py            # 动态前缀、多请求序列、判定、聚合、兼容和结果文件
backend/app/core/pdf_report.py                    # 新旧缓存专项 PDF 统计与逐请求表
frontend/src/views/CacheDiagnostics.vue          # Token、请求次数和计划总请求数配置
frontend/src/views/CacheDiagnosticsResult.vue    # 请求级进度、汇总、Case 统计和逐请求表
tests/test_core_refactors.py                     # 聚焦校验、聚合、串行、停止、兼容和 PDF 测试
docs/specs/cache-diagnostics-volume/             # 本次 SDD 文档
```

不新增 API 路由、数据库迁移或新的前端页面。

## 技术决策

| 决策点 | 选择 | 理由 |
|---|---|---|
| 请求次数含义 | 每个 Case 的业务请求总数 | 与用户配置直觉一致，计划总量可直接计算 |
| 缓存建立样本 | 第 1 次请求不计命中率 | 建立请求没有可比较的前置缓存状态 |
| 命中率分母 | 仅命中与明确未命中的验证请求 | 避免把上游无证据和执行失败误判为未命中 |
| 总体命中率 | 合并所有可判定验证请求 | 避免不同 Case 样本量或失败量导致简单平均失真 |
| 验证失败处理 | 记录失败并继续当前 Case | 保留样本量并观察后续请求，不让单点失败终止整组 |
| 建立失败处理 | 结束当前 Case并继续下一个 | 没有建立上下文时继续该 Case 的验证没有意义 |
| 多轮上下文 | 在内存中连续追加真实回复 | 保证多轮关系真实，同时避免敏感正文持久化 |
| Token 配置 | 代表公共前缀目标长度 | 多轮和协议包装会导致每次实际输入不同，目标值不能冒充实际值 |
| 旧数据兼容 | 读取时投影，不迁移、不写回 | 不改数据库和历史文件，降低发布风险 |
| 测试方式 | 少量聚焦后端测试加前端构建和 PDF 实物检查 | 符合用户要求的 SDD 与简单测试范围 |
