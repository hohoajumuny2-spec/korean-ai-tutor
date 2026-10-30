"""해설지 읽기: AI 답 정리와 지시문."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import study_extras as s  # noqa: E402


class ParseExplainReplyTests(unittest.TestCase):
    def test_full_items(self):
        text = '```json\n{"items": {"1": {"answer": "③", "detail": "2문단에서\\n확인된다.", "summary": "2문단 근거", "tag": "추론"},' \
               ' "2번": {"detail": "", "summary": "", "tag": "어휘"}}}\n```'
        got = s.parse_explain_reply(text)
        self.assertEqual(got["1"], {"detail": "2문단에서\n확인된다.", "summary": "2문단 근거", "tag": "추론", "answer": 3})
        self.assertEqual(got["2"], {"detail": "", "summary": "", "tag": "어휘"})

    def test_list_form_trailing_comma_and_empty_dropped(self):
        text = '{"items": [{"no": 4, "explanation": "④가 답", "summary": "", "tag": ""}, {"no": 5, "detail": "", "summary": "", "tag": ""},]}'
        self.assertEqual(s.parse_explain_reply(text), {"4": {"detail": "④가 답", "summary": "", "tag": ""}})

    def test_long_text_clipped_and_bad_answer_dropped(self):
        got = s.parse_explain_reply('{"items": {"7": {"detail": "%s", "summary": "요약", "answer": 9}}}' % ("가" * 2500))
        self.assertTrue(got["7"]["detail"].endswith("…"))
        self.assertLessEqual(len(got["7"]["detail"]), 2001)
        self.assertNotIn("answer", got["7"])

    def test_no_json(self):
        self.assertEqual(s.parse_explain_reply("읽을 수 없습니다"), {})
        self.assertEqual(s.parse_explain_reply(""), {})


class ExplainPromptTests(unittest.TestCase):
    def test_known_tags_listed_once(self):
        p = s.explain_prompt("추론, 어휘\n추론")
        self.assertIn("그중에서 고르세요: 추론, 어휘", p)
        self.assertNotIn("{tags}", p)

    def test_no_tags(self):
        self.assertIn("모르면 빈 글자", s.explain_prompt(""))


if __name__ == "__main__":
    unittest.main()
