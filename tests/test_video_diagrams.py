"""해설 영상 도표: AI 설계도 정리 · 항목이 나타나는 때 · 장면 그리기."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import explain_video as ev  # noqa: E402
import video_diagrams as vd  # noqa: E402


def fake_tts(text):
    return ev._silence(0.04 * len(text) + 0.2)


class ParseTests(unittest.TestCase):
    def test_fenced_reply_with_trailing_comma(self):
        raw = '설계도입니다.\n```json\n{"scenes": [{"type": "title", "title": "진달래꽃", "lines": ["시작해요."]},' \
              ' {"type": "list", "heading": "포인트", "items": ["반어", "율격",], "lines": ["둘이에요."]},]}\n```'
        sb = vd.parse_storyboard(raw)
        self.assertEqual([s["type"] for s in sb], ["title", "list"])
        self.assertEqual(sb[1]["items"], ["반어", "율격"])

    def test_bad_scenes_dropped_or_downgraded(self):
        sb = vd.parse_storyboard({"scenes": [
            {"type": "relation", "nodes": ["화자", "임"], "edges": [{"from": "화자", "to": "없는사람"}], "lines": ["a"]},
            {"type": "timeline", "events": [{"label": "1", "text": "하나"}], "lines": ["b"]},   # 하나뿐 → 버림
            {"type": "chart3d", "lines": ["모르는 모양은 문장 장면으로"]},
            {"type": "quote", "text": "원문이다", "highlight": "원문에 없는 말", "lines": ["c"]},
            {"type": "keyword", "keyword": "반어"},                                          # 문장 없음 → 글자를 읽음
            "장면 사이 문장은 문장 장면으로",
            "이어진 문장은 같은 장면에",
            42,
        ]})
        self.assertEqual([s["type"] for s in sb], ["caption", "quote", "keyword", "caption"])
        self.assertEqual(sb[3]["lines"], ["장면 사이 문장은 문장 장면으로", "이어진 문장은 같은 장면에"])
        self.assertEqual(sb[1]["highlight"], "")
        self.assertEqual(sb[2]["lines"], ["반어"])

    def test_old_sentence_list_and_line_cap(self):
        sb = vd.parse_storyboard(["첫 문장.", "둘째 문장.", "셋째 문장."], max_lines=2)
        self.assertEqual(sb, [{"type": "caption", "lines": ["첫 문장.", "둘째 문장."]}])

    def test_markup_stripped_and_clipped(self):
        sc = vd.clean_scene({"type": "title", "title": "**" + "가" * 40 + "**", "lines": ["# 안녕"]})
        self.assertLessEqual(len(sc["title"]), 24)
        self.assertNotIn("*", sc["title"])
        self.assertEqual(sc["lines"], ["안녕"])

    def test_garbage(self):
        self.assertEqual(vd.parse_storyboard("모르겠습니다"), [])
        self.assertEqual(vd.parse_storyboard(None), [])


class AlignTests(unittest.TestCase):
    def test_matches_by_words(self):
        items = ["반어적 표현", "7·5조 3음보 율격", "수미상관 구조"]
        lines = ["시험에는 세 가지가 나와요.", "첫째, 반어적 표현.", "둘째, 3음보 율격.", "셋째, 수미상관 구조."]
        self.assertEqual(vd.align_items(items, lines), [1, 2, 3])

    def test_no_match_aligns_to_end_and_never_goes_back(self):
        self.assertEqual(vd.align_items(["ㄱ", "ㄴ"], ["도입", "가", "나"]), [1, 2])
        self.assertEqual(vd.align_items(["ㄱ", "ㄴ", "ㄷ"], ["하나"]), [0, 0, 0])
        got = vd.align_items(["수미상관 구조", "반어적 표현"], ["수미상관 구조예요", "반어적 표현이죠"])
        self.assertEqual(got, [0, 1])


class RenderTests(unittest.TestCase):
    def test_every_kind_renders(self):
        sb = vd.parse_storyboard({"scenes": [
            {"type": "title", "title": "진달래꽃", "subtitle": "반어", "lines": ["시작."]},
            {"type": "quote", "source": "1연", "text": "말없이 고이 보내 드리우리다", "highlight": "고이", "lines": ["봐요."]},
            {"type": "keyword", "keyword": "반어", "desc": "반대로 말하기", "lines": ["반어.", "뜻."]},
            {"type": "list", "heading": "포인트", "items": ["하나", "둘"], "lines": ["하나.", "둘."]},
            {"type": "timeline", "heading": "흐름", "events": [{"label": "1연", "text": "가정"}, {"label": "4연", "text": "다짐"}],
             "lines": ["가정.", "다짐."]},
            {"type": "compare", "heading": "비교", "left": {"title": "겉", "points": ["보내리"]},
             "right": {"title": "속", "points": ["가지 마"]}, "lines": ["겉.", "속."]},
            {"type": "relation", "heading": "관계", "nodes": ["화자", "임", "꽃"],
             "edges": [{"from": "임", "to": "화자", "label": "떠남"}], "lines": ["떠나요."]},
            {"type": "caption", "lines": ["끝."]},
        ]})
        self.assertEqual(len(sb), 8)
        r = vd.render_storyboard_video(sb, title="진달래꽃", tts=fake_tts)
        self.assertEqual(r.video[4:8], b"ftyp")

    def test_reveal_times_follow_lines(self):
        sc = vd.build_scene(vd.clean_scene({"type": "list", "items": ["반어적 표현", "수미상관 구조"],
                                            "lines": ["두 가지예요.", "반어적 표현.", "수미상관 구조."]}))
        sc.setup([(0.0, 1.0), (1.3, 1.0), (2.6, 1.0)], 3.9)
        self.assertAlmostEqual(sc.reveal[0], 1.45)
        self.assertAlmostEqual(sc.reveal[1], 2.75)
        self.assertEqual(sc.state(1.0)[:2], (-1, -1))
        self.assertGreaterEqual(sc.state(3.5)[1], 0)

    def test_list_uses_option_numbers(self):
        sc = vd.ListScene(["a"], "오답", ["① 반대", "⑤ 하나"])
        self.assertEqual(sc.nums, ["1", "5"])
        self.assertEqual(sc.items, ["반대", "하나"])
        sc = vd.ListScene(["a"], "포인트", ["반어", "② 율격"])
        self.assertEqual(sc.nums, ["1", "2"])
        self.assertEqual(sc.items, ["반어", "② 율격"])

    def test_question_video_with_diagram(self):
        diagram = vd.build_scene(vd.clean_scene({"type": "compare", "left": {"title": "A", "points": ["a"]},
                                                 "right": {"title": "B", "points": ["b"]}, "lines": ["비교."]}))
        r = ev.render_question_video(2, "근거 문장이다.", (0, 7), "", [], 0, {}, ["근거."], ["설명."],
                                     extra_scenes=[diagram], tts=fake_tts)
        self.assertEqual(r.video[4:8], b"ftyp")


if __name__ == "__main__":
    unittest.main()
