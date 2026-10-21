"""python -m question_maker 로 켠다."""
import os
import webbrowser

import uvicorn

from .app import create_app


def main():
    host = os.environ.get("QM_HOST", "127.0.0.1")
    port = int(os.environ.get("QM_PORT", "8800"))
    app = create_app()
    print(f"\n문제 공장이 켜졌습니다 → http://{host}:{port}\n(끄려면 Ctrl+C)\n")
    if os.environ.get("QM_NO_BROWSER", "") == "" and host in ("127.0.0.1", "localhost"):
        try:
            webbrowser.open(f"http://{host}:{port}")
        except Exception:
            pass
    uvicorn.run(app, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    main()
