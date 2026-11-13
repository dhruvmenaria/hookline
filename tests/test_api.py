import json

import pytest

from conftest import signed_headers


def body_for(mode="success", event_id="evt-1001"):
    payload = {"invoice": "INV-2048", "amount": 12500}
    if mode != "success":
        payload["simulate"] = mode
    return json.dumps({"event_id": event_id, "event_type": "invoice.paid", "source": "demo-billing", "payload": payload}, separators=(",", ":")).encode()


@pytest.mark.asyncio
async def test_rejects_bad_signature_before_persisting(client):
    response = await client.post("/api/events", content=body_for(), headers={
        "X-Hookline-Signature": "bad", "Idempotency-Key": "key-1",
    })
    assert response.status_code == 401
    assert (await client.get("/api/events")).json() == []


@pytest.mark.asyncio
async def test_accepts_and_delivers_event(client):
    raw = body_for()
    response = await client.post("/api/events", content=raw, headers=signed_headers(raw, "key-1"))
    assert response.status_code == 202
    assert response.json()["status"] == "delivered"
    assert response.json()["attempts"] == 1


@pytest.mark.asyncio
async def test_idempotency_returns_original_and_rejects_body_conflict(client):
    first = body_for(event_id="evt-1001")
    second = body_for(event_id="evt-2002")
    await client.post("/api/events", content=first, headers=signed_headers(first, "same-key"))
    duplicate = await client.post("/api/events", content=first, headers=signed_headers(first, "same-key"))
    conflict = await client.post("/api/events", content=second, headers=signed_headers(second, "same-key"))
    assert duplicate.status_code == 202 and duplicate.json()["duplicate"] is True
    assert conflict.status_code == 409


@pytest.mark.asyncio
async def test_transient_failure_can_be_retried(client):
    raw = body_for("transient")
    received = await client.post("/api/events", content=raw, headers=signed_headers(raw, "transient-key"))
    assert received.json()["status"] == "retry_wait"
    retried = await client.post(f"/api/events/{received.json()['id']}/retry", json={})
    assert retried.status_code == 200
    assert retried.json()["status"] == "delivered"
    assert [a["outcome"] for a in retried.json()["delivery_attempts"]] == ["retryable_failure", "success"]


@pytest.mark.asyncio
async def test_permanent_failure_stays_in_dead_letter_after_operator_replay(client):
    raw = body_for("permanent")
    received = await client.post("/api/events", content=raw, headers=signed_headers(raw, "permanent-key"))
    assert received.json()["status"] == "dead_letter"
    retried = await client.post(f"/api/events/{received.json()['id']}/retry", json={})
    assert retried.status_code == 200
    assert retried.json()["status"] == "dead_letter"
    replayed_again = await client.post(f"/api/events/{received.json()['id']}/retry", json={})
    assert replayed_again.status_code == 200
    assert replayed_again.json()["status"] == "dead_letter"
    assert replayed_again.json()["attempts"] == 3


@pytest.mark.asyncio
async def test_delivered_event_cannot_be_retried(client):
    raw = body_for()
    received = await client.post("/api/events", content=raw, headers=signed_headers(raw, "delivered-key"))
    response = await client.post(f"/api/events/{received.json()['id']}/retry", json={})
    assert response.status_code == 409
