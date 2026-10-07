import hashlib
import hmac
import json
import os

os.environ["VERIFY_TOKEN"] = "test-token"
os.environ["APP_SECRET"] = "test-secret"
os.environ["ENABLE_SIMULATE"] = "true"

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402

client = TestClient(main.app)


def sign(body: bytes) -> str:
    return "sha256=" + hmac.new(b"test-secret", body, hashlib.sha256).hexdigest()


def test_verify_ok():
    r = client.get("/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "test-token", "hub.challenge": "123"})
    assert r.status_code == 200 and r.text == "123"


def test_verify_wrong_token():
    r = client.get("/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "nope", "hub.challenge": "123"})
    assert r.status_code == 403


def test_webhook_bad_signature():
    r = client.post("/webhook", content=b"{}", headers={"x-hub-signature-256": "sha256=bad"})
    assert r.status_code == 401


def test_webhook_bad_json():
    body = b"not json"
    r = client.post("/webhook", content=body, headers={"x-hub-signature-256": sign(body)})
    assert r.status_code == 400


def test_webhook_valid_signature_acks():
    body = json.dumps({"object": "page", "entry": []}).encode()
    r = client.post("/webhook", content=body, headers={"x-hub-signature-256": sign(body)})
    assert r.status_code == 200


def test_simulate_pushes_live_over_websocket():
    with client.websocket_connect("/ws") as ws:
        assert ws.receive_json()["type"] == "snapshot"
        lead = client.post("/debug/simulate").json()
        msg = ws.receive_json()
        assert msg["type"] == "lead" and msg["lead"]["id"] == lead["id"]


def test_dedupe():
    lead = {"id": "dup_1", "fields": {}}
    assert main.save_lead(lead) is True
    assert main.save_lead(lead) is False