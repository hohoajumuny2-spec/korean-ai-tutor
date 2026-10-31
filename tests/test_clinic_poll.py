"""클리닉 시간 신청 계산 · 반별 과제 제출표."""
import os
import sys
import unittest
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import clinic_poll as cp  # noqa: E402
import homework_status as hs  # noqa: E402


class ClinicPollTests(unittest.TestCase):
    def test_slots_normalized(self):
        slots = cp.normalize_slots([{"weekday": 1, "time": "17:00"}, {"weekday": 1, "time": "17:00"},
                                    {"weekday": 0, "time": "9:30"}, {"weekday": 2, "time": "25:00"}, {"weekday": "x", "time": "10:00"}])
        self.assertEqual([s["label"] for s in slots], ["월 09:30", "화 17:00"])
        self.assertEqual(slots[1]["id"], "w1-1700")

    def test_summary(self):
        slots = cp.normalize_slots([{"weekday": 1, "time": "17:00"}, {"weekday": 3, "time": "18:00"}])
        answers = [{"student_name": "김가", "slot_ids": ["w1-1700", "w3-1800", "w9-0000"], "confirmed_slot": "w3-1800"},
                   {"student_name": "이나", "slot_ids": ["w1-1700"], "memo": "목요일은 학원 수업"}]
        out = cp.summary(slots, answers, ["김가", "이나", "박다"])
        self.assertEqual(out["slots"][0]["available"], ["김가", "이나"])
        self.assertEqual(out["slots"][1]["confirmed"], ["김가"])
        self.assertEqual(out["students"][0]["slot_ids"], ["w1-1700", "w3-1800"])   # 없는 시간은 빠짐
        self.assertEqual(out["missing"], ["박다"])
        self.assertEqual(cp.clean_choice(["w3-1800", "w1-1700"], slots), ["w1-1700", "w3-1800"])


class ClassGridTests(unittest.TestCase):
    def test_grid(self):
        today = date(2026, 10, 31)
        hws = [{"title": "문법", "deadline": "2026-10-28"}, {"title": "독서", "deadline": "2026-11-03"},
               {"title": "다른반", "deadline": "2026-10-29", "target": "x"}]
        reports = {"문법": [{"student_name": "김가", "submitted_at": "2026-10-27"}]}
        g = hs.class_grid(today, hws, ["김가", "이나"], reports, lambda h: h.get("target") != "x",
                          lambda d: d < "2026-10-31")
        self.assertEqual([c["title"] for c in g["homeworks"]], ["독서", "문법"])
        self.assertEqual(g["homeworks"][1]["counts"], {"submitted": 1, "late": 0, "missing": 1, "pending": 0})
        self.assertEqual([c["status"] for c in g["rows"][1]["cells"]], ["pending", "missing"])
        self.assertEqual(g["rows"][1]["missing"], 1)

    def test_far_deadline_still_shows_but_old_homework_does_not(self):
        today = date(2026, 10, 31)
        hws = [{"title": "방학 과제", "deadline": "2027-01-20"}, {"title": "옛날", "deadline": "2026-08-01"}]
        g = hs.class_grid(today, hws, ["김가"], {}, lambda h: True, lambda d: d < "2026-10-31")
        self.assertEqual([c["title"] for c in g["homeworks"]], ["방학 과제"])


if __name__ == "__main__":
    unittest.main()
