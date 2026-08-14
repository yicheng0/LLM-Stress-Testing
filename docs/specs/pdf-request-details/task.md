# PDF 请求明细完整化 Tasks

## 文件清单

| 操作 | 文件 | 职责 |
|---|---|---|
| 修改 | `backend/app/core/pdf_report.py` | 格式化完整请求详情、输出双表并控制 PDF 分页样式 |
| 修改 | `tests/test_core_refactors.py` | 验证完整字段、成功失败请求和缺失值规则 |
| 新建 | `docs/specs/pdf-request-details/checklist.md` | 开发前定义最终验收步骤 |

## T1: 扩充请求详情格式化

**文件：** `backend/app/core/pdf_report.py`
**依赖：** 无

**步骤：**

1. 为每条请求统一读取 ID、成功状态、HTTP 状态码、延迟、TTFT、输入/输出/总 Token、三类缓存 Token、错误类型和错误信息。
2. 复用现有单请求缓存命中率和 TPS 计算规则。
3. 规定数值缺失为“不可用”、错误字段空值为“-”、真实零值保留。
4. 保证字典形式的历史详情和当前请求结果对象都能读取。

**验证：** 运行 `python -m py_compile backend/app/core/pdf_report.py`，期望退出码为 0。

## T2: 将请求明细改为双表布局

**文件：** `backend/app/core/pdf_report.py`
**依赖：** T1

**步骤：**

1. 输出“请求状态、延迟与 Token”表，包含 ID、结果、状态码、总延迟、TTFT、输入 Token、输出 Token、总 Token 和 TPS。
2. 输出“请求缓存与错误”表，包含 ID、缓存命中 Token、缓存创建 Token、含缓存 Token、缓存命中率、错误类型和错误信息。
3. 两张表按相同请求顺序展示全部成功和失败请求。
4. 保留失败样本聚合摘要。
5. 调整表格样式，使表头跨页可识别、行不被拆开、错误信息可换行且不撑破 A4 页面。

**验证：** 使用一个成功请求和一个失败请求调用 PDF HTML 渲染入口，期望 HTML 中出现两张表的全部标题、两个请求 ID、`OK`、`FAIL`、状态码和错误内容。

## T3: 增加轻量回归测试

**文件：** `tests/test_core_refactors.py`
**依赖：** T2

**步骤：**

1. 扩充现有 PDF 请求明细测试，断言全部列名进入 HTML。
2. 用一个成功请求和一个失败请求，断言二者都进入两张明细表。
3. 断言成功请求错误字段为“-”，失败请求保留错误类型和错误信息。
4. 断言缺失 TTFT/TPS 显示“不可用”，真实零 TTFT 显示 `0.0000s`。

**验证：** 运行 `PYTHONPATH=. <项目虚拟环境>/bin/python -m unittest tests.test_core_refactors -q`，期望全部测试通过。

## T4: 生成并检查实际 PDF

**文件：** 不修改生产文件
**依赖：** T3

**步骤：**

1. 在临时目录生成包含多条成功与失败请求的示例 PDF，确保明细跨页。
2. 使用 `pdfinfo` 确认文件有效、A4 页面和页数。
3. 使用 `pdftotext -layout` 确认全部字段和代表性数据进入最终 PDF。
4. 使用 `pdftoppm` 将页面渲染为 PNG，逐页检查表头、列宽、换行、重叠和截断。
5. 删除或保留在临时目录中，不提交生成的 PDF、PNG 或结果数据。

**验证：** 期望 PDF 文本包含两张明细表及完整字段，PNG 页面没有裁切、重叠或不可读列。

## T5: 最终范围与差异检查

**文件：** `backend/app/core/pdf_report.py`、`tests/test_core_refactors.py`、`docs/specs/pdf-request-details/`
**依赖：** T4

**步骤：**

1. 运行 `git diff --check`。
2. 核对实现未修改数据库结构、采集算法、网页请求明细或下载 API。
3. 核对 `frontend/node_modules` 和其它既有无关脏改动未被纳入本次范围。

**验证：** `git diff --check` 无输出，业务差异仅覆盖批准的 PDF 请求明细范围和 SDD 文档。

## 执行顺序

```text
T1 -> T2 -> T3 -> T4 -> T5
```
