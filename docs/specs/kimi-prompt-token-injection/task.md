# Kimi Prompt Token 注入检测 Tasks

## 文件清单

| 操作 | 文件 | 职责 |
|---|---|---|
| 修改 | `backend/app/core/kimi_suite.py` | 注册 Prompt Token Case、Token 估算、usage 提取、判定和实时结果 |
| 修改 | `backend/app/models/schemas.py` | 扩展 Kimi Case 类型和数量上限 |
| 修改 | `frontend/src/views/KimiSuite.vue` | 展示并默认选择第 10 个 Case |
| 修改 | `frontend/src/views/KimiSuiteResult.vue` | 展示 Prompt Token 结果和详情证据 |
| 修改 | `tests/test_kimi_suite.py` | 新增单元测试和旧 Case 回归测试 |
| 新建 | `docs/specs/kimi-prompt-token-injection/checklist.md` | 验收清单 |

## T1: 扩展 Case 注册与 Schema

**文件：** `backend/app/core/kimi_suite.py`、`backend/app/models/schemas.py`

**依赖：** 无

**步骤：**
1. 新增固定 Case ID `prompt_token_injection` 和对应 Case/Scenario 文案。
2. 将 Kimi Case ID 类型、默认 Case 列表和最大数量从 9 扩展到 10。
3. 保持重复 Case 去重、未知 Case 拒绝和空 Case 拒绝逻辑不变。

**验证：** 运行 `.venv/bin/python -m unittest tests/test_kimi_suite.py`，预期新增 Case 注册测试失败，直到 T2 完成。

## T2: 实现 Prompt Token 估算和判定

**文件：** `backend/app/core/kimi_suite.py`

**依赖：** T1

**步骤：**
1. 为固定测试消息生成协议无关的本地 Token 估算值，并记录估算方法。
2. 从 OpenAI-compatible、Anthropic、Gemini 的 usage 结构提取输入 Token；字段缺失返回不可比较状态。
3. 实现绝对容差与相对容差判定，输出通过、疑似注入、无法判定、接口不支持和请求失败。
4. 将请求摘要、Token 证据、usage 和断言结果写入现有场景结果结构，禁止写入完整 Prompt、API Key 和完整响应。

**验证：** 新增并运行判定单元测试，覆盖容差内、明显超出、usage 缺失、协议不支持和请求失败五种结果，预期全部通过。

## T3: 接入协议请求与实时进度

**文件：** `backend/app/core/kimi_suite.py`

**依赖：** T2

**步骤：**
1. 使用现有协议 URL、Header 和 Body 构造逻辑发起第 10 个 Case 请求。
2. 确保检测专用字段只用于本地判定，不发送到上游。
3. 在请求开始、响应完成和 Case 完成时更新实时进度行。
4. 保持原有 9 个 Case 的 payload 和断言行为不变。

**验证：** 使用本地字典响应或模拟请求运行 Runner，预期实时快照包含第 10 个 Case 和 `token_evidence`，原有 Case 快照结构不变。

## T4: 更新 Kimi 配置页

**文件：** `frontend/src/views/KimiSuite.vue`

**依赖：** T1

**步骤：**
1. 在 Case 表格中增加“Prompt Token 注入检测”行。
2. 默认将新 Case 加入选中列表，并使选中数量显示为 `10 / 10`。
3. 保持 Ant Design 表格、复选框和状态标签样式一致。

**验证：** 运行 `npm run build`，预期前端生产构建通过；手动打开 Kimi 配置页，预期第 10 个 Case 默认选中且可取消选择。

## T5: 更新 Kimi 结果页证据展示

**文件：** `frontend/src/views/KimiSuiteResult.vue`

**依赖：** T3

**步骤：**
1. 在实时结果表中展示新 Case 的状态、耗时和失败原因。
2. 在右侧详情抽屉增加本地估算 Token、上游输入 Token、差值、差值比例、容差和判定说明。
3. 对缺失字段显示“—”或“无法判定”，不得显示 0 代替缺失值。
4. 保持表格行点击、抽屉打开和 1.5 秒轮询刷新行为。

**验证：** 使用包含四种判定状态的模拟结果打开结果页，预期表格和抽屉显示对应状态与证据；运行 `npm run build` 预期通过。

## T6: 完善回归测试

**文件：** `tests/test_kimi_suite.py`

**依赖：** T2、T3

**步骤：**
1. 测试 Case 数量、默认选择和未知 Case 校验。
2. 测试 OpenAI-compatible、Anthropic、Gemini usage 提取。
3. 测试通过、疑似注入、无法判定、接口不支持和请求失败判定。
4. 测试敏感字段不会出现在保存的结果摘要中。
5. 运行已有 Kimi 测试，确认原有 9 个 Case 断言继续通过。

**验证：** 运行 `.venv/bin/python -m unittest tests/test_kimi_suite.py`，预期全部通过。

## T7: 生成并执行验收清单

**文件：** `docs/specs/kimi-prompt-token-injection/checklist.md`

**依赖：** T4、T5、T6

**步骤：**
1. 将 `spec.md` 中 AC1-AC8 映射为可观察清单项。
2. 添加前端构建、后端专项测试、脱敏检查和完整用户流程检查。
3. 逐项执行验证并记录实际结果。

**验证：** 运行清单中的所有命令，预期每项标记通过后再交付。

## 执行顺序

```text
T1 -> T2 -> T3 -> T5 -> T6 -> T7
  \-> T4 -----------^
```
