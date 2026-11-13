"""해설지 PDF 나눠 읽기 · 합치기 · 끊긴 AI 답 살리기."""
import ast
import os
import unittest

import fitz

import study_extras

_SRC = open(os.path.join(os.path.dirname(__file__), "..", "main.py"), encoding="utf-8").read()
_NAMES = {"split_pdf_for_ai", "merge_explain_items", "EXPLAIN_PDF_PAGES_PER_CALL"}
_ns = {"fitz": fitz}
_code = ""
for _n in ast.parse(_SRC).body:
    if (isinstance(_n, ast.FunctionDef) and _n.name in _NAMES) or \
            (isinstance(_n, ast.Assign) and any(getattr(t, "id", None) in _NAMES for t in _n.targets)):
        _code += ast.get_source_segment(_SRC, _n) + "\n"
exec(_code, _ns)
split, merge = _ns["split_pdf_for_ai"], _ns["merge_explain_items"]


def _pdf(pages):
    d = fitz.open()
    for i in range(pages):
        d.new_page().insert_text((72, 72), f"page {i + 1}")
    b = d.tobytes()
    d.close()
    return b


class SplitTests(unittest.TestCase):
    def test_short_pdf_stays_whole(self):
        raw = _pdf(3)
        self.assertEqual(split(raw), [raw])

    def test_long_pdf_split_by_three(self):
        parts = split(_pdf(7))
        self.assertEqual([fitz.open(stream=p, filetype="pdf").page_count for p in parts], [3, 3, 1])

    def test_not_pdf_returned_as_is(self):
        self.assertEqual(split(b"hello"), [b"hello"])


class MergeTests(unittest.TestCase):
    def test_joins_continued_explanation(self):
        got = merge([{"1": {"detail": "앞부분", "summary": "", "answer": 3}},
                     {"1": {"detail": "뒷부분", "summary": "요약"}, "2": {"detail": "둘"}}])
        self.assertEqual(got["1"]["detail"], "앞부분\n뒷부분")
        self.assertEqual(got["1"]["summary"], "요약")
        self.assertEqual(list(got), ["1", "2"])

    def test_number_order(self):
        self.assertEqual(list(merge([{"10": {"detail": "a"}}, {"2": {"detail": "b"}}])), ["2", "10"])


class SalvageTests(unittest.TestCase):
    def test_cut_off_reply_keeps_finished_items(self):
        t = '{"items": {"1": {"answer": 3, "detail": "가"}, "2": {"detail": "나"}, "3": {"detail": "끊'
        self.assertEqual(sorted(study_extras.parse_explain_reply(t)), ["1", "2"])


if __name__ == "__main__":
    unittest.main()
