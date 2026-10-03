"""Regenerate platform icons from the shipped 1024 px application icon."""

from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parent.parent
APP_RESOURCES = ROOT / "app" / "resources"
MASTER = APP_RESOURCES / "icon.png"
FRONTEND_PUBLIC = ROOT / "frontend" / "public"


def main() -> None:
    source = Image.open(MASTER).convert("RGBA")
    if source.width != source.height or source.width < 1024:
        raise ValueError("app/resources/icon.png must be a square image at least 1024 pixels wide")

    # Small icons need a closer crop so the bot remains recognizable in the tray.
    inset = round(source.width * 0.13)
    small = source.crop((inset, inset, source.width - inset, source.height - inset))
    source.save(APP_RESOURCES / "icon.icns", format="ICNS")

    sizes = (16, 24, 32, 48, 64, 128, 256)
    frames = [small.resize((size, size), Image.Resampling.LANCZOS) for size in sizes]
    frames[-1].save(
        APP_RESOURCES / "icon.ico",
        format="ICO",
        append_images=frames[:-1],
        sizes=[(size, size) for size in sizes],
    )
    frames[4].save(APP_RESOURCES / "tray.png", optimize=True)
    FRONTEND_PUBLIC.mkdir(exist_ok=True)
    frames[-1].save(FRONTEND_PUBLIC / "icon.png", optimize=True)


if __name__ == "__main__":
    main()
