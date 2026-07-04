import hashlib
import hmac
import json

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from janus.github.webhook import verify_signature
from janus.ingest.router import router
from janus.store import repo as store


def sign(body: bytes, secret: str = "test-secret") -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def issue_payload(
    delivery: str, sender_login: str = "human", sender_type: str = "User"
) -> tuple[bytes, dict]:
    payload = {
        "action": "opened",
        "issue": {"number": 7, "title": "bug", "body": "steps"},
        "repository": {"full_name": "dogukanurker/flaskblog"},
        "installation": {"id": 42},
        "sender": {"login": sender_login, "type": sender_type},
    }
    body = json.dumps(payload).encode()
    return body, {
        "x-github-delivery": delivery,
        "x-github-event": "issues",
        "x-hub-signature-256": sign(body),
        "content-type": "application/json",
    }


@pytest.fixture
async def client():
    app = FastAPI()
    app.include_router(router)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class TestSignature:
    def test_valid(self):
        body = b"payload"
        assert verify_signature("s", body, sign(body, "s"))

    def test_invalid(self):
        assert not verify_signature("s", b"payload", "sha256=deadbeef")

    def test_missing(self):
        assert not verify_signature("s", b"payload", None)


class TestWebhookEndpoint:
    async def test_bad_signature_401(self, client):
        body, headers = issue_payload("d1")
        headers["x-hub-signature-256"] = "sha256=wrong"
        resp = await client.post("/webhook", content=body, headers=headers)
        assert resp.status_code == 401

    async def test_happy_path_enqueues(self, client):
        body, headers = issue_payload("d2")
        resp = await client.post("/webhook", content=body, headers=headers)
        assert resp.json() == {"queued": True}
        event = await store.claim_next_event()
        assert event is not None and event.delivery_id == "d2"

    async def test_duplicate_delivery_dedups(self, client):
        body, headers = issue_payload("d3")
        await client.post("/webhook", content=body, headers=headers)
        resp = await client.post("/webhook", content=body, headers=headers)
        assert resp.json() == {"dedup": True}

    async def test_self_event_dropped(self, client):
        body, headers = issue_payload("d4", sender_login="janus-maintainer[bot]", sender_type="Bot")
        resp = await client.post("/webhook", content=body, headers=headers)
        assert resp.json() == {"self": True}
        assert await store.claim_next_event() is None

    async def test_unhandled_event_ignored(self, client):
        body, headers = issue_payload("d5")
        headers["x-github-event"] = "star"
        resp = await client.post("/webhook", content=body, headers=headers)
        assert resp.json() == {"ignored": True}

    async def test_healthz(self, client):
        resp = await client.get("/healthz")
        assert resp.json() == {"ok": True}


class TestStore:
    async def test_claim_marks_processing_and_finish(self):
        await store.enqueue_event("e1", "issues", "opened", "r/r", {})
        event = await store.claim_next_event()
        assert event.status == "processing"
        await store.finish_event(event.id, "done")
        assert await store.claim_next_event() is None

    async def test_approval_lifecycle(self):
        approval = await store.create_approval("r/r", "merge_pr", {"number": 5}, "merge #5")
        await store.resolve_approval(approval.id, "approved")
        claimed = await store.claim_resolved_approvals()
        assert [a.id for a in claimed] == [approval.id]
        assert await store.claim_resolved_approvals() == []

    async def test_resolve_only_touches_pending(self):
        approval = await store.create_approval("r/r", "merge_pr", {"number": 5}, "merge #5")
        await store.resolve_approval(approval.id, "approved")
        await store.resolve_approval(approval.id, "rejected")
        claimed = await store.claim_resolved_approvals()
        assert claimed[0].status == "approved"

    async def test_oss_dev_stub(self, tmp_path, monkeypatch):
        import janus.store.oss as oss_module

        monkeypatch.setattr(oss_module, "DEV_STUB_DIR", tmp_path)
        oss_module.archive.cache_clear()
        key = await oss_module.archive().put_action_detail(1, {"x": 1})
        assert (tmp_path / key).exists()
        oss_module.archive.cache_clear()
