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
    assert data["status"] == "success"
    assert "workshop_topology" in data
    assert data["workshop_topology"]["hall_length_m"] == 138.0
    assert data["workshop_topology"]["crane_capacity_tons"] is None
    assert len(data["workshop_topology"]["spans"]) == 3
    assert "workshop_anatomy" in data["knowledge_base"]
    assert "clearance_rules" in data["knowledge_base"]

