import os
from PIL import Image


def generate_geneva_overlay(
    gtfs_png_path: str,
    hrdf_png_path: str,
    output_png_path: str,
    alpha_gtfs: float = 0.65,
    alpha_hrdf: float = 0.65,
    background: str = "white",
) -> None:
    """
    Create an overlay image by alpha-compositing GTFS and HRDF Geneva PNGs.

    Assumptions:
    - Both input images share the same extent and size (they were generated with identical map bounds).
    - If sizes differ, the HRDF image will be resized to GTFS size.
    """
    os.makedirs(os.path.dirname(output_png_path), exist_ok=True)

    base = Image.open(gtfs_png_path).convert("RGBA")
    top = Image.open(hrdf_png_path).convert("RGBA")

    if top.size != base.size:
        top = top.resize(base.size, resample=Image.BILINEAR)

    # Apply alpha to inputs
    r, g, b, a = top.split()
    a = a.point(lambda p: int(alpha_hrdf * p))
    top = Image.merge("RGBA", (r, g, b, a))

    r2, g2, b2, a2 = base.split()
    a2 = a2.point(lambda p: int(alpha_gtfs * p))
    base = Image.merge("RGBA", (r2, g2, b2, a2))

    # Composite over background
    if background == "white":
        bg = Image.new("RGBA", base.size, (255, 255, 255, 255))
    else:
        bg = Image.new("RGBA", base.size, (0, 0, 0, 255))

    composite = Image.alpha_composite(bg, base)
    composite = Image.alpha_composite(composite, top)

    composite.convert("RGB").save(output_png_path, format="PNG", optimize=True)


def generate_geneva_triptych(atlas_png: str, gtfs_png: str, hrdf_png: str, output_png: str) -> None:
    """
    Concatenate three Geneva PNGs (ATLAS, GTFS, HRDF) horizontally into a single image.
    If sizes differ, each is resized to the max height, preserving aspect, then padded to the same height.
    """
    os.makedirs(os.path.dirname(output_png), exist_ok=True)
    imgs = [Image.open(p).convert('RGB') for p in (atlas_png, gtfs_png, hrdf_png)]
    # Increase target height by ~20% for larger panels
    max_h = int(round(max(im.size[1] for im in imgs) * 1.2))
    resized = []
    for im in imgs:
        w, h = im.size
        if h != max_h:
            new_w = int(round(w * (max_h / h)))
            im = im.resize((new_w, max_h), resample=Image.BILINEAR)
        resized.append(im)
    total_w = sum(im.size[0] for im in resized)
    out = Image.new('RGB', (total_w, max_h), (255, 255, 255))
    x = 0
    for im in resized:
        out.paste(im, (x, 0))
        x += im.size[0]
    out.save(output_png, format='PNG', optimize=True)


if __name__ == "__main__":
    gtfs = os.path.join("memoire", "figures", "plots", "gtfs_points_geneva.png")
    hrdf = os.path.join("memoire", "figures", "plots", "hrdf_quays_geneva.png")
    atlas = os.path.join("memoire", "figures", "plots", "atlas_points_geneva.png")
    out_overlay = os.path.join("memoire", "figures", "plots", "gtfs_hrdf_geneva_overlay.png")
    out_triptych = os.path.join("memoire", "figures", "plots", "geneva_triptych_atlas_gtfs_hrdf.png")
    if os.path.exists(gtfs) and os.path.exists(hrdf):
        generate_geneva_overlay(gtfs, hrdf, out_overlay)
    if os.path.exists(atlas) and os.path.exists(gtfs) and os.path.exists(hrdf):
        generate_geneva_triptych(atlas, gtfs, hrdf, out_triptych)


