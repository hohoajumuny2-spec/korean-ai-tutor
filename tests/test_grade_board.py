import os
import sys
import unittest
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import homework_status as hs


class GradeBoardTests(unittest.TestCase):
    def test_grade_key_matches_roster_rules(self):
        self.assertEqual(hs.grade_key("하남고", "2"), "고2")
        self.assertEqual(hs.grade_key("미사중", "3학년"), "중3")
        self.assertEqual(hs.grade_key("", "재수"), "재수·N수")
        self.assertEqual(hs.grade_key("", ""), "학년 미입력")
        self.assertLess(hs.grade_rank("중3"), hs.grade_rank("고1"))

    def test_board_lists_answers_and_who_submitted_only_for_targeted_students(self):
        hws = [
            {"title": "문학 3", "kind": "class", "deadline": "2026-11-09T22:00", "answers": ["1", "2", "-", ""], "created_at": "2026-11-05"},
            {"title": "클리닉 1", "kind": "clinic", "deadline": "2026-11-20T22:00", "answers": [], "answer_file": "x.pdf"},
            {"title": "옛 과제", "deadline": "2026-08-01"},
        ]
        reports = {"문학 3": [{"student_name": "김하나", "percent": 90}, {"student_name": "박세나", "percent": 70, "late": True}]}
        visible = lambda hw, n: not (hw["title"] == "클리닉 1" and n == "박세나")
        out = hs.grade_board(date(2026, 11, 10), hws, ["김하나", "박세나", "이두리"], reports, visible,
                             lambda d: d < "2026-11-10")
        self.assertEqual([h["title"] for h in out], ["클리닉 1", "문학 3"])
        lit = out[1]
        self.assertEqual(lit["question_count"], 3)
        self.assertEqual([s["name"] for s in lit["submitted"]], ["김하나", "박세나"])
        self.assertTrue(lit["submitted"][1]["late"])
        self.assertEqual(lit["missing"], ["이두리"])
        clinic = out[0]
        self.assertEqual((clinic["kind"], clinic["audience"], clinic["pending"], clinic["has_answer_file"]),
                         ("clinic", 2, ["김하나", "이두리"], True))


if __name__ == "__main__":
    unittest.main()
