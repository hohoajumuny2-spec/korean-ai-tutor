"""학생별 약점 분석(weakness.py)."""
import os
import sys
import unittest
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import weakness as wk  # noqa: E402

TODAY = date(2026, 11, 26)
META = {
    ("과제 제출", "독서 1"): {"1": {"tag": "추론"}, "2": {"tag": "추론"}, "3": {"tag": "어휘"}, "4": {"tag": "사실적 이해"}},
    ("타임어택 퀴즈", "문법 퀴즈"): {"1": {"tag": "품사"}, "2": {"tag": "품사"}, "3": {"tag": "추론"}},
    ("과제 제출", "옛날 과제"): {"1": {"tag": "추론"}, "2": {"tag": "추론"}, "3": {"tag": "어휘"}},
    ("모의고사", "유형없는 시험"): {},
}


def meta_for(kind, title):
    return META.get((kind, title), {})


ROWS = [
    {"type": "과제 제출", "task_name": "독서 1", "submitted_at": "2026-11-24 20:00", "wrongs": [1, 2, 3],
     "reasons": {"1": "guess", "2": "two"}, "unsure": [3]},
    {"type": "과제 제출", "task_name": "독서 1", "submitted_at": "2026-11-20 20:00", "wrongs": [1, 2, 3, 4]},   # 예전 제출(무시)
    {"type": "타임어택 퀴즈", "task_name": "문법 퀴즈", "submitted_at": "2026-11-22 18:00", "wrongs": [3],
     "reasons": {"3": "misread"}},
    {"type": "과제 제출", "task_name": "옛날 과제", "submitted_at": "2026-10-01 18:00", "wrongs": []},        # 예전엔 추론을 잘했다
    {"type": "모의고사", "task_name": "유형없는 시험", "submitted_at": "2026-11-25 10:00", "wrongs": [2, 7, 9]},
    {"type": "로그인", "task_name": "x", "submitted_at": "2026-11-25"},
]


class WeaknessTests(unittest.TestCase):
    def setUp(self):
        self.r = wk.analyze(ROWS, meta_for, TODAY)

    def test_weak_tags_ranked_with_counts_and_rates(self):
        w = {x["tag"]: x for x in self.r["all"]}
        self.assertEqual((w["추론"]["solved"], w["추론"]["wrong"]), (5, 3))      # 독서1 1·2 + 퀴즈 3 + 옛날 1·2
        self.assertEqual(w["추론"]["correct_rate"], 40)
        self.assertEqual(w["품사"]["wrong"], 0)
        self.assertEqual(self.r["weak"][0]["tag"], "추론")                         # 찍음 · 둘 중 고민이 있는 추론이 맨 위
        self.assertNotIn("품사", [x["tag"] for x in self.r["weak"]])
        self.assertEqual(w["추론"]["reasons"], {"guess": 1, "two": 1, "misread": 1})
        self.assertEqual(w["어휘"]["reasons"], {"unsure": 1})

    def test_trend_compares_recent_with_before(self):
        w = {x["tag"]: x for x in self.r["all"]}
        self.assertEqual(w["추론"]["trend"], "down")                               # 10월엔 다 맞혔는데 최근 3/3 틀림

    def test_only_latest_submission_and_untagged_reported(self):
        self.assertEqual(self.r["tasks"], 4)
        self.assertEqual(self.r["untagged_wrong"], 3)
        self.assertEqual(self.r["untagged_tasks"], [{"kind": "모의고사", "title": "유형없는 시험", "wrong": 3}])
        self.assertEqual(self.r["reasons"], {"찍음": 1, "둘 중 고민": 1, "모름": 1, "잘못 봄": 1})

    def test_retry_fixed_items_drop_except_guess(self):
        r = {"type": "과제 제출", "task_name": "독서 1", "submitted_at": "2026-11-24", "wrongs": [1, 2, 3],
             "reasons": {"1": "guess"}, "retry": {"count": 1, "wrongs": [3]}}
        self.assertEqual(wk.wrong_set(r), {1, 3})

    def test_summary_line(self):
        self.assertIn("'추론'(5문항 중 3개 틀림)", wk.summary_line(self.r, "박서연"))
        self.assertIn("없습니다", wk.summary_line(wk.analyze([], meta_for, TODAY), "김지수"))

    def test_student_view_keeps_only_what_students_see(self):
        v = wk.student_view(self.r)
        self.assertEqual(v["weak"][0]["tag"], "추론")
        self.assertEqual(v["weak"][0]["trend_label"], "요즘 더 틀림")
        self.assertEqual(set(v["weak"][0]), {"tag", "solved", "wrong", "correct_rate", "trend", "trend_label"})   # 틀린 이유 · 예시는 안 보냄
        self.assertLessEqual(len(v["weak"]), 3)
        self.assertEqual(v["tasks"], 4)


if __name__ == "__main__":
    unittest.main()
