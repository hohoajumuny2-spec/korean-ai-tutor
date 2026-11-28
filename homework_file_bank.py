"""과제에 올린 파일에서 글을 읽어 문제 보관함 자료로 만든다 (2026-11-28 원장님 요청).

과제를 올릴 때 붙인 파일(PDF · 워드 · 한글(hwpx) · 글 파일)의 글과, 함께 올린 정답표 · 문항별 해설을
'출제' 화면 자료와 같은 모양([정답 및 해설] · [정답표])으로 묶어 문제 보관함에 넣는다.
사진이나 예전 한글(.hwp)처럼 글을 꺼낼 수 없는 파일은 정답 · 해설만 담고 원본 파일 주소를 남긴다.
"""
import io
import re
import zipfile
from xml.etree import ElementTree as ET

ORIGIN = "homework_file"
TEXT_MAX = 60000
_CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩"


def _zip_xml_text(data: bytes, names, para_tag: str, text_tag: str) -> str:
    """워드(docx) · 한글(hwpx) 안의 XML에서 문단마다 글을 꺼낸다."""
    out = []
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for name in names(z.namelist()):
            try:
                root = ET.fromstring(z.read(name))
            except ET.ParseError:
                continue
            for p in root.iter():
                if p.tag.endswith(para_tag):
                    line = "".join(t.text or "" for t in p.iter() if t.tag.endswith(text_tag))
                    out.append(line)
    return "\n".join(out)


def file_text(data: bytes, filename: str, pdf_reader=None) -> str:
    """파일에서 글을 꺼낸다. 못 꺼내면 ''.  pdf_reader(data) -> str 은 PDF 를 읽는 함수(서버에서 PyMuPDF)."""
    if not data:
        return ""
    ext = (re.search(r"\.([A-Za-z0-9]+)$", filename or "") or [None, ""])[1].lower()
    text = ""
    try:
        if ext == "pdf" and pdf_reader:
            text = pdf_reader(data) or ""
        elif ext == "docx":
            text = _zip_xml_text(data, lambda ns: [n for n in ns if n == "word/document.xml"], "}p", "}t")
        elif ext == "hwpx":
            text = _zip_xml_text(data, lambda ns: sorted(n for n in ns if re.match(r"Contents/section\d+\.xml$", n)),
                                 "}p", "}t")
        elif ext in ("txt", "md"):
            for enc in ("utf-8-sig", "cp949", "utf-16"):
                try:
                    text = data.decode(enc)
                    break
                except UnicodeDecodeError:
                    continue
    except (zipfile.BadZipFile, KeyError, ValueError):
        text = ""
    text = re.sub(r"[ \t ]+\n", "\n", text or "")
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text[:TEXT_MAX]


def _answer_label(v) -> str:
    s = str(v if v is not None else "").strip()
    if re.fullmatch(r"\d", s) and 1 <= int(s) <= len(_CIRCLED):
        return _CIRCLED[int(s) - 1]
    return s


def build_content(file_name: str, text: str, answer_list, explanations) -> str:
    """보관함 글: 파일 글 → [정답 및 해설] → [정답표] (출제 화면 자료와 같은 모양이라 그대로 다시 쓸 수 있다)."""
    expl = {str(k): str(v or "").strip() for k, v in (explanations or {}).items() if str(v or "").strip()}
    answers = [_answer_label(a) for a in (answer_list or [])]
    parts = []
    if text:
        parts.append(text)
    else:
        parts.append(f"(과제 파일 '{file_name}'에서 글을 꺼내지 못했습니다 — 사진 · 예전 한글 파일이면 원본 파일을 열어 보세요.)"
                     if file_name else "(문제 글 없이 정답 · 해설만 올린 과제입니다.)")
    nums = sorted({int(k) for k in expl if k.isdigit()} | {i + 1 for i, a in enumerate(answers) if a})
    if nums:
        lines = []
        for n in nums:
            a = answers[n - 1] if n - 1 < len(answers) else ""
            head = f"{n}. 정답: {a}" if a else f"{n}."
            lines.append(head + (f"\n{expl[str(n)]}" if expl.get(str(n)) else ""))
        parts.append("[정답 및 해설]\n" + "\n\n".join(lines))
    if any(answers):
        parts.append("[정답표]\n" + "\n".join(f"{i + 1}번 {a}" for i, a in enumerate(answers) if a))
    return "\n\n".join(parts).strip()


def worth_saving(file_name: str, text: str, explanations) -> bool:
    """정답표만 있고 파일도 해설도 없으면 보관함에 넣을 것이 없다."""
    return bool(file_name or text or any(str(v or "").strip() for v in (explanations or {}).values()))
