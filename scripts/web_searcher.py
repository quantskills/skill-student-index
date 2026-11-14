"""
联网搜索模块 — 大学生指数

负责：
1. 为每个板块生成多组搜索关键词（含平台定向搜索）
2. 归一化不同搜索引擎/工具返回的结果格式
3. 去重（基于标题相似度）
4. 相关性过滤（剔除明显无关的结果）
5. 提供 mock 搜索函数（无网络时用于测试）

设计原则：
- 不依赖任何特定搜索引擎 API，由上层 Agent 提供搜索能力
- 搜索函数接口灵活：search_web(query: str) -> list[dict]
- 返回的 dict 至少包含 title 和 snippet/content 字段，其余字段可选
"""

import re
import hashlib
import html
import random
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable, Optional
from datetime import datetime

# ============================================================
# 板块定义
# ============================================================

PLATE_ETF_CODES = {
    "纳斯达克ETF": "513100",
    "黄金ETF": "518880",
    "CPO通信ETF": "515880",
    "半导体ETF": "512480",
}

# 板块别名/关键词（用于搜索关键词扩展）
PLATE_KEYWORDS = {
    "纳斯达克ETF": ["纳斯达克", "纳指", "513100", "美股ETF", "QDII纳指"],
    "黄金ETF": ["黄金", "金价", "518880", "金ETF", "避险黄金"],
    "CPO通信ETF": ["CPO", "光模块", "通信", "515880", "AI算力", "光通信"],
    "半导体ETF": ["半导体", "芯片", "512480", "国产替代", "集成电路"],
}

# 目标平台（用于 site: 定向搜索）
TARGET_PLATFORMS = [
    {"name": "小红书", "site": "xiaohongshu.com", "alias": "小红书"},
    {"name": "微博", "site": "weibo.com", "alias": "微博"},
    {"name": "雪球", "site": "xueqiu.com", "alias": "雪球"},
    {"name": "贴吧", "site": "tieba.baidu.com", "alias": "贴吧"},
]

# 学生党身份关键词（用于结果过滤）
STUDENT_IDENTITY_KEYWORDS = [
    "大学生", "学生党", "学生", "研究生", "本科生", "大一", "大二", "大三", "大四",
    "生活费", "零花钱", "压岁钱", "宿舍", "室友", "同学", "学长", "学姐",
    "校园", "在校", "刚毕业", "新生", "没工作", "没收入",
]

# 投资/交易相关关键词（用于结果过滤，确保搜索结果是投资讨论而非无关内容）
INVESTMENT_KEYWORDS = [
    "ETF", "基金", "买", "卖", "涨", "跌", "赚", "亏", "上车", "下车",
    "梭哈", "加仓", "减仓", "割肉", "套牢", "开户", "定投", "申购",
    "分红", "净值", "行情", "盘", "仓位", "止盈", "止损",
]


# ============================================================
# 搜索关键词生成
# ============================================================

def build_search_queries(plate_name: str, etf_code: str) -> list[dict]:
    """
    为指定板块生成多组搜索关键词

    Returns:
        list[dict]: 每项包含 query(搜索词) 和 purpose(搜索目的) 和 platform(目标平台, 可选)
    """
    plate_kws = PLATE_KEYWORDS.get(plate_name, [plate_name, etf_code])
    primary_kw = plate_kws[0]  # 主关键词

    queries = []

    # --- 通用搜索（不限平台）---
    # 身份 + 板块 + 行为
    queries.append({"query": f"大学生 {primary_kw} ETF 买了 上车", "purpose": "身份+行为", "platform": None})
    queries.append({"query": f"学生党 {etf_code} 买了 生活费", "purpose": "身份+行为", "platform": None})
    queries.append({"query": f"大学生 {primary_kw} 能买吗 新手", "purpose": "求助型", "platform": None})

    # 身份 + 板块 + 情绪
    queries.append({"query": f"大学生 {primary_kw} 亏了 割肉 套牢", "purpose": "恐慌情绪", "platform": None})
    queries.append({"query": f"学生党 {primary_kw} 涨疯了 梭哈 追涨", "purpose": "追涨情绪", "platform": None})

    # 身份 + 板块 + 跟风
    queries.append({"query": f"大学生 {primary_kw} 同学 室友 推荐", "purpose": "跟风盲从", "platform": None})

    # 板块别名扩展
    for kw in plate_kws[1:3]:  # 取2个别名
        queries.append({"query": f"大学生 {kw} 买了 上车", "purpose": f"别名扩展({kw})", "platform": None})

    # --- 平台定向搜索 ---
    for platform in TARGET_PLATFORMS:
        # 每个平台搜一次"大学生 + 板块"
        queries.append({
            "query": f"site:{platform['site']} 大学生 {primary_kw} ETF",
            "purpose": f"{platform['name']}定向",
            "platform": platform["name"],
        })

    # --- 时间限定搜索（最近讨论）---
    current_year = datetime.now().year
    queries.append({
        "query": f"大学生 {primary_kw} ETF {current_year}",
        "purpose": "当年讨论",
        "platform": None,
    })

    return queries


def build_all_queries() -> dict[str, list[dict]]:
    """为所有板块生成搜索关键词"""
    result = {}
    for plate_name, etf_code in PLATE_ETF_CODES.items():
        result[plate_name] = build_search_queries(plate_name, etf_code)
    return result


# ============================================================
# 搜索结果归一化
# ============================================================

def normalize_search_result(item: dict, plate_name: str, source_tag: str = "联网搜索") -> dict:
    """
    将不同搜索引擎/工具返回的结果归一化为统一的帖子格式

    支持的字段名变体：
    - title / title_text / name / subject
    - snippet / content / abstract / summary / description / text
    - url / link / href / source_url
    - publish_time / time / date / published / create_time
    - source / source_name / site_name / from
    - author / author_name / user / nickname
    """
    # 标题
    title = (
        item.get("title")
        or item.get("title_text")
        or item.get("name")
        or item.get("subject")
        or ""
    )
    # 如果标题为空，尝试从 snippet 截取前50字
    if not title:
        snippet = item.get("snippet") or item.get("content") or item.get("abstract") or ""
        title = snippet[:50] if snippet else ""

    # 内容/摘要
    content = (
        item.get("snippet")
        or item.get("content")
        or item.get("abstract")
        or item.get("summary")
        or item.get("description")
        or item.get("text")
        or title
    )

    # URL
    url = (
        item.get("url")
        or item.get("link")
        or item.get("href")
        or item.get("source_url")
        or ""
    )

    # 发布时间
    pub_time = (
        item.get("publish_time")
        or item.get("time")
        or item.get("date")
        or item.get("published")
        or item.get("create_time")
        or ""
    )

    # 来源平台
    source = (
        item.get("source")
        or item.get("source_name")
        or item.get("site_name")
        or item.get("from")
        or source_tag
    )

    # 作者
    author = (
        item.get("author")
        or item.get("author_name")
        or item.get("user")
        or item.get("nickname")
        or "全网用户"
    )

    return {
        "title": title.strip(),
        "content": content.strip(),
        "author": author.strip() if isinstance(author, str) else str(author),
        "time": pub_time.strip() if isinstance(pub_time, str) else str(pub_time),
        "source": source.strip() if isinstance(source, str) else str(source),
        "plate": plate_name,
        "url": url.strip() if isinstance(url, str) else str(url),
    }


# ============================================================
# 去重
# ============================================================

def _normalize_title_for_dedup(title: str) -> str:
    """将标题归一化用于去重比较：去空格、标点、转小写"""
    # 去除 HTML 标签
    clean = re.sub(r"<[^>]+>", "", title)
    # 去除所有非中文非字母数字字符
    clean = re.sub(r"[^\u4e00-\u9fa5a-zA-Z0-9]", "", clean)
    return clean.lower()


def _title_hash(title: str) -> str:
    """计算标题的哈希值用于快速比较"""
    normalized = _normalize_title_for_dedup(title)
    return hashlib.md5(normalized.encode("utf-8")).hexdigest()


def _title_similarity(t1: str, t2: str) -> float:
    """
    计算两个标题的相似度（基于字符重叠率）
    返回 0-1 之间的值
    """
    n1 = _normalize_title_for_dedup(t1)
    n2 = _normalize_title_for_dedup(t2)
    if not n1 or not n2:
        return 0.0
    # 短标题包含在长标题中 → 高相似度
    if n1 in n2 or n2 in n1:
        return 1.0 if min(len(n1), len(n2)) >= 5 else 0.8
    # 字符集交集
    set1 = set(n1)
    set2 = set(n2)
    intersection = set1 & set2
    union = set1 | set2
    return len(intersection) / len(union) if union else 0.0


def deduplicate_posts(posts: list[dict], similarity_threshold: float = 0.8) -> list[dict]:
    """
    对帖子列表去重

    Args:
        posts: 帖子列表
        similarity_threshold: 标题相似度阈值，超过则视为重复

    Returns:
        去重后的帖子列表
    """
    if not posts:
        return []

    seen_hashes = set()
    result = []

    for post in posts:
        title = post.get("title", "")
        if not title:
            continue

        h = _title_hash(title)

        # 完全匹配去重
        if h in seen_hashes:
            continue

        # 相似度去重
        is_duplicate = False
        for existing in result:
            existing_title = existing.get("title", "")
            if _title_similarity(title, existing_title) >= similarity_threshold:
                is_duplicate = True
                break

        if not is_duplicate:
            seen_hashes.add(h)
            result.append(post)

    return result


# ============================================================
# 相关性过滤
# ============================================================

def is_relevant_post(post: dict) -> bool:
    """
    判断搜索结果是否与学生党投资相关

    过滤规则：
    - 标题或内容中必须包含至少1个学生身份关键词
    - 且必须包含至少1个投资/交易关键词
    - 纯广告/导航/无关结果会被过滤

    Returns:
        True 如果相关
    """
    text = (post.get("title", "") + " " + post.get("content", "")).lower()

    # 检查是否包含学生身份关键词
    has_student_kw = any(kw.lower() in text for kw in STUDENT_IDENTITY_KEYWORDS)

    # 检查是否包含投资关键词
    has_invest_kw = any(kw.lower() in text for kw in INVESTMENT_KEYWORDS)

    # 两个条件都满足才保留
    return has_student_kw and has_invest_kw


def filter_relevant_posts(posts: list[dict], strict: bool = True) -> list[dict]:
    """
    过滤出与学生党投资相关的帖子

    Args:
        posts: 帖子列表
        strict: True=严格过滤（必须同时含学生关键词和投资关键词）
                False=宽松过滤（只需含学生关键词）

    Returns:
        过滤后的帖子列表
    """
    if not strict:
        # 宽松模式：只要含学生关键词就保留
        return [
            p for p in posts
            if any(kw.lower() in (p.get("title", "") + p.get("content", "")).lower()
                   for kw in STUDENT_IDENTITY_KEYWORDS)
        ]

    return [p for p in posts if is_relevant_post(p)]


# ============================================================
# 核心搜索函数
# ============================================================

def search_plate_posts(
    search_func: Callable[[str], list[dict]],
    plate_name: str,
    etf_code: str,
    max_results: int = 15,
    deduplicate: bool = True,
    filter_relevant: bool = True,
) -> list[dict]:
    """
    对指定板块执行多组搜索，归一化、去重、过滤后返回帖子列表

    Args:
        search_func: 搜索函数，签名 search_func(query: str) -> list[dict]
        plate_name: 板块名称
        etf_code: ETF代码
        max_results: 最终返回的最大帖子数
        deduplicate: 是否去重
        filter_relevant: 是否过滤无关结果

    Returns:
        list[dict]: 帖子列表
    """
    queries = build_search_queries(plate_name, etf_code)
    all_posts = []
    search_errors = []

    for q_info in queries:
        query = q_info["query"]
        purpose = q_info.get("purpose", "")
        platform = q_info.get("platform", "")

        try:
            results = search_func(query)
            if results is None:
                results = []
            if not isinstance(results, list):
                results = [results] if results else []

            source_tag = f"联网搜索-{platform}" if platform else "联网搜索"
            for item in results:
                post = normalize_search_result(item, plate_name, source_tag)
                if post["title"]:  # 标题不能为空
                    all_posts.append(post)

        except Exception as e:
            search_errors.append({"query": query, "error": str(e)})
            print(f"[web_searcher] 搜索失败 [{purpose}] '{query[:30]}...': {e}")

    print(f"[web_searcher] {plate_name}: 原始搜索结果 {len(all_posts)} 条"
          f"（{len(queries)} 组查询，{len(search_errors)} 组失败）")

    # 去重
    if deduplicate:
        before = len(all_posts)
        all_posts = deduplicate_posts(all_posts)
        if before != len(all_posts):
            print(f"[web_searcher] {plate_name}: 去重 {before} → {len(all_posts)} 条")

    # 过滤
    if filter_relevant:
        before = len(all_posts)
        strict_results = filter_relevant_posts(all_posts, strict=True)
        if len(strict_results) >= 5:
            all_posts = strict_results
            print(f"[web_searcher] {plate_name}: 严格过滤 {before} → {len(all_posts)} 条")
        else:
            all_posts = filter_relevant_posts(all_posts, strict=False)
            print(
                f"[web_searcher] {plate_name}: 严格过滤仅剩 {len(strict_results)} 条，"
                f"改用宽松过滤 {before} → {len(all_posts)} 条"
            )

    # 截断
    all_posts = all_posts[:max_results]

    print(f"[web_searcher] {plate_name}: 最终返回 {len(all_posts)} 条")
    return all_posts


def search_all_plates(
    search_func: Callable[[str], list[dict]],
    plates: Optional[list[str]] = None,
    max_per_plate: int = 15,
) -> dict[str, list[dict]]:
    """
    对所有（或指定）板块执行联网搜索

    Args:
        search_func: 搜索函数
        plates: 指定板块列表，None=全部
        max_per_plate: 每板块最大帖子数

    Returns:
        dict[str, list[dict]]: {板块名: 帖子列表}
    """
    result = {}
    for plate_name, etf_code in PLATE_ETF_CODES.items():
        if plates and plate_name not in plates:
            continue
        posts = search_plate_posts(search_func, plate_name, etf_code, max_per_plate)
        result[plate_name] = posts
    return result


# ============================================================
# 预收集结果适配器
# ============================================================

def ingest_precollected_posts(
    raw_results: list[dict],
    plate_name: str,
    deduplicate: bool = True,
    filter_relevant: bool = True,
) -> list[dict]:
    """
    将 Agent 预先通过 WebSearch 工具搜索的结果列表导入为标准帖子格式

    适用于 Agent 先自行调用搜索工具，再将结果批量传入的场景。
    raw_results 中的每个 dict 至少应包含 title 或 snippet 字段。

    Args:
        raw_results: Agent 预收集的搜索结果列表
        plate_name: 目标板块
        deduplicate: 是否去重
        filter_relevant: 是否过滤无关结果

    Returns:
        归一化、去重、过滤后的帖子列表
    """
    posts = []
    for item in raw_results:
        post = normalize_search_result(item, plate_name, "联网搜索(预收集)")
        if post["title"]:
            posts.append(post)

    if deduplicate:
        posts = deduplicate_posts(posts)

    if filter_relevant:
        posts = filter_relevant_posts(posts, strict=False)

    return posts


def ingest_precollected_by_plate(
    raw_by_plate: dict[str, list[dict]],
    deduplicate: bool = True,
    filter_relevant: bool = True,
) -> dict[str, list[dict]]:
    """
    批量导入 Agent 预收集的搜索结果（按板块分组）

    Args:
        raw_by_plate: {板块名: [搜索结果dict, ...]}
        deduplicate: 是否去重
        filter_relevant: 是否过滤

    Returns:
        {板块名: [帖子dict, ...]}
    """
    result = {}
    for plate_name, raw_list in raw_by_plate.items():
        result[plate_name] = ingest_precollected_posts(
            raw_list, plate_name, deduplicate, filter_relevant
        )
    return result


# ============================================================
# 真实联网搜索适配器（无需 API Key）
# ============================================================

_SEARCH_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
]

_last_search_request = 0.0


def _fetch_search_html(url: str, timeout: int = 12) -> str:
    """请求搜索页面并返回解码后的 HTML，带限速和简单重试。"""
    global _last_search_request

    min_interval = 0.8
    elapsed = time.monotonic() - _last_search_request
    if elapsed < min_interval:
        time.sleep(min_interval - elapsed)

    headers = {
        "User-Agent": random.choice(_SEARCH_USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    for attempt in range(3):
        _last_search_request = time.monotonic()
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
            for enc in ("utf-8", "gb18030", "gbk"):
                try:
                    return raw.decode(enc)
                except UnicodeDecodeError:
                    continue
            return raw.decode("utf-8", errors="ignore")
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503) and attempt < 2:
                time.sleep(2 ** attempt * 1.5)
                continue
            print(f"[web_searcher] 搜索页 HTTP {e.code}: {url[:80]}")
            return ""
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            if attempt < 2:
                time.sleep(2 ** attempt * 1.0)
                continue
            print(f"[web_searcher] 请求搜索页失败 {url[:80]}: {e}")
            return ""

    return ""


def _clean_html_text(value: str) -> str:
    """去除 HTML 标签并反转义，返回可读文本。"""
    return html.unescape(re.sub(r"<[^>]+>", "", value)).strip()


def _parse_duckduckgo_results(html_text: str) -> list[dict]:
    """解析 DuckDuckGo HTML 搜索结果。"""
    results = []
    pattern = r'<a[^>]*class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>'
    for m in re.finditer(pattern, html_text, re.DOTALL):
        href = m.group(1)
        title = _clean_html_text(m.group(2))
        if not title:
            continue

        real_url = href
        uddg_match = re.search(r'[?&]uddg=([^&"]+)', href)
        if uddg_match:
            real_url = urllib.parse.unquote(uddg_match.group(1))
        if real_url.startswith("//"):
            real_url = "https:" + real_url

        snippet = ""
        tail = html_text[m.end():m.end() + 2500]
        snippet_match = re.search(r'<a[^>]*class="result__snippet"[^>]*>(.*?)</a>', tail, re.DOTALL)
        if snippet_match:
            snippet = _clean_html_text(snippet_match.group(1))

        source = urllib.parse.urlsplit(real_url).netloc or "全网搜索"
        results.append({
            "title": title,
            "snippet": snippet,
            "url": real_url,
            "source": source,
        })

    return results


def _parse_so360_results(html_text: str) -> list[dict]:
    """解析 360 搜索结果。"""
    results = []
    for block in re.findall(r'<li class="res-list".*?</li>', html_text, re.DOTALL):
        title_match = re.search(r'<h3[^>]*class="res-title"[^>]*>.*?<a[^>]*>(.*?)</a>', block, re.DOTALL)
        if not title_match:
            continue

        title = _clean_html_text(title_match.group(1))
        if not title:
            continue

        url_match = re.search(r'data-mdurl="([^"]+)"', block) or re.search(
            r'<a[^>]*href="([^"]+)"', block
        )
        url = url_match.group(1) if url_match else ""

        snippet = ""
        snippet_match = re.search(r'<p[^>]*class="res-desc"[^>]*>(.*?)</p>', block, re.DOTALL)
        if snippet_match:
            snippet = _clean_html_text(snippet_match.group(1))

        source = urllib.parse.urlsplit(url).netloc or "全网搜索"
        results.append({
            "title": title,
            "snippet": snippet,
            "url": url,
            "source": source,
        })

    return results


def _parse_bing_results(html_text: str) -> list[dict]:
    """解析 Bing HTML 搜索结果。"""
    results = []
    for block in re.findall(r'<li class="b_algo".*?</li>', html_text, re.DOTALL):
        title_match = re.search(
            r'<h2[^>]*>.*?<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', block, re.DOTALL
        )
        if not title_match:
            continue

        url = title_match.group(1)
        title = _clean_html_text(title_match.group(2))
        if not title:
            continue

        snippet_match = (
            re.search(r'<p class="b_lineclamp[^"]*"[^>]*>(.*?)</p>', block, re.DOTALL)
            or re.search(r'<div class="b_caption">.*?<p[^>]*>(.*?)</p>', block, re.DOTALL)
        )
        snippet = _clean_html_text(snippet_match.group(1)) if snippet_match else ""

        source = urllib.parse.urlsplit(url).netloc or "全网搜索"
        results.append({
            "title": title,
            "snippet": snippet,
            "url": url,
            "source": source,
        })

    return results


def create_web_search_func(timeout: int = 12, bing_fallback: bool = False) -> Callable[[str], list[dict]]:
    """
    创建真实联网搜索函数：360 优先，DuckDuckGo 次之，Bing 可选兜底。

    返回的函数签名与 search_func(query: str) -> list[dict] 一致，
    可直接作为 run_student_index(search_web_func=...) 的参数。
    """
    def search_web(query: str) -> list[dict]:
        results = _parse_so360_results(
            _fetch_search_html(
                "https://www.so.com/s?q=" + urllib.parse.quote(query),
                timeout=timeout,
            )
        )
        if not results:
            results = _parse_duckduckgo_results(
                _fetch_search_html(
                    "https://html.duckduckgo.com/html/?q=" + urllib.parse.quote(query),
                    timeout=timeout,
                )
            )
        if not results and bing_fallback:
            results = _parse_bing_results(
                _fetch_search_html(
                    "https://www.bing.com/search?q=" + urllib.parse.quote(query) + "&mkt=zh-CN",
                    timeout=timeout,
                )
            )
        return results

    return search_web


def create_web_search_func_bing_fallback(timeout: int = 12) -> Callable[[str], list[dict]]:
    """带 Bing 兜底的搜索函数，作为 create_web_search_func 的兼容别名。"""
    return create_web_search_func(timeout=timeout, bing_fallback=True)


# ============================================================
# Mock 搜索函数（用于无网络环境测试）
# ============================================================

def create_mock_search_func() -> Callable[[str], list[dict]]:
    """
    创建一个 mock 搜索函数，返回模拟搜索结果
    用于无网络环境下的测试，保证流程可跑通

    Returns:
        可作为 search_func 传入的函数
    """

    # 模拟搜索结果池（根据查询关键词返回不同结果）
    mock_data = [
        # 纳斯达克ETF
        {"title": "大学生第一次买纳斯达克ETF，生活费梭哈了", "snippet": "我是大三学生，看室友都赚钱了，513100涨疯了赶紧上车，all in生活费闭眼冲", "url": "https://xiaohongshu.com/post/1", "source": "小红书", "publish_time": "2026-08-20"},
        {"title": "学生党求问纳斯达克ETF现在能买吗", "snippet": "刚接触基金，学长说纳指ETF稳赚，能上车吗？怎么开户？完全不懂求教", "url": "https://xueqiu.com/post/1", "source": "雪球", "publish_time": "2026-08-19"},
        {"title": "纳斯达克ETF跌惨了，生活费亏没了", "snippet": "亏麻了套牢了，要不要割肉吃土，跌得睡不着觉", "url": "https://weibo.com/post/1", "source": "微博", "publish_time": "2026-08-18"},
        {"title": "宿舍都在聊纳斯达克ETF，跟风买了点", "snippet": "同学都买513100，都说不错，我也跟着买了一点，博主推荐闭眼入", "url": "https://tieba.baidu.com/post/1", "source": "贴吧", "publish_time": "2026-08-21"},
        {"title": "大学生纳斯达克ETF做T短线操作", "snippet": "今天买明天卖，天天盯盘频繁操作，超短线做差价", "url": "https://xueqiu.com/post/2", "source": "雪球", "publish_time": "2026-08-22"},

        # 黄金ETF
        {"title": "学生党黄金ETF买了点，求带", "snippet": "刚入学，学长说避险可以买黄金ETF，生活费买了点，求教怎么操作", "url": "https://xiaohongshu.com/post/2", "source": "小红书", "publish_time": "2026-08-19"},
        {"title": "黄金ETF跌了套牢了怎么办，要不要吃土", "snippet": "生活费亏没了，亏得饭都吃不起了，快跑还是等回本", "url": "https://weibo.com/post/2", "source": "微博", "publish_time": "2026-08-18"},
        {"title": "大学生黄金ETF梭哈了，肯定涨", "snippet": "金价暴涨起飞了，稳赚不赔闭眼买，再不买来不及了", "url": "https://tieba.baidu.com/post/2", "source": "贴吧", "publish_time": "2026-08-21"},
        {"title": "朋友圈都在晒黄金ETF收益，我也买了", "snippet": "大家都在买黄金，热度很高，跟风买了点518880", "url": "https://xiaohongshu.com/post/3", "source": "小红书", "publish_time": "2026-08-20"},

        # CPO通信ETF
        {"title": "大学生CPO通信ETF上车了，博主说必涨", "snippet": "AI算力暴涨，博主推荐515880闭眼冲，起飞了赶紧追", "url": "https://xueqiu.com/post/3", "source": "雪球", "publish_time": "2026-08-21"},
        {"title": "学生党CPO光模块ETF亏麻了", "snippet": "追高被套，跌得受不了，割肉还是等涨，研究生生活费没了", "url": "https://weibo.com/post/3", "source": "微博", "publish_time": "2026-08-19"},
        {"title": "室友推荐CPO通信ETF，能买吗", "snippet": "同学说光通信板块要涨，新手能上车不，学长带带", "url": "https://tieba.baidu.com/post/3", "source": "贴吧", "publish_time": "2026-08-20"},

        # 半导体ETF
        {"title": "大学生半导体ETF今天买明天卖做T", "snippet": "短线操作天天盯盘，超短线做差价，频繁操作高抛低吸", "url": "https://xueqiu.com/post/4", "source": "雪球", "publish_time": "2026-08-22"},
        {"title": "半导体ETF涨疯了，学生党梭哈生活费", "snippet": "芯片暴涨涨停，all in满仓干，肯定涨不可能跌", "url": "https://xiaohongshu.com/post/4", "source": "小红书", "publish_time": "2026-08-21"},
        {"title": "大学生半导体ETF套牢了，要不要割肉", "snippet": "512480跌惨了血亏，生活费亏没了，完了完了回不了本", "url": "https://weibo.com/post/4", "source": "微博", "publish_time": "2026-08-18"},
        {"title": "同学都买半导体ETF，我也跟风入了", "snippet": "群里说国产替代必涨，大家都买我也买了点", "url": "https://tieba.baidu.com/post/4", "source": "贴吧", "publish_time": "2026-08-20"},
    ]

    def mock_search(query: str) -> list[dict]:
        """根据查询关键词匹配模拟数据"""
        query_lower = query.lower()
        results = []

        # 提取查询中的板块关键词
        plate_matched = None
        for plate, kws in PLATE_KEYWORDS.items():
            for kw in kws:
                if kw.lower() in query_lower:
                    plate_matched = plate
                    break
            if plate_matched:
                break

        # 如果匹配到板块，返回该板块的模拟数据
        if plate_matched:
            plate_kws = PLATE_KEYWORDS[plate_matched]
            for item in mock_data:
                # 检查模拟数据是否属于该板块
                item_text = (item["title"] + " " + item["snippet"]).lower()
                if any(kw.lower() in item_text for kw in plate_kws):
                    results.append(item.copy())

        # 如果没有匹配到板块或结果为空，返回全部数据（截断）
        if not results:
            results = [item.copy() for item in mock_data[:5]]

        # 模拟搜索引擎的行为：根据查询中的情绪词排序
        if "亏" in query or "套牢" in query or "割肉" in query:
            results.sort(key=lambda x: ("亏" not in x["title"] and "套" not in x["title"]))
        elif "涨" in query or "梭哈" in query or "上车" in query:
            results.sort(key=lambda x: ("涨" not in x["title"] and "梭哈" not in x["title"] and "上车" not in x["title"]))

        return results[:8]  # 每次搜索最多返回8条

    return mock_search


# ============================================================
# 自测
# ============================================================

if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    print("=" * 60)
    print("web_searcher 模块自测")
    print("=" * 60)

    # 1. 测试搜索关键词生成
    print("\n--- 搜索关键词生成 ---")
    queries = build_search_queries("纳斯达克ETF", "513100")
    for q in queries:
        platform = q.get("platform") or "全网"
        print(f"  [{q['purpose']}] ({platform}) {q['query']}")
    print(f"  共 {len(queries)} 组查询")

    # 2. 测试 mock 搜索
    print("\n--- Mock 搜索测试 ---")
    mock_func = create_mock_search_func()
    for plate in ["纳斯达克ETF", "黄金ETF", "CPO通信ETF", "半导体ETF"]:
        etf_code = PLATE_ETF_CODES[plate]
        posts = search_plate_posts(mock_func, plate, etf_code, max_results=10)
        print(f"\n  {plate}: {len(posts)} 条帖子")
        for p in posts[:3]:
            print(f"    [{p['source']}] {p['title'][:40]}")

    # 3. 测试归一化
    print("\n--- 归一化测试 ---")
    raw = {"title_text": "测试标题", "abstract": "测试内容", "link": "http://test.com", "date": "2026-08-20"}
    normalized = normalize_search_result(raw, "测试板块")
    print(f"  归一化前: {raw}")
    print(f"  归一化后: {normalized}")

    # 4. 测试去重
    print("\n--- 去重测试 ---")
    dup_posts = [
        {"title": "大学生纳斯达克ETF买了", "content": "test"},
        {"title": "大学生 纳斯达克ETF 买了", "content": "test2"},  # 标点差异 → 重复
        {"title": "大学生纳斯达克ETF梭哈了", "content": "test3"},  # 不同
        {"title": "大学生纳斯达克ETF买了", "content": "test4"},  # 完全重复
    ]
    deduped = deduplicate_posts(dup_posts)
    print(f"  去重前: {len(dup_posts)} 条, 去重后: {len(deduped)} 条")

    # 5. 测试过滤
    print("\n--- 相关性过滤测试 ---")
    test_posts = [
        {"title": "大学生纳斯达克ETF买了生活费梭哈", "content": "投资讨论"},  # 相关
        {"title": "大学生期末考试安排通知", "content": "教务处通知"},  # 无关（无投资词）
        {"title": "纳斯达克ETF行情分析", "content": "专业分析"},  # 无关（无学生词）
    ]
    filtered = filter_relevant_posts(test_posts, strict=True)
    print(f"  严格过滤: {len(test_posts)} → {len(filtered)} 条")
    filtered_loose = filter_relevant_posts(test_posts, strict=False)
    print(f"  宽松过滤: {len(test_posts)} → {len(filtered_loose)} 条")

    print("\n" + "=" * 60)
    print("自测完成")
    print("=" * 60)
