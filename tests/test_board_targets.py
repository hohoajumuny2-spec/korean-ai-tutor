"""학생을 고른 공지가 누구에게 보이는지 — main.py 에서 필요한 함수만 꺼내 시험한다."""
import ast
import os
import re
import unittest

_SRC = open(os.path.join(os.path.dirname(__file__), "..", "main.py"), encoding="utf-8").read()
_NAMES = {"normalize_target_classes", "task_target_classes", "normalize_target_students",
          "board_visible_to_student", "task_visible_to_student", "is_preview", "PREVIEW_NAME", "_NO_INFO"}
_ns = {"re": re, "normalize_subject": lambda s: s}
_code = ""
for _n in ast.parse(_SRC).body:
    if (isinstance(_n, ast.FunctionDef) and _n.name in _NAMES) or \
            (isinstance(_n, ast.Assign) and any(getattr(t, "id", None) in _NAMES for t in _n.targets)):
        _code += ast.get_source_segment(_SRC, _n) + "\n"
exec(_code, _ns)
visible = _ns["board_visible_to_student"]


def info(cls="", withdrawn=False):
    return {"subjects": ["korean"], "classes": {"korean": cls}, "all_classes": [cls] if cls else [],
            "withdrawn": withdrawn}


class BoardTargetTests(unittest.TestCase):
    def test_no_targets_is_everyone(self):
        self.assertTrue(visible({}, "김하나", info("A반")))

    def test_class_only(self):
        row = {"target_classes": ["A반"]}
        self.assertTrue(visible(row, "김하나", info("A반")))
        self.assertFalse(visible(row, "이두리", info("B반")))

    def test_picked_students_only(self):
        row = {"target_students": ["김하나", "박세나"]}
        self.assertTrue(visible(row, "김하나", info("A반")))
        self.assertFalse(visible(row, "이두리", info("A반")))

    def test_students_plus_class(self):
        row = {"target_classes": ["B반"], "target_students": ["김하나"]}
        self.assertTrue(visible(row, "김하나", info("A반")))
        self.assertTrue(visible(row, "이두리", info("B반")))
        self.assertFalse(visible(row, "최서준", info("C반")))

    def test_withdrawn_never_sees(self):
        self.assertFalse(visible({"target_students": ["김하나"]}, "김하나", info("A반", withdrawn=True)))

    def test_names_from_text(self):
        self.assertEqual(_ns["normalize_target_students"]("김하나, 박세나\n김하나"), ["김하나", "박세나"])


if __name__ == "__main__":
    unittest.main()
