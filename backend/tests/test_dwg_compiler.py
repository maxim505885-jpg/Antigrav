import sys
from pathlib import Path
sys.path.insert(0, str(Path("backend").resolve()))

from scan2bim.cad.dwg_compiler import (
    convert_dxf_to_dwg_native,
    convert_dxf_to_dwg_accore,
    batch_convert_album_to_dwg,
    find_accoreconsole,
    is_valid_dwg,
)


def test_accoreconsole_detection():
    accore = find_accoreconsole()
    assert accore is not None, "accoreconsole.exe должен быть обнаружен в системе"
    assert accore.is_file()


def test_batch_convert_album_to_dwg():
    test_album_dir = Path("data/output/single_pass_release/spds_album")
    if not test_album_dir.is_dir():
        import pytest

        pytest.skip("prebuilt release DXF album is not included in this working copy")
    dwg_files = batch_convert_album_to_dwg(test_album_dir)
    assert len(dwg_files) >= 5, "Ожидалось не менее 5 скомпилированных DWG чертежей"
    for dwg in dwg_files:
        assert dwg.is_file()
        assert dwg.stat().st_size > 1024
        assert is_valid_dwg(dwg)
        with open(dwg, "rb") as f:
            header = f.read(6)
        assert header.startswith(b"AC10"), f"Неверный заголовок DWG: {header}"


def test_convert_single_dxf_to_dwg(tmp_path):
    test_dxf = Path("data/output/single_pass_release/spds_album/02_plan_podkranovyh_balok_SPDS.dxf")
    if test_dxf.is_file():
        out_dwg = tmp_path / "test_crane.dwg"
        res = convert_dxf_to_dwg_native(test_dxf, out_dwg, force_recompile=True)
        assert res.is_file()
        assert res.stat().st_size > 1024
        assert is_valid_dwg(res)
        with open(res, "rb") as f:
            assert f.read(6).startswith(b"AC10")


def test_convert_dxf_to_dwg_accore_direct(tmp_path):
    test_dxf = Path("data/output/single_pass_release/spds_album/01_plan_kolonn_SPDS.dxf")
    if test_dxf.is_file():
        out_dwg = tmp_path / "direct_accore.dwg"
        res = convert_dxf_to_dwg_accore(test_dxf, out_dwg)
        assert res.is_file()
        assert res.stat().st_size > 1024
        assert is_valid_dwg(res)
        with open(res, "rb") as f:
            assert f.read(6) == b"AC1032"
