import pytest
import numpy as np
from scan2bim.recognition.structural_fitting import extract_actual_workshop_structural_members


def test_structural_fitting_synthetic():
    # Создаем синтетические точки подкрановых балок и ферм
    np.random.seed(42)
    pts = []
    
    # Рельс на Y = 6.0, Z = 4.0, длина 60 м вдоль X
    x_crane = np.linspace(-30, 30, 15000)
    y_crane = np.random.normal(6.0, 0.05, size=len(x_crane))
    z_crane = np.random.normal(4.0, 0.05, size=len(x_crane))
    pts.append(np.column_stack([x_crane, y_crane, z_crane]))

    # Ферма на X = 12.0, Z = 6.8, пролет 30 м вдоль Y
    y_truss = np.linspace(-15, 15, 60000)
    x_truss = np.random.normal(12.0, 0.05, size=len(y_truss))
    z_truss = np.random.normal(6.8, 0.3, size=len(y_truss))
    pts.append(np.column_stack([x_truss, y_truss, z_truss]))

    cloud_pts = np.vstack(pts)
    res = extract_actual_workshop_structural_members(cloud_pts, rotation_deg=0.0)

    assert res["result_type"] == "experimental_hypothesis"
    assert res["verified"] is False
    assert len(res["crane_rails"]) >= 1
    rail = res["crane_rails"][0]
    assert abs(rail["y_local_m"] - 6.0) < 0.2
    assert abs(rail["z_local_m"] - 4.0) < 0.2

    assert len(res["trusses"]) >= 1
    truss = res["trusses"][0]
    assert abs(truss["x_local_m"] - 12.0) < 0.5
