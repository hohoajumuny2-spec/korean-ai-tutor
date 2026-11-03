"""단답형 · 분수 · 복수 정답 채점(main.answer_matches 등) — main.py 를 통째로 불러오지 않고 그 함수만 꺼내 시험한다."""
import ast
import os
import unittest

_SRC = open(os.path.join(os.path.dirname(__file__), "..", "main.py"), encoding="utf-8").read()
_NAMES = {"is_choice_combo", "answer_slots", "answer_picks", "_answer_key_sets", "_norm_answer_text", "_as_number",
          "answer_matches", "answer_label", "slot_kind", "literal_answer", "slot_pick_count", "is_skip_slot", "SKIP_MARKS"}
_ns = {}
_code = "import re, json\n"
for _n in ast.parse(_SRC).body:
    if (isinstance(_n, ast.FunctionDef) and _n.name in _NAMES) or \
            (isinstance(_n, ast.Assign) and any(getattr(t, "id", None) in _NAMES for t in _n.targets)):
        _code += ast.get_source_segment(_SRC, _n) + "\n"
exec(_code, _ns)
matches, label, kind = _ns["answer_matches"], _ns["answer_label"], _ns["slot_kind"]
slots, picks = _ns["answer_slots"], _ns["answer_picks"]


class AnswerMatchTests(unittest.TestCase):
    def test_choice_combos_still_work(self):
        self.assertEqual(slots("3/5"), ["3", "5"])
        self.assertEqual(picks("2+4"), ["2", "4"])
        self.assertTrue(matches("5", "3/5"))
        self.assertTrue(matches("4+2", "2+4"))
        self.assertFalse(matches("2", "2+4"))
        self.assertEqual(label("1+2/3+4"), "1번과 2번 또는 3번과 4번")
        self.assertEqual(kind("3/5"), "choice")
        self.assertEqual(kind("2+4"), "multi2")

    def test_fraction_marked_with_equals_is_one_short_answer(self):
        self.assertEqual(slots("3/4"), ["3", "4"])       # 표시가 없으면 예전처럼 '3번 또는 4번'
        self.assertEqual(slots("=3/4"), ["=3/4"])        # '=' 를 붙이면 분수 3/4 그대로
        self.assertEqual(slots("7/8"), ["7/8"])          # 보기 번호(1~5)가 아니면 표시 없이도 분수
        self.assertEqual(picks("2x+1"), ["2x+1"])
        self.assertEqual(kind("=3/4"), "short")
        self.assertEqual(kind("x+2"), "short")
        self.assertEqual(label("=3/4"), "3/4")
        self.assertTrue(matches("3/4", "=3/4"))
        self.assertFalse(matches("3", "=3/4"))
        self.assertFalse(matches("4", "=3/4"))

    def test_same_number_written_differently_is_right(self):
        self.assertTrue(matches("0.75", "=3/4"))
        self.assertTrue(matches("6/8", "=3/4"))
        self.assertTrue(matches("1 1/2", "=3/2"))
        self.assertTrue(matches("0.875", "7/8"))
        self.assertTrue(matches("-2", "−2"))
        self.assertTrue(matches("2 x + 1", "2x+1"))
        self.assertTrue(matches("X^2", "x²"))
        self.assertFalse(matches("0.7", "=3/4"))
        self.assertFalse(matches("1/2", "=3/4"))

    def test_roots_and_pi_written_any_way(self):
        self.assertTrue(matches("루트3", "√3"))
        self.assertTrue(matches("sqrt(3)", "√3"))
        self.assertTrue(matches("2루트3", "2√3"))
        self.assertTrue(matches("2*√3", "2√3"))
        self.assertTrue(matches("3 파이", "3π"))
        self.assertTrue(matches("x = 2", "x=2"))
        self.assertFalse(matches("√2", "√3"))
        self.assertEqual(kind("√3"), "short")

    def test_word_answers_unchanged(self):
        self.assertTrue(matches("훈민 정음", "훈민정음"))
        self.assertFalse(matches("훈민정음", "용비어천가"))
        self.assertEqual(kind("-"), "none")


if __name__ == "__main__":
    unittest.main()
