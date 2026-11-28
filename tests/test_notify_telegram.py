"""2026-11-28: 홈페이지 서버 알림을 텔레그램으로 대신 보내기 — 비밀 글자가 맞아야만."""
import os
import unittest

_SRC = open(os.path.join(os.path.dirname(__file__), "..", "main.py"), encoding="utf-8").read()


class TelegramRelayTests(unittest.TestCase):
    def test_endpoint_checks_secret_and_uses_existing_sender(self):
        body = _SRC[_SRC.index('@app.post("/api/notify/telegram")'):]
        body = body[:body.index("\n@app.")]
        self.assertIn("compare_digest(secret, x_notify_secret.strip())", body)
        self.assertIn('raise HTTPException(status_code=403', body)
        self.assertIn("send_telegram_message(text)", body)
        self.assertIn("[:3500]", body)


if __name__ == "__main__":
    unittest.main()
