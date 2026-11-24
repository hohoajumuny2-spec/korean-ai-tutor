"""클리닉 쌍둥이 문제: 세트 점검 · 틀린 문제의 쌍둥이만 고르기 · 채점 · 질문 번호 · 문제지 PDF."""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import clinic as cl  # noqa: E402


def _v(stem, ans):
    return {"stem": stem, "box": [], "choices": ["가", "나", "다", "라", "마"], "answer": ans}


# 화면(TwinSet.parse)이 보내는 모양 — '지문:' · '원 N번의 쌍둥이' · 'N-A.' 양식
BANK = {"title": "", "passages": [{"id": "p1", "title": "접근제어", "lead": "다음 글을 읽고 물음에 답하시오.", "text": "정보 시스템에 대한 '접근'이란…"}],
        "items": [{"no": 1, "twinOnly": True, "passage": "p1", "variants": [_v("윗글을 바탕으로 추론한 내용으로 가장 적절한 것은?", 3),
                                                                            _v("윗글을 바탕으로 추론한 내용으로 적절하지 않은 것은?", 5)]},
                  {"no": 2, "twinOnly": True, "passage": "p1", "variants": [{**_v("〈보기〉를 이해한 내용으로 적절한 것은?", 2), "box": ["어느 회사는…"]}]},
                  {"no": 3, "twinOnly": True, "passage": "p1", "variants": [_v("쌍둥이 3", 1)]}]}


def _sset():
    return {"questions": [{"no": n, "answer": "1"} for n in ("1", "2", "3", "4")], "twins": cl.clean_twins(json.dumps(BANK), "1단계")}


class TwinFlowTests(unittest.TestCase):
    def test_clean_fills_title_and_names_variants(self):
        tw = cl.clean_twins(json.dumps(BANK), "독서 클리닉")
        self.assertEqual(tw["title"], "독서 클리닉")
        self.assertEqual([v["vid"] for v in tw["items"][0]["variants"]], ["1-A", "1-B"])
        with self.assertRaises(ValueError):
            cl.clean_twins("이건 JSON 이 아니다")
        with self.assertRaises(ValueError):          # 선택지가 모자라면
            bad = json.loads(json.dumps(BANK)); bad["items"][0]["variants"][0]["choices"] = ["가"]
            cl.clean_twins(json.dumps(bad))

    def test_only_twins_of_first_wrong_questions_in_wrong_order(self):
        s = _sset()
        self.assertEqual(cl.twin_ids_for(s, ["3", "1"]), ["3-A", "1-A", "1-B"])
        self.assertEqual(cl.twin_ids_for(s, ["4"]), [])                 # 쌍둥이가 없는 문제
        self.assertEqual(cl.twin_ids_for({"questions": []}, ["1"]), [])  # 쌍둥이 세트가 없는 문제지

    def test_after_retry_goes_to_twin_or_old_flow(self):
        s = _sset()
        st = {"first": {"wrong": ["1", "4"]}, "second": {"fixed": ["1"], "still": ["4"]}}
        self.assertEqual(cl.after_retry(st, s), "twin")
        self.assertEqual(st["twin_ids"], ["1-A", "1-B"])
        old = {"first": {"wrong": ["4"]}, "second": {"fixed": [], "still": ["4"]}}
        self.assertEqual(cl.after_retry(old, s), "ask")
        self.assertEqual(cl.after_retry({"first": {"wrong": ["4"]}, "second": {"fixed": ["4"], "still": []}}, s), "next")

    def test_grade_twin_then_ask_numbers(self):
        s = _sset()
        st = {"first": {"wrong": ["1", "2", "4"]}, "second": {"fixed": ["1", "2"], "still": ["4"]}}
        cl.after_retry(st, s)
        self.assertEqual(st["twin_ids"], ["1-A", "1-B", "2-A"])
        nxt = cl.grade_twin(st, s, {"1-A": "3", "1-B": "1", "2-A": "2", "남의 번호": "1"})
        self.assertEqual(st["twin"]["wrong"], ["1-B"])
        self.assertEqual((st["twin"]["correct"], st["twin"]["total"]), (2, 3))
        self.assertEqual(nxt, "ask")
        self.assertEqual(cl.ask_nos(st), ["1", "4"])            # 쌍둥이를 틀린 1번 + 다시 풀어도 틀린 4번

    def test_all_twins_right_and_nothing_still_goes_next(self):
        s = _sset()
        st = {"first": {"wrong": ["3"]}, "second": {"fixed": ["3"], "still": []}}
        cl.after_retry(st, s)
        self.assertEqual(cl.grade_twin(st, s, {"3-A": "1"}), "next")
        self.assertEqual(cl.ask_nos(st), [])

    def test_twin_sheet_has_passage_and_only_chosen_questions_without_answers(self):
        s = _sset()
        run = {"student_name": "김로지", "sets": {"main": {"twin_ids": ["2-A", "1-B"]}}}
        prog = {"title": "독서 클리닉", "sets": {"main": s}}
        text = "\n".join(t for t, *_ in cl.twin_lines(run, prog, "main"))
        self.assertIn("정보 시스템에 대한", text)
        self.assertIn("2-A.", text); self.assertIn("1-B.", text); self.assertNotIn("1-A.", text)
        self.assertIn("〈보기〉 어느 회사는", text)
        self.assertNotIn("정답", text)
        pdf = cl.build_twin_pdf(run, prog, "main")
        self.assertTrue(pdf.startswith(b"%PDF"))

    def test_summary_mentions_twins(self):
        run = {"path": ["main"], "sets": {"main": {"first": {"score": 50, "wrong": ["1", "2"]}, "second": {"fixed": ["1", "2"], "still": []},
                                                   "twin": {"total": 3, "correct": 2, "wrong": ["1-B"]}, "asked": ["1"]}}}
        self.assertEqual(cl.summarize(run), "1단계 문제 50점(틀린 2문제 중 다시 풀어 2문제 해결, 쌍둥이 3문제 중 2문제 맞힘, 1문제 질문)")
        old = {"path": ["main"], "sets": {"main": {"first": {"score": 50, "wrong": ["1", "2"]}, "second": {"fixed": ["1"], "still": ["2"]}}}}
        self.assertEqual(cl.summarize(old), "1단계 문제 50점(틀린 2문제 중 다시 풀어 1문제 해결, 1문제 질문)")


if __name__ == "__main__":
    unittest.main()
