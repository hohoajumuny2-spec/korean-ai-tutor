"""학생을 고른 공지가 누구에게 보이는지 — main.py 에서 필요한 함수만 꺼내 시험한다."""
import ast
import os
import re
import unittest

_SRC = open(os.path.join(os.path.dirname(__file__), "..", "main.py"), encoding="utf-8").read()
_NAMES = {"normalize_target_classes", "task_target_classes", "normalize_target_students",
          "board_visible_to_student", "homework_visible_to_student", "task_visible_to_student", "is_preview", "PREVIEW_NAME", "_NO_INFO"}
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


class HomeworkTargetTests(unittest.TestCase):
    """과제도 학생을 골라 낼 수 있다 — 공지와 같은 규칙을 그대로 쓴다."""

    def test_homework_picked_students(self):
        hw = {"title": "문법 과제", "target_classes": [], "target_students": ["김하나"]}
        self.assertTrue(visible(hw, "김하나", info("A반")))
        self.assertFalse(visible(hw, "이두리", info("A반")))

    def test_homework_without_students_keeps_class_rule(self):
        hw = {"title": "문법 과제", "target_classes": ["A반"]}
        self.assertTrue(visible(hw, "김하나", info("A반")))
        self.assertFalse(visible(hw, "이두리", info("B반")))

    def test_homework_visible_helper_is_same_rule(self):
        self.assertIn("def homework_visible_to_student(hw: dict, student_name: str, info=_NO_INFO)", _SRC)
        self.assertIn("return board_visible_to_student(hw, student_name, info=info)", _SRC)


class HomeworkStudentsOnlyTests(unittest.TestCase):
    """2026-11-28: 학생을 고른 과제는 반이 함께 골라져 있어도 그 학생에게만 간다(공지는 예전 규칙)."""

    def test_picked_student_ignores_class(self):
        hw_visible = _ns["homework_visible_to_student"]
        hw = {"title": "김지유 과제", "target_classes": ["고1 심화A"], "target_students": ["김지유"]}
        self.assertTrue(hw_visible(hw, "김지유", info("고1 심화A")))
        self.assertFalse(hw_visible(hw, "이두리", info("고1 심화A")))
        self.assertFalse(hw_visible({**hw, "target_classes": [], "target_class": "고1 심화A"}, "이두리", info("고1 심화A")))

    def test_board_still_adds_class(self):
        row = {"target_classes": ["B반"], "target_students": ["김하나"]}
        self.assertTrue(visible(row, "이두리", info("B반")))

    def test_class_only_homework_unchanged(self):
        hw_visible = _ns["homework_visible_to_student"]
        self.assertTrue(hw_visible({"target_classes": ["A반"]}, "김하나", info("A반")))
        self.assertFalse(hw_visible({"target_classes": ["A반"]}, "이두리", info("B반")))


class HomeworkNoAutoNoticeTests(unittest.TestCase):
    """2026-11-28: 과제를 올려도 앱 알림 · 카톡을 자동으로 보내지 않는다."""

    def test_create_homework_sends_nothing(self):
        start = _SRC.index("async def create_homework(")
        end = _SRC.index("\ndef ", start)
        body = _SRC[start:end]
        for call in ("kakao_new_post(", "send_push_to_names(", "send_push_to_audience("):
            self.assertNotIn(call, body)
