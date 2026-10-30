"""홍보글 공장: 글 종류 여러 개 · 홈페이지 과목 소개 · 직접 쓴 소개."""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from sns_maker import generator as g, homepage as h  # noqa: E402

GUIDE = '<html><script type="application/json" id="page-data">' + json.dumps({"subjects": [
    {"name": "국어", "lead": "원장 직강 국어. DIDIM 체계.", "programs": [
        {"name": "중등부 국어", "target": "중1~3", "goal": "읽기 → 요약 → 서술", "points": ["서·논술형 대비", "어휘 쪽지 시험"], "outcome": "서술형에 강한 상태"}]},
    {"name": "수학", "lead": "개념 → 유형 → 심화", "programs": [{"name": "중등 수학", "target": "중1~3", "goal": "실수 없는 내신"}]},
    {"name": "문해력", "lead": "모든 과목의 바탕", "programs": []},
]}, ensure_ascii=False) + '</script></html>'

BASE = {"channels": ["blog"], "topic": "겨울방학 국어"}


class RequestTests(unittest.TestCase):
    def test_many_kinds_and_old_single_kind(self):
        r = g.normalize_request(dict(BASE, kinds=["intro", "exam", "intro", "bad", "tip", "daily"]))
        self.assertEqual(r["kinds"], ["intro", "exam", "tip"])
        self.assertEqual(r["kind"], "intro")
        self.assertEqual(g.normalize_request(dict(BASE, kind="event"))["kinds"], ["event"])
        self.assertEqual(g.normalize_request(BASE)["kinds"], ["tip"])
        self.assertTrue(g.is_promo({"kinds": ["tip", "recruit"]}))
        self.assertFalse(g.is_promo({"kinds": ["tip", "daily"]}))
        line = g.kind_line({"kinds": ["intro", "exam"]})
        self.assertIn("학원 소개 + 시험 대비 안내", line)
        self.assertIn("한 흐름으로", line)

    def test_custom_intro_needs_text(self):
        with self.assertRaises(g.GenerationError):
            g.normalize_request(dict(BASE, intro_mode="custom", custom_intro="  "))
        r = g.normalize_request(dict(BASE, intro_mode="custom", custom_intro="새 고1 기초반"))
        self.assertEqual(r["custom_intro"], "새 고1 기초반")
        self.assertEqual(g.normalize_request(dict(BASE, custom_intro="무시"))["custom_intro"], "")

    def test_prompt_uses_homepage_or_custom(self):
        req = g.normalize_request(dict(BASE, kinds=["intro", "recruit"], subject="국어"))
        p = g.build_generate_prompt(req, g.merge_profile({}), "2026-10-30", "■ 국어: 원장 직강")
        self.assertIn("홈페이지(logyedu.com) 과목별 안내", p)
        self.assertIn("■ 국어: 원장 직강", p)
        self.assertIn("학원 소개 + 신규 모집", p)
        req2 = g.normalize_request(dict(BASE, intro_mode="custom", custom_intro="새 반 소개"))
        p2 = g.build_generate_prompt(req2, g.merge_profile({}), "2026-10-30", "■ 국어: 원장 직강")
        self.assertIn("원장님이 직접 쓴 내용", p2)
        self.assertNotIn("원장 직강", p2)


class HomepageTests(unittest.TestCase):
    def setUp(self):
        h.reset_cache()

    def test_parse_and_notes(self):
        subs = h.parse_guide(GUIDE)
        self.assertEqual([s["name"] for s in subs], ["국어", "수학", "문해력"])
        kor = h.notes_for(subs, "국어")
        self.assertIn("중등부 국어 (중1~3): 읽기 → 요약 → 서술", kor)
        self.assertIn("특징: 서·논술형 대비 / 어휘 쪽지 시험", kor)
        self.assertIn("■ 문해력", kor)                     # 국어 글엔 문해력도
        self.assertNotIn("수학", kor)
        allsub = h.notes_for(subs, "")
        self.assertIn("■ 수학", allsub)
        self.assertNotIn("특징", allsub)                    # 학원 전체는 짧게
        self.assertEqual(h.notes_for(subs, "과학"), "")
        self.assertEqual(h.parse_guide("<html>없음</html>"), [])

    def test_cache_and_fallback(self):
        calls = []
        def ok(url):
            calls.append(url); return GUIDE
        def bad(url):
            raise OSError("down")
        subs, err = h.load(ok, now=1000)
        self.assertEqual(len(subs), 3); self.assertEqual(err, "")
        h.load(ok, now=1500)
        self.assertEqual(len(calls), 1)                     # 1시간 안엔 다시 안 읽음
        subs, err = h.load(bad, now=1000 + h.CACHE_SEC + 1)
        self.assertEqual(len(subs), 3)                      # 홈페이지가 안 열려도 예전 내용으로
        self.assertIn("열지 못했습니다", err)


if __name__ == "__main__":
    unittest.main()
