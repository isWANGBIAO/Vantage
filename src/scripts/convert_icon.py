"""Build runtime PNG and Windows multi-resolution ICO from the root artwork."""
from pathlib import Path

from PIL import Image

root = Path(__file__).resolve().parents[2]
assets = root / "src" / "webapp" / "assets"
assets.mkdir(parents=True, exist_ok=True)
with Image.open(root / "icon.png") as source:
    image = source.convert("RGBA")
    image.resize((512, 512), Image.Resampling.LANCZOS).save(assets / "icon.png")
    image.save(assets / "icon.ico", sizes=[(n, n) for n in (16, 20, 24, 32, 40, 48, 64, 128, 256)])
print("Generated runtime icon.png and multi-resolution icon.ico")
