# -*- coding: utf-8 -*-
"""
tests/test_eval_metrics.py —— 评测指标与判定逻辑的回归测试

指标算错比没有指标更危险（会得出"改了之后变好了"的错误结论），所以这里把
scripts/eval_rag.py 里的纯函数全部钉住：
    - chunk_matches：编号命中 / 行号区间重叠 两种判定
    - first_hit_rank：首个命中的名次
    - summarize：hit@1 / hit@k / MRR 的计算
    - load_qa：评测集本身格式合法（40 题、id 唯一、行号落在知识库范围内）

    python -m unittest discover -s tests -v
    python tests/run_all.py
"""
from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = TESTS_DIR.parent
for _path in (str(PROJECT_ROOT), str(PROJECT_ROOT / "src"), str(PROJECT_ROOT / "scripts")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import eval_rag  # noqa: E402


def make_hit(content: str, line_start: int, line_end: int):
    """构造一个只带判定所需字段的假 Hit。"""
    return types.SimpleNamespace(
        doc=types.SimpleNamespace(page_content=content),
        line_start=line_start,
        line_end=line_end,
    )


class TestChunkMatches(unittest.TestCase):
    def test_matches_by_entry_id(self):
        hit = make_hit("……【Q4-08】打印机卡纸和面板报错代码如何处理？……", 1377, 1400)
        self.assertTrue(eval_rag.chunk_matches(hit, ["Q4-08"], [[1377, 1407]]))

    def test_matches_by_line_overlap_when_id_absent(self):
        # 片段从条目中间开始，正文里没有编号 —— 只能靠行号区间判定
        hit = make_hit("步骤 7：常见错误代码参考 ……", 1393, 1405)
        self.assertTrue(eval_rag.chunk_matches(hit, ["Q4-08"], [[1377, 1407]]))

    def test_no_match_when_id_and_range_both_miss(self):
        hit = make_hit("完全无关的内容 vpn 连接", 409, 430)
        self.assertFalse(eval_rag.chunk_matches(hit, ["Q4-08"], [[1377, 1407]]))

    def test_touching_range_counts_as_overlap(self):
        hit = make_hit("边界片段", 1407, 1420)
        self.assertTrue(eval_rag.chunk_matches(hit, ["Q4-08"], [[1377, 1407]]))

    def test_missing_line_info_does_not_crash(self):
        hit = make_hit("没有行号", -1, -1)
        # 行号缺失时不能靠区间判定，但也不能抛异常
        self.assertFalse(eval_rag.chunk_matches(hit, ["Q4-08"], [[1377, 1407]]))
        self.assertFalse(eval_rag.chunk_matches(hit, ["Q4-08"], []))
        # 编号仍然能独立命中
        hit2 = make_hit("……【Q4-08】打印机卡纸……", -1, -1)
        self.assertTrue(eval_rag.chunk_matches(hit2, ["Q4-08"], []))


class TestFirstHitRank(unittest.TestCase):
    def setUp(self):
        self.hits = [
            make_hit("无关 A", 1, 10),
            make_hit("无关 B", 20, 30),
            make_hit("【Q2-05】VPN 错误 691", 465, 493),
            make_hit("无关 C", 500, 510),
        ]

    def test_returns_first_matching_rank(self):
        self.assertEqual(eval_rag.first_hit_rank(self.hits, ["Q2-05"], [[465, 493]]), 3)

    def test_returns_one_when_top_hit_is_correct(self):
        self.assertEqual(eval_rag.first_hit_rank(self.hits[:1], [], [[1, 10]]), 1)

    def test_returns_none_when_nothing_matches(self):
        self.assertIsNone(eval_rag.first_hit_rank(self.hits, ["Q9-99"], [[9999, 10000]]))

    def test_empty_hits(self):
        self.assertIsNone(eval_rag.first_hit_rank([], ["Q2-05"], [[465, 493]]))


class TestSummarize(unittest.TestCase):
    def test_metrics_math(self):
        # 名次：1、2、None、4（共 4 题）
        ranks = [1, 2, None, 4]
        latencies = [100.0, 200.0, 300.0, 400.0]
        m = eval_rag.summarize(ranks, latencies)
        self.assertEqual(m["total"], 4)
        self.assertAlmostEqual(m["hit@1"], 0.25)          # 只有 1 题是第一名
        self.assertAlmostEqual(m["hit@k"], 0.75)          # 3/4 命中
        self.assertAlmostEqual(m["mrr"], (1 + 1 / 2 + 1 / 4) / 4)
        self.assertAlmostEqual(m["avg_ms"], 250.0)

    def test_all_miss(self):
        m = eval_rag.summarize([None, None], [50.0, 50.0])
        self.assertEqual(m["hit@1"], 0.0)
        self.assertEqual(m["hit@k"], 0.0)
        self.assertEqual(m["mrr"], 0.0)

    def test_empty(self):
        m = eval_rag.summarize([], [])
        self.assertEqual(m["total"], 0)


class TestRefusalDetection(unittest.TestCase):
    """回归保护：判定器曾把「有步骤、末尾附免责」的正常回答误判成拒答。

    真实事故：旧判定是 `any(marker in answer)`，于是
    「……处理步骤如下：1. …… 2. ……」这种**已经有实质答案**的回复也被算成拒答，
    误拒答率虚高到 32%，差点据此得出"模型爱拒答"的错误结论。
    """

    def test_pure_refusal_is_detected(self):
        self.assertTrue(eval_rag.looks_like_refusal(
            "知识库中未收录该信息，建议联系 IT 服务台（内线 8800）。"))

    def test_substantive_answer_with_trailing_disclaimer_is_not_refusal(self):
        answer = ("可以按以下步骤排查：\n1. 先确认目标地址属于内网；\n2. 再检查 DNS 解析。\n"
                  "片段未收录的部分请提交工单给服务台。")
        self.assertFalse(eval_rag.looks_like_refusal(answer))

    def test_answer_citing_entry_is_not_refusal(self):
        answer = "参考【Q4-08】：卡纸时先断电再取纸。其余细节知识库中未收录。"
        self.assertFalse(eval_rag.looks_like_refusal(answer))

    def test_plain_answer_is_not_refusal(self):
        self.assertFalse(eval_rag.looks_like_refusal("1. 第一步\n2. 第二步"))


class TestQaDataset(unittest.TestCase):
    """评测集本身的质量检查：格式、唯一性、行号必须落在知识库范围内。"""

    @classmethod
    def setUpClass(cls):
        cls.items = eval_rag.load_qa()

    def test_has_expected_size_and_id_uniqueness(self):
        self.assertGreaterEqual(len(self.items), 40)
        ids = [item["id"] for item in self.items]
        self.assertEqual(len(ids), len(set(ids)), "评测集 id 不能重复")

    def test_every_item_has_required_fields(self):
        for item in self.items:
            self.assertTrue(item.get("question"), item)
            self.assertTrue(item.get("expect_ids"), item)
            self.assertTrue(item.get("expect_lines"), item)
            self.assertIsInstance(item["expect_lines"][0], list)

    def test_expectations_point_into_the_knowledge_base(self):
        kb = (PROJECT_ROOT / "data" / "knowledge_base.txt").read_text(encoding="utf-8")
        total_lines = len(kb.splitlines())
        for item in self.items:
            for lo, hi in item["expect_lines"]:
                self.assertGreaterEqual(lo, 1, item["id"])
                self.assertLessEqual(hi, total_lines, f"{item['id']} 行号超出知识库范围")

    def test_entry_ids_exist_in_knowledge_base(self):
        kb = (PROJECT_ROOT / "data" / "knowledge_base.txt").read_text(encoding="utf-8")
        for item in self.items:
            for eid in item["expect_ids"]:
                self.assertIn(f"【{eid}】", kb, f"{item['id']} 期望的条目 {eid} 不在知识库里")

    def test_questions_are_colloquial_not_titles(self):
        """防止有人图省事把条目标题直接抄进评测题（那样关键词检索会"抄答案"）。

        规则：问题里不得出现「」/【】这类标题标记，也不得与知识库里的标题整句相同。
        """
        kb = (PROJECT_ROOT / "data" / "knowledge_base.txt").read_text(encoding="utf-8")
        titles = [
            line.strip() for line in kb.splitlines()
            if line.strip().startswith("【Q") and "】" in line
        ]
        for item in self.items:
            self.assertNotIn("【", item["question"], item["id"])
            for title in titles:
                self.assertNotIn(title, item["question"], f"{item['id']} 疑似直接抄了标题")


if __name__ == "__main__":
    unittest.main()
