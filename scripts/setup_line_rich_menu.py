import json
import os
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = Path(os.environ.get("RICH_MENU_CONFIG_PATH", ROOT / "line-rich-menu-config.json"))
IMAGE_PATH = Path(os.environ.get("RICH_MENU_IMAGE_PATH", ROOT / "line-rich-menu.png"))
TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN") or os.environ.get("CHANNEL_ACCESS_TOKEN")


def request_json(method, url, payload=None, content_type="application/json"):
    if not TOKEN:
        raise RuntimeError("請先設定 LINE_CHANNEL_ACCESS_TOKEN")
    data = None
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Content-Type": content_type,
        },
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        body = response.read().decode("utf-8")
    return json.loads(body) if body else {}


def main():
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    create_result = request_json("POST", "https://api.line.me/v2/bot/richmenu", config)
    rich_menu_id = create_result["richMenuId"]

    if not IMAGE_PATH.exists():
        raise RuntimeError(f"找不到圖文選單圖片：{IMAGE_PATH}")
    image_req = urllib.request.Request(
        f"https://api-data.line.me/v2/bot/richmenu/{rich_menu_id}/content",
        data=IMAGE_PATH.read_bytes(),
        method="POST",
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Content-Type": "image/png",
        },
    )
    with urllib.request.urlopen(image_req, timeout=60) as response:
        response.read()

    request_json("POST", f"https://api.line.me/v2/bot/user/all/richmenu/{rich_menu_id}")
    print(f"已設定預設圖文選單：{rich_menu_id}")


if __name__ == "__main__":
    main()
