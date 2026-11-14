"""
分析引擎 — 判断帖子是否为"学生党帖"并评分
纯本地关键词规则，不调用任何外部API，不依赖任何专属平台
"""

import re
from typing import Optional

# ============================================================
# 7维度信号词库（大学生 / 学生党 视角）
# ============================================================

SIGNAL_WORDS = {
    "身份自述": {
        "keywords": [
            "大学生", "学生党", "我是学生", "在校", "研究生", "大一", "大二",
            "大三", "大四", "毕业生", "刚入学", "本科生", "硕士", "博士",
            "生活费", "零花钱", "压岁钱", "还没工作", "没收入", "穷学生",
            "学费", "勤工俭学", "助学贷款", "宿舍", "寝室", "校友",
        ],
        "score": 8,
    },
    "知识求助": {
        "keywords": [
            "这个能买吗", "能上车吗", "怎么开户", "怎么买基金", "能不能买",
            "现在能进吗", "现在买吗", "要不要买", "该不该买", "可以买吗",
            "求带", "学长带带", "学姐带带", "室友说", "同学说", "求教",
            "怎么操作", "怎么买", "多少钱可以买", "适合买吗", "值得买吗",
            "能买不", "能买吗", "可以买不", "现在可以买吗", "要不要上车",
            "能上车不", "教教我", "不懂啊", "完全不会",
        ],
        "score": 6,
    },
    "情绪恐慌": {
        "keywords": [
            "跌惨了", "套牢了", "生活费亏没了", "要不要吃土", "亏得饭都吃不起了",
            "亏麻了", "血亏", "跌没了", "还能涨吗", "会不会跌没了",
            "赶紧跑", "快跑", "跌得受不了", "跌停了", "被套", "深套",
            "跌得心慌", "跌得睡不着", "亏光了", "本金都没了", "爆仓了",
            "吃土", "下个月生活费", "饭都吃不起了", "完了完了", "回不了本",
        ],
        "score": 5,
    },
    "追涨冲动": {
        "keywords": [
            "涨疯了", "赶紧上车", "再不买来不及了", "涨得太猛", "追涨",
            "追高", "买买买", "all in", "梭哈", "满仓干", "生活费梭哈",
            "涨这么多", "起飞了", "暴涨", "涨停", "冲冲冲",
            "再不买就晚了", "涨得看不懂", "涨得心痒", "怕踏空", "踏空了",
            "赶紧追", "闭眼冲", "梭哈生活费",
        ],
        "score": 7,
    },
    "跟风盲从": {
        "keywords": [
            "同学都买", "室友赚钱了", "宿舍都在聊", "朋友圈都在晒", "学长推荐",
            "学姐推荐", "博主推荐", "主播说", "up主说", "大v说", "老师推荐",
            "群里说", "都说不错", "看好的人多", "热度很高", "很多人买",
            "看别人赚", "跟着买", "跟风", "随大流", "大家都在买", "听说涨",
        ],
        "score": 6,
    },
    "认知偏差": {
        "keywords": [
            "肯定涨", "跌不下去了", "稳赚", "稳了", "必然涨", "不可能跌",
            "只涨不跌", "包赚", "稳赚不赔", "绝对涨", "一定能涨", "涨定了",
            "铁定涨", "闭眼买", "这个位置很安全", "已经到底了", "底部确认",
            "跌不动了", "学生党都能赚", "闭眼入",
        ],
        "score": 4,
    },
    "高频操作": {
        "keywords": [
            "今天买了明天卖", "做T", "频繁操作", "短线", "今天进明天出",
            "超短线", "T+0", "做波段", "高抛低吸", "快进快出",
            "今天买明天卖", "做差价", "日内T", "每天操作", "天天盯盘",
            "盯盘", "盘中", "割完又买",
        ],
        "score": 5,
    },
}

# 买入意图关键词
BUY_SIGNALS = [
    "上车", "买了", "加仓", "抄底", "建仓", "买入", "入手",
    "进场", "开仓", "all in", "满仓", "申购", "补仓",
    "重仓", "低吸", "上车了", "买了点", "建仓了", "梭哈",
]

# 卖出意图关键词
SELL_SIGNALS = [
    "割肉", "清仓", "跑了", "卖了", "下车", "止盈", "止损",
    "卖出", "减仓", "出局", "抛了", "已卖", "出货",
    "空仓", "离场", "撤退", "清仓了", "全卖了",
]


def analyze_post(title: str, content: Optional[str] = None) -> dict:
    """
    分析单条帖子，判断是否为学生党帖并评分

    Args:
        title: 帖子标题
        content: 帖子内容（可选，如无则用标题）

    Returns:
        dict: 分析结果
    """
    text = (title + " " + (content or "")).lower()

    # 各维度得分
    dimension_scores = {}
    total_score = 0
    matched_keywords = []

    for dim_name, dim_info in SIGNAL_WORDS.items():
        dim_score = 0
        for kw in dim_info["keywords"]:
            if kw.lower() in text:
                dim_score += dim_info["score"]
                matched_keywords.append((dim_name, kw, dim_info["score"]))

        if dim_score > 0:
            dimension_scores[dim_name] = min(dim_score, dim_info["score"] * 3)  # 单维度封顶3倍
            total_score += dimension_scores[dim_name]

    # 判定方向（买入/卖出/中性）
    buy_count = sum(1 for s in BUY_SIGNALS if s in text)
    sell_count = sum(1 for s in SELL_SIGNALS if s in text)

    if buy_count > sell_count:
        direction = "买入"
    elif sell_count > buy_count:
        direction = "卖出"
    else:
        direction = "中性"

    # 判定是否为学生党帖（总分 >= 5 分）
    is_student = total_score >= 5

    return {
        "is_student": is_student,
        "total_score": total_score,
        "dimension_scores": dimension_scores,
        "direction": direction,
        "matched_keywords": matched_keywords,
        "buy_signals": buy_count,
        "sell_signals": sell_count,
    }


def analyze_posts(posts: list[dict]) -> list[dict]:
    """批量分析帖子"""
    results = []
    for post in posts:
        title = post.get("title", "")
        content = post.get("content", "")
        analysis = analyze_post(title, content)
        results.append({**post, **analysis})
    return results


if __name__ == "__main__":
    # 测试
    test_posts = [
        {"title": "大学生求问，513100现在能上车吗？", "content": "我是学生，看室友都赚钱了，现在还能买吗？"},
        {"title": "黄金ETF今天涨疯了，生活费梭哈！", "content": "再不买来不及了，all in！"},
        {"title": "纳斯达克ETF跌惨了，生活费亏没了", "content": "亏得饭都吃不起了，要不要割肉"},
        {"title": "ETF长期持有策略分析", "content": "从估值角度看当前配置价值"},
    ]
    results = analyze_posts(test_posts)
    for r in results:
        print(f"[{'学生党' if r['is_student'] else '正常'}] {r['title']} 评分:{r['total_score']} 方向:{r['direction']}")
