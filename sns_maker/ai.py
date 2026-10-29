"""AI(구글 Gemini). 문제 공장과 같은 연결을 그대로 쓴다.

키가 없을 때 화면을 둘러볼 수 있도록 '연습용 AI'(FakeAI)도 둔다.
"""

import json
import os

from question_maker.ai import AIError, GeminiAI, parse_json_text  # noqa: F401  (다른 모듈이 여기서 가져다 씀)


class FakeAI:
    """키 없이 화면을 둘러보기 위한 연습용 AI. 정해진 틀에 주제만 끼워 넣는다."""
    name = "연습용 AI(가짜 글)"

    def generate_json(self, prompt: str, task: dict, quality: bool = True) -> dict:
        mode = task.get("mode")
        topic = (task.get("topic") or "학원 소식").strip()[:40]
        academy = (task.get("profile") or {}).get("name") or "우리 학원"
        if mode == "generate":
            out = {}
            if "instagram" in task["channels"]:
                n = task.get("slide_count", 5)
                out["instagram"] = {
                    "caption": f"📚 {topic}\n\n{academy}이(가) 준비한 이야기예요.\n연습용 AI가 쓴 글이라 실제 내용은 없어요.\n\n👉 상담은 프로필 링크에서!",
                    "hashtags": ["#학원", "#공부스타그램", "#국어학원", "#공부팁", "#내신대비"],
                    "slides": [{"title": topic if i == 0 else f"{i}. 연습 카드 제목",
                                "body": "" if i == 0 else "연습용 AI가 쓴 카드 내용입니다. 실제 키를 넣으면 주제에 맞춰 씁니다."}
                               for i in range(n)],
                    "image_ideas": ["밝은 교실에서 공부하는 학생들의 뒷모습", "정리된 필기 노트를 위에서 찍은 사진"],
                    "reel_script": "(0~3초) 화면에 큰 글씨: " + topic + "\n(3~10초) 연습용 대본입니다.",
                }
            if "blog" in task["channels"]:
                out["blog"] = {
                    "titles": [f"{topic} | {academy}", f"{academy}가 알려 드리는 {topic}", f"{topic}, 이렇게 준비하세요"],
                    "keywords": ["학원", "국어학원", "공부법"],
                    "intro": f"안녕하세요, {academy}입니다. 오늘은 '{topic}'에 대해 이야기해 보려고 해요.",
                    "sections": [{"heading": f"{i + 1}. 연습 소제목", "body": "연습용 AI가 쓴 문단입니다. 실제 키를 넣으면 주제에 맞춰 씁니다.",
                                  "photo": "수업 장면 사진"} for i in range(3)],
                    "outro": "궁금한 점은 언제든 문의해 주세요.",
                    "tags": ["학원", "공부법", "국어"],
                }
            return out
        if mode == "revise":
            data = json.loads(json.dumps(task["data"]))
            if "instagram" in data:
                data["instagram"]["caption"] = data["instagram"]["caption"] + "\n(연습용 AI: 고친 글)"
            if "blog" in data:
                data["blog"]["intro"] = data["blog"]["intro"] + " (연습용 AI: 고친 글)"
            data["summary"] = "연습용 AI는 '(고친 글)' 표시만 붙입니다."
            return data
        if mode == "ideas":
            kinds = list(task.get("kinds") or ["tip"])
            return {"ideas": [{"kind": kinds[i % len(kinds)], "topic": f"연습 주제 {i + 1}",
                               "why": "연습용 AI가 만든 추천입니다.", "channel": "instagram" if i % 2 else "blog"}
                              for i in range(task.get("count", 8))]}
        raise AIError("알 수 없는 요청입니다.")


def make_ai():
    """환경 변수에 따라 AI를 고른다. SNS_DEMO=1(또는 QM_DEMO=1)이면 연습용 AI."""
    for flag in ("SNS_DEMO", "QM_DEMO"):
        if os.environ.get(flag, "").strip() in ("1", "true", "yes"):
            return FakeAI()
    key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if key:
        return GeminiAI(key)
    return None
