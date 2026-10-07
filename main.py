"""Meta Lead Ads -> live React Native feed.

Meta webhook (leadgen) -> this server -> Graph API (fetch lead) -> WebSocket -> app.
"""
import hashlib
import hmac
import json
import logging
import os
import time
from datetime import datetime, timezone

import httpx
from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, Query, Request, Response, WebSocket, WebSocketDisconnect

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("leads")

VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "")
APP_SECRET = os.getenv("APP_SECRET", "")
PAGE_ACCESS_TOKEN = os.getenv("PAGE_ACCESS_TOKEN", "")
GRAPH_VERSION = os.getenv("GRAPH_VERSION", "v21.0")
ENABLE_SIMULATE = os.getenv("ENABLE_SIMULATE", "true").lower() == "true"
MAX_LEADS = 200

if not VERIFY_TOKEN:
    log.warning("VERIFY_TOKEN is empty: Meta webhook verification will be rejected.")
if not APP_SECRET:
    log.warning("APP_SECRET is empty: webhook signatures are NOT being verified (OK for local demo only).")

app = FastAPI(title="Meta Leads Live")

# ---- In-memory store (swap for a database in production) ----
leads: list[dict] = []  # newest first
seen: set[str] = set()  # dedupe Meta retries
clients: set[WebSocket] = set()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def save_lead(lead: dict) -> bool:
    """Store a lead. Returns False if we have already seen this id."""
    if lead["id"] in seen:
        return False
    seen.add(lead["id"])
    leads.insert(0, lead)
    del leads[MAX_LEADS:]
    return True


async def broadcast(msg: dict) -> None:
    dead = []
    for ws in list(clients):  # copy: set can change while we await
        try:
            await ws.send_json(msg)
        except Exception:
            dead.append(ws)
    for ws in dead:
        clients.discard(ws)


# ---- WebSocket ----
@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    clients.add(ws)
    await ws.send_json({"type": "snapshot", "leads": leads})  # hydrate a freshly opened screen
    try:
        while True:
            await ws.receive_text()  # keep the connection open; client messages are ignored
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        clients.discard(ws)


# ---- Meta webhook ----
def token_ok(token: str | None) -> bool:
    return bool(VERIFY_TOKEN) and token is not None and hmac.compare_digest(
        token.encode(), VERIFY_TOKEN.encode()
    )


@app.get("/webhook")
def verify(
    mode: str = Query(None, alias="hub.mode"),
    token: str = Query(None, alias="hub.verify_token"),
    challenge: str = Query(None, alias="hub.challenge"),
):
    """Meta's verification handshake."""
    if mode == "subscribe" and token_ok(token) and challenge is not None:
        return Response(content=challenge, media_type="text/plain")
    return Response(status_code=403)


def valid_signature(raw: bytes, header: str | None) -> bool:
    if not APP_SECRET:
        return True  # local demo convenience; set APP_SECRET to enforce
    if not header:
        return False
    expected = "sha256=" + hmac.new(APP_SECRET.encode(), raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(header, expected)


@app.post("/webhook")
async def webhook(request: Request, background: BackgroundTasks):
    raw = await request.body()  # Meta signs the exact bytes, so verify before parsing
    if not valid_signature(raw, request.headers.get("x-hub-signature-256")):
        log.warning("Rejected webhook: bad signature")
        return Response(status_code=401)

    try:
        body = json.loads(raw)
    except ValueError:
        return Response(status_code=400)

    if body.get("object") == "page":
        for entry in body.get("entry", []):
            for change in entry.get("changes", []):
                if change.get("field") == "leadgen" and "leadgen_id" in change.get("value", {}):
                    background.add_task(handle_leadgen, change["value"])
    return Response(status_code=200)  # ack fast; Meta retries if we are slow


async def handle_leadgen(v: dict) -> None:
    """The webhook carries only IDs, so fetch the actual answers from the Graph API."""
    leadgen_id = str(v["leadgen_id"])
    log.info("leadgen event %s", leadgen_id)

    fields: dict[str, str] = {}
    status = "ok"
    try:
        url = f"https://graph.facebook.com/{GRAPH_VERSION}/{leadgen_id}"
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(url, params={"access_token": PAGE_ACCESS_TOKEN})
        data = r.json()
        if r.status_code != 200:
            raise RuntimeError(data.get("error", data))
        for f in data.get("field_data", []):
            fields[f["name"]] = ", ".join(f.get("values", []))
    except Exception as e:
        log.error("Graph fetch failed: %s", e)
        status = "fetch_failed"  # still surface the event so nothing is silently lost

    created = v.get("created_time")
    lead = {
        "id": leadgen_id,
        "formId": str(v["form_id"]) if v.get("form_id") else None,
        "pageId": str(v["page_id"]) if v.get("page_id") else None,
        "adId": str(v["ad_id"]) if v.get("ad_id") else None,
        "createdTime": datetime.fromtimestamp(created, timezone.utc).isoformat() if created else now_iso(),
        "receivedAt": now_iso(),
        "status": status,
        "fields": fields,
    }
    if save_lead(lead):
        await broadcast({"type": "lead", "lead": lead})


# ---- Helpers ----
@app.get("/leads")
def get_leads():
    return leads


@app.get("/health")
def health():
    return {"ok": True, "clients": len(clients)}


if ENABLE_SIMULATE:

    @app.post("/debug/simulate")
    async def simulate():
        """Push a fake lead (no Meta needed). Disable with ENABLE_SIMULATE=false."""
        ms = int(time.time() * 1000)
        n = ms % 9000 + 1000
        lead = {
            "id": f"sim_{ms}",
            "createdTime": now_iso(),
            "receivedAt": now_iso(),
            "status": "simulated",
            "fields": {
                "full_name": f"Test User {n}",
                "email": f"test{n}@example.com",
                "phone_number": f"+1555{n}000",
            },
        }
        save_lead(lead)
        await broadcast({"type": "lead", "lead": lead})
        return lead