"""
Generates icon.ico for the Monitor Manager exe.
Run automatically by the GitHub Actions build before PyInstaller.
Requires Pillow.
"""
from PIL import Image, ImageDraw


def draw_monitor(size: int) -> Image.Image:
    s   = size
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d   = ImageDraw.Draw(img)

    # Layout proportions
    pad      = max(1, s // 12)
    bezel    = max(1, s // 10)
    stand_w  = max(2, s // 5)
    stand_h  = max(1, s // 10)
    base_w   = max(4, s * 2 // 5)
    base_h   = max(1, s // 14)

    body_l = pad
    body_t = pad
    body_r = s - pad
    body_b = s - pad - stand_h - base_h - 1

    # Monitor bezel (#89b4fa — Catppuccin blue)
    d.rectangle([body_l, body_t, body_r, body_b], fill="#89b4fa")

    # Screen interior (#1e1e2e — Catppuccin base)
    d.rectangle(
        [body_l + bezel, body_t + bezel, body_r - bezel, body_b - bezel],
        fill="#1e1e2e",
    )

    # Small accent dot on screen (green — like a status light)
    if s >= 32:
        dot = max(2, s // 16)
        cx  = body_l + bezel + dot + 1
        cy  = body_b - bezel - dot - 1
        d.ellipse([cx - dot, cy - dot, cx + dot, cy + dot], fill="#a6e3a1")

    # Stand
    sl = s // 2 - stand_w // 2
    sr = s // 2 + stand_w // 2
    d.rectangle([sl, body_b, sr, body_b + stand_h], fill="#cdd6f4")

    # Base
    bl = s // 2 - base_w // 2
    br = s // 2 + base_w // 2
    d.rectangle([bl, body_b + stand_h, br, body_b + stand_h + base_h], fill="#cdd6f4")

    return img


sizes  = [16, 32, 48, 64, 128, 256]
images = [draw_monitor(s) for s in sizes]

images[0].save(
    "icon.ico",
    format="ICO",
    sizes=[(s, s) for s in sizes],
    append_images=images[1:],
)
print("icon.ico created successfully")
