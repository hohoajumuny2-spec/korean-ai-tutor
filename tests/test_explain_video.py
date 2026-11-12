"""해설 영상: 줄 나누기 · 선지 찾기 · Gemini 음성 · 영상 만들기."""
import base64
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import explain_video as ev  # noqa: E402


def fake_tts(text):
    """글자 수에 비례하는 길이의 조용한 소리 (네트워크 없이 시험)."""
    return ev._silence(0.05 * len(text) + 0.2)


class WrapTests(unittest.TestCase):
    def test_positions_point_back_into_text(self):
        text = "조선 후기에는 상품 화폐 경제가 발달하면서 사회 구조에 큰 변화가 나타났다.\n둘째 줄입니다."
        lines = ev.wrap(text, ev.font(46), 400)
        self.assertGreater(len(lines), 2)
        for line, start in lines:
            self.assertEqual(text[start:start + len(line)], line)
            self.assertLessEqual(ev.font(46).getlength(line), 400)

    def test_long_word_is_split_by_char(self):
        lines = ev.wrap("가" * 60, ev.font(46), 300)
        self.assertGreater(len(lines), 1)
        self.assertEqual("".join(l for l, _ in lines), "가" * 60)


class OptionRefTests(unittest.TestCase):
    def test_refs(self):
        self.assertEqual(ev.option_refs("정답은 ③번입니다."), [3])
        self.assertEqual(ev.option_refs("2번 선지와 ⑤는 틀렸어요."), [2, 5])
        self.assertEqual(ev.option_refs("3번 문항 해설입니다."), [])
        self.assertEqual(ev.option_refs("12번은 아니에요"), [])

    def test_speech_text(self):
        self.assertEqual(ev.speech_text("정답은 ③입니다. **중요**"), "정답은 3번 입니다. 중요")


class GeminiTTSTests(unittest.TestCase):
    def _resp(self, status, payload=None, text=""):
        r = mock.Mock()
        r.status_code = status
        r.text = text
        r.json.return_value = payload or {}
        return r

    def test_parse_audio(self):
        pcm = b"\x01\x00" * 100
        data = {"candidates": [{"content": {"parts": [{"inlineData": {
            "mimeType": "audio/L16;codec=pcm;rate=24000", "data": base64.b64encode(pcm).decode()}}]}}]}
        self.assertEqual(ev.pcm_from_gemini_response(data), pcm)
        self.assertEqual(ev.pcm_from_gemini_response({"candidates": []}), b"")

    def test_next_model_when_not_found(self):
        pcm = b"\x02\x00" * 10
        ok = {"candidates": [{"content": {"parts": [{"inlineData": {"data": base64.b64encode(pcm).decode()}}]}}]}
        calls = []

        def post(url, **kw):
            calls.append(url)
            self.assertEqual(kw["headers"]["x-goog-api-key"], "k")
            return self._resp(404) if len(calls) == 1 else self._resp(200, ok)

        with mock.patch.dict(os.environ, {"GOOGLE_API_KEY": "k", "VIDEO_TTS_MODEL": "a-tts,b-tts"}), \
                mock.patch.object(ev.requests, "post", side_effect=post):
            self.assertEqual(ev.gemini_tts("안녕"), pcm)
        self.assertIn("a-tts", calls[0])
        self.assertIn("b-tts", calls[1])

    def test_falls_back_to_gtts_for_every_line(self):
        env = {k: v for k, v in os.environ.items() if k not in ("GOOGLE_API_KEY", "GEMINI_API_KEY")}
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.object(ev, "gtts_tts", side_effect=lambda t: b"\x00\x00" * 5) as g:
            pcms, voice = ev._voice_all(["하나", "둘"])
        self.assertEqual(voice, "gtts")
        self.assertEqual(len(pcms), 2)
        self.assertEqual(g.call_count, 2)


class RenderTests(unittest.TestCase):
    def test_question_video(self):
        passage = "앞 문장이다. 근거가 되는 문장이다. 뒤 문장이다."
        quote = "근거가 되는 문장이다."
        i = passage.find(quote)
        opts = ["① 하나", "② 둘", "③ 셋", "④ 넷", "⑤ 다섯"]
        r = ev.render_question_video(1, passage, (i, i + len(quote)), "1. 맞는 것은?", opts, 2,
                                     {"1": "틀림"}, ["근거를 봐요."], ["정답은 ②번.", "①은 틀렸어요."],
                                     tts=fake_tts)
        self.assertEqual(r.video[4:8], b"ftyp")
        self.assertEqual(r.voice, "custom")
        self.assertGreater(r.seconds, 3)

    def test_option_reveal_follows_narration(self):
        sc = ev.OptionsScene(["정답은 ②번.", "④는 반대예요."], "", ["① a", "② b", "③ c", "④ d", "⑤ e"], 2, {})
        sc.setup([(0.0, 1.0), (1.3, 1.0)], 2.6)
        self.assertAlmostEqual(sc.reveal[2], 0.2)
        self.assertAlmostEqual(sc.reveal[4], 1.5)
        self.assertEqual(set(sc.reveal), {1, 2, 3, 4, 5})

    def test_caption_video(self):
        r = ev.render_caption_video(["첫 문장입니다.", "둘째 문장입니다."], title="제목", tts=fake_tts)
        self.assertEqual(r.video[4:8], b"ftyp")


if __name__ == "__main__":
    unittest.main()
