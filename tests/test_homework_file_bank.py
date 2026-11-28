"""2026-11-28: 과제 파일 글 · 정답 · 해설을 문제 보관함 자료로 만들기."""
import io
import os
import unittest
import zipfile

import homework_file_bank as fb


def _zip(files: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for k, v in files.items():
            z.writestr(k, v)
    return buf.getvalue()


DOCX = _zip({"word/document.xml": (
    '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'
    '<w:p><w:r><w:t>[1~2] 다음 글을 읽고 물음에 답하시오.</w:t></w:r></w:p>'
    '<w:p><w:r><w:t>1. 윗글의 </w:t></w:r><w:r><w:t>내용으로 적절한 것은?</w:t></w:r></w:p>'
    '</w:body></w:document>')})
HWPX = _zip({"Contents/section0.xml": (
    '<hs:sec xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section" xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph">'
    '<hp:p><hp:run><hp:t>2. 밑줄 친 말의 뜻은?</hp:t></hp:run></hp:p></hs:sec>')})


class FileTextTests(unittest.TestCase):
    def test_docx(self):
        t = fb.file_text(DOCX, "과제.docx")
        self.assertIn("다음 글을 읽고", t)
        self.assertIn("1. 윗글의 내용으로 적절한 것은?", t)

    def test_hwpx(self):
        self.assertIn("밑줄 친 말의 뜻은?", fb.file_text(HWPX, "과제.HWPX"))

    def test_txt_cp949(self):
        self.assertEqual(fb.file_text("가나다".encode("cp949"), "a.txt"), "가나다")

    def test_pdf_uses_reader(self):
        self.assertEqual(fb.file_text(b"%PDF", "a.pdf", pdf_reader=lambda d: "PDF 글"), "PDF 글")

    def test_unknown_or_broken(self):
        self.assertEqual(fb.file_text(b"\x89PNG", "a.png"), "")
        self.assertEqual(fb.file_text(b"not zip", "a.docx"), "")
        self.assertEqual(fb.file_text(b"", "a.txt"), "")


class ContentTests(unittest.TestCase):
    def test_build_content_has_sections(self):
        c = fb.build_content("과제.docx", "1. 문제", ["3", "5", ""], {"1": "2문단 근거", "3": "어휘"})
        self.assertTrue(c.startswith("1. 문제"))
        self.assertIn("[정답 및 해설]\n1. 정답: ③\n2문단 근거", c)
        self.assertIn("3.\n어휘", c)
        self.assertIn("[정답표]\n1번 ③\n2번 ⑤", c)

    def test_no_text_note(self):
        c = fb.build_content("사진.jpg", "", ["1"], {})
        self.assertIn("글을 꺼내지 못했습니다", c)

    def test_parsed_back_by_bank_parser(self):
        # 출제 화면 자료와 같은 모양이라 보관함 파서가 정답을 다시 읽는다
        import ast, re
        src = open(os.path.join(os.path.dirname(__file__), "..", "main.py"), encoding="utf-8").read()
        ns = {"re": re}
        code = ""
        for n in ast.parse(src).body:
            if isinstance(n, ast.FunctionDef) and n.name == "parse_question_bank_content" or \
                    isinstance(n, ast.Assign) and any(getattr(t, "id", None) == "PROBLEM_NUM_RE" for t in n.targets):
                code += ast.get_source_segment(src, n) + "\n"
        exec(code, ns)
        parsed = ns["parse_question_bank_content"](fb.build_content("a.docx", "1. 문제 하나\n2. 문제 둘", ["3", "1"], {"2": "해설"}))
        self.assertEqual(parsed["answers"], {1: "③", 2: "①"})
        self.assertIn(1, parsed["problems"])
        self.assertIn(2, parsed["explanations"])

    def test_worth_saving(self):
        self.assertFalse(fb.worth_saving("", "", {}))
        self.assertTrue(fb.worth_saving("a.pdf", "", {}))
        self.assertTrue(fb.worth_saving("", "", {"1": "해설"}))


if __name__ == "__main__":
    unittest.main()
