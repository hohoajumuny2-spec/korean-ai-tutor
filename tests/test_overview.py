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


class RecentScoresTests(unittest.TestCase):
    def test_latest_per_test_and_avg(self):
        rows = [
            {"type": "모의고사", "task_name": "10월", "score": 60, "total_score": 100, "submitted_at": "2026-10-19 10:00:00"},
            {"type": "모의고사", "task_name": "10월", "score": 90, "total_score": 100, "submitted_at": "2026-10-20 10:00:00"},
            {"type": "과제 제출", "task_name": "문법", "score": 7, "total_score": 10, "submitted_at": "2026-10-25 10:00:00"},
            {"type": "로그인", "task_name": "", "score": "", "submitted_at": "2026-10-26 10:00:00"},
        ]
        out = o.recent_scores(rows, 10)
        self.assertEqual([x["title"] for x in out["scores"]], ["문법", "10월"])
        self.assertEqual(out["scores"][1]["score"], "90/100")
        self.assertEqual(out["avg"], 80.0)
        self.assertEqual(o.recent_scores([], 5), {"scores": [], "avg": None})



class WeeklyTests(unittest.TestCase):
    def test_this_week_first_then_past_weeks(self):
        from datetime import date
        today = date(2026, 11, 4)                       # 수요일 → 이번 주는 11/2~11/8
        hws = [{"title": "문법1", "deadline": "2026-11-03T22:00"},
               {"title": "독서1", "deadline": "2026-10-28"},
               {"title": "멀리", "deadline": "2026-12-20"},
               {"title": "다른반", "deadline": "2026-11-03", "target": "x"},
               {"title": "옛날", "deadline": "2026-09-01"}]
        reports = [{"student_name": "박서연", "type": "과제 제출", "task_name": "독서1", "submitted_at": "2026-10-27"}]
        start = date(2026, 10, 26)
        hw = o.homework_items(today, hws, reports, ["박서연"], lambda h, n: h.get("target") != "x",
                              lambda d: d[:10] < "2026-11-04", start)
        self.assertEqual([h["title"] for h in hw["박서연"]], ["멀리", "문법1", "독서1"])
        att = [{"name": "박서연", "present": 3, "late": 1, "absent": 1, "absentDays": ["2026-10-30"],
                "presentDates": ["2026-10-27", "2026-11-02", "2026-11-03"], "lateDates": ["2026-11-03"],
                "clinicDates": ["2026-10-29"]}]
        out = o.build([{"name": "박서연"}], [], att, today=today, n_weeks=2, homework=hw)
        w = out["rows"][0]["weeks"]
        self.assertEqual([x["label"] for x in w], ["11/2~11/8", "10/26~11/1"])
        self.assertEqual((w[0]["present"], w[0]["late"], w[0]["absent"], w[0]["clinic"]), (2, 1, 0, 0))
        self.assertEqual((w[1]["present"], w[1]["late"], w[1]["absent"], w[1]["clinic"]), (1, 0, 1, 1))
        self.assertEqual((w[0]["homework"]["missing"], w[0]["homework"]["pending"], w[0]["homework"]["total"]), (1, 1, 2))
        self.assertEqual(w[1]["homework"]["submitted"], 1)

    def test_old_site_without_dates_still_counts_absences(self):
        from datetime import date
        out = o.build([{"name": "김가"}], [], [{"name": "김가", "absentDays": ["2026-11-02"]}],
                      today=date(2026, 11, 4), n_weeks=1, homework={})
        w = out["rows"][0]["weeks"][0]
        self.assertEqual(w["absent"], 1)
        self.assertNotIn("present", w)

if __name__ == "__main__":
    unittest.main()


class ClassLabelTests(unittest.TestCase):
    """과목별 반에만 넣은 학생도 한눈에 보기에 반이 보여야 한다."""

    def test_subject_classes_joined(self):
        s = {"class_name": "", "class_names": {"korean": "고2 국어", "math": "고2 수학"}}
        self.assertEqual(o.student_class_label(s), "고2 국어 · 고2 수학")

    def test_legacy_only(self):
        self.assertEqual(o.student_class_label({"class_name": "중3 국어"}), "중3 국어")

    def test_math_only_not_blank(self):
        self.assertEqual(o.student_class_label({"class_names": {"math": "고1 수학"}}), "고1 수학")
