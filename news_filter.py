"""News relevance filter — keyword-based scoring to reduce noise before LLM consumption.

Three-tier keyword system (no ML, no external imports):
- Strong keywords (+30 pts): high-impact events that almost always move prices
- Include keywords (+15 pts): moderately relevant market signals
- Exclude keywords (-20 pts): noise (ads, recruitment, charity, sports)

Articles scoring >= threshold (default 15) pass through; rest are dropped.

Usage:
    from subagent_pipeline.news_filter import filter_news, score_article

    # Filter a list of article dicts
    filtered = filter_news(articles, threshold=15)

    # Score a single article
    pts = score_article({"title": "华大智造获重大合同", "content": "..."})
"""

import logging
from typing import Dict, List

logger = logging.getLogger(__name__)

# ── Keyword Tiers ────────────────────────────────────────────────────────

# Strong (+30): events that almost always trigger price movement
STRONG_KEYWORDS = [
    # Earnings & guidance
    "业绩预告", "业绩快报", "业绩预增", "业绩预减", "业绩预亏", "扭亏",
    "盈利预测", "超预期", "不及预期", "下修", "上修",
    # Major corporate events
    "重大合同", "中标", "定增", "增发", "配股", "回购", "分红",
    "减持", "增持", "解禁", "质押", "强制平仓", "爆仓",
    "停牌", "复牌", "退市风险", "退市", "摘帽", "撤销风险警示",
    "收购", "并购", "重组", "借壳", "资产注入", "剥离",
    # Regulatory & compliance
    "立案调查", "行政处罚", "监管函", "问询函", "关注函",
    "财务造假", "内幕交易", "操纵市场",
    # Industry-level shocks
    "禁令", "制裁", "反倾销", "关税", "政策利好", "政策利空",
]

# Include (+15): moderately relevant signals
INCLUDE_KEYWORDS = [
    # Market signals
    "涨停", "跌停", "封板", "炸板", "连板", "龙虎榜",
    "机构调研", "机构买入", "机构卖出", "北向资金", "外资",
    "大宗交易", "融资融券", "融资买入", "融券卖出",
    # Fundamentals
    "营收", "净利润", "毛利率", "ROE", "现金流", "负债率",
    "订单", "签约", "产能", "投产", "达产", "扩产",
    # Sector rotation
    "板块异动", "概念股", "题材", "轮动", "主线",
    # Analyst activity
    "研报", "评级", "目标价", "首次覆盖", "调高", "调低",
]

# Exclude (-20): noise that wastes tokens
EXCLUDE_KEYWORDS = [
    # Ads & spam
    "广告", "推广", "赞助", "冠名",
    # Non-financial
    "招聘", "校招", "社招", "公益", "捐赠", "慈善",
    "体育", "足球", "篮球", "马拉松",
    # Boilerplate
    "投资者关系", "互动平台回复", "股吧", "吧友",
    "免责声明", "风险提示：以上内容",
]

# ── Scoring ──────────────────────────────────────────────────────────────

_STRONG_PTS = 30
_INCLUDE_PTS = 15
_EXCLUDE_PTS = -20


def score_article(article: Dict) -> int:
    """Score a single news article dict by keyword matching.

    Checks both 'title' and 'content' fields.
    Returns integer score (can be negative).
    """
    text = (article.get("title", "") + " " + article.get("content", "")).strip()
    if not text:
        return 0

    score = 0
    # Strong keywords (check first — a single strong match is sufficient)
    for kw in STRONG_KEYWORDS:
        if kw in text:
            score += _STRONG_PTS
            break  # one strong match is enough, avoid double-counting

    # Include keywords (additive, up to 2 matches)
    include_hits = 0
    for kw in INCLUDE_KEYWORDS:
        if kw in text:
            score += _INCLUDE_PTS
            include_hits += 1
            if include_hits >= 2:
                break

    # Exclude keywords (subtractive)
    for kw in EXCLUDE_KEYWORDS:
        if kw in text:
            score += _EXCLUDE_PTS
            break  # one exclude match is enough

    return score


# ── Filter ───────────────────────────────────────────────────────────────


def filter_news(
    articles: List[Dict],
    threshold: int = 15,
    max_articles: int = 10,
) -> List[Dict]:
    """Filter and rank news articles by relevance score.

    Args:
        articles: List of article dicts with 'title' and optional 'content'.
        threshold: Minimum score to pass (default 15 = at least one Include match).
        max_articles: Maximum articles to return after filtering.

    Returns:
        Filtered list sorted by score descending, capped at max_articles.
        Each dict gets a '_relevance_score' field added.
    """
    if not articles:
        return []

    scored = []
    for art in articles:
        pts = score_article(art)
        art_copy = dict(art)
        art_copy["_relevance_score"] = pts
        scored.append((pts, art_copy))

    # Filter by threshold
    passed = [(pts, art) for pts, art in scored if pts >= threshold]

    # Sort by score descending
    passed.sort(key=lambda x: -x[0])

    result = [art for _, art in passed[:max_articles]]

    dropped = len(articles) - len(result)
    if dropped > 0:
        logger.debug("News filter: %d/%d passed (threshold=%d, dropped %d)",
                      len(result), len(articles), threshold, dropped)

    return result
