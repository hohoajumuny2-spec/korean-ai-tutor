"""재촉 엔진: 연속 기록 · 방패 · 재촉 시간표 · 말투 · 보낼 길 · 리그."""
import os
import sys
import unittest
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import nudge as nd  # noqa: E402

D = date(2026, 11, 24)


def at(h, m=0, d=D):
    return datetime(d.year, d.month, d.day, h, m)


class NameTests(unittest.TestCase):
    def test_call_name(self):
        self.assertEqual(nd.call_name("박서연"), "서연아")
        self.assertEqual(nd.call_name("김지수"), "지수야")
        self.assertEqual(nd.call_name("남궁민수"), "민수야")
        self.assertEqual(nd.call_name("박서연(고2)"), "서연아")


class StreakTests(unittest.TestCase):
    def test_days_in_a_row_grow_and_same_day_is_counted_once(self):
        s, _, _ = nd.mark_active(None, D)
        s, _, _ = nd.mark_active(s, D)
        self.assertEqual(s["current"], 1)
        s, _, _ = nd.mark_active(s, D + timedelta(days=1))
        self.assertEqual((s["current"], s["best"]), (2, 2))

    def test_shield_covers_a_missed_day_then_break_without_shield(self):
        s, _, _ = nd.mark_active(None, D)                       # 방패 1개로 시작
        s, _, ev = nd.mark_active(s, D + timedelta(days=2))     # 하루 빠짐 → 방패
        self.assertEqual((s["current"], s["shields"]), (2, 0))
        self.assertIn("shield:1", ev)
        s, _, ev = nd.mark_active(s, D + timedelta(days=4))     # 또 빠짐, 방패 없음 → 끊김
        self.assertEqual(s["current"], 1)
        self.assertIn("broken:2", ev)
        self.assertEqual(s["best"], 2)

    def test_seven_days_give_a_shield_and_bonus(self):
        s = None
        total = 0
        for k in range(7):
            s, bonus, ev = nd.mark_active(s, D + timedelta(days=k))
            total += bonus
        self.assertEqual(s["current"], 7)
        self.assertEqual(s["shields"], 2)           # 처음 1 + 7일 1
        self.assertEqual(total, nd.MILESTONES[7])
        s2, bonus2, _ = nd.mark_active(s, D + timedelta(days=7))
        self.assertEqual(bonus2, 0)                 # 보너스는 한 번만

    def test_view_shows_risk_and_broken(self):
        s, _, _ = nd.mark_active(None, D)
        v = nd.streak_view(s, D + timedelta(days=1))            # 어제 했고 오늘 아직
        self.assertEqual((v["current"], v["at_risk"], v["done_today"]), (1, True, False))
        v = nd.streak_view(s, D + timedelta(days=2))            # 하루 빠졌지만 방패 1개
        self.assertEqual(v["current"], 1)
        v = nd.streak_view(s, D + timedelta(days=3))            # 이틀 빠짐 → 끊김
        self.assertEqual(v["current"], 0)
        self.assertEqual(len(v["week"]), 7)


def ctx(**kw):
    base = {"name": "박서연", "streak": 5, "active_today": False, "last_active": D - timedelta(days=1),
            "practice": True, "practice_done": False, "homeworks": [], "clinic": None}
    base.update(kw)
    return base


class DueTests(unittest.TestCase):
    def keys(self, c, now, sent=()):
        return [m["key"] for m in nd.due_messages(c, now, set(sent))]

    def test_homework_steps_by_time_left(self):
        hw = [{"title": "독서 3회", "deadline": "2026-11-25T22:00", "submitted": False}]
        self.assertEqual(self.keys(ctx(homeworks=hw, active_today=True), at(9)), [])                       # 17시 전
        self.assertEqual(self.keys(ctx(homeworks=hw, active_today=True), at(17, 0)), ["hwd:독서 3회"])     # D-1 17시
        self.assertEqual(self.keys(ctx(homeworks=hw, active_today=True), at(19, 30, D + timedelta(1))), ["hwd:독서 3회"])  # D-day
        self.assertEqual(self.keys(ctx(homeworks=hw, active_today=True), at(19, 30, D + timedelta(1)), ["hwd:독서 3회"]), ["hw3:독서 3회"])
        self.assertEqual(self.keys(ctx(homeworks=hw, active_today=True), at(21, 10, D + timedelta(1)), ["hwd:독서 3회"]), ["hw1:독서 3회"])
        self.assertEqual(self.keys(ctx(homeworks=hw, active_today=True), at(8, 30, D + timedelta(2))), ["hwlate:독서 3회"])
        self.assertEqual(self.keys(ctx(homeworks=hw, active_today=True), at(21, 10, D + timedelta(1)), ["hwd:독서 3회", "hw1:독서 3회"]), [])
        done = [{**hw[0], "submitted": True}]
        self.assertEqual(self.keys(ctx(homeworks=done, active_today=True), at(21, 10, D + timedelta(1))), [])

    def test_homework_daily_from_three_days_before(self):
        hw = [{"title": "독서", "deadline": "2026-11-28T22:00", "submitted": False}]
        c = ctx(homeworks=hw, active_today=True)
        self.assertEqual(self.keys(c, at(17, 5, date(2026, 11, 24))), [])                    # D-4: 아직
        for d in (25, 26, 27, 28):                                                        # D-3 ~ D-day 매일
            m = nd.due_messages(c, at(17, 5, date(2026, 11, d)), set())
            self.assertEqual([x["key"] for x in m], ["hwd:독서"])
            self.assertEqual(m[0]["kakao_kind"], "과제마감")
        self.assertIn("D-3", nd.due_messages(c, at(17, 5, date(2026, 11, 25)), set())[0]["title"])
        self.assertIn("D-day", nd.due_messages(c, at(17, 5, date(2026, 11, 28)), set())[0]["title"])
        early = [{"title": "독서", "deadline": "2026-11-24T10:00", "submitted": False}]   # 당일 오전 마감 → 아침 8시에
        self.assertEqual(self.keys(ctx(homeworks=early, active_today=True), at(8, 0)), ["hwd:독서"])
        late = nd.route(nd.due_messages(ctx(homeworks=early, active_today=True), at(10, 30), set()), True, 0, 0, True)
        self.assertEqual([(m["key"], m["via"]) for m in late], [("hwlate:독서", ["push", "kakao"])])   # 마감 지나면 카톡

    def test_daily_practice_steps_and_quiet_hours(self):
        self.assertEqual(self.keys(ctx(), at(18, 59)), [])
        self.assertEqual(self.keys(ctx(), at(19, 5)), ["pr19"])
        self.assertEqual(self.keys(ctx(), at(21, 40)), ["pr2130"])
        self.assertEqual(self.keys(ctx(), at(23, 5)), ["pr23"])
        self.assertEqual(self.keys(ctx(), at(23, 40)), [])                  # 조용한 시간
        self.assertEqual(self.keys(ctx(), at(7, 50)), [])
        self.assertEqual(self.keys(ctx(active_today=True), at(21, 40)), [])  # 오늘 다른 공부를 했으면 안 보냄
        self.assertEqual(self.keys(ctx(practice=False), at(19, 5)), ["pr19"])   # 매일 문제가 없어도 연속 기록이 있으면
        self.assertEqual(self.keys(ctx(practice=False, streak=0), at(19, 5)), [])

    def test_clinic_before_and_after(self):
        cl = {"time": "18:00", "attended": False}
        self.assertEqual(self.keys(ctx(clinic=cl, active_today=True), at(16, 10)), ["cl2h"])
        self.assertEqual(self.keys(ctx(clinic=cl, active_today=True), at(18, 40)), ["cl30"])
        self.assertEqual(self.keys(ctx(clinic={**cl, "attended": True}, active_today=True), at(18, 40)), [])

    def test_idle_after_two_days(self):
        c = ctx(practice=False, streak=0, last_active=D - timedelta(days=3))
        self.assertEqual(self.keys(c, at(17, 5)), ["idle"])
        self.assertEqual(self.keys(c, at(16, 5)), [])

    def test_tone_gets_firmer_and_has_name_and_numbers(self):
        m1 = nd.due_messages(ctx(), at(19, 5), set())[0]
        m3 = nd.due_messages(ctx(), at(23, 5), set())[0]
        self.assertEqual((m1["level"], m3["level"]), (1, 3))
        self.assertTrue("서연" in m1["body"] or "5일" in m1["body"] or "오늘" in m1["body"])
        self.assertNotIn("{", m3["body"])


class RouteTests(unittest.TestCase):
    def test_kakao_only_for_firm_or_no_push_and_daily_caps(self):
        msgs = [{"key": "a", "level": 1}, {"key": "b", "level": 3}, {"key": "c", "level": 2}]
        r = {m["key"]: m["via"] for m in nd.route(msgs, True, 0, 0, True)}
        self.assertEqual(r, {"b": ["push", "kakao"], "c": ["push"], "a": ["push"]})
        r = {m["key"]: m["via"] for m in nd.route(msgs, False, 0, 0, True)}
        self.assertEqual(r, {"b": ["kakao"], "c": ["kakao"], "a": []})       # 앱 알림이 없으면 2단계부터 카톡
        r = {m["key"]: m["via"] for m in nd.route(msgs, True, 5, nd.MAX_KAKAO_PER_DAY, True)}
        self.assertEqual(r, {"a": [], "b": [], "c": []})                     # 하루 한도
        r = {m["key"]: m["via"] for m in nd.route(msgs, True, 0, 0, False)}
        self.assertEqual(r["b"], ["push"])                                   # 카톡 끔
        guide = [{"key": "h", "kind": "hwd", "level": 1}, {"key": "w", "kind": "hw1", "level": 3}, {"key": "c2", "kind": "cl2h", "level": 1}]
        r = {m["key"]: m["via"] for m in nd.route(guide, True, 0, 0, True)}
        self.assertEqual(r, {"h": ["push", "kakao"], "c2": ["push"], "w": ["push"]})  # 과제 안내는 늘 카톡, 클리닉 · 1시간 전은 앱만


class LeagueTests(unittest.TestCase):
    def test_week_id_and_rank(self):
        self.assertEqual(nd.week_id(date(2026, 11, 23)), nd.week_id(date(2026, 11, 29)))   # 월~일 같은 주
        self.assertNotEqual(nd.week_id(date(2026, 11, 29)), nd.week_id(date(2026, 11, 30)))
        lg = nd.league([{"name": "가", "xp": 50}, {"name": "나", "xp": 120}, {"name": "다", "xp": 0}], "가")
        self.assertEqual([r["name"] for r in lg["top"]], ["나", "가"])
        self.assertEqual((lg["my_rank"], lg["my_xp"], lg["size"]), (2, 50, 2))
        self.assertIsNone(nd.league([{"name": "나", "xp": 10}], "가")["my_rank"])


if __name__ == "__main__":
    unittest.main()
