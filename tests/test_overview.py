"""학생 한눈에 보기: 성적 + 키오스크 출결 합치기."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import overview as o  # noqa: E402


class OverviewTests(unittest.TestCase):
    def test_merge_scores_and_attendance(self):
        students = [{"name": "박서연", "school": "미사고", "grade": "2", "class_name": "고2 국어"},
                    {"name": "김결석", "class_name": "고2 국어"},
                    {"name": "이퇴원", "withdrawn": True}]
        reports = [
            {"student_name": "박서연", "type": "모의고사", "task_name": "10월 모의", "score": 80, "total_score": 100, "submitted_at": "2026-10-20 18:00:00"},
            {"student_name": "박서연", "type": "모의고사", "task_name": "10월 모의", "score": 60, "total_score": 100, "submitted_at": "2026-10-19 18:00:00"},
            {"student_name": "박서연", "type": "과제 제출", "task_name": "문법 과제", "score": 9, "total_score": 10, "submitted_at": "2026-10-25 20:00:00"},
            {"student_name": "박서연", "type": "로그인", "task_name": "", "score": "", "submitted_at": "2026-10-26 20:00:00"},
        ]
        att = [{"name": "박서연(고2)", "status": "등원", "present": 8, "late": 1, "absent": 0},
               {"name": "최키오", "status": "", "present": 2}]
        out = o.build(students, reports, att)
        names = [r["name"] for r in out["rows"]]
        self.assertEqual(names, ["김결석", "박서연"])
        p = out["rows"][1]
        self.assertEqual(p["tests"], 2)
        self.assertEqual(p["avg"], 85.0)                       # 다시 낸 모의고사는 마지막(80)만
        self.assertEqual(p["recent"][0]["title"], "문법 과제")
        self.assertEqual(p["recent"][0]["score"], "9/10")
        self.assertEqual(p["attendance"]["present"], 8)          # '박서연(고2)' 도 같은 학생
        self.assertIsNone(out["rows"][0]["attendance"])
        self.assertEqual(out["kiosk_only"], ["최키오"])

    def test_no_attendance_and_odd_scores(self):
        out = o.build([{"name": "가"}], [{"student_name": "가", "type": "타임어택 퀴즈", "task_name": "퀴즈", "score": "완료"}], None)
        self.assertEqual(out["rows"][0]["recent"][0]["score"], "완료")
        self.assertIsNone(out["rows"][0]["avg"])


if __name__ == "__main__":
    unittest.main()
