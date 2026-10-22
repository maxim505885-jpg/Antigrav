import os
from pathlib import Path
import matplotlib.pyplot as plt
import ezdxf
from ezdxf.addons.drawing import Frontend, RenderContext
from ezdxf.addons.drawing.matplotlib import MatplotlibBackend

album_dir = Path("data/output/workshop_release/spds_album")
preview_dir = Path(r"C:\Users\maxim\.gemini\antigravity\brain\d61ab238-5e62-402e-ad44-bec32b87db1b")
preview_dir.mkdir(parents=True, exist_ok=True)

dxfs = sorted(list(album_dir.glob("*.dxf")))
for dxf_path in dxfs:
    doc = ezdxf.readfile(str(dxf_path))
    msp = doc.modelspace()

    png_name = dxf_path.stem + ".png"
    out_png = preview_dir / png_name

    fig = plt.figure(figsize=(16, 11), dpi=150)
    ax = fig.add_axes([0, 0, 1, 1])

    ctx = RenderContext(doc)
    ctx.set_current_layout(msp)
    backend = MatplotlibBackend(ax)
    frontend = Frontend(ctx, backend)
    frontend.draw_layout(msp, finalize=True)

    ax.set_aspect("equal", "datalim")
    ax.axis("off")
    fig.savefig(str(out_png), format="png", dpi=150, bbox_inches="tight", pad_inches=0.02)
    plt.close(fig)
    print("Rendered PNG preview:", out_png, "Size:", out_png.stat().st_size)
