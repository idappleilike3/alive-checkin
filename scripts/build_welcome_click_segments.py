"""Build seamless welcome-card segments with two independent LINE actions."""

from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
SOURCE = ASSETS / "welcome-approved-full-20260802-help-large.jpg"


def main() -> None:
    source = Image.open(SOURCE).convert("RGB")
    if source.size != (865, 1818):
        raise ValueError(f"unexpected source size: {source.size}")

    # Keep all approved artwork unchanged through the three setup steps. Enlarge
    # only the existing help-button strip and discard the emergency disclaimer.
    upper = source.crop((0, 0, 865, 1570))
    help_button = source.crop((0, 1570, 865, 1705)).resize(
        (865, 185), Image.Resampling.LANCZOS
    )
    finished = Image.new("RGB", (865, 1755))
    finished.paste(upper, (0, 0))
    finished.paste(help_button, (0, 1570))

    segments = {
        "welcome-card-top-20260802.png": (0, 910),
        "welcome-card-trial-20260802.png": (910, 1110),
        "welcome-card-steps-20260802.png": (1110, 1570),
        "welcome-card-help-20260802.png": (1570, 1755),
    }
    for filename, (top, bottom) in segments.items():
        finished.crop((0, top, 865, bottom)).save(
            ASSETS / filename, format="PNG", optimize=True
        )


if __name__ == "__main__":
    main()
