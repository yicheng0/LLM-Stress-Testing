# Kimi Prompt Token 注入检测 Checklist

> 每项均通过运行代码或观察行为验证。

## 实现完整性

- [ ] Case 列表包含第 10 个“Prompt Token 注入检测”，默认选中且可单独取消（验证：打开 Kimi 配置页，期望显示 `10 / 10 Case`，取消后变为 `9 / 10 Case`）。
- [ ] 本地估算值和估算方法写入结果证据（验证：运行模拟 Runner，期望结果包含 `local_prompt_tokens` 与 `estimation_method`）。
- [ ] 输入 Token 在绝对和相对容差内时判定通过（验证：单元测试，期望状态为 `passed`）。
- [ ] 输入 Token 明显超出容差时判定疑似注入（验证：单元测试，期望状态为 `suspected_injection`）。
- [ ] usage 缺失时判定无法核验（验证：单元测试，期望状态为 `unverifiable`，不是通过）。
- [ ] 协议不提供输入 Token 字段时判定接口不支持（验证：Gemini/Anthropic 缺失字段场景，期望状态为 `unsupported` 或约定的无法判定状态）。
- [ ] 请求异常时判定请求失败并保留脱敏错误（验证：模拟 HTTP/网络错误，期望状态为 `request_failed`）。

## 集成

- [ ] 第 10 个 Case 使用当前协议请求构造逻辑，未将本地检测字段发送给上游（验证：检查模拟请求 payload，期望无 `local_prompt_tokens`、`tolerance` 等内部字段）。
- [ ] 实时进度包含第 10 个 Case 行和 Token 证据（验证：运行模拟 Runner，期望 ProgressHub 快照包含该 Case）。
- [ ] 结果页表格展示 Token 检测状态，右侧抽屉展示本地值、上游值、差值、比例和容差（验证：加载模拟结果页面并点击该行）。
- [ ] 既有 9 个 Case 的请求和断言保持兼容（验证：原有 Kimi 专项测试全部通过）。

## 脱敏与边界

- [ ] summary、details、报告不包含 API Key（验证：对生成结果执行敏感字段检索，期望无密钥值）。
- [ ] summary、details、报告不包含完整 Prompt、完整请求体和完整响应体（验证：检索结果文件，期望只有摘要和 Token 数值）。
- [ ] 缺失数值显示“—”或无法判定，不显示 0 代替缺失值（验证：加载缺 usage 结果页面）。
- [ ] 短 Prompt 和长 Prompt 均使用同一判定顺序，不依据延迟或文本相似度判定（验证：单元测试和模拟响应）。

## 编译与测试

- [ ] Kimi 专项测试全部通过（验证：`.venv/bin/python -m unittest tests/test_kimi_suite.py`）。
- [ ] 前端生产构建无错误（验证：`npm run build`）。
- [ ] Python 文件语法检查通过（验证：`.venv/bin/python -m py_compile backend/app/core/kimi_suite.py backend/app/models/schemas.py`）。
- [ ] 代码无空白错误（验证：`git diff --check`）。

## 端到端场景

- [ ] 用户选择第 10 个 Case 并启动测试 -> 结果页实时显示待测试、测试中、完成状态 -> 点击行打开详情抽屉查看 Token 证据（验证：本地模拟接口完成一次任务）。
- [ ] 模拟网关注入额外系统提示词 -> 上游输入 Token 超出容差 -> 页面显示“疑似提示词注入”并给出差值比例（验证：可控模拟响应）。
- [ ] 模拟网关不返回 usage -> 页面显示“无法判定” -> 不得显示通过（验证：可控模拟响应）。
