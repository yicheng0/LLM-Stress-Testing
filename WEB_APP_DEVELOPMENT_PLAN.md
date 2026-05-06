# LLM API 性能测试平台 Web 改造方案

## 1. 项目目标

当前项目已经具备命令行压测能力，核心脚本为 `llm_load_test.py`。本方案目标是将它改造为前后端一体、易部署的 Web 应用，让非命令行用户也能完成 LLM API 性能测试、查看实时进度、管理历史记录并导出报告。

平台需要优先支持三类协议：

- OpenAI-compatible API：包括 GLM、Qwen、DeepSeek、OpenAI 以及其它兼容 `/chat/completions` 或 `/responses` 的模型接口。
- Anthropic Messages API：兼容 `/messages`、`x-api-key` 和 `anthropic-version` 请求头。
- Gemini API：兼容 `generateContent` / `streamGenerateContent`、`x-goog-api-key` 和 `usageMetadata` token 统计。

核心指标包括：

- RPM：每分钟请求数
- TPM：每分钟 Token 数
- TPS：每秒 Token 数
- TTFT：首 Token 延迟，仅流式模式准确
- 平均延迟、P50、P90、P95、P99
- 成功率、失败率、错误码分布
- 输入 Token、输出 Token、总 Token 统计

## 2. 产品定位

产品定位是面向小团队和开发者的“模型 API 性能测试控制台”，而不是大规模分布式压测平台。第一版优先保证简单、稳定、可部署、可复用现有代码。

第一版不做完整多租户、团队权限、分布式 Worker 和复杂任务编排。生产部署至少需要简单访问保护、并发上限、任务停止能力和结果清理策略。

## 3. 技术选型

### 后端

推荐使用：

- `FastAPI`：异步 Web 框架，适合包装现有 `asyncio + aiohttp` 压测逻辑，并自动生成 OpenAPI 文档。
- `SQLite`：保存任务配置、状态、汇总结果和报告索引，MVP 无需额外数据库服务。
- `SQLAlchemy 2.x`：统一数据访问层，后续可平滑切换 PostgreSQL。
- `asyncio.Task + asyncio.Queue`：MVP 后台任务执行方案。
- `Redis`：生产增强项，用于任务队列、进度缓存和跨进程状态同步。
- `results/`：继续保存 JSON、JSONL、Markdown、HTML、CSV 等文件。

后端职责：

- 创建测试任务
- 后台执行压测
- 查询任务状态和实时进度
- 通过 WebSocket 推送进度
- 停止正在运行的任务
- 管理历史记录和报告文件
- 限制最大并发和同时运行任务数

### 前端

推荐使用 ClaudeCode 方案中的：

- `Vue 3 + Vite`：开发轻量，和中后台控制台场景匹配。
- `Element Plus`：表单、表格、弹窗、分页等后台组件成熟，适合快速构建配置型界面。
- `ECharts`：现有 HTML 报告已经使用，Web 报告页可以复用图表数据结构和展示思路。
- `Pinia`：管理当前任务、历史筛选条件和报告状态。
- `Vue Router`：管理测试配置页、运行页、报告页和历史页。

UI 风格采用数据密集型控制台：紧凑布局、清晰表格、KPI 卡片、图表和日志流并列展示。主色建议使用蓝色系表示稳定状态，橙色用于启动、告警和关键操作；避免营销式大 Hero 和装饰性布局。

### 部署

推荐两种形态：

- 开发环境：前端 Vite dev server + FastAPI dev server。
- 生产环境：前端构建为静态文件，由 Nginx 或 FastAPI 静态服务托管；FastAPI 提供 `/api/*` 和 `/ws/*`。

MVP 可用单容器或 Docker Compose 部署。后续需要 Redis 时再扩展为多服务 Compose。

## 4. 推荐架构

```text
浏览器
  -> Vue 3 前端
     - 测试配置
     - 实时进度
     - 历史记录
     - 可视化报告
  -> HTTP / WebSocket
  -> FastAPI 后端
     - API 路由
     - TaskManager
     - WebLoadTestRunner
     - ProgressHub
     - ReportService
     - Repository
  -> SQLite + results/
```

关键原则：

- CLI 能力继续保留，Web 改造不能破坏 `python llm_load_test.py ...` 的使用方式。
- 压测核心先做轻量模块化，再由 Web 层包装，不重写核心算法。
- 任务状态以数据库为准，实时进度以内存为主，任务结束后固化汇总结果。
- 请求详情优先写 JSONL 文件，数据库只保存汇总和索引，避免大量明细拖慢 SQLite。

## 4.1 当前实现状态

截至 v0.2 开发阶段，项目已经完成 Web MVP 的主要骨架：

- 后端：FastAPI、SQLite、Repository、TaskManager、ProgressHub、WebSocket、任务停止、报告下载。
- 前端：Vue 3、Element Plus、ECharts、配置页、运行页、报告页、历史页。
- 核心脚本：保留 CLI，已支持进度回调、停止信号、日志回调和矩阵测试。
- 协议：已支持 OpenAI-compatible、Anthropic Messages、Gemini API。

v0.2 的重点不是重写功能，而是补齐协议抽象、Gemini 细节、UI 体验和基础安全。

## 5. 核心代码复用策略

现有 `llm_load_test.py` 已包含可复用能力：

- `LoadTestRunner`：异步压测执行
- `PromptFactory`：长文本 Prompt 生成
- `TokenEstimator`：Token 估算
- `summarize()`：汇总指标
- `render_markdown_report()`：Markdown 报告
- `render_html_report()`：HTML + ECharts 报告
- `run_matrix()`、`render_matrix_report()`、`generate_matrix_csv()`：矩阵测试能力

建议改造为三步：

1. 保持 CLI 入口不变，新增 `core/` 包或服务类包装现有对象。
2. 给 `LoadTestRunner` 增加可选参数：`progress_callback`、`stop_event`、`log_callback`。
3. 后端通过 `WebLoadTestRunner` 将 Web 配置转换为 `argparse.Namespace`，并调用现有运行和报告函数。

示例接口：

```python
class WebLoadTestRunner:
    def __init__(self, config, progress_callback=None, stop_event=None):
        self.config = config
        self.progress_callback = progress_callback
        self.stop_event = stop_event

    async def run(self) -> dict:
        args = self.to_namespace(self.config)
        tester = LoadTestRunner(
            args,
            progress_callback=self.progress_callback,
            stop_event=self.stop_event,
        )
        summary = await tester.run()
        return {
            "summary": summary,
            "details": tester.results,
        }
```

如果短期不想修改 `LoadTestRunner` 构造函数，可以先用轮询方式读取 `tester.results` 推送进度。但长期推荐回调钩子，因为日志、停止任务和矩阵进度都更清晰。

## 6. 功能模块

### 6.1 测试配置

页面分为四块：

- 基础配置：测试名称、Base URL、Endpoint 类型、模型名称、API Key。
- 负载配置：并发数、测试时长、输入 Token 数、最大输出 Token 数、预热请求数。
- 高级配置：流式开关、temperature、timeout、connect timeout、max retries、retry backoff、think time。
- 矩阵模式：`input_tokens_list x concurrency_list`，提交前展示计划预览。

MVP 只需要单次测试 + 核心参数。矩阵测试可以保留后端能力，前端作为第二阶段开放。

### 6.2 实时进度

实时页面展示：

- 状态：queued、running、stopping、completed、failed、cancelled。
- 进度：已完成请求数、成功数、失败数、运行时间。
- 实时指标：当前 QPS/RPM、当前 TPM、成功率、最近窗口平均延迟。
- 日志流：最近 50 条事件。
- 操作：停止任务、跳转报告。

WebSocket 推送格式：

```json
{
  "type": "progress",
  "test_id": "uuid",
  "data": {
    "completed_requests": 1234,
    "successful_requests": 1200,
    "failed_requests": 34,
    "success_rate": 0.9724,
    "current_qps": 45.2,
    "current_rpm": 2712,
    "current_tpm": 123456,
    "avg_latency_sec": 2.34,
    "elapsed_sec": 80
  }
}
```

推送策略：

- 默认每 2 秒推送一次。
- 或每完成 10 个请求触发一次，但要做节流，避免高并发时刷爆 WebSocket。
- 前端断线后可用 `GET /api/tests/{id}` 恢复当前状态。

### 6.3 报告展示

报告页展示：

- 配置摘要：模型、Base URL、并发、输入 Token、输出 Token、流式模式、测试时长。
- 指标总览：总请求、成功率、RPM、TPM、TPS、平均延迟、P95、P99。
- TTFT 分析：仅流式模式展示，并明确非流式模式不可准确测量。
- 图表：延迟分布、TTFT 分布、QPS/TPM 时间序列、错误分布。
- 结论摘要：复用现有规则，给出延迟、吞吐、错误率和瓶颈判断。
- 下载：summary JSON、details JSONL、Markdown、HTML、矩阵 CSV。

### 6.4 历史记录

历史页展示：

- 表格列：名称、模型、并发、输入 Token、时长、成功率、RPM、TPM、状态、创建时间。
- 筛选：模型、状态、时间范围。
- 排序：创建时间、TPM、成功率、P95 延迟。
- 操作：查看报告、复制配置重跑、删除记录。

对比功能放在 P1，不进入 MVP 必选范围。

## 7. 后端 API 设计

### 任务 API

```text
POST   /api/tests              创建并启动测试
GET    /api/tests              历史列表
GET    /api/tests/{id}         查询任务状态
POST   /api/tests/{id}/stop    停止任务
DELETE /api/tests/{id}         删除任务和报告索引
```

### 报告 API

```text
GET /api/tests/{id}/report              获取报告结构化数据
GET /api/tests/{id}/details             分页读取 JSONL 明细
GET /api/tests/{id}/download/summary    下载 summary JSON
GET /api/tests/{id}/download/details    下载 details JSONL
GET /api/tests/{id}/download/markdown   下载 Markdown 报告
GET /api/tests/{id}/download/html       下载 HTML 报告
```

### WebSocket

```text
WS /ws/tests/{id}
```

WebSocket 只承载实时状态，不作为最终结果来源。最终结果仍以数据库和 `results/` 文件为准。

## 8. 数据库设计

MVP 推荐三张表：任务表、结果表、事件表。请求详情继续保存在 JSONL 文件中。

```sql
CREATE TABLE test_tasks (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    base_url TEXT NOT NULL,
    endpoint TEXT NOT NULL,
    model TEXT NOT NULL,
    status TEXT NOT NULL,
    concurrency INTEGER NOT NULL,
    duration_sec INTEGER NOT NULL,
    input_tokens INTEGER NOT NULL,
    max_output_tokens INTEGER NOT NULL,
    enable_stream BOOLEAN NOT NULL,
    matrix_mode BOOLEAN NOT NULL DEFAULT 0,
    config_json TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL,
    started_at TIMESTAMP,
    completed_at TIMESTAMP
);

CREATE TABLE test_results (
    task_id TEXT PRIMARY KEY,
    summary_json TEXT,
    error_message TEXT,
    summary_path TEXT,
    details_jsonl_path TEXT,
    report_md_path TEXT,
    report_html_path TEXT,
    matrix_csv_path TEXT,
    FOREIGN KEY (task_id) REFERENCES test_tasks(id)
);

CREATE TABLE test_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,
    level TEXT NOT NULL,
    message TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL,
    FOREIGN KEY (task_id) REFERENCES test_tasks(id)
);

CREATE INDEX idx_test_tasks_status ON test_tasks(status);
CREATE INDEX idx_test_tasks_created_at ON test_tasks(created_at DESC);
CREATE INDEX idx_test_tasks_model ON test_tasks(model);
CREATE INDEX idx_test_events_task_id ON test_events(task_id);
```

API Key 策略：

- MVP：API Key 只在任务运行期间保存在内存，不写入数据库、日志或结果文件。
- 生产增强：如需保存配置模板，再使用 `cryptography.fernet` 加密，并将加密主密钥放入环境变量。
- 前端输入框默认按密钥处理，历史记录和报告中只展示脱敏值。

## 9. 任务执行与隔离

MVP 使用进程内任务管理：

- `TaskManager` 维护 `test_id -> asyncio.Task`。
- 每个测试有独立 `stop_event`、进度快照和日志队列。
- 设置 `MAX_RUNNING_TESTS` 和 `MAX_CONCURRENCY_PER_TEST`，避免用户误操作。
- FastAPI 启动时扫描数据库，将未完成的 `running/queued` 任务标记为 `failed` 或 `interrupted`。

生产增强：

- 引入 Redis 保存任务状态和进度。
- 使用独立 Worker 进程执行压测。
- 如果需要跨机器压测，再设计分布式调度，不在 MVP 中提前复杂化。

## 10. 前端信息架构

推荐路由：

```text
/                 重定向到 /tests/new
/tests/new        新建测试
/tests/:id/run    实时运行
/tests/:id/report 报告详情
/history          历史记录
/compare          测试对比，P1
```

核心组件：

- `ConfigForm.vue`：测试配置表单。
- `MetricCards.vue`：KPI 指标卡。
- `ProgressPanel.vue`：进度、状态和停止按钮。
- `LogStream.vue`：实时日志。
- `MetricsTable.vue`：延迟、TTFT、吞吐指标表。
- `ChartPanel.vue`：ECharts 图表容器。
- `HistoryTable.vue`：历史列表。

交互要求：

- 表单项必须有清晰 label、范围提示和错误提示。
- 启动按钮在提交中禁用，防止重复启动。
- 停止任务需要二次确认。
- 所有图表提供表格数据兜底。
- 移动端可查看结果，但主要优化桌面端操作效率。

## 11. 部署方案

### Docker Compose MVP

```yaml
services:
  app:
    build: .
    ports:
      - "8000:8000"
    volumes:
      - ./data:/app/data
      - ./results:/app/results
    environment:
      - DATABASE_URL=sqlite:////app/data/llm_test.db
      - RESULTS_DIR=/app/results
      - MAX_RUNNING_TESTS=2
      - MAX_CONCURRENCY_PER_TEST=500
    restart: unless-stopped
```

### Nginx/Caddy 增强

生产环境建议增加：

- HTTPS
- Basic Auth 或轻量登录
- `/api/*` 反向代理到 FastAPI
- `/ws/*` WebSocket 代理
- 静态文件缓存
- 请求体大小和超时配置

## 12. 开发阶段规划

### 阶段 1：核心模块化与后端 MVP

- 保留 CLI 行为不变。
- 为 `LoadTestRunner` 增加进度回调、停止信号和日志回调。
- 新建 FastAPI 服务。
- 实现 SQLite 表结构和 Repository。
- 实现创建任务、查询任务、停止任务。
- 完成单次测试的结果落库和报告文件生成。

### 阶段 2：前端 MVP

- 新建 Vue 3 + Vite + Element Plus 项目。
- 实现新建测试表单。
- 实现运行状态页和 WebSocket 进度展示。
- 实现历史列表。
- 实现报告详情页的核心指标和下载入口。

### 阶段 3：报告和矩阵增强

- 将现有 HTML 报告中的 ECharts 数据拆成结构化图表 API。
- 增加 TTFT、延迟分布、错误分布、时间序列图。
- 支持矩阵测试配置和矩阵报告。
- 增加复制配置重跑和 2-4 个测试对比。

### 阶段 4：生产部署

- 增加 Dockerfile、docker-compose.yml、`.env.example`。
- 增加 Nginx/Caddy 示例配置。
- 增加访问保护。
- 增加结果清理策略。
- 编写部署文档和用户使用说明。

### 当前阶段：v0.2 打磨

- 抽象协议适配层，集中管理三类协议的 headers、payload、endpoint 和 usage 解析。
- 完善 Gemini 支持：默认 Base URL、流式/非流式 endpoint 自动切换、`usageMetadata` 解析。
- 美化配置页：用提供商卡片替代普通协议单选，保持数据密集型控制台风格。
- 补强文件安全：报告下载限制在 `results/` 下，删除任务同步删除对应结果目录。
- 增加协议烟测和构建验证，确保 CLI 与 Web 都不回退。

## 13. MVP 范围

MVP 必须包含：

- 单模型单次测试
- 核心参数配置
- API Key 内存使用且不落库
- 后台任务运行
- 任务停止
- WebSocket 实时进度
- RPM、TPM、TTFT、延迟、成功率统计
- 自动生成 JSON、JSONL、Markdown、HTML 报告
- 历史记录

v0.2 增补：

- OpenAI-compatible、Anthropic、Gemini 三协议选择
- Gemini stream/non-stream endpoint 联动
- 专业化配置表单 UI
- 报告下载路径安全校验
- 删除历史时清理任务结果目录

生产部署阶段再包含：

- Docker 本地部署
- Nginx/Caddy 示例配置
- 访问保护
- 结果清理策略

MVP 暂不包含：

- 完整用户系统
- 分布式压测
- 团队权限
- 定时任务
- 多模型自动横向对比
- Redis 队列
- API Key 模板化持久保存

## 14. 风险与缓解

| 风险 | 影响 | 缓解措施 |
| --- | --- | --- |
| 单机并发过高 | 服务器或目标 API 被打满 | 限制最大并发和同时运行任务数 |
| 任务中断后状态不一致 | 历史记录误导用户 | 启动时修复未完成任务状态 |
| API Key 泄露 | 安全事故 | 默认不落库、不写日志、报告脱敏 |
| 请求详情过大 | SQLite 查询慢、磁盘膨胀 | 明细写 JSONL，历史只存汇总，增加清理策略 |
| WebSocket 断线 | 前端进度丢失 | 支持 REST 状态恢复 |
| TTFT 指标误用 | 非流式结果不准确 | 非流式模式隐藏或标记 TTFT 不可用 |
| 修改核心脚本破坏 CLI | 现有用户受影响 | CLI 回归测试，先包装后拆分 |

## 15. 验收标准

后端：

- `python llm_load_test.py ...` 原 CLI 命令仍可运行。
- `python llm_load_test.py --help` 能看到 `--api-protocol {openai,anthropic,gemini}`。
- `POST /api/tests` 能启动一次测试并返回 `test_id`。
- `GET /api/tests/{id}` 能查询状态和关键进度。
- `POST /api/tests/{id}/stop` 能停止运行中的任务。
- 测试完成后能生成 summary、details、Markdown、HTML 报告。
- 下载报告不能访问 `results/` 之外的文件。
- 删除任务会清理对应 `results/{task_id}/` 目录。

前端：

- 用户无需命令行即可启动测试。
- 用户可以在 OpenAI-compatible、Anthropic Messages、Gemini API 之间选择协议。
- Gemini 开启/关闭流式模式时自动切换 endpoint。
- 运行页能实时看到成功数、失败数、RPM、TPM、延迟。
- 历史页能筛选和打开报告。
- 报告页能查看核心指标和下载文件。
- 表单错误、接口错误、任务失败都有明确提示。

部署：

- `docker compose up` 后可访问 Web 页面。
- `data/` 和 `results/` 可持久化。
- `.env.example` 覆盖必要配置项。

## 16. 后续扩展

- Redis 队列和独立 Worker
- PostgreSQL 存储
- 多模型横向对比
- 参数模板管理
- 自动寻找最佳并发区间
- 定时压测和趋势分析
- 团队共享报告
- Prometheus/Grafana 监控
- 完整登录和权限系统

