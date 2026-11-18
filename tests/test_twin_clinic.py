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
