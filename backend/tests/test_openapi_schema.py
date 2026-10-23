"""API schema remains available for the full route set."""


def test_openapi_schema_includes_learning_sample_request(client):
    response = client.get("/openapi.json")

    assert response.status_code == 200
    schema = response.json()
    assert "SampleCreate" in schema["components"]["schemas"]
    assert "/api/v1/projects/{project_id}/samples" in schema["paths"]


def test_openapi_documents_point_provenance_in_column_annotations(client):
    response = client.get("/openapi.json")
    assert response.status_code == 200
    schemas = response.json()["components"]["schemas"]

    annotation = schemas["ColumnAnnotationSave"]
    assert annotation["properties"]["algorithm_suggestions_verified"]["type"] == "boolean"
    height = schemas["ColumnAnnotationHeightMeasurement"]
    provenance_ref = height["properties"]["source_provenance"]["anyOf"][0]["$ref"]
    provenance_name = provenance_ref.rsplit("/", 1)[-1]
    provenance = schemas[provenance_name]
    assert set(provenance["required"]) == {
        "source_point_row_id_count", "source_point_row_id_sample", "source_index_space", "analysis_algorithm",
    }
    assert provenance["properties"]["source_index_space"]["const"] == "derived_positions_row_index/1"
