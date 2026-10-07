from fastapi.testclient import TestClient

from backend.main import app
from backend.schemas import RoleCardIn
from test_role_cards import role_payload


EXPECTED = {
    "backend:junior": {"data_trace", "validation", "http_api"},
    "backend:middle": {"event_idempotency", "data_integrity", "failure_recovery"},
    "frontend:junior": {"javascript_trace", "ui_state", "forms"},
    "frontend:middle": {"request_races", "derived_state", "error_recovery"},
    "qa:junior": {"test_design", "bug_reporting", "api_testing"},
    "qa:middle": {"risk_based_testing", "automation_design", "reliability_testing"},
    "data_analyst:junior": {"sql_querying", "data_quality", "metric_definition"},
    "data_analyst:middle": {"experiment_analysis", "metric_integrity", "data_validation"},
}


def test_public_category_catalog_matches_supported_competency_pairs():
    with TestClient(app) as client:
        response = client.get("/api/v1/taxonomy/categories")
        openapi = client.get("/api/openapi.json").json()

    assert response.status_code == 200, response.text
    payload = response.json()
    by_id = {item["id"]: item for item in payload}
    assert set(by_id) == set(EXPECTED)
    for category_id, competency_ids in EXPECTED.items():
        item = by_id[category_id]
        assert item["available"] is True
        assert item["specialization"], item
        assert item["grade"] in {"junior", "middle"}
        assert item["label"]
        assert item["blueprint_version"]
        assert {competency["id"] for competency in item["competencies"]} == competency_ids
        assert all(competency["label"] for competency in item["competencies"])
    schema = openapi["paths"]["/api/v1/taxonomy/categories"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    assert schema["type"] == "array"
    item_schema = openapi["components"]["schemas"][schema["items"]["$ref"].split("/")[-1]]
    assert {"id", "specialization", "grade", "label", "blueprint_version", "available", "competencies"} <= set(item_schema["properties"])


def test_role_card_schema_accepts_new_catalog_pairs():
    for specialization, grade, competency in (
        ("qa", "junior", "test_design"),
        ("qa", "middle", "risk_based_testing"),
        ("data_analyst", "junior", "sql_querying"),
        ("data_analyst", "middle", "experiment_analysis"),
    ):
        card = RoleCardIn.model_validate(role_payload(
            specialization=specialization, grade=grade, competencies=[competency],
        ))
        assert (card.specialization, card.grade, card.competencies) == (specialization, grade, [competency])
