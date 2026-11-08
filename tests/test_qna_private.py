"""과제 · 클리닉 질문: '선생님께만' 질문은 질문한 학생과 원장님만 본다."""
import ast
import os
import re
import unittest

_SRC = open(os.path.join(os.path.dirname(__file__), "..", "main.py"), encoding="utf-8").read()
_NAMES = {"_qna_can_see", "_qna_video", "QNA_TOPICS"}
_ns = {"re": re}
_code = ""
for _n in ast.parse(_SRC).body:
    if (isinstance(_n, ast.FunctionDef) and _n.name in _NAMES) or \
            (isinstance(_n, ast.Assign) and any(getattr(t, "id", None) in _NAMES for t in _n.targets)):
        _code += ast.get_source_segment(_SRC, _n) + "\n"
exec(_code, _ns)
can_see, video = _ns["_qna_can_see"], _ns["_qna_video"]


class QnaPrivateTests(unittest.TestCase):
    def test_public_question_everyone(self):
        self.assertTrue(can_see({"author": "김하나"}, "이두리", False))
        self.assertTrue(can_see({"author": "김하나"}, "", False))

    def test_private_question_only_author_and_admin(self):
        p = {"author": "김하나", "private": True, "topic": "homework"}
        self.assertTrue(can_see(p, "김하나", False))
        self.assertFalse(can_see(p, "이두리", False))
        self.assertFalse(can_see(p, "", False))
        self.assertTrue(can_see(p, "", True))

    def test_shared_students_can_see(self):
        p = {"author": "김하나", "private": True, "shared_with": ["박세나"]}
        self.assertTrue(can_see(p, "박세나", False))
        self.assertFalse(can_see(p, "이두리", False))
        self.assertTrue(can_see({**p, "shared_all": True}, "이두리", False))

    def test_video_link_must_be_web_address(self):
        self.assertEqual(video("https://youtu.be/abc"), "https://youtu.be/abc")
        self.assertEqual(video("javascript:alert(1)"), "")
        self.assertEqual(video(""), "")

    def test_topics(self):
        self.assertEqual(set(_ns["QNA_TOPICS"]), {"homework", "clinic"})
