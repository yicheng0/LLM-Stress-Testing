# 项目结构说明

## 当前活跃文件

### 核心脚本
- **glm_tpm_test.py** (64KB, 1526行) - 主压测工具
  - 支持流式TTFT测量
  - 矩阵测试模式
  - 完整的指标统计（TPM/TPS/TTFT/Decode）
  - HTML可视化报告

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
- **archive/** - 旧版本脚本（已被glm_tpm_test.py取代）
  - load_test_llm_api(1).py
  - load_test_llm_tpm.py
  - README.md - 归档说明

## 输出目录
- **results/** - 测试结果输出
  - summary_*.json - 汇总指标
  - details_*.jsonl - 详细数据
  - report_*.md - Markdown报告
  - report_*.html - HTML可视化报告
