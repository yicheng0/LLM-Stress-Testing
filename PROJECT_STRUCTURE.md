# 项目结构说明

## 当前活跃文件

### 核心压测模块
- **llm_load_test.py** - 推荐 CLI 启动入口
- **loadtest/** - 可复用压测核心包
  - config.py - CLI / Web 共用配置对象
  - protocols.py - 多协议 URL、headers、payload、usage、error 处理
  - executor.py / streaming.py - RequestExecutor、SseStreamParser 等单请求执行、重试和流式解析组件
  - runner.py / summary.py - LoadTestRunner、MetricsSummaryBuilder 等并发调度、矩阵测试和指标汇总组件
  - result_writer.py / reports.py - ReportArtifactWriter 和报告渲染组件

### 快速测试脚本
- **quick_test.py** - 快速验证测试（并发10，30秒，1k tokens）
- **quick_extreme_test.py** - 极限压测（并发500，30秒，60k tokens）

### 功能验证
- **test_glm_features.py** - API功能验证测试
  - max_tokens参数测试
  - stop序列测试
  - 模型名大小写测试

## 文档
- **CLAUDE.md** - 完整项目文档（架构、使用、配置）
- **CHANGELOG.md** - 优化点追踪
- **压测脚本增强实施计划.md** - 原始需求文档

## Memory系统
- **.claude/memory/** - 项目记忆系统
  - MEMORY.md - 索引
  - project_*.md - 项目背景和架构
  - feedback_*.md - 反馈和工作流
  - user_role.md - 用户角色

## 归档文件
- **archive/** - 历史说明目录；旧版本脚本已删除，保留 README 作为说明
  - README.md - 历史说明

## 输出目录
- **results/** - 测试结果输出
  - summary_*.json - 汇总指标
  - details_*.jsonl - 详细数据
  - report_*.md - Markdown报告
  - report_*.html - HTML可视化报告

