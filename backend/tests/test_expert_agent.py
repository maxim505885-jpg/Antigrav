import pytest

def test_expert_agent_answers_questions(client):
    res = client.post("/api/v1/expert/ask", json={
        "query": "Как сделать привязку колонн и какие допуски по СП 70?",
        "cloud_context": {"columns_count": 233}
    })
    assert res.status_code == 200
    data = res.json()
    assert "Колонны" in data["topic"]
    assert "СП 70.13330" in str(data["referenced_norms"]) or "СП 70.13330" in str(data["recommendations"])
    assert len(data["cad_shortcut_tips"]) > 0
    context = " ".join(data["recommendations"])
    assert "233 кандидатов колонн" in context
    assert "87 колонн" not in context

def test_expert_agent_crane_rails_knowledge(client):
    res = client.post("/api/v1/expert/ask", json={
        "query": "Какие правила для подкрановых балок и рельса КР-70?"
    })
    assert res.status_code == 200
    data = res.json()
    assert "рельс" in data["answer"].lower() or "балк" in data["answer"].lower()
    assert len(data["recommendations"]) > 0


def test_expert_agent_knowledge_summary(client):
    res = client.get("/api/v1/expert/knowledge-summary")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "partial_project_inputs"
    assert "workshop_topology" in data
    topology = data["workshop_topology"]
    assert topology["confirmed_inputs"]["longitudinal_column_pitch_m"] == 6.0
    assert topology["confirmed_inputs"]["source"] == "user-provided nominal value"
    assert topology["engineering_tolerance_mm"] is None
    assert topology["hall_length_m"] is None
    assert topology["hall_width_m"] is None
    assert topology["spans"] is None
    assert topology["axes_count"] is None
    assert topology["elevations"] is None
    assert data["workshop_topology"]["crane_capacity_tons"] is None
    assert "workshop_anatomy" in data["knowledge_base"]
    assert "clearance_rules" in data["knowledge_base"]


def test_expert_agent_does_not_fill_missing_project_layout_from_typical_values(client):
    response = client.post("/api/v1/expert/ask", json={
        "query": "Какие размеры пролётов и отметка подкрановых путей у нашего цеха?",
        "cloud_context": {},
    })

    assert response.status_code == 200
    text = " ".join(response.json()["recommendations"] + [response.json()["answer"]])
    assert "13.25" not in text
    assert "11.70" not in text
    assert "138 м" not in text
    assert "6000 мм" in text
    assert "не заданы" in text

