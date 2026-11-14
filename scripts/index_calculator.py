"""
指数计算器 — 根据分析结果计算大学生指数
不依赖任何专属平台
"""

from typing import Optional


def calculate_student_index(analyzed_posts: list[dict]) -> dict:
    """
    计算指定板块的大学生指数

    Args:
        analyzed_posts: 分析后的帖子列表，每项含 is_student, total_score, direction 等字段

    Returns:
        dict: 指数计算结果
    """
    total = len(analyzed_posts)
    if total == 0:
        return {
            "index": None,
            "student_ratio": 0,
            "student_intensity": 0,
            "emotional_extreme": 0,
            "signal_purity": 0,
            "total_posts": 0,
            "student_posts": 0,
            "interpretation": "数据不足",
            "signal": "neutral",
        }

    # 学生党帖统计
    student_posts = [p for p in analyzed_posts if p.get("is_student")]
    student_count = len(student_posts)

    # 1. 学生党占比 (0-100)
    student_ratio = (student_count / total) * 100

    # 2. 学生党强度 (0-100) — 学生党帖的平均得分归一化
    if student_count > 0:
        avg_score = sum(p.get("total_score", 0) for p in student_posts) / student_count
        student_intensity = min(avg_score / 10 * 100, 100)
    else:
        student_intensity = 0

    # 3. 情绪极端度 (0-100) — 恐慌帖 + 追涨帖的占比
    panic_posts = [p for p in student_posts if "情绪恐慌" in p.get("dimension_scores", {})]
    chase_posts = [p for p in student_posts if "追涨冲动" in p.get("dimension_scores", {})]

    panic_ratio = (len(panic_posts) / total) * 100 if total > 0 else 0
    chase_ratio = (len(chase_posts) / total) * 100 if total > 0 else 0

    emotional_extreme = panic_ratio * 0.5 + chase_ratio * 0.5

    # 4. 信号纯度 (0-100) — 学生党帖中买入倾向占比
    if student_count > 0:
        buy_student = [p for p in student_posts if p.get("direction") == "买入"]
        buy_ratio = (len(buy_student) / student_count) * 100
        signal_purity = buy_ratio
    else:
        signal_purity = 0

    # 综合指数 (0-100)
    student_index = (
        student_ratio * 0.40 +
        student_intensity * 0.25 +
        emotional_extreme * 0.20 +
        signal_purity * 0.15
    )

    student_index = min(student_index, 100)  # 封顶100

    # 解读
    if student_index >= 65:
        interpretation = "过热（反向卖出信号）"
        signal = "sell"
    elif student_index >= 50:
        interpretation = "偏热（关注回调风险）"
        signal = "watch"
    elif student_index >= 35:
        interpretation = "正常波动"
        signal = "neutral"
    elif student_index >= 20:
        interpretation = "偏冷（关注机会）"
        signal = "accumulate"
    else:
        interpretation = "恐慌（可能见底）"
        signal = "buy"

    return {
        "index": round(student_index, 1),
        "student_ratio": round(student_ratio, 1),
        "student_intensity": round(student_intensity, 1),
        "emotional_extreme": round(emotional_extreme, 1),
        "signal_purity": round(signal_purity, 1),
        "total_posts": total,
        "student_posts": student_count,
        "panic_posts": len(panic_posts),
        "chase_posts": len(chase_posts),
        "interpretation": interpretation,
        "signal": signal,
    }


def calculate_all_plates(analyzed_posts_by_plate: dict[str, list[dict]]) -> dict[str, dict]:
    """计算所有板块的大学生指数"""
    results = {}
    for plate_name, posts in analyzed_posts_by_plate.items():
        results[plate_name] = calculate_student_index(posts)
    return results


def get_advice(plate_results: dict[str, dict]) -> str:
    """根据所有板块的指数生成交易建议"""
    if not plate_results:
        return "暂无数据"

    # 找到最热和最冷的板块
    sorted_plates = sorted(
        [(name, data) for name, data in plate_results.items() if data["index"] is not None],
        key=lambda x: x[1]["index"],
        reverse=True
    )

    if not sorted_plates:
        return "数据不足，无法给出建议"

    hottest = sorted_plates[0]
    coldest = sorted_plates[-1]

    lines = []

    # 整体判断
    avg_index = sum(d["index"] for _, d in sorted_plates) / len(sorted_plates)
    if avg_index > 60:
        lines.append("⚠️ 整体市场情绪偏热，学生党情绪指标偏高，注意控制仓位")
    elif avg_index < 30:
        lines.append("📈 整体市场情绪偏冷，逆向思考可能蕴含机会")
    else:
        lines.append("📊 整体市场情绪正常")

    # 最强信号
    lines.append(f"🚨 最强信号：{hottest[0]} 指数 {hottest[1]['index']}，{hottest[1]['interpretation']}")
    lines.append(f"✅ 最冷板块：{coldest[0]} 指数 {coldest[1]['index']}，{coldest[1]['interpretation']}")

    # 具体建议
    for name, data in sorted_plates:
        idx = data["index"]
        if idx >= 65:
            lines.append(f"🔴 {name}：学生党情绪过热，建议逢高减仓")
        elif idx >= 50:
            lines.append(f"🟡 {name}：情绪偏热，注意回调风险")
        elif idx <= 20:
            lines.append(f"🟢 {name}：情绪恐慌，逆向思维可关注")
        elif idx <= 35:
            lines.append(f"🔵 {name}：情绪偏冷，可考虑逐步布局")

    return "\n".join(lines)


if __name__ == "__main__":
    # 测试
    test_data = {
        "纳斯达克ETF": [
            {"is_student": True, "total_score": 12, "direction": "买入", "dimension_scores": {"身份自述": 8, "追涨冲动": 7}},
            {"is_student": True, "total_score": 8, "direction": "买入", "dimension_scores": {"知识求助": 6}},
            {"is_student": False, "total_score": 2, "direction": "中性", "dimension_scores": {}},
            {"is_student": True, "total_score": 10, "direction": "买入", "dimension_scores": {"情绪恐慌": 5, "跟风盲从": 6}},
            {"is_student": False, "total_score": 0, "direction": "中性", "dimension_scores": {}},
        ],
        "黄金ETF": [
            {"is_student": False, "total_score": 3, "direction": "中性", "dimension_scores": {}},
            {"is_student": True, "total_score": 7, "direction": "买入", "dimension_scores": {"身份自述": 8}},
            {"is_student": False, "total_score": 1, "direction": "中性", "dimension_scores": {}},
            {"is_student": True, "total_score": 6, "direction": "卖出", "dimension_scores": {"情绪恐慌": 5}},
        ],
    }
    results = calculate_all_plates(test_data)
    for name, data in results.items():
        print(f"{name}: 指数 {data['index']} — {data['interpretation']}")
    print("\n" + get_advice(results))
