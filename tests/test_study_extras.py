import unittest
from datetime import date

import study_extras as se


class MetaTests(unittest.TestCase):
    def test_parse_and_clean(self):
        m = se.parse_meta_map({"1": {"tag": "  추론 ", "summary": "요약", "video": "youtu.be/abcdefghijk"},
                               "x": {"tag": "버림"}, "2": {"tag": ""}, "0": {"tag": "버림"}})
        self.assertEqual(m, {"1": {"tag": "추론", "summary": "요약", "video": "https://youtu.be/abcdefghijk"}})

    def test_video_rejects_scripts(self):
        self.assertEqual(se.clean_video("javascript:alert(1)"), "")
        self.assertEqual(se.youtube_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=3"), "dQw4w9WgXcQ")

    def test_merge_only_sent_fields(self):
        old = {"1": {"tag": "추론", "summary": "옛 요약"}, "2": {"tag": "어휘"}}
        new = se.merge_meta(old, {"1": {"summary": ""}, "3": {"tag": "비판", "video": "https://x.com/v.mp4"}})
        self.assertEqual(new, {"1": {"tag": "추론"}, "2": {"tag": "어휘"},
                               "3": {"tag": "비판", "video": "https://x.com/v.mp4"}})
        self.assertEqual(se.merge_meta(old, {"2": {"tag": ""}}), {"1": old["1"]})


class ReasonTests(unittest.TestCase):
    def test_feedback_differs(self):
        a, b, c = (se.reason_feedback(r, "추론") for r in ("guess", "two", "misread"))
        self.assertNotEqual(a["title"], b["title"])
        self.assertIn("추론", " ".join(a["tips"]))
        self.assertEqual(c["practice"], "적게")
        self.assertEqual(se.reason_feedback("x")["tips"], [])


class WeakTagTests(unittest.TestCase):
    def test_reason_weights_and_decay(self):
        today = date(2026, 10, 27)
        misses = [{"tag": "추론", "reason": "guess", "at": "2026-10-26"},
                  {"tag": "어휘", "reason": "misread", "at": "2026-10-26"},
                  {"tag": "비판", "at": "2026-08-01"}]
        w = se.weak_tags(misses, today=today)
        self.assertEqual([x["tag"] for x in w][0], "추론")
        self.assertEqual(w[0]["reasons"], {"guess": 1})
        self.assertLess(next(x for x in w if x["tag"] == "비판")["score"], 0.5)

    def test_practice_success_lowers_weight(self):
        today = date(2026, 10, 27)
        misses = [{"tag": "추론", "reason": "two", "at": "2026-10-27"}]
        self.assertEqual(se.weak_tags(misses, {"추론": {"right": 5, "wrong": 0}}, today), [])


class PickTests(unittest.TestCase):
    def setUp(self):
        self.pool = [{"qid": f"a#{i}", "tag": "추론"} for i in range(5)] + \
                    [{"qid": f"b#{i}", "tag": "어휘"} for i in range(5)]
        self.weak = [{"tag": "추론", "score": 3}, {"tag": "어휘", "score": 1}]

    def test_round_robin_and_count(self):
        got = se.pick_daily(self.weak, self.pool, 3, seed="s")
        self.assertEqual([g["tag"] for g in got], ["추론", "어휘", "추론"])
        self.assertEqual(len({g["qid"] for g in got}), 3)

    def test_same_day_same_set(self):
        self.assertEqual(se.pick_daily(self.weak, self.pool, 3, "kim|2026-10-27"),
                         se.pick_daily(self.weak, self.pool, 3, "kim|2026-10-27"))

    def test_prefers_unsolved(self):
        right = [f"a#{i}" for i in range(4)]
        got = se.pick_daily([{"tag": "추론", "score": 1}], self.pool, 1, "s", solved_right=right)
        self.assertEqual(got[0]["qid"], "a#4")

    def test_empty(self):
        self.assertEqual(se.pick_daily([], self.pool, 3, "s"), [])
        self.assertEqual(se.pick_daily(self.weak, [], 3, "s"), [])
        self.assertEqual(len(se.pick_daily(self.weak, self.pool, 99, "s")), se.DAILY_MAX)


if __name__ == "__main__":
    unittest.main()
