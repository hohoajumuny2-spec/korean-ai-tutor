"""정답표 읽기(main.parse_answer_list) — main.py 를 통째로 불러오지 않고 그 함수만 꺼내 시험한다."""
import ast
import os
import unittest

_SRC = open(os.path.join(os.path.dirname(__file__), "..", "main.py"), encoding="utf-8").read()
_NAMES = {"multi_choice_slot", "parse_answer_list", "_CIRCLED", "ANSWER_MAX_CHARS"}
_ns = {}
_code = "import re, json\n"
for _n in ast.parse(_SRC).body:
    if (isinstance(_n, ast.FunctionDef) and _n.name in _NAMES) or \
            (isinstance(_n, ast.Assign) and any(getattr(t, "id", None) in _NAMES for t in _n.targets)):
        _code += ast.get_source_segment(_SRC, _n) + "\n"
exec(_code, _ns)
parse = _ns["parse_answer_list"]


class AnswerListTests(unittest.TestCase):
    def test_plain_rows_still_split(self):
        self.assertEqual(parse("1,3,5,2,4"), ["1", "3", "5", "2", "4"])
        self.assertEqual(parse("①②③④⑤"), ["1", "2", "3", "4", "5"])
        self.assertEqual(parse("3 1 5"), ["3", "1", "5"])

    def test_numbered_line_with_several_choices_is_one_slot(self):
        got = parse("1번 3\n2번 ③⑤\n3번 2+4\n4번 3, 5\n5번 ③/⑤\n6번 훈민정음")
        self.assertEqual(got, ["3", "3/5", "2+4", "3/5", "3/5", "훈민정음"])

    def test_short_answer_with_comma_kept(self):
        self.assertEqual(parse("1번 ③\n2번 가난하고 외롭고, 높고"), ["3", "가난하고 외롭고, 높고"])

    def test_slash_and_plus_inline(self):
        self.assertEqual(parse("1, 3/5, 2+4"), ["1", "3/5", "2+4"])


if __name__ == "__main__":
    unittest.main()
