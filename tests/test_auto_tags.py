"""유형 자동 붙이기: AI에게 보낼 글과 AI 답 읽기."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import study_extras as s  # noqa: E402

ALLOWED = ["사실적 이해", "추론", "어휘·문맥", "문법-음운"]


class ParseTagReplyTests(unittest.TestCase):
    def test_plain_json(self):
        self.assertEqual(s.parse_tag_reply('{"1": "추론", "2": "사실적 이해"}', ALLOWED, [1, 2]),
                         {"1": "추론", "2": "사실적 이해"})

    def test_code_fence_and_loose_names(self):
        text = "```json\n{\"1\": \"어휘 문맥\", \"2\": \"문법 - 음운\"}\n```"
        self.assertEqual(s.parse_tag_reply(text, ALLOWED, [1, 2]), {"1": "어휘·문맥", "2": "문법-음운"})

    def test_unknown_names_and_numbers_dropped(self):
        text = '{"1": "새로운 유형", "2": "", "9": "추론", "3번": "추론"}'
        self.assertEqual(s.parse_tag_reply(text, ALLOWED, [1, 2, 3]), {"3": "추론"})

    def test_broken_json_still_read(self):
        text = '{"1": "추론", "2": "사실적 이해",}'
        self.assertEqual(s.parse_tag_reply(text, ALLOWED, [1, 2]), {"1": "추론", "2": "사실적 이해"})

    def test_no_json(self):
        self.assertEqual(s.parse_tag_reply("잘 모르겠습니다", ALLOWED, [1]), {})


class TagPromptTests(unittest.TestCase):
    def test_prompt_has_list_and_items(self):
        p = s.tag_prompt("국어", ALLOWED, [
            {"no": 1, "text": "윗글의 내용과 일치하는 것은?", "options": ["가", "나"], "answer": "2", "explanation": "2문단 근거"},
            {"no": 2, "text": "", "options": [], "answer": "", "explanation": "문맥상 '드러내다'"},
        ], has_file=True)
        for want in ("- 추론", "[1번]", "보기: 1) 가 / 2) 나", "해설: 문맥상", "[2번]", "첨부한 그림"):
            self.assertIn(want, p)
        self.assertNotIn("문제: \n", p)


if __name__ == "__main__":
    unittest.main()
