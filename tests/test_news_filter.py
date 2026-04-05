"""Tests for news_filter.py — keyword-based relevance scoring."""

import sys
import pytest
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from subagent_pipeline.news_filter import score_article, filter_news


class TestScoreArticle:

    def test_strong_keyword_high_score(self):
        art = {"title": "华大智造获重大合同10亿元", "content": ""}
        assert score_article(art) >= 30

    def test_include_keyword_moderate_score(self):
        art = {"title": "北向资金今日净流入50亿", "content": ""}
        assert 15 <= score_article(art) < 30

    def test_exclude_keyword_negative(self):
        art = {"title": "某公司赞助足球赛事", "content": "体育赞助公益活动"}
        assert score_article(art) < 0

    def test_strong_plus_include(self):
        art = {"title": "业绩预告：涨停", "content": ""}
        assert score_article(art) >= 45  # 30 + 15

    def test_strong_minus_exclude(self):
        art = {"title": "重大合同 免责声明", "content": ""}
        assert score_article(art) == 10  # 30 - 20

    def test_empty_article(self):
        assert score_article({"title": "", "content": ""}) == 0
        assert score_article({}) == 0

    def test_content_field_checked(self):
        art = {"title": "普通标题", "content": "公司获得减持公告"}
        assert score_article(art) >= 30

    def test_no_keyword_zero(self):
        art = {"title": "今天天气不错", "content": "阳光明媚"}
        assert score_article(art) == 0

    def test_multiple_include_capped_at_2(self):
        art = {"title": "涨停 龙虎榜 机构调研 北向资金", "content": ""}
        score = score_article(art)
        # max 2 include hits = 30, not 60
        assert score == 30


class TestFilterNews:

    def _make_articles(self):
        return [
            {"title": "华大智造获重大合同", "content": ""},          # strong +30
            {"title": "北向资金净流入", "content": ""},              # include +15
            {"title": "今天天气不错", "content": ""},               # 0 → dropped
            {"title": "公司赞助马拉松", "content": "体育公益"},     # -20 → dropped
            {"title": "业绩预告超预期", "content": "涨停"},          # strong+include +45
            {"title": "普通公司动态", "content": ""},               # 0 → dropped
        ]

    def test_filters_low_score(self):
        articles = self._make_articles()
        result = filter_news(articles, threshold=15)
        # Only 3 articles should pass: 重大合同(30), 北向资金(15), 业绩预告(45)
        assert len(result) == 3

    def test_sorted_by_score_descending(self):
        articles = self._make_articles()
        result = filter_news(articles, threshold=15)
        assert result[0]["title"] == "业绩预告超预期"  # highest score
        assert result[1]["title"] == "华大智造获重大合同"

    def test_max_articles_cap(self):
        articles = self._make_articles()
        result = filter_news(articles, threshold=0, max_articles=2)
        assert len(result) == 2

    def test_empty_input(self):
        assert filter_news([]) == []

    def test_score_field_added(self):
        articles = [{"title": "重大合同", "content": ""}]
        result = filter_news(articles, threshold=0)
        assert "_relevance_score" in result[0]
        assert result[0]["_relevance_score"] >= 30

    def test_threshold_zero_passes_all_non_negative(self):
        articles = [
            {"title": "普通新闻", "content": ""},         # 0
            {"title": "赞助公益活动", "content": ""},     # -20
        ]
        result = filter_news(articles, threshold=0)
        assert len(result) == 1  # only score=0 passes, -20 dropped
