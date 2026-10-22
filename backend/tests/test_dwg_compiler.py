import sys
from pathlib import Path
sys.path.insert(0, str(Path("backend").resolve()))

from scan2bim.cad.dwg_compiler import convert_dxf_to_dwg_native, batch_convert_album_to_dwg


def test_batch_convert_album_to_dwg():
    test_album_dir = Path("data/output/single_pass_release/spds_album")
    dwg_files = batch_convert_album_to_dwg(test_album_dir)
    assert len(dwg_files) >= 5, "Ожидалось не менее 5 скомпилированных DWG чертежей"
    for dwg in dwg_files:
        assert dwg.is_file()
        assert dwg.stat().st_size > 1024
        with open(dwg, "rb") as f:
            header = f.read(6)
        assert header.startswith(b"AC10"), f"Неверный заголовок DWG: {header}"


def test_convert_single_dxf_to_dwg(tmp_path):
    test_dxf = Path("data/output/single_pass_release/spds_album/02_plan_podkranovyh_balok_SPDS.dxf")
    if test_dxf.is_file():
        out_dwg = tmp_path / "test_crane.dwg"
        res = convert_dxf_to_dwg_native(test_dxf, out_dwg)
        assert res.is_file()
        assert res.stat().st_size > 1024
        with open(res, "rb") as f:
            assert f.read(6).startswith(b"AC10")
