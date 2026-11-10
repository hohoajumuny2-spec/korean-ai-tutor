import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import survey as sv  # noqa: E402


class SurveyTests(unittest.TestCase):
    def setUp(self):
        self.qs = sv.normalize_questions([
            {"kind": "single", "text": "방학 특강 들을 거예요?", "options": ["네", "아니요", "네"]},
            {"kind": "multi", "text": "듣고 싶은 과목", "options": ["문학", "문법", "독서"]},
            {"kind": "scale", "text": "수업 만족도"},
            {"kind": "text", "text": "하고 싶은 말", "required": False},
            {"kind": "single", "text": "보기가 하나뿐", "options": ["네"]},
            {"kind": "text", "text": "   "},
        ])

    def test_normalize(self):
        self.assertEqual([q["kind"] for q in self.qs], ["single", "multi", "scale", "text"])
        self.assertEqual(self.qs[0]["options"], ["네", "아니요"])
        self.assertEqual(len({q["id"] for q in self.qs}), 4)

    def test_clean_and_missing(self):
        ids = [q["id"] for q in self.qs]
        a = sv.clean_answers(self.qs, {ids[0]: 1, ids[1]: [2, 0, 9, "x"], ids[2]: 7, ids[3]: " 좋아요 "})
        self.assertEqual(a, {ids[0]: 1, ids[1]: [0, 2], ids[3]: "좋아요"})
        self.assertEqual(sv.missing_required(self.qs, a), [3])

    def test_summary(self):
        ids = [q["id"] for q in self.qs]
        rows = [{"student_name": "김하나", "answers": {ids[0]: 0, ids[1]: [0, 1], ids[2]: 5, ids[3]: "재밌어요"}},
                {"student_name": "박세나", "answers": {ids[0]: 0, ids[1]: [1], ids[2]: 3}}]
        s = sv.summary(self.qs, rows, ["김하나", "박세나", "이두리"])
        self.assertEqual(s["questions"][0]["counts"], [2, 0])
        self.assertEqual(s["questions"][1]["counts"], [1, 2, 0])
        self.assertEqual(s["questions"][1]["who"][1], ["김하나", "박세나"])
        self.assertEqual(s["questions"][2]["avg"], 4.0)
        self.assertEqual(s["questions"][3]["texts"], [{"name": "김하나", "text": "재밌어요"}])
        self.assertEqual(s["missing"], ["이두리"])
        anon = sv.summary(self.qs, rows, ["김하나"], anonymous=True)
        self.assertNotIn("who", anon["questions"][0])
        self.assertEqual(anon["questions"][3]["texts"][0]["name"], "")
        self.assertEqual(anon["answered"], [])


if __name__ == "__main__":
    unittest.main()
