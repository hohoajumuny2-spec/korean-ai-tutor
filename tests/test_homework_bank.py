"""과제 · 클리닉 문제를 문제 보관함에 잇는 계산 점검."""
import unittest
from datetime import datetime, timedelta

import homework_bank as hb

NOW = datetime(2026, 11, 22, 15, 0, 0)
FMT = "%Y-%m-%d %H:%M:%S"
EXPL = {"1": "2문단에서 기술의 한계를 말하므로 ③이 맞다.", "2": "글쓴이는 대조를 통해 주장을 펼친다."}


def ago(hours):
    return (NOW - timedelta(hours=hours)).strftime(FMT)


class KeyTitleTests(unittest.TestCase):
    def test_key_ignores_spacing(self):
        self.assertEqual(hb.content_key("가 나\n\n다"), hb.content_key(" 가  나 다 "))
        self.assertNotEqual(hb.content_key("가나다"), hb.content_key("가나라"))

    def test_title_skips_guide_lines(self):
        text = "※ 다음 글을 읽고 물음에 답하시오.\n[지문]\n기술 발전과 인간의 노동\n본문..."
        self.assertEqual(hb.guess_title(text, NOW), "기술 발전과 인간의 노동")

    def test_title_fallback(self):
        self.assertTrue(hb.guess_title("", NOW).startswith("과제 붙여넣기"))


class MatchTests(unittest.TestCase):
    def setUp(self):
        self.fp = hb.fingerprint([3, 5, ""], EXPL)

    def test_same_homework_matches(self):
        self.assertGreater(hb.match_score(self.fp, ["③", "5", "기술"], EXPL), 0.9)

    def test_different_length_never_matches(self):
        self.assertEqual(hb.match_score(self.fp, ["3", "5"], EXPL), 0.0)

    def test_different_explanations_reject(self):
        other = {"1": "전혀 다른 해설", "2": "이것도 다른 해설"}
        self.assertEqual(hb.match_score(self.fp, ["3", "5", "x"], other), 0.0)

    def test_answers_only_need_most_to_agree(self):
        fp = hb.fingerprint(["1", "2", "3", "4", "5"], {})
        self.assertGreater(hb.match_score(fp, ["1", "2", "3", "4", "5"], {}), 0)
        self.assertEqual(hb.match_score(fp, ["1", "2", "4", "3", "5"], {}), 0.0)

    def test_pick_newest_fresh_match(self):
        rows = [
            {"id": "old", "pending_at": ago(10), "fp": self.fp},       # 너무 오래됨
            {"id": "a", "pending_at": ago(2), "fp": self.fp},
            {"id": "b", "pending_at": ago(1), "fp": self.fp},          # 같은 점수면 더 최근
            {"id": "x", "pending_at": ago(0.5), "fp": hb.fingerprint([1, 1, 1], {})},
        ]
        self.assertEqual(hb.pick_pending(rows, ["3", "5", "기술"], EXPL, NOW), "b")

    def test_pick_none(self):
        self.assertEqual(hb.pick_pending([], ["3"], {}, NOW), "")
        self.assertEqual(hb.pick_pending([{"id": "a", "pending_at": "엉뚱", "fp": self.fp}], ["3", "5", ""], EXPL, NOW), "")


class LinkTests(unittest.TestCase):
    def test_link_accumulates_homeworks(self):
        prev = {"homework_titles": ["11월 3주 과제"], "target_classes": ["고1A"], "tags": ["추론"]}
        f = hb.link_fields(prev, "11월 3주 클리닉", "클리닉 과제", ["고1B"], "korean", ["추론", "적용"], NOW)
        self.assertEqual(f["homework_titles"], ["11월 3주 과제", "11월 3주 클리닉"])
        self.assertEqual(f["target_classes"], ["고1A", "고1B"])
        self.assertEqual(f["tags"], ["추론", "적용"])
        self.assertFalse(f["pending_link"])
        self.assertEqual(f["title"], "[클리닉 과제] 11월 3주 클리닉")

    def test_renamed_homework_replaces_old_title(self):
        f = hb.link_fields({"homework_titles": ["예전 제목"]}, "새 제목", "수업 과제", [], "korean", [], NOW,
                           old_title="예전 제목")
        self.assertEqual(f["homework_titles"], ["새 제목"])

    def test_tags_from_qmeta(self):
        self.assertEqual(hb.tags_from_qmeta({"1": {"tag": "추론"}, "2": {"tag": "추론"}, "3": {"summary": "x"}}),
                         ["추론"])


if __name__ == "__main__":
    unittest.main()
