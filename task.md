# 供应商模型接入模板与测试任务中心 Tasks

## 文件清单

| 操作 | 文件 | 职责 |
|---|---|---|
| 新建 | `backend/app/api/vendor_templates.py` | 模板 CRUD、启停和权限校验接口 |
| 新建 | `frontend/src/views/VendorTemplates.vue` | 模板列表、筛选和启停操作 |
| 新建 | `frontend/src/views/VendorTemplateForm.vue` | 模板新建和编辑表单 |
| 新建 | `tests/test_vendor_templates.py` | 模板接口、权限、停用和脱敏回归 |
| 新建 | `scripts/mock_vendor_billing.py` | 本地可控供应商/参考接口模拟服务 |
| 修改 | `backend/app/models/database.py` | 增加模板数据表 |
| 修改 | `backend/app/models/schemas.py` | 增加模板和任务中心 Schema |
| 修改 | `backend/app/core/repository.py` | 增加模板 CRUD 和任务扩展数据读取 |
| 修改 | `backend/app/core/task_manager.py` | 支持从模板合并运行配置 |
| 修改 | `backend/app/api/vendor_billing.py` | 增加基于模板发起自测接口 |
| 修改 | `backend/app/api/tests.py` | 输出供应商任务的模板、Case、Token 和计费状态 |
| 修改 | `backend/app/main.py` | 注册模板路由 |
| 修改 | `frontend/src/api/client.js` | 增加模板 API 和基于模板发起 API |
| 修改 | `frontend/src/views/VendorBillingSelfTest.vue` | 改为选择模板并填写一次性凭证 |
| 修改 | `frontend/src/views/History.vue` | 展示供应商任务中心字段和筛选 |
| 修改 | `frontend/src/router/index.js` | 增加模板路由 |
| 修改 | `frontend/src/App.vue` | 增加模板菜单和页面标题 |

## T1: 增加模板数据模型和 Schema

**文件：** `backend/app/models/database.py`、`backend/app/models/schemas.py`

**依赖：** 无

**步骤：**
1. 在数据库模型中增加供应商模型模板表，保存所有非敏感模板字段、版本号、启用状态和创建更新时间。
2. 为模板所有者、供应商、启用状态和更新时间增加查询所需索引。
3. 增加模板创建、更新、列表、详情和启停输出 Schema。
4. 增加基于模板发起自测的请求 Schema，仅允许 `template_id`、本次 API Key、官方参考 API Key 和任务名称等发起参数。
5. 复用现有协议、URL、Token 长度、容差和价格规则校验；模板 Schema 不定义任何可持久化的 API Key 字段。

**验证：** 执行 `.venv/bin/python -m py_compile backend/app/models/database.py backend/app/models/schemas.py`，期望命令成功退出。

## T2: 实现模板 Repository

**文件：** `backend/app/core/repository.py`，必要时新建 `backend/app/core/vendor_template_repository.py`

**依赖：** T1

**步骤：**
1. 实现按用户权限读取模板列表和单个模板的方法。
2. 实现创建模板、更新模板、启用模板和停用模板的方法。
3. 更新模板时递增版本号，并保留历史任务使用的原配置。
4. root 用户可管理全部模板，guest 用户只能管理或使用自己创建的模板。
5. Repository 返回数据时确认不包含 API Key、Prompt、完整请求或响应字段。

**验证：** 使用 SQLite 临时数据库执行模板创建、读取、更新、停用和启用流程，确认版本递增、状态变化和敏感字段不出现在返回对象中。

## T3: 实现模板 HTTP API

**文件：** `backend/app/api/vendor_templates.py`、`backend/app/main.py`

**依赖：** T1、T2

**步骤：**
1. 新增 `GET /api/vendor-templates`，支持分页、供应商和启用状态筛选。
2. 新增 `POST /api/vendor-templates`，校验请求并创建模板。
3. 新增 `GET /api/vendor-templates/{template_id}`，返回脱敏详情。
4. 新增 `PUT /api/vendor-templates/{template_id}`，更新配置并递增版本。
5. 新增启用和停用接口，并在错误响应中不回显凭证。
6. 所有接口接入现有认证依赖和用户权限判断。

**验证：** 运行后端测试并使用认证请求调用模板接口，确认合法模板返回成功，非法 Token 组、协议不匹配价格规则和越权访问返回明确错误。

## T4: 增加基于模板发起供应商自测

**文件：** `backend/app/api/vendor_billing.py`、`backend/app/core/task_manager.py`

**依赖：** T2、T3

**步骤：**
1. 新增 `POST /api/vendor-billing/from-template`。
2. 创建任务前重新从数据库读取模板并检查启用状态，拒绝停用模板。
3. 将模板的非敏感字段与请求中的一次性凭证合并为现有 Runner 配置。
4. 复用现有供应商与官方接口成对请求流程，不增加额外预检请求。
5. 任务配置入库前确认供应商 API Key 和官方 API Key 已被脱敏清除。
6. 保留原有直接配置的 `POST /api/vendor-billing`，确保旧页面和旧调用方可用。

**验证：** 使用模拟接口创建模板自测任务，确认任务进入 queued/running 状态；使用停用模板创建任务时返回模板不可用；检查数据库任务配置、事件和结果文件不存在 API Key。

## T5: 扩展统一任务中心输出

**文件：** `backend/app/api/tests.py`、`backend/app/models/schemas.py`

**依赖：** T4

**步骤：**
1. 在任务列表输出中保留现有通用压测和缓存专项字段。
2. 对供应商自测任务增加模板名称、供应商名称、Case 总数、成功数、失败数、Token 结论和计费结论。
3. 从供应商自测 summary 提取三态结论，不把缺失 usage 或价格字段转成 0 或通过。
4. 输出 Token 差异只作为观察字段，不单独改变总体结论。
5. 确认任务详情、运行页、结果页和下载接口继续按任务类型正常工作。

**验证：** 准备通用压测、缓存专项和供应商自测三类任务数据，调用 `GET /api/tests`，确认三类任务字段正确区分，供应商任务不伪造并发、成功率和 TPM。

## T6: 开发模板列表和模板表单页面

**文件：** `frontend/src/views/VendorTemplates.vue`、`frontend/src/views/VendorTemplateForm.vue`、`frontend/src/api/client.js`

**依赖：** T3

**步骤：**
1. 增加模板列表页面，显示名称、供应商、模型、协议、版本、启用状态和更新时间。
2. 增加新建和编辑表单，覆盖已批准 Schema 中的全部模板配置字段。
3. 增加协议切换时的 Endpoint 和模型默认值。
4. 增加 Token 长度、容差、URL、价格规则和价格来源状态提示。
5. 增加启用、停用、编辑和基于模板发起测试入口。
6. 让前端 API 客户端支持模板列表、详情、创建、更新和启停请求。

**验证：** 执行 `cd frontend && npm run build`，期望生产构建成功；浏览器中创建、刷新、编辑和停用模板，确认列表状态与后端一致。

## T7: 改造供应商自测发起页

**文件：** `frontend/src/views/VendorBillingSelfTest.vue`、`frontend/src/api/client.js`

**依赖：** T4、T6

**步骤：**
1. 将默认流程改为先选择启用模板，再展示模板只读配置摘要。
2. 仅显示本次供应商 API Key 和官方参考 API Key 输入框。
3. 发起请求改用 `POST /api/vendor-billing/from-template`。
4. API Key 只保存在当前表单内存，不写入 localStorage、URL、模板或任务配置。
5. 停用模板在前端不可选择，同时处理后端并发停用返回的错误提示。

**验证：** 浏览器中选择模板并输入测试凭证后能进入运行页；刷新或重新打开页面后凭证字段为空；停用模板不会出现在可选列表中。

## T8: 改造历史任务中心和导航

**文件：** `frontend/src/views/History.vue`、`frontend/src/router/index.js`、`frontend/src/App.vue`

**依赖：** T5、T6

**步骤：**
1. 在历史任务表格中增加任务类型、模板、供应商、模型、Token 结论和计费结论列。
2. 对供应商自测任务隐藏并发、成功率和 TPM 等无意义字段。
3. 保留通用压测和缓存专项测试原有列及操作入口。
4. 增加模板管理菜单和页面标题，补齐新建、编辑路由。
5. 确认供应商自测任务仍可进入运行页、结果页和 Case 明细页。

**验证：** 浏览器中分别查看三类历史任务，确认列显示符合任务类型；从模板管理、任务列表进入详情并返回，路由不丢失。

## T9: 增加本地模拟接口与统一回归验证

**文件：** `scripts/mock_vendor_billing.py`、`tests/test_vendor_templates.py`、现有 `tests/` 和 `data/`

**依赖：** T1 至 T8

**步骤：**
1. 提供本地模拟供应商和官方参考接口，支持 OpenAI-compatible 非流式与 SSE 流式返回。
2. 让模拟接口能够返回正常 usage、缺失 usage、输出 Token 不同和可控缓存 usage。
3. 增加模板 CRUD、停用保护、权限隔离和脱敏回归验证。
4. 执行现有后端测试、供应商核心逻辑测试和模拟接口端到端流程。
5. 执行前端生产构建并检查浏览器控制台错误。
6. 检查结果目录、数据库配置、日志和前端持久化数据中不存在测试凭证和完整请求内容。

**验证命令：**

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m py_compile backend/app/**/*.py scripts/mock_vendor_billing.py
cd frontend && npm run build
```

**期望结果：** 后端测试全部通过，Python 编译成功，前端生产构建成功；非流式和流式模拟自测均能形成任务状态、Token 结论、计费结论和报告下载结果。

## 执行顺序

```text
T1 -> T2 -> T3 -> T4 -> T5
                    ├-> T6 -> T7 -> T8
                    └-> T9（T8 完成后统一执行）
```

实现完成后再统一运行回归，不采用 TDD；执行期间只修改本任务范围文件，不清理或覆盖既有无关工作区改动。
