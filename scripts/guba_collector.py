"""
东方财富股吧数据采集器（大学生指数版）
仅使用 Python 标准库 urllib 请求并解析股吧页面 HTML，提取帖子内容。
不依赖 requests，不依赖任何专属平台（无 Coze 依赖）。
若网络不可用或解析失败，返回空列表，由上层使用内置示例数据补充。
"""

import re
import time
import random
import json
import urllib.request
import urllib.error
from typing import Optional

# 板块对应的股吧ID（与 ETF 代码一致）
PLATE_GBID = {
    "纳斯达克ETF": "513100",
    "黄金ETF": "518880",
    "CPO通信ETF": "515880",
    "半导体ETF": "512480",
}

PLATE_NAMES = {
    "513100": "纳斯达克ETF",
    "518880": "黄金ETF",
    "515880": "CPO通信ETF",
    "512480": "半导体ETF",
}

PLATE_ETF_CODES = {
    "纳斯达克ETF": "513100",
    "黄金ETF": "518880",
    "CPO通信ETF": "515880",
    "半导体ETF": "512480",
}

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
]


def _fetch_html(url: str, timeout: int = 15) -> str:
    """使用标准库 urllib 发起 GET 请求并返回文本"""
    headers = {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Referer": "https://guba.eastmoney.com/",
        "Connection": "keep-alive",
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            # 尝试用 gb18030/gbk 解码（东方财富常用）
            raw = resp.read()
            for enc in ("utf-8", "gb18030", "gbk"):
                try:
                    return raw.decode(enc)
                except UnicodeDecodeError:
                    continue
            return raw.decode("utf-8", errors="ignore")
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as e:
        print(f"[guba_collector] 请求 {url} 失败: {e}")
        return ""


def fetch_guba_posts(gbid: str, page: int = 1, max_posts: int = 30) -> list[dict]:
    """
    获取东方财富股吧指定板块的帖子列表

    Args:
        gbid: 股吧ID（如 "513100"）
        page: 页码
        max_posts: 最大获取帖子数

    Returns:
        list[dict]: 帖子列表（失败返回空列表）
    """
    url = f"https://guba.eastmoney.com/list,{gbid}_{page}.html"

    html = _fetch_html(url)
    posts = []

    if not html:
        return posts

    def _clean(html_fragment: str) -> str:
        return re.sub(r"<[^>]+>", "", html_fragment).strip()

    # 新版股吧列表结构（2026-08 起）：<tbody class="listbody"><tr class="listitem">...
    row_pattern = r'<tr class="listitem">(.*?)</tr>'
    blocks = re.findall(row_pattern, html, re.DOTALL)

    for block in blocks:
        if len(posts) >= max_posts:
            break

        title_match = re.search(r'<div class="title">\s*<a[^>]*>(.*?)</a>', block, re.DOTALL)
        title = _clean(title_match.group(1)) if title_match else ""

        author_match = re.search(r'<div class="author">\s*<a[^>]*>(.*?)</a>', block, re.DOTALL)
        author = _clean(author_match.group(1)) if author_match else "匿名"

        time_match = re.search(r'<div class="update">(.*?)</div>', block, re.DOTALL)
        post_time = _clean(time_match.group(1)) if time_match else ""

        read_match = re.search(r'<div class="read">(.*?)</div>', block, re.DOTALL)
        reads = _clean(read_match.group(1)) if read_match else "0"

        if not title:
            continue

        post = {
            "title": title,
            "content": title,
            "author": author,
            "time": post_time,
            "reads": reads,
            "source": "东方财富股吧",
            "plate": PLATE_NAMES.get(gbid, gbid),
        }
        posts.append(post)

    # 旧版股吧列表结构（兼容历史页面）
    pattern = r'<div class="articleh[^"]*">(.*?)</div>\s*</div>'
    blocks = re.findall(pattern, html, re.DOTALL)

    for block in blocks:
        if len(posts) >= max_posts:
            break

        title_match = re.search(r'<span class="l3[^"]*">.*?<a[^>]*href="[^"]*"[^>]*>(.*?)</a>', block, re.DOTALL)
        title = title_match.group(1).strip() if title_match else ""

        author_match = re.search(r'<a[^>]*class="l4[^"]*"[^>]*>(.*?)</a>', block, re.DOTALL)
        author = author_match.group(1).strip() if author_match else "匿名"

        time_match = re.search(r'<span class="l6[^"]*">(.*?)</span>', block, re.DOTALL)
        post_time = time_match.group(1).strip() if time_match else ""

        read_match = re.search(r'<span class="l1[^"]*">(.*?)</span>', block, re.DOTALL)
        reads = read_match.group(1).strip() if read_match else "0"

        if not title:
            continue

        post = {
            "title": title,
            "content": title,
            "author": author,
            "time": post_time,
            "reads": reads,
            "source": "东方财富股吧",
            "plate": PLATE_NAMES.get(gbid, gbid),
        }
        posts.append(post)

    # 备选模式
    if not posts:
        pattern2 = r'class="l3[^"]*"[^>]*>.*?<a[^>]*>(.*?)</a>'
        titles = re.findall(pattern2, html, re.DOTALL)
        for t in titles[:max_posts]:
            t = t.strip()
            if not t:
                continue
            post = {
                "title": t,
                "content": t,
                "author": "股吧用户",
                "time": "",
                "reads": "0",
                "source": "东方财富股吧",
                "plate": PLATE_NAMES.get(gbid, gbid),
            }
            posts.append(post)

    return posts


def collect_all_plates(max_posts_per_plate: int = 30) -> dict[str, list[dict]]:
    """采集所有板块的股吧帖子"""
    result = {}
    for plate_name, gbid in PLATE_GBID.items():
        posts = fetch_guba_posts(gbid, max_posts=max_posts_per_plate)
        result[plate_name] = posts
        time.sleep(1)
    return result


def get_sample_posts(plate_name: str, etf_code: str) -> list[dict]:
    """
    内置示例数据（仅在联网/股吧不可用时回退使用，保证看板可生成）。
    数据为示意性质，不代表真实行情。
    """
    samples = {
        "纳斯达克ETF": [
            {"title": "大学生求问，513100现在能上车吗？", "content": "我是学生，看室友都赚钱了，现在还能买吗？", "author": "校园小白", "time": "今天", "source": "示例数据"},
            {"title": "纳斯达克ETF涨疯了，生活费梭哈！", "content": "再不买来不及了，all in！闭眼冲", "author": "追涨党", "time": "今天", "source": "示例数据"},
            {"title": "纳斯达克ETF跌惨了，生活费亏没了", "content": "亏得饭都吃不起了，要不要割肉", "author": "吃土中", "time": "今天", "source": "示例数据"},
            {"title": "长期持有纳斯达克ETF的策略分析", "content": "从估值与现金流角度看配置价值", "author": "理性派", "time": "昨天", "source": "示例数据"},
        ],
        "黄金ETF": [
            {"title": "学生党黄金ETF买了点，求带", "content": "刚接触，学长说避险可以买", "author": "新生", "time": "今天", "source": "示例数据"},
            {"title": "黄金ETF跌了，套牢了怎么办", "content": "生活费亏没了，要不要吃土", "author": "焦虑党", "time": "今天", "source": "示例数据"},
            {"title": "黄金价格走势与宏观分析", "content": "实际利率与黄金负相关", "author": "研究僧", "time": "昨天", "source": "示例数据"},
        ],
        "CPO通信ETF": [
            {"title": "大学生CPO通信ETF上车了", "content": "博主说AI算力必涨，闭眼买", "author": "跟风侠", "time": "今天", "source": "示例数据"},
            {"title": "CPO板块技术分析", "content": "量价配合，关注支撑位", "author": "技术流", "time": "昨天", "source": "示例数据"},
        ],
        "半导体ETF": [
            {"title": "半导体ETF今天买明天卖做T", "content": "天天盯盘，频繁操作", "author": "短线客", "time": "今天", "source": "示例数据"},
            {"title": "半导体行业周期研究", "content": "国产化替代逻辑", "author": "产业党", "time": "昨天", "source": "示例数据"},
        ],
    }
    out = []
    for s in samples.get(plate_name, []):
        out.append({
            "title": s["title"],
            "content": s["content"],
            "author": s.get("author", "用户"),
            "time": s.get("time", ""),
            "reads": "0",
            "source": s.get("source", "示例数据"),
            "plate": plate_name,
        })
    return out


if __name__ == "__main__":
    posts = fetch_guba_posts("513100", max_posts=5)
    if not posts:
        posts = get_sample_posts("纳斯达克ETF", "513100")
    for p in posts:
        print(f"[{p['plate']}] {p['title']}")
