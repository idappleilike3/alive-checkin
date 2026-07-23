"""Regenerate welcome Flex assets: transparent upright logo + hero banner (no logo)."""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
SRC_LOGO = Path(
    r"C:\Users\WIN11\AppData\Roaming\Cursor\User\workspaceStorage\empty-window\images"
    r"\logo-f56e3c8b-b693-4c64-b46a-8cda185c403c.png"
)
MOCKUP = Path(
    r"C:\Users\WIN11\AppData\Roaming\Cursor\User\workspaceStorage\empty-window\images"
    r"\image-3aa6054d-14e5-4472-9dc0-95d19cb3c178.png"
)


def _font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    candidates = [
        r"C:\Windows\Fonts\msjhbd.ttc" if bold else r"C:\Windows\Fonts\msjh.ttc",
        r"C:\Windows\Fonts\msyhbd.ttc" if bold else r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\mingliu.ttc",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _draw_heart(draw: ImageDraw.ImageDraw, cx: int, cy: int, size: int, fill) -> None:
    """Simple heart via overlapping circles + polygon."""
    r = size // 2
    draw.ellipse((cx - size, cy - r, cx, cy + r), fill=fill)
    draw.ellipse((cx, cy - r, cx + size, cy + r), fill=fill)
    draw.polygon(
        [
            (cx - size, cy),
            (cx + size, cy),
            (cx, cy + int(size * 1.25)),
        ],
        fill=fill,
    )


def make_logo() -> Path:
    im = Image.open(SRC_LOGO).convert("RGBA")
    arr = np.array(im).astype(np.float32)
    r, g, b, a = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2], arr[:, :, 3]
    cream = np.array([253.0, 246.0, 236.0])
    dist = np.sqrt((r - cream[0]) ** 2 + (g - cream[1]) ** 2 + (b - cream[2]) ** 2)
    alpha = np.clip((dist - 16.0) / 20.0, 0.0, 1.0) * 255.0
    out = arr.copy()
    out[:, :, 3] = np.minimum(a, alpha)

    alpha_u8 = out[:, :, 3].astype(np.uint8)
    ys, xs = np.where(alpha_u8 > 12)
    pad = 12
    y0, y1 = max(0, int(ys.min()) - pad), min(out.shape[0], int(ys.max()) + pad + 1)
    x0, x1 = max(0, int(xs.min()) - pad), min(out.shape[1], int(xs.max()) + pad + 1)
    cropped = Image.fromarray(out.astype(np.uint8)).crop((x0, y0, x1, y1))

    w, h = cropped.size
    side = max(w, h)
    sq = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    sq.paste(cropped, ((side - w) // 2, (side - h) // 2), cropped)
    logo = sq.resize((512, 512), Image.Resampling.LANCZOS)

    out_path = ASSETS / "daily-peace-logo.png"
    logo.save(out_path, "PNG")

    preview = Image.new("RGBA", (640, 640), (255, 245, 248, 255))
    scaled = logo.resize((520, 520), Image.Resampling.LANCZOS)
    preview.paste(scaled, (60, 60), scaled)
    preview.convert("RGB").save(ASSETS / "_logo_preview.png")
    print(f"logo -> {out_path} size={logo.size}")
    return out_path


def make_banner() -> Path:
    """Hero: soft pink + white card + heart + large text + phone 我平安. NO brand logo."""
    W, H = 1200, 540
    pink_bg = (255, 245, 248, 255)
    pink_soft = (255, 228, 236, 255)
    pink_accent = (219, 39, 119, 255)
    heart_fill = (244, 114, 182, 255)
    text_dark = (131, 24, 67, 255)
    white = (255, 255, 255, 255)
    phone_green = (34, 197, 94, 255)

    canvas = Image.new("RGBA", (W, H), pink_bg)
    blob = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    bd = ImageDraw.Draw(blob)
    bd.ellipse((-80, -60, 280, 260), fill=(255, 200, 220, 70))
    bd.ellipse((900, 280, 1280, 620), fill=(255, 190, 210, 80))
    canvas = Image.alpha_composite(canvas, blob)
    draw = ImageDraw.Draw(canvas)

    margin = 36
    draw.rounded_rectangle(
        [margin, 28, W - margin, H - 28],
        radius=36,
        fill=white,
        outline=(255, 182, 205, 255),
        width=3,
    )

    # left heart circle
    cx, cy, cr = 150, H // 2 - 10, 78
    draw.ellipse((cx - cr, cy - cr, cx + cr, cy + cr), fill=pink_soft)
    _draw_heart(draw, cx, cy - 6, 34, heart_fill)

    title_font = _font(54, bold=True)
    sub_font = _font(36, bold=True)
    tx = 260
    draw.text((tx, 145), "每天 10 秒，報個平安", font=title_font, fill=pink_accent)
    draw.text((tx, 235), "平常不打擾，有事才通知守護人", font=sub_font, fill=text_dark)

    # phone visual
    phone_x, phone_y = 920, 95
    pw, ph = 170, 320
    draw.ellipse(
        (phone_x - 40, phone_y + 220, phone_x + pw + 30, phone_y + ph + 40),
        fill=(255, 210, 220, 180),
    )
    draw.rounded_rectangle(
        (phone_x, phone_y, phone_x + pw, phone_y + ph),
        radius=28,
        fill=(40, 40, 48, 255),
    )
    draw.rounded_rectangle(
        (phone_x + 14, phone_y + 28, phone_x + pw - 14, phone_y + ph - 28),
        radius=18,
        fill=(250, 250, 252, 255),
    )
    gcx, gcy, gr = phone_x + pw // 2, phone_y + 130, 48
    draw.ellipse((gcx - gr, gcy - gr, gcx + gr, gcy + gr), fill=phone_green)
    # check mark
    draw.line(
        [(gcx - 18, gcy), (gcx - 4, gcy + 16), (gcx + 22, gcy - 18)],
        fill=white,
        width=8,
    )
    label_font = _font(30, bold=True)
    label = "我平安"
    bbox = draw.textbbox((0, 0), label, font=label_font)
    lw = bbox[2] - bbox[0]
    draw.text((gcx - lw // 2, gcy + 58), label, font=label_font, fill=phone_green)

    for hx, hy, sz in ((880, 130, 14), (1085, 170, 12), (870, 310, 10)):
        _draw_heart(draw, hx, hy, sz, (244, 114, 182, 210))

    out_path = ASSETS / "welcome-heart-banner.png"
    canvas.convert("RGB").save(out_path, "PNG")
    print(f"banner -> {out_path} size={canvas.size}")
    return out_path


def main() -> None:
    ASSETS.mkdir(exist_ok=True)
    if not SRC_LOGO.exists():
        raise SystemExit(f"missing logo source: {SRC_LOGO}")
    make_logo()
    make_banner()
    if MOCKUP.exists():
        Image.open(MOCKUP).convert("RGB").save(ASSETS / "_welcome_design_ref.png")


if __name__ == "__main__":
    main()
