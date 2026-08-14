# 缓存专项可配置样本量 Tasks

## 文件清单

| 操作 | 文件 | 职责 |
|---|---|---|
| 修改 | `backend/app/models/schemas.py` | Token 长度、请求次数默认值与边界校验 |
| 修改 | `backend/app/core/cache_diagnostics.py` | 动态前缀、多请求串行执行、判定、聚合、进度、兼容和文件结果 |
| 修改 | `backend/app/core/pdf_report.py` | 新旧缓存专项 PDF 配置、统计和逐请求表 |
| 修改 | `frontend/src/views/CacheDiagnostics.vue` | 新增 Token 与请求次数配置及计划请求提示 |
| 修改 | `frontend/src/views/CacheDiagnosticsResult.vue` | 请求级进度、总体/Case 统计和逐请求明细 |
| 修改 | `tests/test_core_refactors.py` | 聚焦行为与报告回归测试 |
| 已建 | `docs/specs/cache-diagnostics-volume/spec.md` | 已批准需求 |
| 已建 | `docs/specs/cache-diagnostics-volume/plan.md` | 已批准设计 |
| 新建 | `docs/specs/cache-diagnostics-volume/checklist.md` | 最终验收清单 |

## T1: 扩展创建配置与边界校验

**文件：** `backend/app/models/schemas.py`

**依赖：** 无

**步骤：**

1. 将缓存专项 `input_tokens` 改为可提交的正整数，默认 4096。
2. 增加 `requests_per_case`，默认 10，限制为 2 到 100。
3. 保持并发、矩阵和缓存模式固定元数据不变。
4. 确认脱敏后的任务配置会自然保存两个新字段，不新增数据库列。

**验证：** 运行缓存专项配置模型的聚焦测试，期望默认值通过，Token 为 0、请求次数为 1 或 101 时校验失败。

## T2: 让公共前缀使用用户 Token 配置

**文件：** `backend/app/core/cache_diagnostics.py`

**依赖：** T1

**步骤：**

1. 让公共前缀生成接收目标 Token 长度，不再固定使用 4096。
2. Runner 初始化时从配置读取目标长度并生成前缀。
3. Summary 同时保存目标 Token 和本地实际估算 Token。
4. 保持请求证据中的输入 Token 优先使用上游 usage，缺失时才回退本地估算。

**验证：** 生成 1024 和 8192 Token 前缀，期望实际估算达到对应目标附近且 Summary 的目标值与配置一致。

## T3: 建立统一请求序列与单请求判定

**文件：** `backend/app/core/cache_diagnostics.py`

**依赖：** T2

**步骤：**

1. 为请求证据增加 Case 内序号、建立/验证阶段标签和验证请求判定。
2. 第 1 次请求标记为缓存建立，不执行缓存命中分类。
3. 第 2 次及以后分别根据请求成功状态和缓存字段判定四类结果。
4. 保持所有错误信息和当前 API Key 的精确脱敏。
5. 保证 `_response_text` 等仅供内存请求链使用的字段不会进入持久化结果。

**验证：** 构造命中、明确零、无缓存字段和 HTTP 失败证据，期望四类单请求判定正确，建立请求判定为空。

## T4: 实现三个 Case 的多请求消息关系

**文件：** `backend/app/core/cache_diagnostics.py`

**依赖：** T3

**步骤：**

1. 重复请求 Case 的所有请求复用相同消息关系。
2. 尾部变化 Case 第 1 次使用建立尾部，其余请求使用固定验证尾部，公共前缀始终相同。
3. 多轮 Case 每次成功响应后仅在内存中追加真实 assistant 回复，再追加下一轮用户消息。
4. 多轮请求失败时保留当前已建立上下文，后续请求继续使用最近一次成功上下文。
5. 不把消息正文、公共前缀或模型回复写入 Summary、Details、日志和报告。

**验证：** 使用记录消息结构的模拟发送器运行每个 Case 4 次，期望重复请求完全相同、尾部变化关系稳定、多轮消息逐轮增长且持久化文件不含模拟回复。

## T5: 实现请求次数循环、停止和失败隔离

**文件：** `backend/app/core/cache_diagnostics.py`

**依赖：** T4

**步骤：**

1. 外层按 `case_ids` 顺序执行，内层按 `1..requests_per_case` 严格串行发送。
2. 缓存建立失败时结束当前 Case并继续下一个 Case。
3. 验证请求失败时记录失败并继续当前 Case 的下一次验证。
4. 每次业务请求和每次重试前检查停止事件，停止后不再发送任何新请求。
5. 计划请求数只统计业务请求，不包含重试尝试。

**验证：** 模拟 3 个 Case、每个 4 次，期望正常流程调用 12 次；建立失败时减少该 Case 后续调用；验证失败不阻止后续请求；停止后调用数不再增加。

## T6: 聚合 Case 与任务命中率

**文件：** `backend/app/core/cache_diagnostics.py`

**依赖：** T5

**步骤：**

1. 从验证请求计算命中、未命中、无法判定、失败和可判定数量。
2. Case 命中率只使用命中和未命中作为分母，分母为零时返回空值。
3. 按批准的优先级生成 Case 汇总结论，并让部分失败与命中率同时保留。
4. 合并全部 Case 的请求计数生成总体命中率，不平均各 Case 百分比。
5. 保留原有 Case 四类数量字段，新增请求级汇总字段。

**验证：** 构造 6 命中、2 未命中、1 无法判定的验证样本，期望命中率为 0.75；构造多个不同样本量 Case，期望总体结果按合并计数计算。

## T7: 发布请求级进度并兼容旧数据

**文件：** `backend/app/core/cache_diagnostics.py`

**依赖：** T6

**步骤：**

1. 进度增加当前 Case ID、当前请求序号、每 Case 请求数、已执行请求和计划请求。
2. 每次业务请求完成后更新请求级计数和总体命中率。
3. 提供统一读取旧版 `prepare/validate` 和新版 `requests` 的兼容转换。
4. 旧版数据只读投影，不修改历史 Summary 或文件。
5. 旧验证请求只有存在直接缓存证据时才计算新统计。

**验证：** 用旧版 Summary fixture 和新版 Summary fixture 读取统一请求列表，期望旧版得到两条真实证据且不生成额外请求；新版顺序和计数不变。

## T8: 扩展 Summary、Details、Markdown 和 HTML

**文件：** `backend/app/core/cache_diagnostics.py`

**依赖：** T7

**步骤：**

1. Summary 保存新增配置、总体统计、Case 统计和全部请求列表。
2. Details JSONL 每个业务请求写一行，包含请求序号和判定。
3. Markdown 与 HTML 展示公共前缀、请求次数、总体命中率和 Case 统计。
4. 文件结果保持轻量，不写入请求正文和回复内容。
5. 保持现有文件命名、路径和 `detail_count` 口径。

**验证：** 运行模拟任务后检查四类文件，期望请求行数等于实际业务请求数，统计一致且全文搜索不到密钥、公共前缀和模型回复。

## T9: 扩展缓存专项配置页

**文件：** `frontend/src/views/CacheDiagnostics.vue`

**依赖：** T1

**步骤：**

1. 在响应配置中增加“公共前缀 Token”和“每个 Case 请求次数”。
2. 默认值分别为 4096 和 10，控件边界与服务端一致。
3. 展示“已选 Case 数 × 每 Case 请求次数 = 计划请求总数”。
4. 提交时带上两个新字段；现有协议、Endpoint、流式和 Case 选择行为保持不变。
5. 页面说明第 1 次建立缓存、后续请求统计命中率。

**验证：** 运行前端构建；浏览页面检查默认值、边界限制、计划总数和提交请求体。

## T10: 扩展缓存专项结果页

**文件：** `frontend/src/views/CacheDiagnosticsResult.vue`

**依赖：** T7、T8

**步骤：**

1. 进度百分比优先使用请求级已执行数和计划数。
2. 展示当前 Case 和当前请求序号。
3. 总体卡片展示计划请求、已执行请求、可判定验证数、总体命中率、无法判定和失败数。
4. 每个 Case 展示请求统计与命中率。
5. 表格按统一请求列表展示缓存建立和全部验证请求的完整指标及单请求判定。
6. 缺失 TTFT、命中率和旧版新增统计字段按“不可用”展示，真实零值保持零。

**验证：** 运行前端构建；使用新版和旧版模拟结果检查页面，无运行时错误且统计和逐请求行正确。

## T11: 扩展缓存专项 PDF

**文件：** `backend/app/core/pdf_report.py`

**依赖：** T7、T8

**步骤：**

1. 配置表增加公共前缀目标/实际 Token、每 Case 请求次数和计划总请求数。
2. 摘要卡增加实际请求、可判定验证数和总体命中率。
3. 每个 Case 增加统计摘要和命中率。
4. 逐请求表使用统一请求列表，展示序号、阶段、判定、状态码、延迟、TTFT、Token、缓存和错误。
5. 使用现有分页样式确保最多 300 条请求证据可跨页展示，表头重复且行不截断。
6. 旧版 Summary 通过兼容转换正常渲染，不伪造新增请求。
7. 保持每次下载重新生成、临时文件和原子替换逻辑。

**验证：** 运行 PDF HTML 聚焦测试；生成多请求和旧版示例 PDF，使用 `pdfinfo`、文本提取和逐页 PNG 检查字段、分页、截断和敏感信息。

## T12: 增加聚焦回归测试并完成验证

**文件：** `tests/test_core_refactors.py`

**依赖：** T1-T11

**步骤：**

1. 增加配置边界和动态 Token 前缀测试。
2. 增加多请求顺序、失败隔离、停止和多轮内存上下文测试。
3. 增加 Case/总体命中率及全部不可判定边界测试。
4. 增加旧版 Summary 兼容和新版 PDF HTML 字段测试。
5. 运行完整后端测试、Python 编译、前端生产构建和差异检查。
6. 生成实际 PDF 并完成文本和逐页视觉检查。

**验证：** 运行以下命令并确认全部退出码为 0：

```bash
PYTHONPATH=. python -m unittest tests.test_core_refactors -q
python -m py_compile backend/app/models/schemas.py backend/app/core/cache_diagnostics.py backend/app/core/pdf_report.py
git diff --check
```

在 `frontend/` 运行现有 Vite 生产构建，期望构建成功；示例 PDF 为 A4，文本字段齐全且逐页无截断、重叠或敏感正文。

## 执行顺序

```text
T1 -> T2 -> T3 -> T4 -> T5 -> T6 -> T7 -> T8
  \-> T9 -----------------------------> T10
T7 + T8 ------------------------------> T11
T1-T11 -------------------------------> T12
```
