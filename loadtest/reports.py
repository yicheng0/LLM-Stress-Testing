from __future__ import annotations

import json
from typing import Any, Dict, List

from .metrics import _aggregate_by_time_window, _calculate_histogram, _analyze_metric
from .models import RequestResult


def render_markdown_report(summary: Dict[str, Any]) -> str:
    cfg = summary["config"]
    res = summary["results"]
    conclusion: list[str] = []
    if res["success_rate"] >= 0.99:
        conclusion.append("服务在当前压测参数下整体稳定，成功率达到目标水平。")
    elif res["success_rate"] >= 0.95:
        conclusion.append("服务基本可用，但存在一定比例失败，需要定位限流、超时或网关瓶颈。")
    else:
        conclusion.append("服务在当前压测参数下不稳定，建议优先处理容量、限流和请求超时问题。")

    latency_conclusion = _analyze_metric(
        res.get("latency_sec_p95"),
        [
            (60, "P95 延迟较高，长上下文推理或排队延迟可能是主要瓶颈。"),
            (20, "P95 延迟偏高，建议结合服务端队列时长、prefill 时间和 decode 时间继续拆解。"),
            (0, "延迟表现较平稳，尾延迟可接受。"),
        ],
    )
    if latency_conclusion:
        conclusion.append(latency_conclusion)

    ttft_conclusion = _analyze_metric(
        res.get("ttft_sec_p95"),
        [
            (10, "TTFT P95 超过 10 秒，Prefill 阶段存在严重瓶颈，建议检查模型加载、KV cache 分配和批处理策略。"),
            (5, "TTFT P95 偏高，长上下文 Prefill 可能是主要瓶颈。"),
            (0, "TTFT 表现良好，Prefill 阶段无明显瓶颈。"),
        ],
    )
    if ttft_conclusion:
        conclusion.append(ttft_conclusion)

    report = f"""# LLM API 压测报告

## 1. 测试目标
验证 LLM API 在高并发、长上下文条件下的稳定性、吞吐与延迟表现，重点观察：
- 是否能稳定承载长上下文 prefill 压力
- 在高并发下的成功率、尾延迟和错误分布
- 输入 TPM / 总 TPM 是否达到预期容量目标
- TTFT（首 token 时间）和 Decode 时间的分布特征

## 2. 测试配置
- 协议类型: **{cfg.get('api_protocol', 'openai')}**
- Base URL: `{cfg['base_url']}`
- Endpoint: `{cfg['endpoint']}`
- Model: `{cfg['model']}`
- 并发数: **{cfg['concurrency']}**
- 测试时长: **{cfg['duration_sec']} s**
- 目标输入 tokens: **{cfg['input_tokens_target']}**
- 实际输入 tokens: **{cfg['input_tokens_actual']}**
- 最大输出 tokens: **{cfg['max_output_tokens']}**
- 单请求超时: **{cfg['timeout_sec']} s**
- 预热请求数: **{cfg['warmup_requests']}**
- 流式模式: **{'启用' if cfg.get('enable_stream') else '禁用'}**

## 3. 核心结果
### 3.1 吞吐量指标
- 总请求数: **{res['total_requests']}**
- 成功请求数: **{res['successful_requests']}**
- 失败请求数: **{res['failed_requests']}**
- 成功率: **{res['success_rate'] * 100:.2f}%**
- QPS: **{res['qps']}**
- RPM: **{res['rpm']}**

### 3.2 Token 吞吐量
| 指标 | TPM | TPS |
|------|-----|-----|
| 输入 | {res['input_tpm']:,.0f} | {res['input_tps']:,.2f} |
| 输出 | {res['output_tpm']:,.0f} | {res['output_tps']:,.2f} |
| 总计 | {res['total_tpm']:,.0f} | {res['total_tps']:,.2f} |

### 3.3 延迟分布（秒）
| 指标 | 平均值 | P50 | P90 | P95 | P99 |
|------|--------|-----|-----|-----|-----|
| 总延迟 | {res['latency_sec_avg'] or 'N/A'} | {res['latency_sec_p50'] or 'N/A'} | {res['latency_sec_p90'] or 'N/A'} | {res['latency_sec_p95'] or 'N/A'} | {res['latency_sec_p99'] or 'N/A'} |
| TTFT | {res['ttft_sec_avg'] or 'N/A'} | {res['ttft_sec_p50'] or 'N/A'} | {res['ttft_sec_p90'] or 'N/A'} | {res['ttft_sec_p95'] or 'N/A'} | {res['ttft_sec_p99'] or 'N/A'} |
| Decode | {res['decode_sec_avg'] or 'N/A'} | {res['decode_sec_p50'] or 'N/A'} | {res['decode_sec_p90'] or 'N/A'} | {res['decode_sec_p95'] or 'N/A'} | {res['decode_sec_p99'] or 'N/A'} |

**说明**：
- TTFT（Time To First Token）：从请求发送到接收首个 token 的时间，反映 Prefill 阶段性能
- Decode：从首个 token 到完整响应的时间，反映生成阶段性能
- TTFT 样本数：{res.get('ttft_samples', 0)}（仅流式模式可用）

## 4. 状态码分布
```json
{json.dumps(res['status_counts'], ensure_ascii=False, indent=2)}
```

## 5. 错误分布
```json
{json.dumps(res['error_counts'], ensure_ascii=False, indent=2)}
```

## 6. 结果解读
{" ".join(conclusion)}

## 7. 性能瓶颈分析

### 7.1 延迟构成分析
"""
    if res.get("ttft_sec_avg") and res.get("decode_sec_avg"):
        ttft_ratio = res["ttft_sec_avg"] / res["latency_sec_avg"] * 100 if res["latency_sec_avg"] else 0
        decode_ratio = res["decode_sec_avg"] / res["latency_sec_avg"] * 100 if res["latency_sec_avg"] else 0
        report += f"""
- TTFT 占总延迟比例: **{ttft_ratio:.1f}%**
- Decode 占总延迟比例: **{decode_ratio:.1f}%**

**分析**：
"""
        if ttft_ratio > 70:
            report += "- Prefill 阶段是主要瓶颈，建议优化长上下文处理、KV cache 分配策略\n"
        elif decode_ratio > 70:
            report += "- Decode 阶段是主要瓶颈，建议优化生成速度、批处理策略\n"
        else:
            report += "- Prefill 和 Decode 时间较为均衡\n"
    else:
        report += "\n**注意**：未启用流式模式，无法测量 TTFT 和 Decode 时间。建议使用 `--enable-stream` 参数重新测试。\n"

    report += f"""
### 7.2 吞吐量评估
- 峰值 Total-TPM: **{res['total_tpm']:,.0f}**（当前测试）
- 理论 Total-TPM: 取决于模型容量和硬件配置

## 8. 结论与建议
1. **先确认模型上下文窗口**：并非所有模型都支持超长输入；若模型上下文上限低于测试值，失败并不代表服务容量不足。
2. **重点拆分延迟结构**：建议服务端增加 queue time、prefill time、decode time、first token time 指标。
3. **区分限流与容量瓶颈**：若 429 较多，优先调整配额；若 5xx/超时较多，更可能是推理实例瓶颈。
4. **逐级压测更有价值**：建议补充并发 50 / 100 / 150 / 200 的阶梯测试，找出拐点。
5. **长上下文建议单独评估**：超长 prompt 主要施压 prefill 吞吐，不等价于短 prompt 业务场景。
6. **启用流式模式测量 TTFT**：使用 `--enable-stream` 参数可获得更详细的性能分析数据。

## 9. 复现实验命令
```bash
python llm_load_test.py \\
  --api-protocol {cfg.get('api_protocol', 'openai')} \\
  --base-url {cfg['base_url']} \\
  --api-key '$API_KEY' \\
  --model {cfg['model']} \\
  --endpoint {cfg['endpoint']} \\
  --concurrency {cfg['concurrency']} \\
  --duration-sec {cfg['duration_sec']} \\
  --input-tokens {cfg['input_tokens_actual']} \\
  --max-output-tokens {cfg['max_output_tokens']} \\
  --timeout-sec {cfg['timeout_sec']} \\
  --enable-stream \\
  --output-dir ./results
```
"""
    return report


def render_html_report(summary: Dict[str, Any], details: List[RequestResult]) -> str:
    """生成交互式 HTML 可视化报告"""
    cfg = summary["config"]
    res = summary["results"]

    success_details = [d for d in details if d.ok]
    if not success_details:
        time_series_data = []
    else:
        start_time = min(d.started_at for d in success_details)
        time_series_data = []
        for d in success_details:
            time_series_data.append({
                "time": round(d.started_at - start_time, 2),
                "latency": round(d.latency_sec, 4),
                "ttft": round(d.ttft_sec, 4) if d.ttft_sec else None,
                "decode": round(d.latency_sec - d.ttft_sec, 4) if d.ttft_sec else None,
            })

    throughput_data = _aggregate_by_time_window(details, window_sec=2.0)
    latencies = [d.latency_sec for d in success_details]
    latency_hist = _calculate_histogram(latencies, bins=50)
    ttfts = [d.ttft_sec for d in success_details if d.ttft_sec is not None]
    ttft_hist = _calculate_histogram(ttfts, bins=50)

    total_requests = res["total_requests"]
    success_count = res["successful_requests"]
    failed_count = res["failed_requests"]
    error_counts = res["error_counts"]

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>LLM API 压测报告 - {cfg['model']}</title>
    <script src="https://cdn.jsdelivr.net/npm/echarts@5.4.3/dist/echarts.min.js"></script>
    <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-gray-50 p-8">
    <div class="max-w-7xl mx-auto">
        <h1 class="text-4xl font-bold text-gray-900 mb-2">LLM API 压测报告</h1>
        <p class="text-gray-600 mb-8">模型: {cfg['model']} | 并发: {cfg['concurrency']} | 时长: {cfg['duration_sec']}s</p>

        <div class="grid grid-cols-1 md:grid-cols-4 gap-4 mb-8">
            <div class="bg-white rounded-lg shadow p-6">
                <div class="text-sm text-gray-600 mb-1">成功率</div>
                <div class="text-3xl font-bold text-green-600">{res['success_rate']*100:.2f}%</div>
                <div class="text-xs text-gray-500 mt-1">{success_count}/{total_requests} 请求</div>
            </div>
            <div class="bg-white rounded-lg shadow p-6">
                <div class="text-sm text-gray-600 mb-1">QPS / RPM</div>
                <div class="text-3xl font-bold text-blue-600">{res['qps']:.1f}</div>
                <div class="text-xs text-gray-500 mt-1">RPM: {res['rpm']:.1f}</div>
            </div>
            <div class="bg-white rounded-lg shadow p-6">
                <div class="text-sm text-gray-600 mb-1">Total TPM</div>
                <div class="text-3xl font-bold text-purple-600">{res['total_tpm']:,.0f}</div>
                <div class="text-xs text-gray-500 mt-1">TPS: {res['total_tps']:,.1f}</div>
            </div>
            <div class="bg-white rounded-lg shadow p-6">
                <div class="text-sm text-gray-600 mb-1">延迟 P95</div>
                <div class="text-3xl font-bold text-orange-600">{res.get('latency_sec_p95') or 0:.2f}s</div>
                <div class="text-xs text-gray-500 mt-1">平均: {res.get('latency_sec_avg') or 0:.2f}s</div>
            </div>
        </div>

        <div class="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-8">
            <div class="bg-white rounded-lg shadow p-6">
                <h2 class="text-xl font-semibold mb-4">延迟时间序列</h2>
                <div id="latencyTimeline" style="width: 100%; height: 400px;"></div>
            </div>
            <div class="bg-white rounded-lg shadow p-6">
                <h2 class="text-xl font-semibold mb-4">吞吐量趋势</h2>
                <div id="throughputTrend" style="width: 100%; height: 400px;"></div>
            </div>
        </div>

        <div class="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-8">
            <div class="bg-white rounded-lg shadow p-6">
                <h2 class="text-xl font-semibold mb-4">成功率与错误分布</h2>
                <div id="successRate" style="width: 100%; height: 400px;"></div>
            </div>
            <div class="bg-white rounded-lg shadow p-6">
                <h2 class="text-xl font-semibold mb-4">延迟分布直方图</h2>
                <div id="latencyHistogram" style="width: 100%; height: 400px;"></div>
            </div>
        </div>

        <div class="bg-white rounded-lg shadow p-6 mb-8">
            <h2 class="text-xl font-semibold mb-4">详细统计</h2>
            <div class="overflow-x-auto">
                <table class="min-w-full divide-y divide-gray-200">
                    <thead class="bg-gray-50">
                        <tr>
                            <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">指标</th>
                            <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">平均值</th>
                            <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">P50</th>
                            <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">P90</th>
                            <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">P95</th>
                            <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">P99</th>
                        </tr>
                    </thead>
                    <tbody class="bg-white divide-y divide-gray-200">
                        <tr>
                            <td class="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900">总延迟 (s)</td>
                            <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">{res.get('latency_sec_avg') or 'N/A'}</td>
                            <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">{res.get('latency_sec_p50') or 'N/A'}</td>
                            <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">{res.get('latency_sec_p90') or 'N/A'}</td>
                            <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">{res.get('latency_sec_p95') or 'N/A'}</td>
                            <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">{res.get('latency_sec_p99') or 'N/A'}</td>
                        </tr>
                        <tr>
                            <td class="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900">TTFT (s)</td>
                            <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">{res.get('ttft_sec_avg') or 'N/A'}</td>
                            <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">{res.get('ttft_sec_p50') or 'N/A'}</td>
                            <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">{res.get('ttft_sec_p90') or 'N/A'}</td>
                            <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">{res.get('ttft_sec_p95') or 'N/A'}</td>
                            <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">{res.get('ttft_sec_p99') or 'N/A'}</td>
                        </tr>
                        <tr>
                            <td class="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900">Decode (s)</td>
                            <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">{res.get('decode_sec_avg') or 'N/A'}</td>
                            <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">{res.get('decode_sec_p50') or 'N/A'}</td>
                            <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">{res.get('decode_sec_p90') or 'N/A'}</td>
                            <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">{res.get('decode_sec_p95') or 'N/A'}</td>
                            <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">{res.get('decode_sec_p99') or 'N/A'}</td>
                        </tr>
                    </tbody>
                </table>
            </div>
        </div>
    </div>

    <script>
        const timeSeriesData = {json.dumps(time_series_data, ensure_ascii=False)};
        const throughputData = {json.dumps(throughput_data, ensure_ascii=False)};
        const latencyHist = {json.dumps(latency_hist, ensure_ascii=False)};
        const ttftHist = {json.dumps(ttft_hist, ensure_ascii=False)};
        const errorCounts = {json.dumps(error_counts, ensure_ascii=False)};

        const chart1 = echarts.init(document.getElementById('latencyTimeline'));
        chart1.setOption({{
            tooltip: {{ trigger: 'axis', axisPointer: {{ type: 'cross' }} }},
            legend: {{ data: ['总延迟', 'TTFT', 'Decode'] }},
            xAxis: {{ type: 'value', name: '时间 (s)', nameLocation: 'middle', nameGap: 30 }},
            yAxis: {{ type: 'value', name: '延迟 (s)', nameLocation: 'middle', nameGap: 50 }},
            series: [
                {{ name: '总延迟', type: 'scatter', data: timeSeriesData.map(d => [d.time, d.latency]), symbolSize: 4, itemStyle: {{ color: '#3b82f6' }} }},
                {{ name: 'TTFT', type: 'scatter', data: timeSeriesData.filter(d => d.ttft !== null).map(d => [d.time, d.ttft]), symbolSize: 4, itemStyle: {{ color: '#10b981' }} }},
                {{ name: 'Decode', type: 'scatter', data: timeSeriesData.filter(d => d.decode !== null).map(d => [d.time, d.decode]), symbolSize: 4, itemStyle: {{ color: '#f59e0b' }} }}
            ]
        }});

        const chart2 = echarts.init(document.getElementById('throughputTrend'));
        chart2.setOption({{
            tooltip: {{ trigger: 'axis', axisPointer: {{ type: 'cross' }} }},
            legend: {{ data: ['QPS', 'TPM'] }},
            xAxis: {{ type: 'value', name: '时间 (s)', nameLocation: 'middle', nameGap: 30 }},
            yAxis: [
                {{ type: 'value', name: 'QPS', position: 'left', nameLocation: 'middle', nameGap: 50 }},
                {{ type: 'value', name: 'TPM', position: 'right', nameLocation: 'middle', nameGap: 50 }}
            ],
            series: [
                {{ name: 'QPS', type: 'line', data: throughputData.map(d => [d.timestamp, d.qps]), smooth: true, itemStyle: {{ color: '#3b82f6' }} }},
                {{ name: 'TPM', type: 'line', yAxisIndex: 1, data: throughputData.map(d => [d.timestamp, d.tpm]), smooth: true, itemStyle: {{ color: '#8b5cf6' }} }}
            ]
        }});

        const chart3 = echarts.init(document.getElementById('successRate'));
        chart3.setOption({{
            tooltip: {{ trigger: 'item', formatter: '{{b}}: {{c}} ({{d}}%)' }},
            legend: {{ orient: 'vertical', left: 'left' }},
            series: [{{
                name: '请求分布',
                type: 'pie',
                radius: '50%',
                data: [
                    {{ value: {success_count}, name: '成功', itemStyle: {{ color: '#10b981' }} }},
                    {{ value: {failed_count}, name: '失败', itemStyle: {{ color: '#ef4444' }} }}
                ]
            }}]
        }});

        const chart4 = echarts.init(document.getElementById('latencyHistogram'));
        const p50 = {res.get('latency_sec_p50') or 0};
        const p95 = {res.get('latency_sec_p95') or 0};
        const p99 = {res.get('latency_sec_p99') or 0};
        chart4.setOption({{
            tooltip: {{ trigger: 'axis', axisPointer: {{ type: 'shadow' }} }},
            xAxis: {{ type: 'value', name: '延迟 (s)', nameLocation: 'middle', nameGap: 30 }},
            yAxis: {{ type: 'value', name: '请求数', nameLocation: 'middle', nameGap: 50 }},
            series: [{{
                name: '延迟分布',
                type: 'bar',
                data: latencyHist.bins.map((bin, i) => [bin, latencyHist.counts[i]]),
                itemStyle: {{ color: '#3b82f6' }},
                markLine: {{
                    data: [
                        {{ xAxis: p50, name: 'P50', lineStyle: {{ color: '#10b981' }} }},
                        {{ xAxis: p95, name: 'P95', lineStyle: {{ color: '#f59e0b' }} }},
                        {{ xAxis: p99, name: 'P99', lineStyle: {{ color: '#ef4444' }} }}
                    ],
                    label: {{ formatter: '{{b}}: {{c}}s' }}
                }}
            }}]
        }});

        window.addEventListener('resize', () => {{
            chart1.resize();
            chart2.resize();
            chart3.resize();
            chart4.resize();
        }});
    </script>
</body>
</html>"""
    return html


def render_matrix_report(results_matrix: list[Dict[str, Any]]) -> str:
    if not results_matrix:
        return "# 矩阵测试报告\n\n无测试数据。"
    first_result = results_matrix[0]
    cfg = first_result["config"]
    by_point = {
        (item["matrix_config"]["input_tokens"], item["matrix_config"]["concurrency"]): item
        for item in results_matrix
    }
    input_tokens_set = sorted({r["matrix_config"]["input_tokens"] for r in results_matrix})
    concurrency_set = sorted({r["matrix_config"]["concurrency"] for r in results_matrix})

    report = f"""# LLM API 矩阵压测报告

## 1. 测试概览
- Base URL: `{cfg['base_url']}`
- Model: `{cfg['model']}`
- 测试点数量: **{len(results_matrix)}**
- 每个测试点持续时间: **{first_result['config']['duration_sec']} 秒**
- 流式模式: **{'启用' if cfg.get('enable_stream') else '禁用'}**

## 2. 测试矩阵结果
"""

    matrix_specs = [
        ("2.1 吞吐量矩阵（RPM）", lambda result: f"{result['results']['rpm']:.1f}"),
        ("2.2 Total TPM 矩阵", lambda result: f"{result['results']['total_tpm']:,.0f}"),
        ("2.3 TTFT P95 矩阵（秒）", lambda result: f"{result['results'].get('ttft_sec_p95'):.2f}" if result['results'].get('ttft_sec_p95') else "N/A"),
        ("2.4 总延迟 P95 矩阵（秒）", lambda result: f"{result['results'].get('latency_sec_p95'):.2f}" if result['results'].get('latency_sec_p95') else "N/A"),
        ("2.5 成功率矩阵（%）", lambda result: f"{result['results']['success_rate'] * 100:.2f}"),
    ]
    for title, formatter in matrix_specs:
        report += f"\n### {title}\n\n| 输入 Tokens \\ 并发 |"
        for conc in concurrency_set:
            report += f" {conc} |"
        report += "\n|" + "---|" * (len(concurrency_set) + 1) + "\n"
        for input_tokens in input_tokens_set:
            report += f"| {input_tokens:,} |"
            for conc in concurrency_set:
                result = by_point.get((input_tokens, conc))
                report += f" {formatter(result)} |" if result else " N/A |"
            report += "\n"

    report += """
## 3. 矩阵分析

### 3.1 性能趋势
- **输入规模影响**：观察同一并发下，不同输入规模对 TTFT 和吞吐量的影响
- **并发影响**：观察同一输入规模下，不同并发对延迟和成功率的影响
- **最优配置**：找出成功率高、延迟低、吞吐量大的最优配置点

### 3.2 瓶颈识别
- 如果 TTFT 随输入规模线性增长，说明 Prefill 性能稳定
- 如果高并发下成功率下降，说明存在容量瓶颈或限流
- 如果延迟 P95 显著高于 P50，说明存在排队或资源竞争

### 3.3 容量规划建议
1. 根据业务场景的输入规模分布，选择合适的并发配置
2. 预留 20-30% 的容量余量应对突发流量
3. 监控成功率低于 99% 的配置点，避免在生产环境使用
"""
    return report


def generate_matrix_csv(results_matrix: list[Dict[str, Any]]) -> str:
    csv_lines = [
        "input_tokens,concurrency,rpm,qps,input_tpm,output_tpm,total_tpm,input_tps,output_tps,total_tps,"
        "success_rate,latency_avg,latency_p50,latency_p95,latency_p99,"
        "ttft_avg,ttft_p50,ttft_p95,ttft_p99,decode_avg,decode_p95"
    ]
    for result in results_matrix:
        matrix_cfg = result["matrix_config"]
        res = result["results"]
        csv_lines.append(
            f"{matrix_cfg['input_tokens']},{matrix_cfg['concurrency']},"
            f"{res['rpm']},{res['qps']},"
            f"{res['input_tpm']},{res['output_tpm']},{res['total_tpm']},"
            f"{res['input_tps']},{res['output_tps']},{res['total_tps']},"
            f"{res['success_rate']},"
            f"{res.get('latency_sec_avg') or ''},"
            f"{res.get('latency_sec_p50') or ''},"
            f"{res.get('latency_sec_p95') or ''},"
            f"{res.get('latency_sec_p99') or ''},"
            f"{res.get('ttft_sec_avg') or ''},"
            f"{res.get('ttft_sec_p50') or ''},"
            f"{res.get('ttft_sec_p95') or ''},"
            f"{res.get('ttft_sec_p99') or ''},"
            f"{res.get('decode_sec_avg') or ''},"
            f"{res.get('decode_sec_p95') or ''}"
        )
    return "\n".join(csv_lines)
