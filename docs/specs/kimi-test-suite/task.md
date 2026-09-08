# Kimi 能力测试集 Tasks

## 文件清单

| 操作 | 文件 | 职责 |
|---|---|---|
| 新建 | `backend/app/core/kimi_suite.py` | Case Catalog、请求执行、响应证据、断言、Runner 和报告生成 |
| 新建 | `backend/app/api/kimi_suite.py` | Suite 创建、查询、单 Case 重跑接口 |
| 修改 | `backend/app/models/schemas.py` | Suite 请求、重跑请求和结果响应模型 |
| 修改 | `backend/app/core/task_manager.py` | Suite 启动、后台运行、停止和单 Case 重跑生命周期 |
| 修改 | `backend/app/main.py` | 注册 Suite 路由 |
| 新建 | `frontend/src/views/KimiSuite.vue` | Kimi Suite 配置和 Case 选择页 |
| 新建 | `frontend/src/views/KimiSuiteResult.vue` | 进度、结果表、详情和人工重跑页 |
| 修改 | `frontend/src/api/client.js` | Suite 创建、查询、重跑 API 客户端 |
| 修改 | `frontend/src/router/index.js` | Suite 配置和结果路由 |
| 修改 | `frontend/src/App.vue` | 导航项、激活路径和页面标题 |
| 修改 | `frontend/src/views/History.vue` | Kimi Suite 历史任务跳转和操作显示 |
| 新建 | `tests/test_kimi_suite.py` | 后端 Schema、payload、断言、缓存和 Runner 测试 |
| 修改 | `backend/app/api/tests.py` | 历史摘要、任务类型和通用下载/删除逻辑兼容 `kimi_suite` |
| 修改 | `frontend/src/views/Report.vue` | 如通用报告入口命中 Suite，跳转到 Suite 结果页 |

## T1: 建立 Case Catalog 与统一证据模型

**文件：** `backend/app/core/kimi_suite.py`, `tests/test_kimi_suite.py`

**依赖：** 无

**步骤：**
1. 定义 9 个稳定 Case ID、展示名、描述、子场景和请求覆盖参数。
2. 定义统一响应证据、场景结果和 Case 结果结构，明确状态枚举和脱敏字段。
3. 为重复请求、多轮对话和尾部变化生成两阶段消息序列，复用现有缓存消息关系。
4. 编写 Catalog 顺序、Case 去重/未知校验和缓存消息关系测试。

**验证：** `python3 -m unittest tests.test_kimi_suite -k catalog`，期望 Catalog 包含 9 个 Case，顺序稳定，非法选择被拒绝。

## T2: 扩展 OpenAI 请求构建与响应证据提取

**文件：** `backend/app/core/kimi_suite.py`, `loadtest/protocols.py`, `loadtest/streaming.py`, `tests/test_kimi_suite.py`

**依赖：** T1

**步骤：**
1. 实现 Kimi Chat Completions payload 构建，将共享参数和场景覆盖合并，避免未配置参数串入其他 Case。
2. 支持 thinking、`response_format`、`stop`、temperature、top_p、tools、tool_choice、max_tokens。
3. 扩展流式证据解析，累计 content、reasoning/thinking、tool calls、finish reason 和 usage；保留现有普通压测解析行为。
4. 实现非流式响应的同等证据提取，并统一 HTTP、协议和参数不支持错误分类。
5. 增加 payload 隔离、流式/非流式证据和错误分类测试。

**验证：** `python3 -m unittest tests.test_kimi_suite -k payload` 与 `python3 -m unittest tests.test_core_refactors.Streaming* tests.test_core_refactors.TokenUsage*`，期望新增测试通过且现有流式/usage 测试无回归。

## T3: 实现纯函数断言器

**文件：** `backend/app/core/kimi_suite.py`, `tests/test_kimi_suite.py`

**依赖：** T1、T2

**步骤：**
1. 实现 thinking 开启、关闭和证据缺失/明确不支持的判定。
2. 实现 JSON 对象解析、必需键校验和非法 JSON 判定。
3. 实现数字/中文 stop 场景的禁止内容判定和 finish reason 记录。
4. 实现采样参数兼容性判定，不使用文本差异推断随机性。
5. 实现工具调用名称、类型、参数 JSON 和必需字段判定。
6. 实现输出 Token usage 存在性和上限判定。
7. 实现缓存 usage 的命中、未命中、无法判定和执行失败分类。

**验证：** `python3 -m unittest tests.test_kimi_suite -k assertion`，期望合法响应通过，非法 JSON、stop 泄漏、错误工具参数和超限 Token 失败，缺失证据返回不可判定。

## T4: 增加 Schema 与 API 合同

**文件：** `backend/app/models/schemas.py`, `backend/app/api/kimi_suite.py`, `backend/app/main.py`, `tests/test_kimi_suite.py`

**依赖：** T1

**步骤：**
1. 增加 `KimiSuiteCreate`、`KimiSuiteRerunRequest`、Suite 输出模型和 Case 状态模型。
2. 固定 OpenAI 协议、默认 Endpoint、默认模型和默认 9 个 Case。
3. 校验空列表、未知 ID、重复 ID、参数范围和不支持的协议。
4. 新增创建、查询、权限和重跑路由，复用现有任务访问与 Base URL 策略。
5. 在应用入口注册路由，并确保 API Key 仅用于请求、不进入返回模型。

**验证：** `python3 -m unittest tests.test_kimi_suite -k schema`，期望默认值正确、非法请求返回 422/400、任务类型不匹配返回 400。

## T5: 接入 TaskManager 生命周期与结果持久化

**文件：** `backend/app/core/task_manager.py`, `backend/app/core/repository.py`, `backend/app/api/tests.py`, `tests/test_kimi_suite.py`

**依赖：** T2、T3、T4

**步骤：**
1. 增加 `start_kimi_suite`，执行运行数限制和预检后创建 `task_kind=kimi_suite` 任务。
2. 增加 `_run_kimi_suite`，串行运行 Case，发布进度/事件，保存四类结果文件和 Summary。
3. 接入停止事件、取消状态和异常脱敏，单 Case 失败不得让整个 Runner 抛出任务级失败。
4. 实现单 Case 重跑任务，读取旧 Summary、替换目标 Case、重新聚合并原子更新结果文件。
5. 让历史列表、任务摘要、删除/下载和通用权限逻辑识别 `kimi_suite`。

**验证：** `python3 -m unittest tests.test_kimi_suite -k manager`，期望创建、停止、部分失败继续、重跑替换和 API Key 脱敏均通过。

## T6: 实现报告与结果文件

**文件：** `backend/app/core/kimi_suite.py`, `tests/test_kimi_suite.py`

**依赖：** T2、T3、T5

**步骤：**
1. 生成 `summary.json`、`details.jsonl`、Markdown 和 HTML，保存配置、Case、场景、usage、断言和失败证据。
2. 对 API Key、Authorization、x-api-key、请求头和敏感响应字段执行统一脱敏。
3. 生成截图所需列：Case、Endpoint、脱敏 Key、模型、状态、耗时、TTFT、重试、人工重跑、失败原因。
4. 为报告输出增加结构字段和敏感信息扫描测试。

**验证：** `python3 -m unittest tests.test_kimi_suite -k report`，期望四类文件生成，包含断言证据且全文不出现明文 Key 或认证头。

## T7: 实现 Kimi Suite 配置页

**文件：** `frontend/src/views/KimiSuite.vue`, `frontend/src/api/client.js`, `frontend/src/router/index.js`, `frontend/src/App.vue`

**依赖：** T4

**步骤：**
1. 增加连接配置表单，默认显示 OpenAI-compatible、`/v1/chat/completions`、`kimi-k3`。
2. 增加 9 个 Case 选择卡片，默认全选，显示已选数量和预计请求数。
3. 增加流式、超时、重试配置与 API Key 密码输入，提交前校验 URL、Key、模型和 Case。
4. 调用创建接口，成功后跳转 Suite 结果页；失败时展示脱敏错误。
5. 在导航和路由守卫中加入 Suite 入口。

**验证：** `npm run build`，期望前端编译成功；使用前端测试或手工操作验证默认值、空选择校验和成功跳转。

## T8: 实现 Kimi Suite 结果页与人工重跑

**文件：** `frontend/src/views/KimiSuiteResult.vue`, `frontend/src/api/client.js`, `frontend/src/router/index.js`, `frontend/src/App.vue`

**依赖：** T5、T6、T7

**步骤：**
1. 复用现有轮询和进度 WebSocket，展示当前 Case、当前场景、完成数和总体计数。
2. 实现截图风格结果表，区分通过、失败、不支持、无法判定和取消状态。
3. 支持展开查看子场景参数、断言证据、usage、tool calls、响应摘要和错误。
4. 对已结束 Case 增加人工重跑按钮，弹窗要求重新输入 API Key，成功后刷新单 Case 和总体结果。
5. 在历史页和通用报告入口中将 `kimi_suite` 跳转到结果页，禁止加入普通压测对比。

**验证：** `npm run build`，期望结果页编译成功；手工验证运行中、完成、部分失败、重跑和历史打开路径。

## T9: 后端回归与端到端验证

**文件：** `tests/test_kimi_suite.py`, `tests/test_core_refactors.py`（仅在必要时增加兼容断言）

**依赖：** T1-T8

**步骤：**
1. 运行 Kimi Suite 全部单元/API 测试，修复断言、持久化和脱敏问题。
2. 运行现有后端核心回归测试，确认普通压测、缓存专项、批量自定义 Case 和报告逻辑不变。
3. 运行前端测试和生产构建，确认路由、历史页和结果页无编译错误。
4. 使用固定 Fake HTTP 响应完成一次端到端 Suite，检查 9 个 Case 结果、文件内容和 API Key 扫描。
5. 对真实 Kimi endpoint 仅在用户提供凭据并明确要求时执行，不将网络不可用误报为代码失败。

**验证：** `python3 -m unittest tests.test_kimi_suite tests.test_core_refactors`、`npm test`、`npm run build` 和 `git diff --check`；期望命令退出码均为 0，且敏感信息扫描无命中。

## 执行顺序

```text
T1 -> T2 -> T3 -> T4 -> T5 -> T6
                 \-> T7 -> T8
T6 + T8 -> T9
```
