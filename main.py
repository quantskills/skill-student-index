"""
大学生指数 (Student Index) — 主入口脚本
编排流程：采集股吧数据 → 联网搜索 → 分析帖子 → 计算指数 → 生成看板

不依赖任何专属平台（无 Coze / 扣子 依赖）：
- 股吧采集使用标准库 urllib
- 联网搜索使用 scripts/web_searcher.py 模块（支持 search_func 或预收集结果两种模式）
- 若搜索函数未提供且无预收集数据，自动回退到内置示例数据，保证看板可生成
"""

import os
import json
import sys
from datetime import datetime

# 添加当前目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from scripts.guba_collector import collect_all_plates, get_sample_posts, PLATE_ETF_CODES
from scripts.analyzer import analyze_posts
from scripts.index_calculator import calculate_all_plates, get_advice
from scripts.web_searcher import (
    search_plate_posts,
    search_all_plates,
    ingest_precollected_by_plate,
    create_web_search_func,
    create_mock_search_func,
    build_search_queries,
)

PLATE_ORDER = ["纳斯达克ETF", "黄金ETF", "CPO通信ETF", "半导体ETF"]


def search_web_posts(search_web_func, plate_name: str, etf_code: str) -> list[dict]:
    """
    通过 Agent 自身的联网搜索能力获取学生党相关帖子

    已升级为调用 scripts/web_searcher.py 模块，支持：
    - 多组搜索关键词（含平台定向搜索：小红书/微博/雪球/贴吧）
    - 搜索结果归一化（兼容不同搜索引擎返回格式）
    - 自动去重（标题相似度去重）
    - 相关性过滤（保留含学生身份关键词的结果）

    Args:
        search_web_func: 联网搜索函数（由任意 Agent 环境提供，签名 search_web(query)->list[{title,snippet,...}]）
        plate_name: 板块名称
        etf_code: ETF代码

    Returns:
        list[dict]: 帖子列表
    """
    return search_plate_posts(search_web_func, plate_name, etf_code, max_results=15)


def collect_web_posts_by_plate(
    search_web_func=None,
    web_posts_raw: dict[str, list[dict]] | None = None,
    plates: list[str] | None = None,
) -> dict[str, list[dict]]:
    """
    统一的联网搜索数据采集入口，支持两种模式：

    模式 A — 传入搜索函数（search_web_func）：
        Agent 提供一个搜索函数，脚本自动执行多组搜索
    模式 B — 传入预收集结果（web_posts_raw）：
        Agent 已通过自身搜索工具（如 WebSearch）预先搜索，
        将结果按板块分组后直接传入

    Args:
        search_web_func: 搜索函数（模式 A）
        web_posts_raw: 预收集的搜索结果 {板块名: [结果dict, ...]}（模式 B）
        plates: 指定板块，None=全部

    Returns:
        dict[str, list[dict]]: {板块名: [帖子dict, ...]}
    """
    if web_posts_raw:
        # 模式 B：预收集结果
        print("[student_index] 使用预收集的联网搜索结果...")
        return ingest_precollected_by_plate(web_posts_raw, deduplicate=True, filter_relevant=True)

    if search_web_func:
        # 模式 A：搜索函数
        print("[student_index] 使用搜索函数执行联网搜索...")
        return search_all_plates(search_web_func, plates=plates, max_per_plate=15)

    # 两种模式都未提供
    print("[student_index] 未提供搜索函数或预收集数据，将使用内置示例数据")
    return {}


def generate_board_html(
    plate_results: dict[str, dict],
    analyzed_posts_by_plate: dict[str, list[dict]],
    advice_text: str,
    date_str: str,
    output_path: str,
):
    """生成可视化看板HTML"""

    template_path = os.path.join(os.path.dirname(__file__), "scripts", "template.html")
    with open(template_path, "r", encoding="utf-8") as f:
        template = f.read()

    # 生成卡片HTML
    cards_html = ""
    for plate in PLATE_ORDER:
        data = plate_results.get(plate, {})
        idx = data.get("index")
        if idx is None:
            cards_html += f"""
            <div class="card neutral">
                <div class="plate-name">{plate}</div>
                <div class="index-value neutral">--</div>
                <div class="interpretation neutral">数据不足</div>
            </div>"""
            continue

        signal = data.get("signal", "neutral")
        color_class = signal
        interp = data.get("interpretation", "")
        total = data.get("total_posts", 0)
        noob = data.get("student_posts", 0)

        cards_html += f"""
        <div class="card {signal}">
            <div class="plate-name">{plate}</div>
            <div class="index-value {color_class}">{idx}</div>
            <div class="interpretation {color_class}">{interp}</div>
            <div class="meta">
                <span>📝 {total}条帖子</span>
                <span>🎯 {noob}条学生党帖</span>
            </div>
        </div>"""

    # 确定建议颜色
    valid = [d["index"] for d in plate_results.values() if d["index"] is not None]
    avg_index = sum(valid) / len(valid) if valid else 0
    if avg_index > 60:
        advice_class = "sell"
    elif avg_index < 30:
        advice_class = "buy"
    else:
        advice_class = "neutral"

    # 生成表格行
    table_rows = ""
    for plate in PLATE_ORDER:
        posts = analyzed_posts_by_plate.get(plate, [])
        noob_posts = [p for p in posts if p.get("is_student")]
        for p in noob_posts[:5]:  # 每个板块最多展示5条
            title = p.get("title", "")[:40]
            dims = list(p.get("dimension_scores", {}).keys())[:2]
            dim_str = ", ".join(dims) if dims else "—"
            direction = p.get("direction", "中性")
            score = p.get("total_score", 0)
            table_rows += f"""
            <tr>
                <td>{plate}</td>
                <td>{title}</td>
                <td><span class="noob-tag">学生党</span></td>
                <td>{score}</td>
                <td>{direction}</td>
                <td style="font-size:11px;color:#8b949e">{dim_str}</td>
            </tr>"""

    # 生成图表数据
    index_chart_data = {"labels": [], "values": [], "colors": []}
    for plate in PLATE_ORDER:
        data = plate_results.get(plate, {})
        idx = data.get("index")
        if idx is not None:
            index_chart_data["labels"].append(plate)
            index_chart_data["values"].append(idx)
            signal = data.get("signal", "neutral")
            color_map = {
                "sell": "#f85149",
                "watch": "#d29922",
                "neutral": "#58a6ff",
                "accumulate": "#3fb950",
                "buy": "#2ea043",
            }
            index_chart_data["colors"].append(color_map.get(signal, "#58a6ff"))

    detail_chart_data = {"labels": [], "ratios": [], "intensities": []}
    for plate in PLATE_ORDER:
        data = plate_results.get(plate, {})
        if data.get("index") is not None:
            detail_chart_data["labels"].append(plate)
            detail_chart_data["ratios"].append(data.get("student_ratio", 0))
            detail_chart_data["intensities"].append(data.get("student_intensity", 0))

    # 各维度雷达图数据
    dimension_labels = ["身份自述", "知识求助", "情绪恐慌", "追涨冲动", "跟风盲从", "认知偏差", "高频操作"]
    dimension_chart_data = {"labels": dimension_labels, "datasets": []}
    for plate in PLATE_ORDER:
        posts = analyzed_posts_by_plate.get(plate, [])
        dim_scores = {dim: 0 for dim in dimension_labels}
        count = 0
        for p in posts:
            if p.get("is_student"):
                for dim, score in p.get("dimension_scores", {}).items():
                    if dim in dim_scores:
                        dim_scores[dim] += score
                count += 1
        if count > 0:
            avg_dims = [round(dim_scores[d] / count, 1) for d in dimension_labels]
            color_map_plate = {
                "纳斯达克ETF": "rgba(248,81,73,0.7)",
                "黄金ETF": "rgba(210,153,34,0.7)",
                "CPO通信ETF": "rgba(88,166,255,0.7)",
                "半导体ETF": "rgba(63,185,80,0.7)",
            }
            dimension_chart_data["datasets"].append({
                "label": plate,
                "data": avg_dims,
                "borderColor": color_map_plate.get(plate, "#58a6ff"),
                "backgroundColor": color_map_plate.get(plate, "#58a6ff33"),
            })

    # 替换模板占位符
    html = template
    html = html.replace("{date}", date_str)
    html = html.replace("{cards_html}", cards_html)
    html = html.replace("{advice_text}", advice_text)
    html = html.replace("{advice_class}", advice_class)
    html = html.replace("{table_rows}", table_rows)
    html = html.replace("{index_chart_data}", json.dumps(index_chart_data, ensure_ascii=False))
    html = html.replace("{detail_chart_data}", json.dumps(detail_chart_data, ensure_ascii=False))
    html = html.replace("{dimension_chart_data}", json.dumps(dimension_chart_data, ensure_ascii=False))

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"[student_index] 看板已生成: {output_path}")
    return output_path


def run_student_index(
    search_web_func=None,
    web_posts_raw: dict[str, list[dict]] | None = None,
    plates: list[str] | None = None,
    output_dir: str | None = None,
) -> dict:
    """
    运行大学生指数全流程

    Args:
        search_web_func: 联网搜索函数（由任意 Agent 提供，用于联网搜索学生党讨论）。
                          若不提供，则自动回退到内置示例数据。
        web_posts_raw: Agent 预收集的联网搜索结果 {板块名: [结果dict, ...]}。
                        优先级高于 search_web_func；若同时提供，使用 web_posts_raw。
        plates: 指定板块列表，None表示全部
        output_dir: 输出目录

    Returns:
        dict: 包含结果文本和文件路径
    """
    date_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    date_file = datetime.now().strftime("%Y%m%d")

    if output_dir is None:
        output_dir = "."

    # 步骤1: 采集股吧数据（标准库 urllib，失败返回空）
    print("[student_index] 开始采集东方财富股吧数据...")
    guba_posts_by_plate = collect_all_plates(max_posts_per_plate=30)
    guba_empty = all(len(v) == 0 for v in guba_posts_by_plate.values())
    if guba_empty:
        print("[student_index] 股吧数据为空（可能无网络），将使用内置示例数据补充")

    # 步骤2: 联网搜索数据（支持搜索函数或预收集结果两种模式）
    web_posts_by_plate = collect_web_posts_by_plate(
        search_web_func=search_web_func,
        web_posts_raw=web_posts_raw,
        plates=plates,
    )
    for plate_name in PLATE_ORDER:
        if plates and plate_name not in plates:
            continue
        count = len(web_posts_by_plate.get(plate_name, []))
        if count > 0:
            print(f"[student_index] {plate_name}: 获取 {count} 条联网帖子")

    # 合并数据；若某板块合并后仍为空，用内置示例补充
    all_posts_by_plate = {}
    for plate in PLATE_ORDER:
        if plates and plate not in plates:
            continue
        guba = guba_posts_by_plate.get(plate, [])
        web = web_posts_by_plate.get(plate, [])
        merged = guba + web
        if not merged:
            merged = get_sample_posts(plate, PLATE_ETF_CODES.get(plate, ""))
        all_posts_by_plate[plate] = merged

    # 步骤3: 分析帖子
    print("[student_index] 开始分析帖子...")
    analyzed_posts_by_plate = {}
    for plate, posts in all_posts_by_plate.items():
        analyzed_posts_by_plate[plate] = analyze_posts(posts)
        noob_count = sum(1 for p in analyzed_posts_by_plate[plate] if p.get("is_student"))
        print(f"[student_index] {plate}: {len(posts)}条帖子, {noob_count}条学生党帖")

    # 步骤4: 计算指数
    print("[student_index] 计算大学生指数...")
    plate_results = calculate_all_plates(analyzed_posts_by_plate)

    # 步骤5: 生成看板
    print("[student_index] 生成可视化看板...")
    output_path = os.path.join(output_dir, f"student_index_board_{date_file}.html")
    advice_text = get_advice(plate_results)

    generate_board_html(
        plate_results, analyzed_posts_by_plate, advice_text,
        date_str, output_path
    )

    # 构建文字摘要
    summary_lines = [f"📊 大学生指数日报 — {date_str}\n"]
    for plate in PLATE_ORDER:
        data = plate_results.get(plate, {})
        idx = data.get("index")
        if idx is not None:
            interp = data.get("interpretation", "")
            summary_lines.append(f"• {plate}: {idx} — {interp}")
        else:
            summary_lines.append(f"• {plate}: 数据不足")

    summary_lines.append(f"\n{advice_text}")

    return {
        "summary": "\n".join(summary_lines),
        "html_path": output_path,
        "plate_results": plate_results,
    }


if __name__ == "__main__":
    # 测试：真实联网搜索 + mock 兜底，验证完整流程
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    print("=" * 60)
    print("测试模式 A：使用真实联网搜索（mock 兜底）")
    print("=" * 60)
    def make_search_func():
        web_search = create_web_search_func()
        mock_search = create_mock_search_func()

        def search_web(query: str) -> list[dict]:
            results = web_search(query)
            return results if results else mock_search(query)

        return search_web

    result = run_student_index(search_web_func=make_search_func())
    print(result["summary"])
    print(f"\n看板文件: {result['html_path']}")

    print("\n" + "=" * 60)
    print("测试模式 B：使用预收集数据")
    print("=" * 60)
    # 模拟 Agent 预先搜索后传入结果
    mock_search2 = create_mock_search_func()
    precollected = {}
    from scripts.web_searcher import PLATE_ETF_CODES as _PEC, build_search_queries
    for plate, code in _PEC.items():
        queries = build_search_queries(plate, code)
        raw = []
        for q in queries[:3]:  # 每板块取前3组查询
            raw.extend(mock_search2(q["query"]))
        precollected[plate] = raw
    result2 = run_student_index(web_posts_raw=precollected)
    print(result2["summary"])
    print(f"\n看板文件: {result2['html_path']}")

    print("\n" + "=" * 60)
    print("测试模式 C：无搜索（回退到内置示例数据）")
    print("=" * 60)
    result3 = run_student_index()
    print(result3["summary"])
    print(f"\n看板文件: {result3['html_path']}")
