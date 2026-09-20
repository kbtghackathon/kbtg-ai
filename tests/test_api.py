import pytest
from fastapi.testclient import TestClient

from main import app
from tests.conftest import SYNTHETIC_STATEMENT


@pytest.fixture
def client():
    with TestClient(app) as c:  # context manager runs startup hooks
        yield c


def test_health(client):
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["merchant_dict_loaded"] is True
    assert body["merchant_count"] > 0


def test_analyze_text_endpoint(client):
    resp = client.post(
        "/analyze-text",
        data={"statement_text": SYNTHETIC_STATEMENT.read_text(encoding="utf-8"), "current_salary": "30000"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["data_months_available"] == 4
    assert {e["recipient_key"] for e in body["recurring_expenses"]} == {
        "MERCHANT:NETFLIX", "MERCHANT:ร้านกาแฟ", "ACCOUNT:X2660"
    }


def test_analyze_text_upload_endpoint(client):
    with SYNTHETIC_STATEMENT.open("rb") as f:
        resp = client.post(
            "/analyze-text-upload",
            files={"text_file": ("statement.txt", f, "text/plain")},
            data={"current_salary": "30000"},
        )
    assert resp.status_code == 200, resp.text
    assert resp.json()["parsed_transaction_count"] == 14


def test_analyze_rejects_invalid_base64(client):
    resp = client.post("/analyze", json={"statements_pdf_base64": ["not base64!!"], "current_salary": 1000})
    assert resp.status_code == 400


SYNTHETIC_PDF = SYNTHETIC_STATEMENT.with_suffix(".pdf")


def test_analyze_upload_pdf(client):
    with SYNTHETIC_PDF.open("rb") as f:
        resp = client.post(
            "/analyze-upload",
            files={"pdf_files": ("statement.pdf", f, "application/pdf")},
            data={"current_salary": "30000"},
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["parsed_transaction_count"] == 14
    assert body["data_months_available"] == 4
    assert {e["recipient_key"] for e in body["recurring_expenses"]} == {
        "MERCHANT:NETFLIX", "MERCHANT:ร้านกาแฟ", "ACCOUNT:X2660"
    }


def test_analyze_upload_accepts_pdf_with_generic_content_type(client):
    with SYNTHETIC_PDF.open("rb") as f:
        resp = client.post(
            "/analyze-upload",
            files={"pdf_files": ("statement.bin", f, "application/octet-stream")},
            data={"current_salary": "30000"},
        )
    assert resp.status_code == 200, resp.text


def test_analyze_upload_rejects_non_pdf_bytes_with_400(client):
    resp = client.post(
        "/analyze-upload",
        files={"pdf_files": ("statement.pdf", b"hello, not a pdf", "application/pdf")},
        data={"current_salary": "30000"},
    )
    assert resp.status_code == 400
    assert "not a PDF" in resp.json()["detail"]


def test_analyze_upload_rejects_corrupt_pdf_with_400_not_500(client):
    resp = client.post(
        "/analyze-upload",
        files={"pdf_files": ("statement.pdf", b"%PDF-1.4 garbage", "application/pdf")},
        data={"current_salary": "30000"},
    )
    assert resp.status_code == 400
    assert "Could not read PDF" in resp.json()["detail"]


def test_analyze_upload_rejects_oversized_pdf_with_413(client):
    from main import MAX_PDF_BYTES
    big = b"%PDF-1.4" + b"0" * (MAX_PDF_BYTES + 10)
    resp = client.post(
        "/analyze-upload",
        files={"pdf_files": ("statement.pdf", big, "application/pdf")},
        data={"current_salary": "30000"},
    )
    assert resp.status_code == 413


def test_analyze_upload_rejects_malformed_labels_with_400(client):
    with SYNTHETIC_PDF.open("rb") as f:
        resp = client.post(
            "/analyze-upload",
            files={"pdf_files": ("statement.pdf", f, "application/pdf")},
            data={"current_salary": "30000", "existing_user_labels": "[1, 2]"},
        )
    assert resp.status_code == 400
    assert "existing_user_labels" in resp.json()["detail"]


def test_analyze_base64_pdf(client):
    import base64
    encoded = base64.b64encode(SYNTHETIC_PDF.read_bytes()).decode()
    resp = client.post("/analyze", json={"statements_pdf_base64": [encoded], "current_salary": 30000})
    assert resp.status_code == 200, resp.text
    assert resp.json()["parsed_transaction_count"] == 14


def test_analyze_base64_non_pdf_payload_is_400(client):
    resp = client.post("/analyze", json={"statements_pdf_base64": ["aGVsbG8="], "current_salary": 1000})
    assert resp.status_code == 400


def test_openapi_marks_pdf_file_array_as_binary(client):
    schema = client.get("/openapi.json").json()
    body = schema["components"]["schemas"]["Body_analyze_upload_endpoint_analyze_upload_post"]
    assert body["properties"]["pdf_files"]["items"]["format"] == "binary"
