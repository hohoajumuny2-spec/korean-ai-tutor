"""AI(구글 Gemini)와 이야기하는 부분.

키가 없을 때 화면을 둘러볼 수 있도록 '연습용 AI'(FakeAI)도 함께 둔다.
연습용 AI는 지문을 읽지 않고 틀만 갖춘 가짜 문제를 만든다.
"""

import json
import os
import re
import threading

QUALITY_MODELS = ["gemini-3.1-pro-preview", "gemini-2.5-pro", "gemini-1.5-pro-latest", "gemini-1.5-pro"]
FAST_MODELS = ["gemini-3.6-flash", "gemini-2.5-flash", "gemini-1.5-flash"]


# ── 기존 시험지 불러오기 (2026-11-10) ───────────────────────
# 시험지 PDF · 사진을 읽어 '문제지 만들기'의 글 모양으로 옮겨 적게 한다.
# 문제지 만들기는 이 글을 그대로 읽어 자동으로 편집(2단 · 번호 · 선택지 · 정답 모아 보기)한다.
EXAM_IMPORT_PROMPT = """첨부한 시험지(문제지)를 읽고, 아래 '글 모양'에 맞춰 처음부터 끝까지 옮겨 적으세요.
요약하거나 고치거나 새로 만들지 말고, 시험지에 있는 글자 그대로 옮기세요.

[읽는 순서]
- 2단으로 된 쪽은 왼쪽 단을 위에서 아래로 다 읽은 뒤 오른쪽 단을 읽습니다.
- 머리말 · 꼬리말 · 쪽 번호 · 로고 · 교재 코드(예: 1410-141-…) · 저작권 안내는 옮기지 않습니다.

[글 모양]
1) 여러 문제가 함께 보는 글(지문)은 이렇게 적습니다. 범위는 그 지문을 보는 문제 번호입니다.
[1~2] 다음 글을 읽고 물음에 답하시오.
[지문]
(지문 글을 문단 그대로. 문단 사이는 빈 줄 하나)
[/지문]
   - 한 문제만 보는 지문이면 [3~3] 처럼 적습니다.
   - 같은 지문이 시험지에 여러 번 나오면, 나온 대로 다시 적습니다.
   - 지문 옆에 [A] · [B] 같은 표시가 붙은 부분은 그 부분 맨 앞에 [A] 를 적습니다.
2) 문제는 번호와 점을 찍고 한 줄로 시작합니다.  예) 3. [A]를 이해한 내용으로 가장 적절한 것은?
3) 선택지는 한 줄에 하나씩 ① ② ③ ④ ⑤ 로 시작합니다. (원문에 동그라미 숫자가 안 보여도 차례대로 붙이세요)
4) 문제 안의 <보기> 상자는
<보기>
(보기 글)
[/보기]
5) 정답 · 해설이 시험지 어딘가(보통 뒤쪽 '정답 및 해설')에 있으면 각 문제 바로 아래에 붙입니다.
정답: 3
해설: (그 문제의 해설 글. '오답 point' · '오답 파헤치기'처럼 나뉘어 있으면 한 문단으로 이어 적어도 됩니다)
   정답 · 해설이 없으면 이 두 줄은 적지 않습니다. 정답 및 해설 쪽 자체는 따로 옮기지 않습니다.
6) 밑줄 친 글은 __밑줄__, 굵은 글은 **굵게** 로 감쌉니다. ㉠ ⓐ (가) 같은 표시와 한자는 그대로 둡니다.
7) 서술형 · 단답형 문제는 '서술형 1.' 처럼 적고 그 뒤에 문제 글을 적습니다.

옮긴 글 말고 다른 말(설명 · 인사 · ``` 표시)은 쓰지 마세요."""


class AIError(Exception):
    pass


def parse_json_text(text: str):
    """AI 답에서 JSON을 꺼낸다. ```json 울타리나 앞뒤 군말이 붙어 와도 읽는다."""
    raw = (text or "").strip()
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw)
    try:
        return json.loads(raw)
    except ValueError:
        pass
    start, end = raw.find("{"), raw.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(raw[start:end + 1])
        except ValueError:
            pass
    raise AIError("AI 답을 읽지 못했습니다(형식이 깨짐). 한 번 더 시도해주세요.")


def friendly_error(err) -> str:
    raw = str(err or "").strip()
    low = raw.lower()
    if "credit" in low or "billing" in low:
        head = "AI 사용 크레딧이 떨어졌습니다. Google AI Studio에서 충전하거나 결제 수단을 연결해주세요."
    elif "quota" in low or "resource_exhausted" in low or low.startswith("429"):
        head = "AI 사용 한도를 넘었습니다. 잠시 뒤 다시 시도해주세요."
    elif "api key" in low or "api_key" in low or "permission" in low or "unauthenticated" in low:
        head = "AI 열쇠(API 키)가 없거나 잘못됐습니다. GOOGLE_API_KEY를 확인해주세요."
    elif "deadline" in low or "timeout" in low or "timed out" in low:
        head = "AI 응답이 제한 시간을 넘겼습니다. 지문을 조금 줄이거나 문항 수를 줄여 다시 시도해주세요."
    elif "safety" in low or "blocked" in low:
        head = "AI가 안전 정책 때문에 답을 막았습니다. 지문 표현을 일부 바꿔 다시 시도해주세요."
    else:
        return raw[:500]
    return f"{head}\n(원래 오류: {raw[:200]})"


class GeminiAI:
    name = "Gemini"

    def __init__(self, api_key: str):
        import google.generativeai as genai
        self._genai = genai
        genai.configure(api_key=api_key.strip().strip('"').strip("'"))
        self._models = {}
        self._lock = threading.Lock()

    def _model(self, quality: bool, json_mode: bool):
        key = (quality, json_mode)
        with self._lock:
            if key in self._models:
                return self._models[key]
            forced = os.environ.get("QM_MODEL" if quality else "QM_FAST_MODEL", "").strip()
            try:
                available = [m.name.replace("models/", "") for m in self._genai.list_models()
                             if "generateContent" in m.supported_generation_methods]
            except Exception as e:
                raise AIError(friendly_error(e))
            prefs = QUALITY_MODELS if quality else FAST_MODELS + QUALITY_MODELS
            name = forced or next((m for m in prefs if m in available), available[0] if available else None)
            if not name:
                raise AIError("쓸 수 있는 Gemini 모델이 없습니다.")
            config = {"temperature": 0.7}
            if json_mode:
                config["response_mime_type"] = "application/json"
            model = self._genai.GenerativeModel(name, generation_config=config)
            self._models[key] = model
            return model

    def generate_json(self, prompt: str, task: dict, quality: bool = True) -> dict:
        model = self._model(quality, True)
        try:
            resp = model.generate_content(prompt, request_options={"timeout": 600})
            text = resp.text
        except AIError:
            raise
        except Exception as e:
            raise AIError(friendly_error(e))
        return parse_json_text(text)

    def read_exam(self, files: list) -> str:
        """시험지 PDF · 사진(여러 장)을 문제지 만들기의 글 모양으로 옮긴다. files: [(bytes, mime), …]"""
        model = self._model(True, False)
        parts = [EXAM_IMPORT_PROMPT] + [{"mime_type": mime, "data": data} for data, mime in files]
        try:
            resp = model.generate_content(parts, generation_config={"temperature": 0.1, "max_output_tokens": 65536},
                                          request_options={"timeout": 900})
            text = (resp.text or "").strip()
        except Exception as e:
            raise AIError(friendly_error(e))
        return re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", text).strip()

    def transcribe(self, data: bytes, mime: str) -> str:
        model = self._model(False, False)
        prompt = ("첨부된 자료에 적힌 글을 하나도 빠뜨리지 말고 그대로 옮겨 적으세요. 요약하거나 고치지 마세요. "
                  "문단 나눔·줄 바꿈·시의 연 구분을 살리고, 제목·지은이가 있으면 함께 옮기세요. "
                  "흐려서 확실하지 않은 글자는 [?]로 적으세요. 옮긴 글 말고 다른 말은 쓰지 마세요.")
        try:
            resp = model.generate_content([prompt, {"mime_type": mime, "data": data}], request_options={"timeout": 300})
            return (resp.text or "").strip()
        except Exception as e:
            raise AIError(friendly_error(e))


class FakeAI:
    """키 없이 화면을 둘러보기 위한 연습용 AI. 지문을 실제로 읽지 않는다."""
    name = "연습용 AI(가짜 문제)"

    def generate_json(self, prompt: str, task: dict, quality: bool = True) -> dict:
        mode = task.get("mode")
        if mode == "generate":
            first = (task.get("passage") or "").strip().split("\n")[0][:30]
            questions = []
            for i, item in enumerate(task["items"]):
                no = task["start_no"] + i
                kind = item["kind"]
                q = {"no": no, "kind": kind, "difficulty": item["difficulty"],
                     "type": item.get("type") or "사실적 이해(내용 일치)", "box": ""}
                if kind == "mcq":
                    n = task.get("choice_count", 5)
                    q.update(stem=f"윗글의 내용과 일치하는 것은? (연습 문항 {no})",
                             choices=[f"연습 선지 {k + 1}: '{first}'에 관한 진술" for k in range(n)],
                             answer=(no % n) + 1, keep_order=False,
                             explanation="연습용 AI가 만든 문항입니다. 실제 키를 넣으면 지문을 읽고 출제합니다.",
                             choice_notes=[("정답: 지문과 일치" if k == no % n else "오답: 지문과 다름") for k in range(n)])
                elif kind == "ox":
                    q.update(stem=f"글쓴이는 '{first}'에 대해 이야기하고 있다. (연습 {no})", answer="O",
                             explanation="연습용 해설입니다.")
                elif kind == "blank":
                    q.update(stem="윗글의 중심 화제는 ( ㉮ )이다.", answer="㉮ 연습 답", explanation="연습용 해설입니다.")
                else:
                    q.update(stem="윗글에서 핵심어 하나를 찾아 쓰시오.", answer="연습 답", accept=[],
                             explanation="연습용 해설입니다.")
                questions.append(q)
            out = {"questions": questions}
            if task.get("need_passage"):
                out["intro"] = "※ 다음 글을 읽고 물음에 답하시오."
                out["passage"] = task.get("passage", "")
                out["source_note"] = ""
            return out
        if mode == "verify":
            return {"questions": task["draft"]["questions"], "notes": ["연습용 AI는 검수하지 않습니다."]}
        if mode == "revise":
            data = json.loads(json.dumps(task["data"]))
            targets = set(task.get("targets") or [q["no"] for q in data.get("questions", [])])
            for q in data.get("questions", []):
                if q["no"] in targets:
                    q["stem"] = q["stem"] + " (고친 문항)"
            data["summary"] = f"연습용 AI: {len(targets)}개 문항에 '(고친 문항)' 표시만 붙였습니다."
            return data
        raise AIError("알 수 없는 요청입니다.")

    def read_exam(self, files: list) -> str:
        return ("[1~1] 다음 글을 읽고 물음에 답하시오.\n[지문]\n연습용 AI는 시험지를 실제로 읽지 않습니다. AI 키를 넣으면 올린 시험지를 그대로 옮겨 적습니다.\n[/지문]\n\n"
                "1. 연습 문제입니다. 알맞은 것은?\n① 하나\n② 둘\n③ 셋\n④ 넷\n⑤ 다섯\n정답: 1\n해설: 연습용 해설입니다.")

    def transcribe(self, data: bytes, mime: str) -> str:
        return "(연습용 AI는 사진의 글을 읽지 못합니다. 실제 API 키를 넣으면 사진 속 글을 옮겨 적습니다.)"


def make_ai():
    """환경 변수에 따라 AI를 고른다. QM_DEMO=1 이면 연습용 AI."""
    if os.environ.get("QM_DEMO", "").strip() in ("1", "true", "yes"):
        return FakeAI()
    key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if key:
        return GeminiAI(key)
    return None
