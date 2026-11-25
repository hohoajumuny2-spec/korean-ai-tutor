"""재촉 서버 연결(nudge_api): 가짜 DB로 공부 기록 · 리그 · tick · 원장님 보기를 확인한다."""
import os
import sys
import unittest
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import nudge_api as na  # noqa: E402


class Inc:
    def __init__(self, n):
        self.n = n


class Snap:
    def __init__(self, id, data):
        self.id, self._d = id, data
        self.exists = data is not None

    def to_dict(self):
        return dict(self._d) if self._d is not None else None


class Doc:
    def __init__(self, coll, id):
        self.coll, self.id = coll, id

    def get(self):
        return Snap(self.id, self.coll.rows.get(self.id))

    def set(self, data, merge=False):
        cur = dict(self.coll.rows.get(self.id) or {}) if merge else {}
        for k, v in data.items():
            cur[k] = (cur.get(k) or 0) + v.n if isinstance(v, Inc) else v
        self.coll.rows[self.id] = cur


class Query:
    def __init__(self, coll, f=None):
        self.coll, self.f = coll, f

    def where(self, field, op, val):
        ops = {"==": lambda a: a == val, ">=": lambda a: a is not None and str(a) >= str(val)}
        return Query(self.coll, lambda r: ops[op](r.get(field)))

    def stream(self):
        return [Snap(k, v) for k, v in self.coll.rows.items() if self.f is None or self.f(v)]


class Coll(Query):
    def __init__(self):
        self.rows = {}
        super().__init__(self)

    def document(self, id):
        return Doc(self, id)

    def add(self, data):
        self.rows[f"auto{len(self.rows)}"] = dict(data)


class DB:
    def __init__(self):
        self.c = {}

    def collection(self, name):
        return self.c.setdefault(name, Coll())


NOW = [datetime(2026, 11, 24, 19, 10)]


def setup(att=None):
    db = DB()
    sent = {"push": [], "kakao": [], "xp": []}
    na.H.clear()
    na.H.update({
        "db": lambda: db, "sanitize_doc_id": lambda v: v.replace("/", "_"), "now_kst": lambda: NOW[0],
        "is_preview": lambda n: n == "원장님(체험)",
        "add_xp": lambda n, a: sent["xp"].append((n, a)),
        "increment": Inc,
        "targeting_info_from": lambda d: {"classes": {"korean": d.get("class_name", "")},
                                          "all_classes": [d.get("class_name")] if d.get("class_name") else []},
        "homework_visible_to_student": lambda hw, n, info=None: True,
        "send_push_to_student": lambda n, t, b, u, tag: sent["push"].append((n, t, b)) or 1,
        "kakao_message": lambda kind, to, items: sent["kakao"].extend({**i, "kind": kind} for i in items) or {"success": True},
    })
    na.fetch_attendance = lambda day: att
    return db, sent


class RecordTests(unittest.TestCase):
    def test_record_once_per_day_and_league_xp(self):
        db, sent = setup()
        na.record_activity("박서연")
        na.record_activity("박서연")
        self.assertEqual(db.collection("streaks").rows["박서연"]["current"], 1)
        na.add_league_xp("박서연", 30)
        na.add_league_xp("박서연", 20)
        na.add_league_xp("원장님(체험)", 20)
        rows = db.collection("league_xp").rows
        self.assertEqual(list(rows.values()), [{"week": "2026-W48", "student_name": "박서연", "xp": 50}])

    def test_safe_hook_swallows_errors(self):
        na._safe(lambda: 1 / 0)()


class TickTests(unittest.TestCase):
    def seed(self, db):
        st = db.collection("students")
        st.rows["박서연"] = {"class_name": "고2A"}
        st.rows["김지수"] = {"class_name": "고2A"}
        st.rows["이퇴원"] = {"class_name": "고2A", "withdrawn": True}
        db.collection("practice_stats").rows["박서연"] = {"student_name": "박서연"}
        db.collection("push_subs").rows["p1"] = {"student_name": "박서연", "endpoint": "x"}
        db.collection("streaks").rows["박서연"] = {"student_name": "박서연", "current": 4, "best": 4,
                                                 "last_active": "2026-11-23", "shields": 1, "days": ["2026-11-23"]}

    def test_dry_run_plans_but_sends_nothing(self):
        db, sent = setup()
        self.seed(db)
        r = na.run_tick(dry=True, cfg={"enabled": True, "kakao": True, "exclude": []})
        names = {p["name"]: [i["key"] for i in p["items"]] for p in r["planned"]}
        self.assertEqual(names, {"박서연": ["pr19"]})
        self.assertEqual(sent["push"], [])
        self.assertEqual(db.collection("nudge_log").rows, {})

    def test_send_logs_and_does_not_repeat(self):
        db, sent = setup()
        self.seed(db)
        cfg = {"enabled": True, "kakao": True, "exclude": []}
        na.run_tick(False, cfg)
        self.assertEqual(len(sent["push"]), 1)
        log = db.collection("nudge_log").rows["2026-11-24__박서연"]
        self.assertEqual((log["keys"], log["push"], log["kakao"]), (["pr19"], 1, 0))
        na.run_tick(False, cfg)
        self.assertEqual(len(sent["push"]), 1)                      # 같은 재촉은 한 번만
        NOW[0] = datetime(2026, 11, 24, 23, 5)
        try:
            na.run_tick(False, cfg)
        finally:
            NOW[0] = datetime(2026, 11, 24, 19, 10)
        self.assertEqual([i["name"] for i in sent["kakao"]], ["박서연"])   # 3단계는 카톡도

    def test_kiosk_attendance_counts_as_study_and_clinic_missed(self):
        att = [{"name": "김지수", "presentDates": ["2026-11-24"], "clinicDates": []},
               {"name": "박서연", "presentDates": [], "clinicDates": []}]
        db, sent = setup(att)
        self.seed(db)
        db.collection("clinics").rows["c1"] = {"student_name": "박서연", "kind": "weekly", "weekday": 1, "time": "18:00"}
        db.collection("homeworks").rows["독서 3회"] = {"deadline": "2026-11-24T18:00"}
        r = na.run_tick(False, {"enabled": True, "kakao": True, "exclude": ["김지수"]})
        self.assertEqual(r["marked_from_kiosk"], ["김지수"])
        self.assertEqual(db.collection("streaks").rows["김지수"]["current"], 1)
        keys = [i["key"] for p in r["planned"] for i in p["items"]]
        self.assertIn("cl30", keys)
        self.assertIn("hwlate:독서 3회", keys)
        self.assertNotIn("김지수", [p["name"] for p in r["planned"]])      # 빼 둔 학생

        g = na.gather(NOW[0])
        rows = {x["name"]: x for x in na.overview_rows(g)}
        self.assertEqual(rows["박서연"]["overdue"], ["독서 3회"])
        self.assertIn("클리닉 미등원", rows["박서연"]["flags"])
        self.assertTrue(rows["김지수"]["done_today"])
        self.assertNotIn("이퇴원", rows)
        self.assertEqual(list(rows)[0], "박서연")                    # 빠진 학생이 맨 위

    def test_send_test_ignores_time_and_caps(self):
        db, sent = setup()
        self.seed(db)
        NOW[0] = datetime(2026, 11, 24, 23, 50)          # 쉬는 시간이어도
        try:
            r = na.send_test("박서연", "pr23", True, True)
        finally:
            NOW[0] = datetime(2026, 11, 24, 19, 10)
        self.assertTrue(r["success"])
        self.assertTrue(r["title"].startswith("[시험]"))
        self.assertNotIn("{", r["body"])
        self.assertEqual((len(sent["push"]), [i["name"] for i in sent["kakao"]]), (1, ["박서연"]))
        self.assertEqual(db.collection("nudge_log").rows, {})     # 기록 · 한도에는 안 넣는다
        self.assertFalse(na.send_test("박서연", "없는것", True, False)["success"])
        self.assertFalse(na.send_test("", "pr19", True, False)["success"])
        for k in na.nd.TEXTS:                                     # 모든 종류가 빈칸 없이 만들어진다
            self.assertNotIn("{", na.nd.sample_message(k, "김지수", NOW[0])["body"])

    def test_memo_only_when_written_and_not_expired(self):
        from datetime import date
        m = {"title": "T", "body": "B"}
        self.assertEqual(na.push_body(m, ""), "B")                                       # 없으면 그 줄도 없다
        self.assertEqual(na.push_body(m, "기말 대비 주간!"), "B\n💬 기말 대비 주간!")
        d = date(2026, 11, 24)
        self.assertEqual(na.active_memo({"memo": " 힘내 "}, d), "힘내")
        self.assertEqual(na.active_memo({"memo": "힘내", "memo_until": "2026-11-24"}, d), "힘내")
        self.assertEqual(na.active_memo({"memo": "힘내", "memo_until": "2026-11-23"}, d), "")   # 날짜 지나면 자동으로 빠짐
        self.assertEqual(na.active_memo({"memo": ""}, d), "")

    def test_tick_kakao_carries_memo(self):
        db, sent = setup()
        self.seed(db)
        NOW[0] = datetime(2026, 11, 24, 23, 5)
        try:
            na.run_tick(False, {"enabled": True, "kakao": True, "exclude": [], "memo": "이번 주는 기말 대비!"})
        finally:
            NOW[0] = datetime(2026, 11, 24, 19, 10)
        # 카톡은 검수받은 '학습기록' 템플릿 빈칸만(한마디 없음), 한마디는 앱 알림에
        self.assertEqual(sent["kakao"][0], {"name": "박서연", "vars": {"일수": "4"}, "kind": "학습기록"})
        self.assertTrue(sent["push"][0][2].endswith("💬 이번 주는 기말 대비!"))

    def test_each_purpose_goes_to_its_own_kakao_template(self):
        att = [{"name": "박서연", "presentDates": [], "clinicDates": []}]
        db, sent = setup(att)
        self.seed(db)
        db.collection("push_subs").rows.clear()                                  # 앱 알림 없음 → 2단계부터 카톡
        db.collection("clinics").rows["c1"] = {"student_name": "박서연", "kind": "weekly", "weekday": 1, "time": "18:00"}
        db.collection("homeworks").rows["독서 3회"] = {"deadline": "2026-11-24T18:00"}
        na.run_tick(False, {"enabled": True, "kakao": True, "exclude": []})
        got = {k["kind"]: k["vars"] for k in sent["kakao"]}
        self.assertEqual(na.nd.sample_message("hw1", "김지수", NOW[0])["kakao_kind"], "과제마감")   # 마감 전은 재촉 템플릿
        self.assertEqual(got, {"미제출": {"과제": "독서 3회", "마감": "11월 24일 18시"}, "클리닉": {"날짜": "11월 24일(화)", "시각": "18시"}})
        for k in na.nd.TEXTS:                                                     # 모든 종류에 템플릿 · 빈칸이 있다
            m = na.nd.sample_message(k, "김지수", NOW[0])
            self.assertIn(m["kakao_kind"], ("과제마감", "미제출", "클리닉", "학습기록"))
            self.assertTrue(all(str(v) for v in m["kakao_vars"].values()))

    def test_leagues_by_class(self):
        db, _ = setup()
        lg = na.leagues([{"name": "가", "class_name": "A"}, {"name": "나", "class_name": "A"}, {"name": "다", "class_name": "B"}],
                        "2026-W48", [{"week": "2026-W48", "student_name": "나", "xp": 40},
                                     {"week": "2026-W47", "student_name": "가", "xp": 99}])
        self.assertEqual(lg["A"]["top"], [{"rank": 1, "name": "나", "xp": 40}])
        self.assertEqual(lg["B"]["top"], [])


if __name__ == "__main__":
    unittest.main()
