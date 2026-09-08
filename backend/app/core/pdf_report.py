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


def render_pdf_html(
    summary: dict[str, Any],
    charts: dict[str, Any] | None = None,
    *,
    details: list[Any] | None = None,
) -> str:
    charts = charts or {}
    if summary.get("task_kind") == "cache_diagnostics":
        body = _render_cache_diagnostics_body(summary)
    elif summary.get("task_kind") == "vendor_billing_self_test":
        body = _render_vendor_billing_body(summary)
    elif summary.get("matrix"):
        body = _render_matrix_body(summary, charts)
    else:
        body = _render_single_body(summary, charts, details or [])
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
    .detail-table {{ table-layout: fixed; font-size: 9px; break-inside: auto; margin-bottom: 12px; }}
    .detail-table th, .detail-table td {{ padding: 5px 4px; text-align: center; overflow-wrap: anywhere; }}
    .detail-table thead {{ display: table-header-group; }}
    .detail-table tbody {{ break-inside: auto; }}
    .detail-table tr {{ break-inside: avoid; page-break-inside: avoid; }}
    .billing-table {{ table-layout: fixed; font-size: 9px; }}
    .billing-table th, .billing-table td {{ padding: 5px 4px; text-align: center; overflow-wrap: anywhere; }}
    .detail-performance th:nth-child(1) {{ width: 6%; }}
    .detail-performance th:nth-child(2) {{ width: 7%; }}
    .detail-performance th:nth-child(3) {{ width: 8%; }}
    .detail-performance th:nth-child(4), .detail-performance th:nth-child(5) {{ width: 12%; }}
    .detail-performance th:nth-child(6), .detail-performance th:nth-child(7), .detail-performance th:nth-child(8) {{ width: 12%; }}
    .detail-performance th:nth-child(9) {{ width: 9%; }}
    .detail-errors th:nth-child(1) {{ width: 7%; }}
    .detail-errors th:nth-child(2), .detail-errors th:nth-child(3), .detail-errors th:nth-child(4) {{ width: 14%; }}
    .detail-errors th:nth-child(5) {{ width: 11%; }}
    .detail-errors th:nth-child(6) {{ width: 15%; }}
    .detail-errors th:nth-child(7) {{ width: 25%; }}
    .detail-errors td:nth-child(6), .detail-errors td:nth-child(7) {{ text-align: left; word-break: break-word; }}
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
    charts = {} if summary.get("task_kind") in {"cache_diagnostics", "vendor_billing_self_test"} else build_chart_data(summary, details_path, charts_path=charts_path)
    details = _load_pdf_details(details_path)
    html_text = render_pdf_html(summary, charts, details=details)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = output_path.with_name(f".{output_path.name}.{uuid.uuid4().hex}.tmp")
    try:
        render_pdf_file_sync(html_text, temp_path)
        os.replace(temp_path, output_path)
    finally:
        temp_path.unlink(missing_ok=True)
    return output_path


def _load_pdf_details(path: str | None) -> list[dict[str, Any]]:
    if not path or not Path(path).exists():
        return []
    details: list[dict[str, Any]] = []
    with Path(path).open("r", encoding="utf-8") as detail_file:
        for line in detail_file:
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(item, dict):
                details.append(item)
    return details


def _render_single_body(summary: dict[str, Any], charts: dict[str, Any], details: list[Any]) -> str:
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
    <h2>压测结果汇总</h2>{_single_summary_table(cfg, res, details)}
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
    {_single_detail_section(details, cfg)}
    """



def _render_vendor_billing_body(summary: dict[str, Any]) -> str:
    cfg = summary.get("config") or {}
    rule = summary.get("pricing_rule") or {}
    details = summary.get("details") or []
    status = str(summary.get("status") or "unverifiable")
    status_labels = {
        "passed": "通过",
        "token_anomaly": "Token 异常",
        "pricing_unverifiable": "计价规则无法核验",
        "failed": "接口执行失败",
        "unverifiable": "无法核验",
        "cancelled": "已取消",
    }
    status_label = status_labels.get(status, status)
    rows = []
    for item in details:
        supplier = item.get("supplier") or {}
        reference = item.get("reference") or {}
        comparison = item.get("comparison") or {}
        rows.append([
            item.get("input_token_target"),
            supplier.get("input_tokens", "—"),
            reference.get("input_tokens", "—"),
            comparison.get("input_token_delta", "—"),
            supplier.get("output_tokens", "—"),
            reference.get("output_tokens", "—"),
            comparison.get("output_token_delta", "—"),
            comparison.get("supplier_cost", {}).get("total_usd", "—"),
            comparison.get("reference_cost", {}).get("total_usd", "—"),
            status_labels.get(comparison.get("status"), comparison.get("status", "—")),
        ])
    table = _data_table(
        ["输入目标", "供应商输入", "官方输入", "输入差值", "供应商输出", "官方输出", "输出差值", "供应商费用 USD", "官方费用 USD", "状态"],
        rows,
        css_class="billing-table",
    )
    config_rows = [
        ["供应商", cfg.get("supplier_name", "—"), "供应商模型", cfg.get("model", "—")],
        ["供应商 URL", cfg.get("base_url", "—"), "供应商 Endpoint", cfg.get("endpoint", "—")],
        ["官方模型", cfg.get("reference_model", "—"), "官方 Endpoint", cfg.get("reference_endpoint", "—")],
        ["输入长度组", "、".join(str(value) for value in cfg.get("input_token_lengths") or []) or "—", "最大输出 Token", cfg.get("max_output_tokens", "—")],
        ["价格规则", rule.get("id", "—"), "价格版本", rule.get("version", "—")],
        ["计价口径", rule.get("input_mode", "inclusive"), "判定容差", f"绝对 {cfg.get('token_abs_tolerance', '—')}；相对 {_percent(cfg.get('token_relative_tolerance'))}"],
    ]
    cards = [
        ("总体结论", status_label, f"完成 {summary.get('completed_groups', 0)} / {summary.get('total_groups', 0)} 组", "ok" if status == "passed" else "danger" if status in {"failed", "token_anomaly"} else "warn"),
        ("通过组数", _num((summary.get("status_counts") or {}).get("passed")), "输入 Token 在容差内", "ok"),
        ("Token 异常", _num((summary.get("status_counts") or {}).get("token_anomaly")), "输入 Token 差异超出容差", "danger"),
        ("无法核验", _num(sum((summary.get("status_counts") or {}).get(key, 0) for key in ("unverifiable", "pricing_unverifiable"))), "不使用估算值判定通过", "warn"),
    ]
    return f"""
    {_header(cfg, "供应商接入计费自测报告")}
    <p class="notice">本报告核验供应商与官方参考接口的 usage、输入 Token 差异及按价格规则计算的应计费用；不代表供应商实际账单扣费，也不保存 API Key、完整 Prompt 或完整回答。</p>
    <h2>结论摘要</h2>{_cards(cards)}
    <h2>连接与价格规则</h2>{_data_table(["项目", "值", "项目", "值"], config_rows)}
    <h2>逐组 Token 与费用对照</h2>{table}
    <h2>判定说明</h2><p class="muted">{html.escape("；".join(f"{status_labels.get(key, key)} {value} 组" for key, value in (summary.get("status_counts") or {}).items()) or "没有完成的测试组")}</p>
    """

def _render_cache_diagnostics_body(summary: dict[str, Any]) -> str:
    cfg = summary.get("config") or {}
    cases = [_cache_case_view(item, cfg) for item in summary.get("cases") or []]
    results = _cache_results_view(summary.get("results") or {}, cases)
    cards = [
        ("计划请求", _num(results.get("planned_requests")), "所有 Case 业务请求", ""),
        ("实际请求", _num(results.get("executed_requests")), f"Case {_num(results.get('total_cases'))} 个", ""),
        ("可判定验证", _num(results.get("decidable_requests")), "命中与明确未命中", "ok"),
        ("总体命中率", _percent(results.get("cache_hit_rate")), f"命中 {_num(results.get('cache_hit_requests'))} / 可判定 {_num(results.get('decidable_requests'))}", "ok" if results.get("cache_hit_rate") is not None else "warn"),
        ("无法判定", _num(results.get("unverifiable_requests")), "成功但无缓存字段", "warn"),
        ("执行失败", _num(results.get("failed_requests")), "失败样本独立统计", "danger" if results.get("failed_requests") else "ok"),
    ]
    prefix_target = cfg.get("cache_prefix_target_tokens", cfg.get("input_tokens"))
    prefix_actual = cfg.get("cache_prefix_actual_tokens")
    requests_per_case = cfg.get("requests_per_case")
    config_rows = [
        ["测试名称", cfg.get("name") or "缓存专项测试", "协议", cfg.get("api_protocol")],
        ["模型", cfg.get("model"), "Endpoint", cfg.get("endpoint")],
        ["流式", "开启" if cfg.get("enable_stream") else "关闭", "最大输出 Token", _num(cfg.get("max_output_tokens"))],
        ["公共前缀目标 Token", _num(prefix_target), "公共前缀实际 Token", _num(prefix_actual)],
        ["每 Case 请求次数", _num(requests_per_case), "计划请求总数", _num(results.get("planned_requests"))],
        ["选中 Case", "、".join(cfg.get("case_ids") or []), "接入域名", cfg.get("base_url")],
    ]
    case_sections = []
    status_labels = {
        "cache_hit": "缓存命中",
        "cache_miss": "未命中缓存",
        "unverifiable": "无法判定",
        "failed": "执行失败",
    }
    classification_labels = {
        "cache_hit": "缓存命中",
        "cache_miss": "未命中缓存",
        "unverifiable": "无法判定",
        "failed": "执行失败",
    }
    for case in cases:
        performance_rows = []
        cache_rows = []
        for item in case["requests"]:
            cache = item.get("cache") or {}
            request_index = item.get("request_index")
            phase_label = item.get("phase_label") or ("缓存建立" if item.get("phase") == "prepare" else "缓存验证")
            classification = classification_labels.get(item.get("classification"), "不计入")
            performance_rows.append([
                request_index,
                phase_label,
                classification,
                "成功" if item.get("ok") else "失败",
                _num(item.get("status")),
                _seconds(item.get("latency_sec")),
                _seconds(item.get("ttft_sec")),
                _num(item.get("input_tokens")),
                _num(item.get("output_tokens")),
                _num(item.get("total_tokens")),
            ])
            cache_rows.append([
                request_index,
                phase_label,
                classification,
                _num(cache.get("cached_input_tokens")) if cache.get("observed") else "不可用",
                _num(cache.get("cache_creation_input_tokens")) if cache.get("observed") else "不可用",
                _num(cache.get("cache_inclusive_total_tokens")),
                _percent(cache.get("cache_hit_rate")) if cache.get("observed") else "不可用",
                " · ".join(part for part in [item.get("error_type"), item.get("error_message")] if part) or "-",
            ])
        failure = case.get("failure_phase")
        meta = f"判定：{status_labels.get(case.get('status'), case.get('status'))}"
        if failure:
            meta += f" · 失败阶段：{'缓存建立' if failure == 'prepare' else '缓存验证'}"
        stats = _data_table(
            ["计划", "实际", "验证样本", "命中", "未命中", "无法判定", "失败", "可判定", "Case 命中率"],
            [[
                _num(case.get("planned_requests")), _num(case.get("executed_requests")),
                _num(case.get("validation_requests")), _num(case.get("cache_hit_requests")),
                _num(case.get("cache_miss_requests")), _num(case.get("unverifiable_requests")),
                _num(case.get("failed_requests")), _num(case.get("decidable_requests")),
                _percent(case.get("cache_hit_rate")),
            ]],
            css_class="matrix-table",
        )
        if not performance_rows:
            request_tables = '<div class="muted">没有已执行请求。</div>'
        else:
            request_tables = (
                "<h3>逐请求性能与 Token</h3>"
                + _data_table(
                    ["序号", "阶段", "判定", "结果", "状态码", "总延迟", "TTFT", "输入", "输出", "总 Token"],
                    performance_rows,
                    css_class="matrix-table detail-table",
                )
                + "<h3>逐请求缓存与错误</h3>"
                + _data_table(
                    ["序号", "阶段", "判定", "缓存命中", "缓存创建", "含缓存", "请求缓存比例", "错误"],
                    cache_rows,
                    css_class="matrix-table detail-table detail-errors",
                )
            )
        case_sections.append(
            f"<h2>{html.escape(str(case.get('case_name') or '缓存 Case'))}</h2>"
            f"<div class='muted'>{html.escape(meta)} · {html.escape(str(case.get('description') or ''))}</div>"
            f"{stats}{request_tables}"
        )
    notice = (
        '<div class="notice">判定仅依据上游返回的缓存用量字段：命中 Token 大于 0 为“缓存命中”；'
        '明确返回缓存字段但命中为 0 为“未命中缓存”；未返回缓存字段为“无法判定”。不根据延迟或文本相似度推断。</div>'
    )
    cache_header = f"""
    <div class="header">
      <h1>缓存专项测试报告</h1>
      <div class="muted">模型：{html.escape(str(cfg.get('model') or '-'))} · 协议：{html.escape(str(cfg.get('api_protocol') or '-'))} · Base URL：{html.escape(str(cfg.get('base_url') or '-'))}</div>
      <div class="muted">流式：{'开启' if cfg.get('enable_stream') else '关闭'} · Case：{html.escape('、'.join(cfg.get('case_ids') or []))}</div>
    </div>
    """
    return f"""
    {cache_header}
    <h2>执行摘要</h2>{_cards(cards)}
    {notice}
    <h2>测试配置</h2>{_data_table(["项目", "值", "项目", "值"], config_rows)}
    {''.join(case_sections)}
    """


def _cache_request_classification(item: dict[str, Any]) -> str | None:
    if item.get("phase") == "prepare" or int(item.get("request_index") or 0) == 1:
        return None
    if not item.get("ok"):
        return "failed"
    cache = item.get("cache") or {}
    if not cache.get("observed"):
        return "unverifiable"
    return "cache_hit" if int(cache.get("cached_input_tokens") or 0) > 0 else "cache_miss"


def _cache_case_requests(case: dict[str, Any]) -> list[dict[str, Any]]:
    source = case.get("requests")
    legacy = not isinstance(source, list)
    if not legacy:
        raw_requests = [item for item in source if isinstance(item, dict)]
    else:
        raw_requests = [item for item in (case.get("prepare"), case.get("validate")) if isinstance(item, dict)]
    requests = []
    for index, raw in enumerate(raw_requests, start=1):
        item = dict(raw)
        item.setdefault("request_index", index)
        item.setdefault("phase", "prepare" if index == 1 else "validate")
        if legacy:
            default_label = "准备请求（缓存建立）" if item["phase"] == "prepare" else "验证请求（缓存验证）"
        else:
            default_label = "缓存建立" if item["phase"] == "prepare" else "缓存验证"
        item.setdefault("phase_label", default_label)
        if "classification" not in item:
            item["classification"] = _cache_request_classification(item)
        requests.append(item)
    return requests


def _cache_case_view(case: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
    view = dict(case)
    requests = _cache_case_requests(case)
    validation = [item for item in requests if item.get("phase") != "prepare"]
    counts = {
        key: sum(item.get("classification") == classification for item in validation)
        for key, classification in (
            ("cache_hit_requests", "cache_hit"),
            ("cache_miss_requests", "cache_miss"),
            ("unverifiable_requests", "unverifiable"),
            ("failed_requests", "failed"),
        )
    }
    decidable = counts["cache_hit_requests"] + counts["cache_miss_requests"]
    configured = cfg.get("requests_per_case")
    view.update({
        "requests": requests,
        "planned_requests": case.get("planned_requests", configured if configured is not None else len(requests)),
        "executed_requests": case.get("executed_requests", len(requests)),
        "validation_requests": case.get("validation_requests", len(validation)),
        **{key: case.get(key, value) for key, value in counts.items()},
        "decidable_requests": case.get("decidable_requests", decidable),
        "cache_hit_rate": case.get("cache_hit_rate", counts["cache_hit_requests"] / decidable if decidable else None),
    })
    return view


def _cache_results_view(results: dict[str, Any], cases: list[dict[str, Any]]) -> dict[str, Any]:
    view = dict(results)
    summed_fields = [
        "planned_requests", "executed_requests", "validation_requests", "cache_hit_requests",
        "cache_miss_requests", "unverifiable_requests", "failed_requests", "decidable_requests",
    ]
    for field in summed_fields:
        view.setdefault(field, sum(int(case.get(field) or 0) for case in cases))
    view.setdefault("total_cases", len(cases))
    decidable = int(view.get("decidable_requests") or 0)
    view.setdefault("cache_hit_rate", int(view.get("cache_hit_requests") or 0) / decidable if decidable else None)
    return view


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


def _detail_value(item: Any, field: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(field, default)
    return getattr(item, field, default)


def _detail_has_field(item: Any, field: str) -> bool:
    if isinstance(item, dict):
        return field in item
    return hasattr(item, field)


def _detail_decode(item: Any) -> float | None:
    latency = _detail_value(item, "latency_sec")
    ttft = _detail_value(item, "ttft_sec")
    if latency is None or ttft is None:
        return None
    try:
        latency_value = float(latency)
        ttft_value = float(ttft)
    except (TypeError, ValueError):
        return None
    if latency_value < 0 or ttft_value < 0 or ttft_value > latency_value:
        return None
    return latency_value - ttft_value


def _detail_cache_hit_rate(item: Any) -> float | None:
    if not _detail_has_field(item, "cached_input_tokens"):
        return None
    cached = _detail_value(item, "cached_input_tokens")
    created = _detail_value(item, "cache_creation_input_tokens", 0) or 0
    input_tokens = _detail_value(item, "input_tokens")
    try:
        cached_value = float(cached or 0)
        created_value = float(created)
        input_value = float(input_tokens or 0)
    except (TypeError, ValueError):
        return None
    denominator = max(input_value, cached_value + created_value)
    return cached_value / denominator if denominator > 0 else 0.0


def _detail_tps(item: Any) -> float | None:
    decode = _detail_decode(item)
    if decode is None or decode <= 0:
        return None
    try:
        return float(_detail_value(item, "output_tokens", 0) or 0) / decode
    except (TypeError, ValueError):
        return None


def _detail_summary(details: list[Any]) -> dict[str, Any]:
    successful = [item for item in details if _detail_value(item, "ok") is True]
    ttfts = [_detail_value(item, "ttft_sec") for item in successful if _detail_value(item, "ttft_sec") is not None]
    tps_values = [value for item in successful if (value := _detail_tps(item)) is not None]
    return {
        "successful": successful,
        "ttft_avg": sum(ttfts) / len(ttfts) if ttfts else None,
        "ttft_p95": _percentile_value(ttfts, 0.95),
        "tps_avg": sum(tps_values) / len(tps_values) if tps_values else None,
    }


def _percentile_value(values: list[Any], percentile: float) -> float | None:
    numbers = sorted(float(value) for value in values if value is not None)
    if not numbers:
        return None
    if len(numbers) == 1:
        return numbers[0]
    index = (len(numbers) - 1) * percentile
    lower = int(index)
    upper = min(lower + 1, len(numbers) - 1)
    return numbers[lower] + (numbers[upper] - numbers[lower]) * (index - lower)


def _single_summary_table(cfg: dict[str, Any], res: dict[str, Any], details: list[Any]) -> str:
    derived = _detail_summary(details)
    scene = "单次测试"
    if cfg.get("matrix_mode"):
        scene = f"{_num(cfg.get('input_tokens_target'))} × {_num(cfg.get('concurrency'))}"
    ttft_avg = res.get("ttft_sec_avg") if res.get("ttft_sec_avg") is not None else derived["ttft_avg"]
    ttft_p95 = res.get("ttft_sec_p95") if res.get("ttft_sec_p95") is not None else derived["ttft_p95"]
    tps_avg = derived["tps_avg"] if derived["tps_avg"] is not None else res.get("total_tps")
    rows = [[
        scene,
        cfg.get("model"),
        _percent(res.get("success_rate")),
        _num(res.get("total_input_tokens")),
        _num(res.get("total_output_tokens")),
        _percent(res.get("cache_hit_rate")),
        _seconds(res.get("latency_sec_avg")),
        _seconds(res.get("latency_sec_p50")),
        _seconds(res.get("latency_sec_p90")),
        _seconds(res.get("latency_sec_p95")),
        _seconds(ttft_avg),
        _seconds(ttft_p95),
        _num(tps_avg),
    ]]
    headers = ["场景", "模型", "成功率", "实际输入 Token", "实际输出 Token", "实际 Cache 命中率", "延迟 Avg", "延迟 P50", "延迟 P90", "延迟 P95", "TTFT Avg", "TTFT P95", "TPS Avg"]
    return _data_table(headers, rows, css_class="matrix-table")


def _single_detail_section(details: list[Any], cfg: dict[str, Any]) -> str:
    failures = [item for item in details if _detail_value(item, "ok") is not True]
    performance_rows = []
    cache_error_rows = []
    for item in details:
        performance_rows.append([
            _detail_value(item, "request_id"),
            "OK" if _detail_value(item, "ok") is True else "FAIL",
            _num(_detail_value(item, "status")),
            _seconds(_detail_value(item, "latency_sec")),
            _seconds(_detail_value(item, "ttft_sec")),
            _num(_detail_value(item, "input_tokens")),
            _num(_detail_value(item, "output_tokens")),
            _num(_detail_value(item, "total_tokens")),
            _num(_detail_tps(item)),
        ])
        cache_error_rows.append([
            _detail_value(item, "request_id"),
            _detail_metric(item, "cached_input_tokens", _num),
            _detail_metric(item, "cache_creation_input_tokens", _num),
            _detail_metric(item, "cache_inclusive_total_tokens", _num),
            _percent(_detail_cache_hit_rate(item)),
            _detail_value(item, "error_type") or "-",
            _detail_value(item, "error_message") or "-",
        ])
    performance_headers = ["ID", "结果", "状态码", "总延迟(s)", "TTFT(s)", "输入 Token", "输出 Token", "总 Token", "TPS"]
    cache_error_headers = ["ID", "缓存命中 Token", "缓存创建 Token", "含缓存 Token", "缓存命中率", "错误类型", "错误信息"]
    if performance_rows:
        performance_table = _data_table(performance_headers, performance_rows, css_class="detail-table detail-performance")
        cache_error_table = _data_table(cache_error_headers, cache_error_rows, css_class="detail-table detail-errors")
    else:
        performance_table = '<div class="muted">暂无请求明细，字段不可用</div>'
        cache_error_table = ""
    failure_text = _failure_summary(failures)
    notice = _latency_notice(cfg, {"ttft_samples": sum(1 for item in details if _detail_value(item, "ok") is True and _detail_value(item, "ttft_sec") is not None)})
    return (
        f'<h2>单次请求明细</h2>{notice}'
        f'<h3>请求状态、延迟与 Token</h3>{performance_table}'
        f'<h3>请求缓存与错误</h3>{cache_error_table}'
        f'{failure_text}'
    )


def _detail_metric(item: Any, field: str, formatter: Any) -> str:
    if not _detail_has_field(item, field):
        return "不可用"
    return formatter(_detail_value(item, field))


def _failure_summary(failures: list[Any]) -> str:
    if not failures:
        return '<div class="muted">失败样本：0 条</div>'
    groups: dict[str, list[str]] = {}
    for item in failures:
        key = _detail_value(item, "error_type") or f"HTTP_{_detail_value(item, 'status')}"
        request_id = _detail_value(item, "request_id")
        groups.setdefault(str(key), []).append(str(request_id))
    rows = []
    for key, request_ids in groups.items():
        matching = [item for item in failures if str(_detail_value(item, "error_type") or f"HTTP_{_detail_value(item, 'status')}") == key]
        message = next((_detail_value(item, "error_message") for item in matching if _detail_value(item, "error_message")), "-")
        statuses = ", ".join(sorted({str(_detail_value(item, "status")) for item in matching}))
        rows.append([statuses or "-", key, message, f"请求 #{'/#'.join(request_ids)}"])
    return f'<h3>失败样本：{len(failures)} 条</h3>{_data_table(["状态码", "失败原因", "错误信息", "请求编号"], rows)}'


def _data_table(headers: list[str], rows: list[list[Any]], *, css_class: str = "") -> str:
    head = "<tr>" + "".join(f"<th>{_esc(value)}</th>" for value in headers) + "</tr>"
    body = "".join("<tr>" + "".join(f"<td>{_esc(value)}</td>" for value in row) + "</tr>" for row in rows)
    return f'<table class="{css_class}"><thead>{head}</thead><tbody>{body}</tbody></table>'


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
        ("命中 TPM", "cache_hit_tpm", _num), ("Input TPS", "input_tps", _num),
        ("Output TPS", "output_tps", _num), ("Total TPS", "total_tps", _num),
    ]
    return _matrix_values_table(points, columns)


def _matrix_token_table(points: list[dict[str, Any]]) -> str:
    columns = [
        ("输入 Token", "input_tokens", _num), ("并发", "concurrency", _num),
        ("缓存命中率", "cache_hit_rate", _percent),
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
