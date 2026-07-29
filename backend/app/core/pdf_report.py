from __future__ import annotations

import asyncio
import html
import json
import math
import os
import threading
import uuid
from pathlib import Path
from typing import Any

from backend.app.core.report_service import build_chart_data
from loadtest import build_matrix_chart_data


PDF_RENDER_ERROR = (
    "PDF 生成失败：请确认已安装 Playwright Chromium。"
    "本地执行 python -m playwright install chromium；容器请重新构建后端镜像。"
)


def pdf_path_for_result(summary_path: str | None, fallback_dir: Path) -> Path:
    if summary_path:
        source = Path(summary_path)
        if source.name.startswith("matrix_summary_"):
            return source.with_name(source.name.replace("matrix_summary_", "matrix_report_", 1)).with_suffix(".pdf")
        if source.name.startswith("summary_"):
            return source.with_name(source.name.replace("summary_", "report_", 1)).with_suffix(".pdf")
        return source.with_suffix(".pdf")
    return fallback_dir / "report.pdf"


def render_pdf_html(summary: dict[str, Any], charts: dict[str, Any] | None = None) -> str:
    charts = charts or {}
    if summary.get("matrix"):
        body = _render_matrix_body(summary, charts)
    else:
        body = _render_single_body(summary, charts)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <title>LLM API 压测报告</title>
  <style>
    @page {{ size: A4; margin: 14mm; }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; color: #111827; font-family: Arial, "Microsoft YaHei", sans-serif; background: #fff; }}
    h1 {{ margin: 0 0 6px; font-size: 26px; }}
    h2 {{ margin: 22px 0 10px; font-size: 18px; break-after: avoid; }}
    h3 {{ margin: 16px 0 8px; font-size: 14px; break-after: avoid; }}
    .muted {{ color: #4b5563; font-size: 12px; }}
    .notice {{ margin: 10px 0; padding: 10px 12px; border-left: 4px solid #f59e0b; background: #fffbeb; color: #92400e; font-size: 11px; break-inside: avoid; }}
    .header {{ padding-bottom: 14px; border-bottom: 2px solid #111827; }}
    .grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; }}
    .grid-3 {{ grid-template-columns: repeat(3, 1fr); }}
    .card {{ padding: 12px; border: 1px solid #d1d5db; border-left: 4px solid #111827; border-radius: 8px; break-inside: avoid; }}
    .card span {{ display: block; color: #4b5563; font-size: 11px; }}
    .card strong {{ display: block; margin-top: 6px; font-size: 20px; font-family: Consolas, monospace; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 11px; break-inside: avoid; }}
    th, td {{ padding: 7px 8px; border: 1px solid #d1d5db; text-align: left; }}
    th {{ background: #f3f4f6; font-weight: 700; }}
    .matrix-table {{ table-layout: fixed; font-size: 9px; }}
    .matrix-table th, .matrix-table td {{ padding: 5px 4px; text-align: center; overflow-wrap: anywhere; }}
    .charts {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }}
    .chart-card {{ padding: 10px; border: 1px solid #d1d5db; border-radius: 8px; break-inside: avoid; }}
    .chart-title {{ margin-bottom: 8px; color: #111827; font-size: 13px; font-weight: 700; }}
    svg {{ width: 100%; height: auto; display: block; }}
    .page-break {{ page-break-before: always; }}
    .ok {{ border-left-color: #16a34a; }}
    .warn {{ border-left-color: #f59e0b; }}
    .danger {{ border-left-color: #dc2626; }}
  </style>
</head>
<body>{body}</body>
</html>"""


async def render_pdf_file(html_text: str, output_path: Path) -> Path:
    try:
        from playwright.async_api import async_playwright
    except Exception as exc:  # pragma: no cover - depends on optional runtime install
        raise RuntimeError(PDF_RENDER_ERROR) from exc

    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(args=["--no-sandbox"])
            page = await browser.new_page(viewport={"width": 1240, "height": 1754})
            await page.set_content(html_text, wait_until="networkidle")
            await page.pdf(path=str(output_path), format="A4", print_background=True)
            await browser.close()
    except Exception as exc:  # pragma: no cover - depends on local browser runtime
        raise RuntimeError(PDF_RENDER_ERROR) from exc
    return output_path


def render_pdf_file_sync(html_text: str, output_path: Path) -> Path:
    result: dict[str, Any] = {}

    def runner() -> None:
        try:
            result["path"] = asyncio.run(render_pdf_file(html_text, output_path))
        except BaseException as exc:  # noqa: BLE001
            result["error"] = exc

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    thread.join()
    if result.get("error"):
        raise result["error"]
    return result["path"]


def ensure_pdf_report(
    *,
    summary: dict[str, Any],
    details_path: str | None,
    charts_path: str | None,
    output_path: Path,
) -> Path:
    charts = build_chart_data(summary, details_path, charts_path=charts_path)
    html_text = render_pdf_html(summary, charts)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = output_path.with_name(f".{output_path.name}.{uuid.uuid4().hex}.tmp")
    try:
        render_pdf_file_sync(html_text, temp_path)
        os.replace(temp_path, output_path)
    finally:
        temp_path.unlink(missing_ok=True)
    return output_path


def _render_single_body(summary: dict[str, Any], charts: dict[str, Any]) -> str:
    cfg = summary.get("config") or {}
    res = summary.get("results") or {}
    cards = [
        ("成功率", _percent(res.get("success_rate")), f"成功 {res.get('successful_requests', 0)} / 总计 {res.get('total_requests', 0)}", "ok"),
        ("RPM", _num(res.get("rpm")), f"QPS {_num(res.get('qps'))}", ""),
        ("Total TPM", _num(res.get("total_tpm")), f"TPS {_num(res.get('total_tps'))}", ""),
        ("缓存命中率", _percent(res.get("cache_hit_rate")), f"命中 TPM {_num(res.get('cache_hit_tpm'))}", "warn" if not res.get("cache_hit_rate") else "ok"),
        ("含缓存 TPM", _num(res.get("cache_inclusive_tpm") or res.get("total_tpm")), f"含缓存 Token {_num(res.get('total_cache_inclusive_tokens'))}", "ok"),
        ("P95 延迟", _seconds(res.get("latency_sec_p95")), f"平均 {_seconds(res.get('latency_sec_avg'))}", ""),
        ("TTFT P95", _seconds(res.get("ttft_sec_p95")), f"样本 {_num(res.get('ttft_samples'))}", ""),
        ("失败请求", _num(res.get("failed_requests")), "错误分布见下方", "danger" if res.get("failed_requests") else "ok"),
    ]
    return f"""
    {_header(cfg, "LLM API 压测报告")}
    <h2>核心指标</h2>{_cards(cards)}
    <h2>测试配置</h2>{_config_table(cfg)}
    <h2>请求指标</h2>{_request_table(res)}
    <h2>缓存表现</h2>{_cache_table(res)}
    <h2>图表</h2>
    <div class="charts">
      {_chart_card("吞吐趋势", _line_svg(charts.get("timeseries") or [], "time_sec", ["qps", "tpm"]))}
      {_chart_card("延迟直方图", _bar_svg((charts.get("latency_histogram") or {}).get("bins") or [], (charts.get("latency_histogram") or {}).get("counts") or []))}
      {_chart_card("TTFT / Decode", _dual_hist_svg(charts.get("ttft_histogram") or {}, charts.get("decode_histogram") or {}))}
      {_chart_card("错误分布", _pie_svg(charts.get("error_counts") or res.get("error_counts") or {}))}
    </div>
    <h2>延迟分布</h2>{_latency_notice(cfg, res)}{_latency_table(res)}
    <h2>吞吐指标</h2>{_throughput_table(res)}
    <h2>Token 汇总</h2>{_token_table(res)}
    <h2>状态码分布</h2>{_distribution_table(res.get("status_counts") or {}, "无状态码数据")}
    <h2>错误类型分布</h2>{_distribution_table(res.get("error_counts") or {}, "无错误")}
    """


def _render_matrix_body(summary: dict[str, Any], charts: dict[str, Any]) -> str:
    cfg = summary.get("config") or {}
    points = summary.get("results_matrix") or []
    matrix_points = _matrix_points(points, charts.get("matrix_points") or [])
    best_tpm = max([_metric(point, "total_tpm") for point in matrix_points] or [0])
    best_cache_tpm = max([_metric(point, "cache_inclusive_tpm", "total_tpm") for point in matrix_points] or [0])
    best_hit = max([_metric(point, "cache_hit_rate") for point in matrix_points] or [0])
    cards = [
        ("测试点", _num(summary.get("test_points") or len(points)), "输入 Token x 并发", ""),
        ("最高 TPM", _num(best_tpm), "矩阵峰值", "ok"),
        ("最高含缓存 TPM", _num(best_cache_tpm), "缓存吞吐峰值", "ok"),
        ("最高缓存命中率", _percent(best_hit), "矩阵峰值", "ok" if best_hit else "warn"),
    ]
    return f"""
    {_header(cfg, "LLM API 矩阵压测报告")}
    <h2>核心指标</h2>{_cards(cards)}
    <h2>测试配置</h2>{_config_table(cfg)}
    <h2>矩阵热力图</h2>
    <div class="charts">
      {_chart_card("TPM 热力图", _heatmap_svg(matrix_points, "total_tpm"))}
      {_chart_card("缓存命中率热力图", _heatmap_svg(matrix_points, "cache_hit_rate", ratio=True))}
    </div>
    <h2>矩阵测试点</h2>
    <h3>吞吐与成功率</h3>{_matrix_request_table(matrix_points)}<h4>Token 吞吐</h4>{_matrix_throughput_table(matrix_points)}
    <h3>Token 与缓存</h3>{_matrix_token_table(matrix_points)}
    <h3>延迟分布</h3>{_latency_notice(cfg, {"ttft_samples": sum(1 for point in matrix_points if point.get("ttft_avg") is not None)})}{_matrix_latency_table(matrix_points)}
    """


def _matrix_points(results_matrix: list[dict[str, Any]], cached_points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    derived = build_matrix_chart_data(results_matrix).get("matrix_points") if results_matrix else []
    by_key = {
        (point.get("input_tokens"), point.get("concurrency")): dict(point)
        for point in cached_points
    }
    for point in derived:
        key = (point.get("input_tokens"), point.get("concurrency"))
        target = by_key.setdefault(key, {})
        target.update({field: value for field, value in point.items() if value is not None})
    return list(by_key.values())


def _header(cfg: dict[str, Any], title: str) -> str:
    return f"""<div class="header">
      <h1>{_esc(title)}</h1>
      <div class="muted">模型：{_esc(cfg.get('model'))} · 协议：{_esc(cfg.get('api_protocol'))} · Base URL：{_esc(cfg.get('base_url'))}</div>
      <div class="muted">流式：{'开启' if cfg.get('enable_stream') else '关闭'} · 缓存测试：{'开启' if cfg.get('cache_test_enabled') else '关闭'} · 缓存预热：{_num(cfg.get('cache_warmup_requests'))}</div>
    </div>"""


def _cards(items: list[tuple[str, str, str, str]]) -> str:
    return "<div class=\"grid\">" + "".join(
        f"<div class=\"card {tone}\"><span>{_esc(label)}</span><strong>{value}</strong><span>{_esc(sub)}</span></div>"
        for label, value, sub, tone in items
    ) + "</div>"


def _config_table(cfg: dict[str, Any]) -> str:
    rows = [
        ("Endpoint", cfg.get("endpoint")),
        ("并发", cfg.get("concurrency")),
        ("时长", f"{cfg.get('duration_sec')} s"),
        ("输入 Token 目标", cfg.get("input_tokens_target")),
        ("实际输入 Token", cfg.get("input_tokens_actual")),
        ("最大输出 Token", cfg.get("max_output_tokens")),
        ("预热请求", cfg.get("warmup_requests")),
        ("Prompt 来源", cfg.get("prompt_source") or "synthetic"),
    ]
    return _rows_table(rows)


def _cache_table(res: dict[str, Any]) -> str:
    return _rows_table([
        ("缓存命中率", _percent(res.get("cache_hit_rate"))),
        ("缓存命中 Token", _num(res.get("total_cached_input_tokens"))),
        ("缓存创建 Token", _num(res.get("total_cache_creation_input_tokens"))),
        ("含缓存总 Token", _num(res.get("total_cache_inclusive_tokens") or res.get("total_tokens"))),
        ("缓存命中 TPM", _num(res.get("cache_hit_tpm"))),
        ("含缓存 TPM", _num(res.get("cache_inclusive_tpm") or res.get("total_tpm"))),
    ])


def _request_table(res: dict[str, Any]) -> str:
    return _rows_table([
        ("总请求", _num(res.get("total_requests"))),
        ("成功请求", _num(res.get("successful_requests"))),
        ("失败请求", _num(res.get("failed_requests"))),
        ("成功率", _percent(res.get("success_rate"))),
        ("QPS", _num(res.get("qps"))),
        ("RPM", _num(res.get("rpm"))),
    ])


def _latency_table(res: dict[str, Any]) -> str:
    head = "<tr><th>指标</th><th>Avg</th><th>P50</th><th>P90</th><th>P95</th><th>P99</th></tr>"
    rows = "".join(
        "<tr>"
        f"<th>{_esc(label)}</th>"
        + "".join(f"<td>{_seconds(res.get(f'{prefix}_{field}'))}</td>" for field in ["avg", "p50", "p90", "p95", "p99"])
        + "</tr>"
        for prefix, label in [("latency_sec", "总延迟"), ("ttft_sec", "TTFT"), ("decode_sec", "Decode")]
    )
    return f"<table>{head}{rows}</table>"


def _latency_notice(cfg: dict[str, Any], res: dict[str, Any]) -> str:
    if not cfg.get("enable_stream"):
        text = "非流式模式无法准确测量 TTFT / Decode；相关字段显示为不可用，请以总延迟、吞吐和错误分布为准。"
    elif not res or not res.get("ttft_samples"):
        text = "未采集到有效首 Token 样本；TTFT / Decode 缺失字段显示为不可用。"
    else:
        return ""
    return f'<div class="notice">{_esc(text)}</div>'


def _throughput_table(res: dict[str, Any]) -> str:
    return _rows_table([
        ("Input TPM", _num(res.get("input_tpm"))),
        ("Output TPM", _num(res.get("output_tpm"))),
        ("Total TPM", _num(res.get("total_tpm"))),
        ("含缓存 TPM", _num(res.get("cache_inclusive_tpm"))),
        ("缓存命中 TPM", _num(res.get("cache_hit_tpm"))),
        ("缓存命中率", _percent(res.get("cache_hit_rate"))),
        ("Input TPS", _num(res.get("input_tps"))),
        ("Output TPS", _num(res.get("output_tps"))),
        ("Total TPS", _num(res.get("total_tps"))),
    ])


def _token_table(res: dict[str, Any]) -> str:
    return _rows_table([
        ("总输入 Token", _num(res.get("total_input_tokens"))),
        ("总输出 Token", _num(res.get("total_output_tokens"))),
        ("总 Token", _num(res.get("total_tokens"))),
        ("缓存命中 Token", _num(res.get("total_cached_input_tokens"))),
        ("缓存创建 Token", _num(res.get("total_cache_creation_input_tokens"))),
        ("含缓存总 Token", _num(res.get("total_cache_inclusive_tokens"))),
    ])


def _matrix_request_table(points: list[dict[str, Any]]) -> str:
    columns = [
        ("输入 Token", "input_tokens", _num), ("并发", "concurrency", _num),
        ("总请求", "total_requests", _num), ("成功", "successful_requests", _num),
        ("失败", "failed_requests", _num), ("成功率", "success_rate", _percent),
        ("QPS", "qps", _num), ("RPM", "rpm", _num),
    ]
    return _matrix_values_table(points, columns)


def _matrix_throughput_table(points: list[dict[str, Any]]) -> str:
    columns = [
        ("输入 Token", "input_tokens", _num), ("并发", "concurrency", _num),
        ("Input TPM", "input_tpm", _num), ("Output TPM", "output_tpm", _num),
        ("Total TPM", "total_tpm", _num), ("含缓存 TPM", "cache_inclusive_tpm", _num),
        ("命中 TPM", "cache_hit_tpm", _num), ("Total TPS", "total_tps", _num),
    ]
    return _matrix_values_table(points, columns)


def _matrix_token_table(points: list[dict[str, Any]]) -> str:
    columns = [
        ("输入 Token", "input_tokens", _num), ("并发", "concurrency", _num),
        ("总输入 Token", "total_input_tokens", _num), ("总输出 Token", "total_output_tokens", _num),
        ("总 Token", "total_tokens", _num), ("命中 Token", "total_cached_input_tokens", _num),
        ("创建 Token", "total_cache_creation_input_tokens", _num), ("含缓存 Token", "total_cache_inclusive_tokens", _num),
    ]
    return _matrix_values_table(points, columns)


def _matrix_latency_table(points: list[dict[str, Any]]) -> str:
    head = "<tr><th>输入 Token</th><th>并发</th><th>指标</th><th>Avg</th><th>P50</th><th>P90</th><th>P95</th><th>P99</th></tr>"
    rows = []
    for point in points:
        for prefix, label in [("latency", "总延迟"), ("ttft", "TTFT"), ("decode", "Decode")]:
            values = "".join(f"<td>{_seconds(point.get(f'{prefix}_{field}'))}</td>" for field in ["avg", "p50", "p90", "p95", "p99"])
            rows.append(
                f"<tr><td>{_num(point.get('input_tokens'))}</td><td>{_num(point.get('concurrency'))}</td>"
                f"<th>{_esc(label)}</th>{values}</tr>"
            )
    return f'<table class="matrix-table">{head}{"".join(rows)}</table>'


def _matrix_values_table(points: list[dict[str, Any]], columns: list[tuple[str, str, Any]]) -> str:
    head = "<tr>" + "".join(f"<th>{_esc(label)}</th>" for label, _field, _formatter in columns) + "</tr>"
    rows = "".join(
        "<tr>" + "".join(f"<td>{formatter(point.get(field))}</td>" for _label, field, formatter in columns) + "</tr>"
        for point in points
    )
    return f'<table class="matrix-table">{head}{rows}</table>'


def _distribution_table(counts: dict[str, Any], empty_text: str) -> str:
    if not counts:
        return f'<div class="muted">{_esc(empty_text)}</div>'
    return _rows_table([(str(key), _num(value)) for key, value in sorted(counts.items())])


def _rows_table(rows: list[tuple[str, Any]]) -> str:
    return "<table>" + "".join(f"<tr><th>{_esc(k)}</th><td>{_esc(v)}</td></tr>" for k, v in rows) + "</table>"


def _chart_card(title: str, svg: str) -> str:
    return f"<div class=\"chart-card\"><div class=\"chart-title\">{_esc(title)}</div>{svg}</div>"


def _line_svg(data: list[dict[str, Any]], x_key: str, y_keys: list[str], width: int = 520, height: int = 260) -> str:
    if not data:
        return _empty_svg(width, height, "暂无趋势数据")
    colors = ["#2563eb", "#0f766e", "#f97316"]
    xs = [_float(item.get(x_key)) for item in data]
    all_values = [_float(item.get(key)) for item in data for key in y_keys]
    min_x, max_x = min(xs), max(xs) or 1
    max_y = max(all_values) or 1
    pad = 28
    parts = [_svg_axes(width, height, pad)]
    for idx, key in enumerate(y_keys):
        points = []
        for item in data:
            x = pad + (_float(item.get(x_key)) - min_x) / max(max_x - min_x, 1) * (width - pad * 2)
            y = height - pad - _float(item.get(key)) / max_y * (height - pad * 2)
            points.append(f"{x:.1f},{y:.1f}")
        parts.append(f"<polyline points=\"{' '.join(points)}\" fill=\"none\" stroke=\"{colors[idx % len(colors)]}\" stroke-width=\"2\"/>")
        parts.append(f"<text x=\"{pad + idx * 92}\" y=\"16\" font-size=\"11\" fill=\"{colors[idx % len(colors)]}\">{_esc(key.upper())}</text>")
    return f"<svg viewBox=\"0 0 {width} {height}\" role=\"img\">{''.join(parts)}</svg>"


def _bar_svg(labels: list[Any], values: list[Any], width: int = 520, height: int = 260) -> str:
    if not values:
        return _empty_svg(width, height, "暂无分布数据")
    pad = 28
    max_v = max([_float(v) for v in values] or [1]) or 1
    bar_w = (width - pad * 2) / max(len(values), 1)
    parts = [_svg_axes(width, height, pad)]
    for idx, value in enumerate(values):
        bar_h = _float(value) / max_v * (height - pad * 2)
        x = pad + idx * bar_w
        y = height - pad - bar_h
        parts.append(f"<rect x=\"{x:.1f}\" y=\"{y:.1f}\" width=\"{max(bar_w - 1, 1):.1f}\" height=\"{bar_h:.1f}\" fill=\"#2563eb\"/>")
    return f"<svg viewBox=\"0 0 {width} {height}\" role=\"img\">{''.join(parts)}</svg>"


def _dual_hist_svg(first: dict[str, Any], second: dict[str, Any]) -> str:
    bins = first.get("bins") or second.get("bins") or []
    a = first.get("counts") or []
    b = second.get("counts") or []
    if not a and not b:
        return _empty_svg(520, 260, "暂无 TTFT / Decode 数据")
    values = [(_float(a[i]) if i < len(a) else 0) + (_float(b[i]) if i < len(b) else 0) for i in range(max(len(a), len(b), len(bins)))]
    return _bar_svg(bins, values)


def _pie_svg(counts: dict[str, Any], width: int = 520, height: int = 260) -> str:
    total = sum(_float(v) for v in counts.values())
    if total <= 0:
        return _empty_svg(width, height, "无错误")
    rows = "".join(f"<tr><th>{_esc(k)}</th><td>{_num(v)}</td></tr>" for k, v in counts.items())
    return f"<svg viewBox=\"0 0 {width} {height}\"><circle cx=\"80\" cy=\"115\" r=\"58\" fill=\"#dc2626\"/><text x=\"80\" y=\"120\" text-anchor=\"middle\" fill=\"#fff\" font-size=\"16\">{_num(total)}</text><foreignObject x=\"170\" y=\"35\" width=\"320\" height=\"190\"><table xmlns=\"http://www.w3.org/1999/xhtml\">{rows}</table></foreignObject></svg>"


def _heatmap_svg(points: list[dict[str, Any]], field: str, *, ratio: bool = False, width: int = 520, height: int = 300) -> str:
    if not points:
        return _empty_svg(width, height, "暂无矩阵数据")
    inputs = sorted({_float(p.get("input_tokens")) for p in points})
    concurrencies = sorted({_float(p.get("concurrency")) for p in points})
    fallback = None if ratio else "total_tpm"
    max_v = max([_metric(p, field, fallback) for p in points] or [1]) or 1
    pad_l, pad_t = 70, 28
    cell_w = (width - pad_l - 20) / max(len(concurrencies), 1)
    cell_h = (height - pad_t - 30) / max(len(inputs), 1)
    point_map = {(_float(p.get("input_tokens")), _float(p.get("concurrency"))): p for p in points}
    parts = [f"<rect width=\"{width}\" height=\"{height}\" fill=\"#fff\"/>"]
    for y_idx, input_value in enumerate(inputs):
        parts.append(f"<text x=\"4\" y=\"{pad_t + y_idx * cell_h + cell_h / 2 + 4:.1f}\" font-size=\"10\">{_num(input_value)}</text>")
        for x_idx, conc in enumerate(concurrencies):
            p = point_map.get((input_value, conc), {})
            value = _metric(p, field, fallback)
            intensity = min(1, value / max_v)
            color = _blend("#eff6ff", "#0f766e", intensity)
            x = pad_l + x_idx * cell_w
            y = pad_t + y_idx * cell_h
            label = _percent(value) if ratio else _compact(value)
            parts.append(f"<rect x=\"{x:.1f}\" y=\"{y:.1f}\" width=\"{cell_w - 2:.1f}\" height=\"{cell_h - 2:.1f}\" rx=\"4\" fill=\"{color}\"/>")
            parts.append(f"<text x=\"{x + cell_w / 2:.1f}\" y=\"{y + cell_h / 2 + 4:.1f}\" text-anchor=\"middle\" font-size=\"10\" fill=\"#111827\">{label}</text>")
    for x_idx, conc in enumerate(concurrencies):
        parts.append(f"<text x=\"{pad_l + x_idx * cell_w + cell_w / 2:.1f}\" y=\"20\" text-anchor=\"middle\" font-size=\"10\">{_num(conc)}</text>")
    return f"<svg viewBox=\"0 0 {width} {height}\" role=\"img\">{''.join(parts)}</svg>"


def _svg_axes(width: int, height: int, pad: int) -> str:
    return f"<rect width=\"{width}\" height=\"{height}\" fill=\"#fff\"/><line x1=\"{pad}\" y1=\"{height-pad}\" x2=\"{width-pad}\" y2=\"{height-pad}\" stroke=\"#9ca3af\"/><line x1=\"{pad}\" y1=\"{pad}\" x2=\"{pad}\" y2=\"{height-pad}\" stroke=\"#9ca3af\"/>"


def _empty_svg(width: int, height: int, text: str) -> str:
    return f"<svg viewBox=\"0 0 {width} {height}\"><rect width=\"{width}\" height=\"{height}\" fill=\"#f9fafb\"/><text x=\"{width/2}\" y=\"{height/2}\" text-anchor=\"middle\" fill=\"#6b7280\" font-size=\"14\">{_esc(text)}</text></svg>"


def _metric(item: dict[str, Any], field: str, fallback: str | None = None) -> float:
    value = _float(item.get(field))
    if value > 0 or not fallback:
        return value
    return _float(item.get(fallback))


def _blend(start: str, end: str, t: float) -> str:
    def parse(color: str) -> tuple[int, int, int]:
        color = color.lstrip("#")
        return int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16)
    a = parse(start)
    b = parse(end)
    mixed = tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))
    return "#" + "".join(f"{part:02x}" for part in mixed)


def _float(value: Any) -> float:
    try:
        if value is None:
            return 0.0
        number = float(value)
        if math.isnan(number) or math.isinf(number):
            return 0.0
        return number
    except (TypeError, ValueError):
        return 0.0


def _num(value: Any) -> str:
    if value is None:
        return "不可用"
    number = _float(value)
    if abs(number) >= 1000:
        return f"{number:,.0f}"
    if number == int(number):
        return f"{int(number)}"
    return f"{number:,.2f}"


def _compact(value: Any) -> str:
    number = _float(value)
    if abs(number) >= 1_000_000:
        return f"{number / 1_000_000:.1f}M"
    if abs(number) >= 1_000:
        return f"{number / 1_000:.1f}K"
    return _num(number)


def _percent(value: Any) -> str:
    if value is None:
        return "不可用"
    return f"{_float(value) * 100:.2f}%"


def _seconds(value: Any) -> str:
    if value is None:
        return "不可用"
    return f"{_float(value):.4f}s"


def _esc(value: Any) -> str:
    if value is None:
        return "-"
    return html.escape(str(value))
