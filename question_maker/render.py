"""문제 세트를 시험지 모양 HTML로 만든다. 브라우저에서 인쇄(또는 PDF로 저장)하면 된다."""

import html
import re

from .catalog import DIFFICULTIES, KINDS

CIRCLED = "①②③④⑤⑥⑦"


def _esc(text: str) -> str:
    """HTML로 안전하게 바꾸되, 밑줄 <u>…</u>만은 살린다."""
    s = html.escape(text or "")
    s = s.replace("&lt;u&gt;", "<u>").replace("&lt;/u&gt;", "</u>")
    # 짝이 맞지 않는 밑줄이 있으면 뒤 내용 전체에 밑줄이 번지므로 닫아 준다
    opened = s.count("<u>") - s.count("</u>")
    if opened > 0:
        s += "</u>" * opened
    return s


def _multiline(text: str) -> str:
    return _esc(text).replace("\n", "<br>")


def _passage_html(text: str) -> str:
    paras = [p for p in re.split(r"\n\s*\n", (text or "").strip()) if p.strip()]
    out = []
    for p in paras:
        body = _multiline(p.strip())
        body = re.sub(r"\[([A-H])\]", r'<span class="seg">[\1]</span>', body)
        out.append(f"<p>{body}</p>")
    return "\n".join(out)


def answer_text(q: dict) -> str:
    if q["kind"] == "mcq":
        try:
            return CIRCLED[int(q["answer"]) - 1]
        except (ValueError, IndexError, TypeError):
            return str(q["answer"])
    if q["kind"] == "short" and q.get("accept"):
        return f"{q['answer']} (인정: {', '.join(q['accept'])})"
    return str(q["answer"])


def _question_html(q: dict, no: int) -> str:
    parts = [f'<div class="q"><div class="stem"><b>{no}.</b> {_multiline(q["stem"])}</div>']
    if q.get("box"):
        parts.append(f'<div class="box"><div class="box-label">&lt;보 기&gt;</div>{_multiline(q["box"])}</div>')
    if q["kind"] == "mcq":
        parts.append('<ol class="choices">' + "".join(
            f'<li><span class="cn">{CIRCLED[i]}</span> {_esc(c)}</li>' for i, c in enumerate(q["choices"])) + "</ol>")
    elif q["kind"] == "ox":
        parts.append('<div class="ox">( O / X )</div>')
    else:
        parts.append('<div class="write">답: <span class="line"></span></div>')
    parts.append("</div>")
    return "".join(parts)


def _explanation_html(q: dict, no: int) -> str:
    out = [f'<div class="ex"><b>{no}. 정답 {_esc(answer_text(q))}</b>'
           f' <span class="tag">{KINDS.get(q["kind"], "")} · {DIFFICULTIES.get(q["difficulty"], ("",))[0]}'
           f'{" · " + _esc(q["type"]) if q.get("type") else ""}</span>']
    if q.get("explanation"):
        out.append(f"<div>{_multiline(q['explanation'])}</div>")
    if q["kind"] == "mcq" and q.get("choice_notes"):
        out.append('<ul class="notes">' + "".join(
            f"<li>{CIRCLED[i]} {_esc(n)}</li>" for i, n in enumerate(q["choice_notes"])) + "</ul>")
    out.append("</div>")
    return "".join(out)


def render_paper(sets: list, style: dict, mode: str = "both") -> str:
    """sets: [{"title":..., "data": {...}}]  mode: paper | answers | both"""
    font = ("'Noto Serif KR', 'Batang', '바탕', serif" if style.get("font") == "serif"
            else "'Noto Sans KR', 'Malgun Gothic', '맑은 고딕', sans-serif")
    size = style.get("font_size", 10.5)
    cols = style.get("columns", 2)

    body_parts, ex_parts, table_cells = [], [], []
    no = 0
    for s in sets:
        data = s.get("data") or {}
        qs = data.get("questions") or []
        if not qs:
            continue
        first, last = no + 1, no + len(qs)
        head = f"[{first}~{last}] " if len(qs) > 1 else f"[{first}] "
        intro = data.get("intro") or "※ 다음 글을 읽고 물음에 답하시오."
        intro = re.sub(r"^※\s*", "", intro)
        block = [f'<div class="set"><div class="intro">{head}{_esc(intro)}</div>',
                 f'<div class="passage">{_passage_html(data.get("passage", ""))}']
        if data.get("source_note"):
            block.append(f'<div class="src">{_esc(data["source_note"])}</div>')
        block.append("</div>")
        for q in qs:
            no += 1
            block.append(_question_html(q, no))
            ex_parts.append(_explanation_html(q, no))
            table_cells.append(f"<td><b>{no}</b></td><td>{_esc(answer_text(q))}</td>")
        block.append("</div>")
        body_parts.append("".join(block))

    rows = []
    for i in range(0, len(table_cells), 5):
        rows.append("<tr>" + "".join(table_cells[i:i + 5]) + "</tr>")

    header = ""
    if mode in ("paper", "both"):
        name_box = ('<table class="namebox"><tr><th>반</th><td></td><th>번호</th><td></td><th>이름</th>'
                    '<td class="wide"></td></tr></table>') if style.get("show_name_box", True) else ""
        header = f"""<header>
  <div class="academy">{_esc(style.get('academy_name', ''))}</div>
  <h1>{_esc(style.get('paper_title') or '문제지')}</h1>
  <div class="sub">{_esc(style.get('paper_subtitle', ''))}</div>
  {name_box}
</header>"""

    paper = ""
    if mode in ("paper", "both"):
        paper = f'{header}<main class="cols">{"".join(body_parts)}</main>'
    answers = ""
    if mode in ("answers", "both"):
        answers = f"""<section class="answers{' newpage' if mode == 'both' else ''}">
  <h2>정답 및 해설 — {_esc(style.get('paper_title') or '')}</h2>
  <table class="atable">{''.join(rows)}</table>
  <div class="cols">{''.join(ex_parts)}</div>
</section>"""

    title = style.get("paper_title") or "문제지"
    return f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_esc(title)}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@400;700&family=Noto+Serif+KR:wght@400;700&display=swap" rel="stylesheet">
<style>
  @page {{ size: A4; margin: 14mm 12mm; }}
  * {{ box-sizing: border-box; }}
  body {{ font-family: {font}; font-size: {size}pt; line-height: 1.65; color: #111; background: #fff;
         max-width: 210mm; margin: 0 auto; padding: 12px; }}
  header {{ text-align: center; border-bottom: 2px solid #111; padding-bottom: 8px; margin-bottom: 12px; }}
  header h1 {{ font-size: 1.9em; margin: 2px 0; letter-spacing: 0.1em; }}
  .academy {{ font-size: 0.95em; color: #444; }}
  .sub {{ font-size: 1em; color: #333; }}
  .namebox {{ margin: 8px auto 0; border-collapse: collapse; }}
  .namebox th, .namebox td {{ border: 1px solid #333; padding: 3px 8px; font-size: 0.9em; }}
  .namebox td {{ width: 40px; }} .namebox td.wide {{ width: 110px; }}
  .cols {{ column-count: {cols}; column-gap: 9mm; column-rule: 1px solid #999; }}
  .set {{ margin-bottom: 14px; }}
  .intro {{ font-weight: 700; margin-bottom: 4px; }}
  .passage {{ border: 1px solid #333; padding: 8px 10px; margin-bottom: 10px; text-align: justify; }}
  .passage p {{ margin: 0 0 6px; }}
  .passage p:last-child {{ margin-bottom: 0; }}
  .seg {{ font-weight: 700; margin-right: 2px; }}
  .src {{ text-align: right; margin-top: 4px; font-size: 0.92em; }}
  .q {{ break-inside: avoid; margin: 0 0 14px; }}
  .stem {{ margin-bottom: 4px; }}
  .box {{ border: 1px solid #333; padding: 14px 10px 8px; margin: 10px 0 6px; position: relative; }}
  .box-label {{ position: absolute; top: -0.8em; left: 50%; transform: translateX(-50%); background: #fff;
               padding: 0 6px; font-weight: 700; }}
  .choices {{ list-style: none; padding: 0; margin: 0; }}
  .choices li {{ padding-left: 1.4em; text-indent: -1.4em; margin: 1px 0; }}
  .ox {{ text-align: right; letter-spacing: 0.1em; }}
  .write .line {{ display: inline-block; width: 70%; border-bottom: 1px solid #333; height: 1.2em; vertical-align: bottom; }}
  .answers h2 {{ font-size: 1.3em; border-bottom: 2px solid #111; padding-bottom: 4px; }}
  .newpage {{ break-before: page; }}
  .atable {{ border-collapse: collapse; margin: 6px 0 14px; }}
  .atable td {{ border: 1px solid #555; padding: 2px 10px; text-align: center; }}
  .ex {{ break-inside: avoid; margin-bottom: 10px; font-size: 0.95em; }}
  .ex .tag {{ color: #555; font-size: 0.85em; }}
  .notes {{ margin: 2px 0 0; padding-left: 0; list-style: none; }}
  .printbar {{ position: sticky; top: 0; background: #f4f4f4; border-bottom: 1px solid #ccc; padding: 8px;
              margin: -12px -12px 12px; text-align: center; font-family: sans-serif; font-size: 14px; }}
  .printbar button {{ font-size: 15px; padding: 6px 16px; cursor: pointer; }}
  @media print {{ .printbar {{ display: none; }} body {{ padding: 0; }} }}
  @media (max-width: 600px) {{ .cols {{ column-count: 1; }} body {{ padding: 8px 16px; }} }}
</style></head>
<body>
<div class="printbar"><button onclick="window.print()">인쇄 / PDF로 저장</button>
  <span style="margin-left:8px;color:#555">인쇄 창에서 '대상: PDF로 저장'을 고르면 PDF 파일이 됩니다.</span></div>
{paper}
{answers}
</body></html>"""
