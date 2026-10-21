"""API schema remains available for the full route set."""


def test_openapi_schema_includes_learning_sample_request(client):
    response = client.get("/openapi.json")

    assert response.status_code == 200
    schema = response.json()
    assert "SampleCreate" in schema["components"]["schemas"]
    assert "/api/v1/projects/{project_id}/samples" in schema["paths"]
