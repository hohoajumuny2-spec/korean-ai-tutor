"""2026-11-28: 과제 질문 — 이유 고르기 · 여러 문항 고르기."""
import ast
import os
import re
import unittest

_SRC = open(os.path.join(os.path.dirname(__file__), "..", "main.py"), encoding="utf-8").read()
_NAMES = {"QNA_REASONS", "QNA_MAX_QNUMS", "_qna_qnums", "_qna_reasons", "_qna_nums_label"}
_ns = {"re": re}
_code = ""
for _n in ast.parse(_SRC).body:
    if (isinstance(_n, ast.FunctionDef) and _n.name in _NAMES) or \
            (isinstance(_n, ast.Assign) and any(getattr(t, "id", None) in _NAMES for t in _n.targets)):
        _code += ast.get_source_segment(_SRC, _n) + "\n"
exec(_code, _ns)


class QnaNumsTests(unittest.TestCase):
    def test_many_numbers_sorted_unique(self):
        self.assertEqual(_ns["_qna_qnums"]("", "7, 3,5 3"), ["3", "5", "7"])

    def test_old_single_qnum_still_works(self):
        self.assertEqual(_ns["_qna_qnums"]("12", ""), ["12"])
        self.assertEqual(_ns["_qna_qnums"]("4", "2,4"), ["2", "4"])

    def test_junk_and_zero_dropped(self):
        self.assertEqual(_ns["_qna_qnums"]("0", "abc, -1, 1000"), ["1"])

    def test_label(self):
        self.assertEqual(_ns["_qna_nums_label"]({"qnums": ["3", "5"]}), "3·5번")
        self.assertEqual(_ns["_qna_nums_label"]({"qnum": "9"}), "9번")
        self.assertEqual(_ns["_qna_nums_label"]({}), "")


class QnaReasonTests(unittest.TestCase):
    def test_only_known_keys(self):
        self.assertEqual(_ns["_qna_reasons"]("expl,why_wrong,hack,expl"), ["expl", "why_wrong"])
        self.assertEqual(_ns["_qna_reasons"](["etc", "x"]), ["etc"])

    def test_labels_exist(self):
        self.assertIn("why_wrong", _ns["QNA_REASONS"])
        self.assertTrue(all(_ns["QNA_REASONS"].values()))


class QnaCreateSourceTests(unittest.TestCase):
    def test_create_accepts_reason_only_and_multi(self):
        body = _SRC[_SRC.index("async def qna_create("):_SRC.index("@app.post(\"/api/qna/{post_id}/answer\")")]
        self.assertIn('qnums: str = Form("")', body)
        self.assertIn("not reason_keys", body)
        self.assertIn('"qnums": nums', body)

    def test_multi_question_answer_not_saved_to_one_explanation(self):
        body = _SRC[_SRC.index("def _qna_answer_to_homework("):]
        self.assertIn('len(post.get("qnums") or []) > 1', body[:600])


if __name__ == "__main__":
    unittest.main()
