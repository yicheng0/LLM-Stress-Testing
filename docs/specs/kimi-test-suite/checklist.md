# Kimi 能力测试集 Checklist

> 每项均通过运行代码或观察行为验证。

## 配置与 Case

- [ ] AC1：已登录用户能从独立 Kimi 测试集入口创建任务；默认显示 OpenAI-compatible、`/v1/chat/completions` 和 `kimi-k3`。（验证：打开配置页并提交 Fake API 服务，期望生成 `kimi_suite` 任务）
- [ ] AC2：配置页默认选中 9 个内置 Case，用户可取消选择；空列表、未知 ID、重复 ID 和非 OpenAI 协议被接口明确拒绝。（验证：Schema/API 单测，期望合法列表通过，非法输入返回校验错误）
- [ ] F2：页面显示重复请求缓存、多轮对话缓存、尾部变化缓存、思考控制、JSON、stop、采样、工具调用和输出 Token 共 9 个 Case。（验证：配置页快照或组件测试，期望名称与顺序一致）

## 请求与断言

- [ ] AC3：每个场景只包含自身定义的请求覆盖参数，JSON、stop、采样、工具和输出 Token 参数可以从结果明细复核。（验证：payload 单测和 `details.jsonl`，期望不存在跨 Case 参数泄漏）
- [ ] AC4：JSON 对象、stop、工具调用和输出 Token Case 正确区分通过与断言失败。（验证：固定响应单测，期望非法 JSON、stop 泄漏、工具名/参数错误和 Token 超限均失败）
- [ ] AC5：thinking 开启、关闭、参数明确不支持、响应证据缺失分别得到正确的通过、失败、不支持或无法判定状态。（验证：固定响应单测，期望缺少证据绝不显示通过）
- [ ] AC6：三个缓存 Case 分别生成正确的建立/验证消息关系；只有缓存 usage 字段能决定命中或未命中，字段缺失显示无法判定。（验证：Case Catalog 与 usage 分类单测）
- [ ] N3：认证、限流、超时和服务错误显示为请求执行失败，只有明确参数拒绝显示为接口不支持。（验证：HTTP 错误分类测试）

## 执行、结果与安全

- [ ] AC7：Case 按选择顺序串行执行，某个 Case 失败后其他 Case 仍执行；结果表展示状态、耗时、TTFT、重试和失败原因。（验证：Fake HTTP 端到端 Runner 测试，期望后续 Case 结果存在）
- [ ] F8：结果页显示截图所需的 Case、Endpoint、脱敏 API Key、模型、状态、耗时、首 token、重试、人工重跑和失败原因列，且可展开场景证据。（验证：前端构建与页面检查）
- [ ] F9：运行中显示当前 Case/场景和完成数；已结束任务支持单 Case 人工重跑，重跑后仅替换目标 Case 并增加其重跑次数。（验证：TaskManager/API 集成测试）
- [ ] AC8：历史页可重新打开 Kimi Suite 结果；`summary.json`、`details.jsonl`、Markdown、HTML、API 响应和事件日志均不包含 API Key、Authorization 或认证头。（验证：结果文件全文敏感词扫描和历史跳转测试）
- [ ] N2：缓存 Case 和 Case 内子场景严格串行；不使用普通并发压测逻辑。（验证：Runner 调用顺序测试）

## 兼容与构建

- [ ] AC9：现有普通压测、矩阵压测、缓存专项和自定义 Case 的后端回归测试通过。（验证：`python3 -m unittest tests.test_core_refactors`，期望退出码 0）
- [ ] AC9：Kimi Suite 后端 Schema、payload、断言、Runner、API、报告和脱敏测试通过。（验证：`python3 -m unittest tests.test_kimi_suite`，期望退出码 0）
- [ ] AC9：前端测试与生产构建成功，新增路由、导航、历史跳转和结果页不会引入编译错误。（验证：在 `frontend/` 中执行现有测试命令与 `npm run build`，期望退出码 0）
- [ ] N4：Kimi Suite 任务不进入普通压测对比，已有缓存专项、供应商自测与普通任务的路由行为保持原样。（验证：History 路由和对比限制测试）
- [ ] 代码质量：变更文件通过 `git diff --check`，且未修改无关任务文件或删除用户已有工作。（验证：检查目标文件清单与 `git diff --check` 输出）

## 端到端场景

- [ ] 完整流程：用户填写默认 Kimi 配置、输入测试 API Key、保留全部 9 个 Case 并启动；Fake HTTP 服务按不同场景返回固定 JSON、工具、usage 和失败响应。（验证：创建任务 -> 轮询完成 -> 打开结果页，期望有 9 行 Case、场景详情、汇总计数和脱敏报告文件）
- [ ] 边界流程：用户只选择一个缓存 Case且上游不返回缓存 usage。（验证：运行完成后，期望 Case 显示“无法判定”，不显示“缓存命中”或“测试通过”）
- [ ] 边界流程：用户在 Suite 完成后输入错误 API Key 重跑一个 Case。（验证：预检失败，期望原 Summary 和其他 Case 结果不变，错误信息不泄露 API Key）
