import ezdxf
from ezdxf.addons.drawing import Frontend, RenderContext
from ezdxf.addons.drawing.matplotlib import MatplotlibBackend
import matplotlib.pyplot as plt
from pathlib import Path

def convert_dxf_to_pdf(dxf_path: str | Path, pdf_path: str | Path) -> Path:
    dxf_path = Path(dxf_path)
    pdf_path = Path(pdf_path)
    pdf_path.parent.mkdir(parents=True, exist_ok=True)

    doc = ezdxf.readfile(str(dxf_path))
    msp = doc.modelspace()

    # Determine bounding box
    fig = plt.figure(figsize=(16.54, 11.69), dpi=300) # A3 landscape base
    ax = fig.add_axes([0, 0, 1, 1])
    ctx = RenderContext(doc)
    ctx.set_current_layout(msp)
    backend = MatplotlibBackend(ax)
    frontend = Frontend(ctx, backend)
    frontend.draw_layout(msp, finalize=True)

    ax.set_aspect("equal", "datalim")
    ax.axis("off")
    fig.savefig(str(pdf_path), format="pdf", dpi=300, bbox_inches="tight", pad_inches=0.05)
    plt.close(fig)
    return pdf_path

if __name__ == "__main__":
    src_dxf = Path("data/output/workshop_release/workshop_columns_plan_SPDS.dxf")
    out_pdf = Path("data/output/workshop_release/test_spds_render.pdf")
    if src_dxf.exists():
        res = convert_dxf_to_pdf(src_dxf, out_pdf)
        print("Successfully converted to PDF:", res, "Size:", res.stat().st_size)
    else:
        print("Source DXF not found:", src_dxf)
