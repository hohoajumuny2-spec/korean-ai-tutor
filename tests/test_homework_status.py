"""알림장 과제 확인 계산 시험: python3 -m unittest discover -s tests"""
import os, sys, unittest
from datetime import date
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import homework_status as hs

DAY = date(2026, 10, 24)
HWS = [
    {"title": "오늘 마감 과제", "deadline": "2026-10-24T18:00", "created_at": "2026-10-20 10:00:00", "target_classes": ["고2 국어"]},
    {"title": "다음 주 과제", "deadline": "2026-10-28T18:00", "created_at": "2026-10-24 09:00:00"},
    {"title": "마감 없는 과제", "created_at": "2026-10-22 09:00:00"},
    {"title": "한참 지난 과제", "deadline": "2026-09-01T18:00", "created_at": "2026-08-28 09:00:00"},
    {"title": "숨긴 과제", "deadline": "2026-10-24T18:00", "hidden": True},
]
REPORTS = {
    "오늘 마감 과제": [
        {"student_name": "김유경", "submitted_at": "2026-10-23 20:00:00"},
        {"student_name": "박서연", "submitted_at": "2026-10-24 19:00:00", "late": True},
        {"student_name": "곽윤서", "submitted_at": "2026-10-23 10:00:00", "percent": 87.5},
    ],
    "마감 없는 과제": [{"student_name": "김유경", "submitted_at": "2026-10-23 08:00:00"}],
}
CLASS = {"김유경", "박서연", "곽윤서", "강예랑"}


def audience(hw):
    return sorted(CLASS) if hw.get("target_classes") else sorted(CLASS | {"강승윤"})


class HomeworkStatusTests(unittest.TestCase):
    def run_build(self, passed=lambda d: d < "2026-10-24T20:00"):
        return hs.build(DAY, HWS, lambda t: REPORTS.get(t, []), audience, passed)

    def test_picks_homeworks_near_class_day_due_today_first(self):
        titles = [h["title"] for h in self.run_build()]
        self.assertEqual(titles[0], "오늘 마감 과제")
        self.assertIn("다음 주 과제", titles)
        self.assertIn("마감 없는 과제", titles)
        self.assertNotIn("한참 지난 과제", titles)
        self.assertNotIn("숨긴 과제", titles)
        self.assertTrue(self.run_build()[0]["due_on_day"])

    def test_status_per_student(self):
        today = self.run_build()[0]["students"]
        self.assertEqual(today["김유경"]["status"], "submitted")
        self.assertEqual(today["박서연"]["status"], "late")
        self.assertEqual(today["곽윤서"], {"status": "submitted", "submitted_at": "2026-10-23 10:00:00", "percent": 88})
        self.assertEqual(today["강예랑"]["status"], "missing")       # 마감 지남 + 안 냄
        self.assertNotIn("강승윤", today)                               # 대상 반이 아님

    def test_before_deadline_is_pending_and_no_deadline_is_missing(self):
        by = {h["title"]: h["students"] for h in self.run_build()}
        self.assertEqual(by["다음 주 과제"]["김유경"]["status"], "pending")
        self.assertEqual(by["마감 없는 과제"]["김유경"]["status"], "submitted")
        self.assertEqual(by["마감 없는 과제"]["강승윤"]["status"], "missing")
        # 아직 오늘 마감 전이면 안 낸 학생도 pending
        early = self.run_build(passed=lambda d: False)[0]["students"]
        self.assertEqual(early["강예랑"]["status"], "pending")

    def test_latest_submission_wins(self):
        rows = [{"student_name": "김유경", "submitted_at": "2026-10-20 10:00:00", "late": True},
                {"student_name": "김유경", "submitted_at": "2026-10-21 10:00:00"}]
        self.assertFalse(hs.latest_by_student(rows)["김유경"].get("late"))


if __name__ == "__main__":
    unittest.main()
