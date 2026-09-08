# 供应商模型接入模板与测试任务中心 Plan

## 架构概览

在现有供应商自测链路上增加模板管理层，不重写现有自测 Runner。模板只保存可复用的非敏感配置；用户在发起测试时提交一次性供应商 API Key 和官方参考 API Key，由任务管理器仅在运行内存中传递给 Runner，持久化配置继续使用现有脱敏机制。

测试任务中心继续读取现有 `test_tasks`、`test_results` 和任务配置，通过 `task_kind` 区分通用压测、缓存专项测试和供应商接入自测。供应商自测的 Token 与计费结论从现有 summary 中提取，通用压测字段保持原行为。

## 核心数据结构

### SupplierModelTemplate

模板持久化对象包含：

- `id`：模板唯一标识
- `owner_username`、`owner_role`：创建者和权限范围
- `name`：模板名称
- `supplier_name`：供应商名称
- `api_protocol`、`anthropic_version`：协议配置
- `base_url`、`endpoint`、`model`：供应商非敏感接口配置
- `reference_base_url`、`reference_endpoint`、`reference_model`、`reference_anthropic_version`：官方参考配置
- `input_token_lengths`：输入 Token 测试组
- `max_output_tokens`、`temperature`、`timeout_sec`、`connect_timeout_sec`
- `enable_stream`、`cache_test_enabled`
- `pricing_rule_id`、`token_abs_tolerance`、`token_relative_tolerance`
- `version`：模板版本号，编辑后递增
- `enabled`：是否允许新建测试
- `created_at`、`updated_at`

模板不得包含任何 API Key、Prompt、完整请求或响应。

### VendorBillingCreateFromTemplate

发起请求包含：

- `template_id`
- `api_key`
- `reference_api_key`
- 可选的本次任务名称

服务端读取模板配置，合并一次性凭证后调用现有供应商自测启动逻辑；写入数据库和报告前移除两个 API Key。

### VendorBillingTaskView

任务列表补充面向准入的字段：

- `task_kind`
- `template_name`
- `supplier_name`
- `model`
- `api_protocol`
- `case_total`、`case_success`、`case_failed`
- `token_status`
- `pricing_status`
- `overall_status`
- `created_at`、`started_at`、`completed_at`

通用压测任务继续返回并发、成功率、TPM 等原有字段；供应商自测任务不把这些字段伪装成有意义的指标。

## 核心接口

### 模板接口

- `GET /api/vendor-templates`：按当前用户权限分页查询模板，支持启用状态和供应商筛选。
- `POST /api/vendor-templates`：创建模板，校验协议、URL、输入 Token 组、容差和价格规则。
- `GET /api/vendor-templates/{template_id}`：读取单个模板的脱敏详情。
- `PUT /api/vendor-templates/{template_id}`：更新模板，递增版本号并保留更新时间。
- `POST /api/vendor-templates/{template_id}/enable`：启用模板。
- `POST /api/vendor-templates/{template_id}/disable`：停用模板。

### 基于模板发起自测

- `POST /api/vendor-billing/from-template`：校验模板仍启用，接收本次 API Key，构造现有 `VendorBillingCreate` 运行配置并返回测试 ID。

原有 `POST /api/vendor-billing` 保留，兼容旧的直接填写方式；新页面默认使用模板接口。

### 任务中心接口

- 扩展现有 `GET /api/tests`：返回模板名称、供应商名、Token/计费结论和 Case 统计；通过 `task_kind` 保持三类任务兼容。
- 扩展现有任务详情和明细接口：供应商自测继续进入现有运行、结果和明细页面，不暴露敏感请求数据。

## 模块设计

### 数据模型与迁移

**职责：** 存储模板基础信息、版本、启停状态和非敏感测试配置。

**位置：** `backend/app/models/database.py`。

**设计：** 增加 `VendorTemplate` 表及必要索引；沿用项目的 `init_db()` 兼容列策略，SQLite 本地开发和 PostgreSQL 部署均可自动建表。不删除或改写既有任务表。

### Schema 与校验

**职责：** 定义模板创建、更新、列表、发起请求和任务列表输出结构。

**位置：** `backend/app/models/schemas.py`。

**设计：** 复用现有协议 Literal、URL 安全校验、价格目录校验和 Token 长度校验规则；模板更新不允许写入 API Key；对空 Token 组、重复值、非法范围、协议不匹配价格规则返回明确错误。

### Repository

**职责：** 提供模板 CRUD、按用户隔离查询、版本递增和启停操作。

**位置：** `backend/app/core/repository.py`，必要时新增 `backend/app/core/vendor_template_repository.py`。

**设计：** root 可管理全部模板，guest 只能读取和使用自己的模板；读取返回前不包含凭证字段；停用只改变模板状态，不删除历史任务。

### API 路由

**职责：** 实现模板管理和基于模板创建任务的 HTTP 接口。

**位置：** 新增 `backend/app/api/vendor_templates.py`，修改 `backend/app/api/vendor_billing.py` 和 `backend/app/main.py`。

**设计：** 所有接口使用现有认证依赖；创建测试前重新读取数据库中的模板并检查 `enabled`，避免客户端使用旧页面绕过停用状态；错误响应不回显 API Key。

### 任务运行与脱敏

**职责：** 将模板配置和临时凭证组合为现有 Runner 所需的运行配置，并确保凭证只存在于运行时。

**位置：** `backend/app/core/task_manager.py`、`backend/app/core/vendor_billing.py`、`backend/app/core/repository.py`。

**设计：** 持久化前调用现有敏感字段清理；Runner 继续生成脱敏的 usage evidence；事件、错误、summary、details 和下载文件禁止写入凭证、完整 Prompt、请求体和响应体。

### 任务中心前端

**职责：** 提供模板列表、模板编辑表单、从模板发起自测，以及统一任务列表展示。

**位置：**

```text
frontend/src/views/VendorTemplates.vue       # 模板列表
frontend/src/views/VendorTemplateForm.vue    # 新建和编辑模板
frontend/src/views/VendorBillingSelfTest.vue # 改为选择模板并填写一次性凭证
frontend/src/views/History.vue                # 任务中心字段和筛选
frontend/src/api/client.js                    # 模板与发起接口
frontend/src/router/index.js                  # 模板路由
frontend/src/App.vue                          # 菜单和标题
```

**设计：** 模板表单与当前供应商自测表单共享协议、价格和 Token 校验文案；API Key 输入框只属于发起测试页面，不写入 localStorage；任务列表依据 `task_kind` 条件渲染字段和操作入口。

### 测试与可控模拟接口

**职责：** 验证模板 CRUD、停用保护、脱敏、任务中心字段，以及非流式/流式自测流程。

**位置：** `tests/` 下新增后端回归文件，必要时新增 `scripts/` 下的本地模拟供应商脚本；前端使用现有生产构建作为集成检查。

**设计：** 不使用真实 API Key；模拟接口返回可控的 OpenAI-compatible、Anthropic 和 SSE usage，覆盖正常、usage 缺失、价格不可核验和输出 Token 不一致场景。

## 模块交互

### 创建并运行模板自测

```text
前端模板表单
  -> POST /api/vendor-templates
  -> VendorTemplate 持久化

前端选择启用模板并填写一次性凭证
  -> POST /api/vendor-billing/from-template
  -> 重新读取并校验模板 enabled
  -> 合并非敏感模板配置与内存凭证
  -> Repository.create_task 脱敏保存任务元数据
  -> TaskManager.start_vendor_billing
  -> VendorBillingRunner 成对请求供应商与参考接口
  -> 生成 Token/价格三态结论
  -> 保存脱敏 summary、details 和报告
```

### 任务列表展示

```text
GET /api/tests
  -> Repository.list_tasks
  -> 根据 task_kind 解析配置和 summary
  -> 供应商自测提取 Case/Token/计费字段
  -> 前端按任务类型渲染不同列
```

## 文件组织

```text
model_rpm_test/
├── backend/app/models/database.py          # 增加模板表
├── backend/app/models/schemas.py           # 模板和任务中心 Schema
├── backend/app/core/repository.py          # 模板与任务查询
├── backend/app/core/task_manager.py        # 模板任务运行参数拼装
├── backend/app/core/vendor_billing.py      # 复用现有自测和脱敏逻辑
├── backend/app/api/vendor_templates.py     # 模板 CRUD API
├── backend/app/api/vendor_billing.py       # 增加 from-template API
├── backend/app/api/tests.py                 # 任务中心输出字段
├── backend/app/main.py                      # 注册路由
├── frontend/src/views/VendorTemplates.vue  # 模板列表
├── frontend/src/views/VendorTemplateForm.vue # 模板表单
├── frontend/src/views/VendorBillingSelfTest.vue # 模板发起页
├── frontend/src/views/History.vue           # 任务列表
├── frontend/src/api/client.js               # 前端 API
├── frontend/src/router/index.js             # 路由
├── frontend/src/App.vue                     # 菜单
└── tests/                                    # 回归验证
```

## 技术决策

| 决策点 | 选择 | 理由 |
|---|---|---|
| 模板存储 | 与现有任务数据库同库新增表 | 保持权限、部署和本地 SQLite/PostgreSQL 机制一致 |
| 模板版本 | 编辑时递增整数版本 | 能识别任务使用的配置版本，且不引入完整版本快照系统 |
| API Key 生命周期 | 只在一次发起请求和后台运行内存中存在 | 满足临时凭证和不持久化要求 |
| 旧发起入口 | 保留直接配置接口 | 避免破坏已有页面、历史链接和兼容调用方 |
| 任务分类 | 继续使用 `task_kind` | 复用已有任务列表、权限、状态和结果路由 |
| 结论模型 | Token、计费、总体分别使用通过/异常/无法核验 | 避免把缺少证据或输出 Token 差异误判为失败 |
| 价格目录 | 继续只读受控 JSON 目录 | 当前阶段不做价格自动同步，也不提供虚假写入接口 |
| 回归方式 | 先实现，再统一运行后端回归、构建和模拟流程 | 遵循用户明确要求“不使用 TDD” |
