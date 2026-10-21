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
