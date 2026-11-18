"""오답 쌍둥이 클리닉 결과 점검."""
import unittest

import twin_clinic as tc

DOC = {"setId": "miggang2-final-24", "setTitle": "미강고 24제", "student": "김로지", "createdAt": "2026-11-18T09:12:33.000Z",
       "total": 24, "right": 17, "answers": [5, 4, 2] + [1] * 21, "wrong": [3, 8],
       "retry": [{"no": 3, "pick": 2, "correct": True, "reason": "〈보기〉 조건을 놓쳤어요", "extra": "x"}],
       "twins": [{"vid": "3-A", "no": 3, "pick": 4, "correct": True}], "ask": [3]}


class CleanTests(unittest.TestCase):
    def test_keeps_shape(self):
        d = tc.clean_result(DOC)
        self.assertEqual(d["right"], 17)
        self.assertEqual(d["wrong"], [3, 8])
        self.assertNotIn("extra", d["retry"][0])
        self.assertEqual(d["twins"][0]["vid"], "3-A")
        self.assertEqual(d["ask"], [3])

    def test_rejects_bad(self):
        for bad in (None, [], {**DOC, "student": ""}, {**DOC, "right": 30}, {**DOC, "total": "x"}):
            with self.assertRaises(ValueError):
                tc.clean_result(bad)

    def test_rejects_huge(self):
        with self.assertRaises(ValueError):
            tc.clean_result({**DOC, "setTitle": "가" * 70000})


if __name__ == "__main__":
    unittest.main()


def _q(ans=3, **kw):
    return {"stem": "물음", "choices": ["가", "나", "다", "라", "마"], "answer": ans, **kw}


class SetTests(unittest.TestCase):
    def test_good_set(self):
        b = tc.clean_set({"title": "11월 클리닉", "passages": [{"id": "p1", "text": "지문"}],
                          "items": [{"no": 2, "passage": "p1", **_q(), "variants": [_q(1), _q(5)]},
                                    {"no": 1, **_q(), "variants": [_q(2)]}]})
        self.assertEqual([i["no"] for i in b["items"]], [1, 2])
        self.assertEqual(b["items"][1]["variants"][1]["vid"], "2-B")
        self.assertEqual(b["items"][1]["variants"][0]["passage"], "p1")   # 유사 문제는 원래 지문을 따른다

    def test_needs_variants_and_answers(self):
        with self.assertRaisesRegex(ValueError, "유사 문제"):
            tc.clean_set({"title": "t", "items": [{"no": 1, **_q(), "variants": []}]})
        with self.assertRaisesRegex(ValueError, "정답"):
            tc.clean_set({"title": "t", "items": [{"no": 1, **_q(0), "variants": [_q()]}]})
        with self.assertRaisesRegex(ValueError, "제목"):
            tc.clean_set({"title": "", "items": []})
