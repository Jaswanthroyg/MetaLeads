# Meta Lead Ads → live React Native screen

A lead submitted through Meta Lead Ads appears **live** in an already-open React Native screen, with no action on the device.

```
Meta webhook (leadgen) → FastAPI → Graph API (fetch lead) → WebSocket → React Native (Expo)
```

## Why this design
- Meta **pushes** a webhook, but it only contains IDs → the server fetches name/email/phone from the Graph API.
- The app cannot be called by the server over plain HTTP → a **WebSocket** pushes new leads instantly.
- New screens receive a `snapshot` of existing leads, then live `lead` messages. The app auto-reconnects with backoff.
- The webhook returns `200` immediately and works in a background task; duplicate deliveries are ignored; the `X-Hub-Signature-256` signature is verified when `APP_SECRET` is set.

## Status (honest)
| Part | Status |
|---|---|
| Server → app live push (WebSocket, reconnect, snapshot, dedupe) | Working, covered by tests |
| Webhook verification handshake with Meta | Verified against Meta (200 OK) |
| Real Testing Tool lead end-to-end | **Not completed**: still needs the Page subscribed to `leadgen` and a Page token with `leads_retrieval` |
| Demo source of leads | `POST /debug/simulate` (fake lead, same pipeline) |

## Run locally
Requirements: Python 3.10+, Node 20+, Expo Go on your phone (same Wi-Fi as the laptop).

**Backend**
```powershell
cd backend
python -m venv venv
.\venv\Scripts\Activate.ps1          # macOS/Linux: source venv/bin/activate
pip install -r requirements.txt
copy .env.example .env               # macOS/Linux: cp .env.example .env
uvicorn main:app --host 0.0.0.0 --port 3000 --reload
pytest                               # optional: run tests
```

**Mobile**
```powershell
cd mobile
npm install
npx expo install expo-constants react-native-safe-area-context
npx expo start
```
Scan the QR with Expo Go. The app finds the laptop IP automatically (from Expo). To override, set `EXPO_PUBLIC_API_HOST` (e.g. a tunnel host).

**Demo:** with the app open and showing the green "Live" dot:
```powershell
Invoke-RestMethod -Method Post http://localhost:3000/debug/simulate
```
A card appears on the phone without any interaction.

## Using real Meta leads (Lead Ads Testing Tool)
1. Expose port 3000 with a tunnel (ngrok / cloudflared).
2. Meta app → Webhooks → object **Page** → callback `https://<tunnel>/webhook`, verify token = `VERIFY_TOKEN`, subscribe field **leadgen**.
3. Put `APP_SECRET` and a Page access token (`leads_retrieval`, `pages_manage_metadata`, `pages_show_list`, `pages_read_engagement`) in `backend/.env`.
4. Subscribe your app to the Page: `POST /<PAGE_ID>/subscribed_apps?subscribed_fields=leadgen` (Graph API Explorer).
5. Open https://developers.facebook.com/tools/lead-ads-testing → pick Page + form → **Create lead**.

## API
| Endpoint | Purpose |
|---|---|
| `GET /webhook` | Meta verification handshake |
| `POST /webhook` | Receives `leadgen` events |
| `WS /ws` | `snapshot` then live `lead` messages |
| `GET /leads`, `GET /health` | Debug |
| `POST /debug/simulate` | Fake lead (disable with `ENABLE_SIMULATE=false`) |

## Known limitations / next steps
In-memory store (use a database), no auth on `/ws` and `/leads`, push notifications (FCM/APNs) for backgrounded apps, Docker/deployment.

## Security
Never commit `.env`. Rotate any token that has been pasted in chat or logs.