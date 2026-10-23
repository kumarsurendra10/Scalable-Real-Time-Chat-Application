# Scalable Real-Time Chat Application

A horizontally-scalable, real-time group chat backend built with **FastAPI + WebSockets**,
using **Redis pub/sub** as the cross-instance message bus and **PostgreSQL** for durable
storage. Containerized with **Docker**, running **3 app replicas behind Nginx** to
demonstrate the scaling story end-to-end on a single machine.

## Features

- JWT-based authentication (register / login)
- Group chat rooms with membership (owner / admin / member roles)
- Real-time bi-directional messaging over WebSockets
- **Read receipts** — persisted per user per message, broadcast live
- **Typing indicators**
- **User presence tracking** (online/offline) via Redis TTL keys + heartbeat ping
- Message history with pagination (`before_id` cursor)
- Horizontally scalable: 3 stateless app replicas behind Nginx, correctness guaranteed
  by Redis pub/sub fan-out (not in-memory state)
- Dockerized, with health checks on every service

## Why this architecture (the interview-relevant bit)

The core problem with "just add more app servers" for a WebSocket chat app is that a
WebSocket connection is **stateful and pinned to one process**. If user A is connected
to replica `app1` and user B is connected to replica `app3`, a naive in-memory broadcast
on `app1` never reaches `app3`, silently dropping the message for B.

**The fix:** every app replica keeps a `ConnectionManager` (`app/ws/manager.py`) that
only tracks the WebSocket objects held **locally**. When a client sends a chat message,
typing event, or read receipt, the replica:

1. Persists it to PostgreSQL if it needs to be durable (message / read receipt).
2. Publishes an event to a **Redis pub/sub channel** scoped to that room (`app/core/redis_client.py`).

Every replica also runs a background listener subscribed to that same channel
(`app/ws/routes.py::redis_listener`). When *any* replica publishes, *all* replicas
receive it and relay it to whichever locally-connected sockets belong to that room —
regardless of which replica the sender was on. This is what makes `docker-compose.yml`'s
3 replicas + Nginx actually correct instead of just "3 processes that sometimes work."

Presence works the same way: Redis keys with a short TTL act as a heartbeat. The client
pings periodically; as long as the key hasn't expired, the user shows online. This means
presence survives a WebSocket hiccup gracefully and doesn't need sticky state anywhere.

## Tech stack

| Layer | Choice | Why |
|---|---|---|
| API framework | FastAPI | async-native, WebSocket support built in, automatic OpenAPI docs |
| Real-time transport | Native WebSockets | lower overhead than long-polling / SSE for bi-directional chat |
| Message bus | Redis Pub/Sub | simple, low-latency fan-out; also doubles as the presence store |
| Database | PostgreSQL (async via `asyncpg` + SQLAlchemy 2.0) | relational integrity for users/rooms/messages/read receipts |
| Auth | JWT (python-jose) + bcrypt (passlib) | stateless auth, scales horizontally with no session affinity needed |
| Reverse proxy / LB | Nginx | terminates client connections, load-balances across replicas, handles WS upgrade headers |
| Containerization | Docker + Docker Compose | reproducible multi-service local deployment |

## Project layout

```
chat_app/
├── app/
│   ├── main.py              # FastAPI app, router registration, lifespan (create tables)
│   ├── core/
│   │   ├── config.py        # Settings (env-driven)
│   │   ├── security.py      # password hashing + JWT
│   │   └── redis_client.py  # pub/sub + presence helpers
│   ├── db/
│   │   ├── database.py      # async engine/session
│   │   └── models.py        # User, Room, RoomMember, Message, ReadReceipt
│   ├── schemas/              # Pydantic request/response models
│   ├── api/
│   │   ├── auth.py          # /auth/register, /auth/login
│   │   ├── users.py         # /users/me, /users/search
│   │   ├── rooms.py         # room CRUD, message history, presence, read receipts
│   │   └── deps.py          # get_current_user (HTTP + WS variants)
│   └── ws/
│       ├── manager.py       # per-replica local connection registry
│       └── routes.py        # /ws/rooms/{room_id} — the real-time endpoint
├── tests/                    # pytest + SQLite + fakeredis (no external services needed)
├── static_test_client/       # a plain HTML page to manually poke the WS API in a browser
├── nginx/nginx.conf          # load balancer config (WS-aware)
├── docker-compose.yml        # postgres + redis + 3 app replicas + nginx
├── Dockerfile
└── .env.example
```

## Running locally with Docker (recommended)

```bash
cp .env.example .env          # edit JWT_SECRET_KEY at minimum
docker compose up --build
```

This starts: Postgres, Redis, 3 FastAPI replicas (`app1`, `app2`, `app3`), and Nginx on
`http://localhost:8000`. Open `static_test_client/index.html` in a browser (set API base
to `http://localhost:8000`), register two users in two tabs, create a room, and chat —
each request is load-balanced by Nginx across the 3 replicas.

## Running locally without Docker (dev mode)

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
# point DATABASE_URL at a local Postgres and REDIS_URL at a local Redis in .env
uvicorn app.main:app --reload
```

## Running the tests

```bash
pip install -r requirements.txt fakeredis
pytest tests/ -v
```

Tests use an in-memory SQLite database and `fakeredis` so they run without any external
services — 10 tests covering auth, room membership/authorization, and a full WebSocket
message round-trip through the Redis pub/sub path.

## Deploying to the cloud (Render + Neon + Upstash)

- **Postgres** → use a managed provider like [Neon](https://neon.tech); set `DATABASE_URL`
  to its `postgresql+asyncpg://...` connection string.
- **Redis** → e.g. [Upstash](https://upstash.com). **Important:** use the connection
  string from Upstash's **TCP** tab (`rediss://default:<password>@<host>:<port>`), not
  the REST API URL from the "REST API" tab — the app talks to Redis over the native
  protocol (`redis-py`), not HTTP.
- **App** → deploy the `Dockerfile` as a web service on Render (or similar). For a single
  Render service you'd typically run one replica; the 3-replica + Nginx setup in
  `docker-compose.yml` is for demonstrating the horizontal-scaling architecture locally.

## API overview

| Method | Path | Description |
|---|---|---|
| POST | `/auth/register` | Create account, returns JWT |
| POST | `/auth/login` | Returns JWT |
| GET | `/users/me` | Current user profile |
| GET | `/users/search?q=` | Find users by username |
| POST | `/rooms` | Create room (optionally invite members) |
| GET | `/rooms` | List my rooms |
| POST | `/rooms/{id}/join` | Join a room |
| GET | `/rooms/{id}/messages` | Paginated message history |
| GET | `/rooms/{id}/members/presence` | Online/offline status of room members |
| POST | `/rooms/{id}/messages/{msg_id}/read` | Mark a message read (also via WS) |
| WS | `/ws/rooms/{id}?token=<jwt>` | Real-time connection: send `message` / `typing` / `read` / `ping` events |

Full interactive docs available at `/docs` (Swagger UI) once running.

## Honest limitations / what I'd add next

- No message editing/deletion, file/image attachments, or push notifications.
- Presence "offline" on disconnect is best-effort (cleared immediately if the user has no
  other local connections on that replica) but ultimately relies on the TTL heartbeat as
  the source of truth — a hard process crash is covered by the TTL, not the disconnect handler.
- No Alembic migrations wired up yet (tables are created via `create_all` at startup) —
  fine for a portfolio project, not how I'd do schema changes in a real production system.
- Rate limiting / abuse protection on the WebSocket endpoint isn't implemented.

---

## Interview prep

**30-second elevator pitch:**
"I built a real-time chat backend in FastAPI that supports group messaging, read
receipts, typing indicators, and presence over WebSockets. The interesting engineering
problem was making it horizontally scalable — a WebSocket connection is pinned to one
server process, so I used Redis pub/sub as a message bus between replicas: any app
instance can publish an event, and every instance relays it to its own locally-connected
clients. I run 3 replicas behind Nginx in Docker Compose to actually prove that out, with
Postgres for durable storage of users, rooms, and messages."

**Likely questions and how to answer them:**

- *"What happens if Redis goes down?"* — Pub/sub messages in flight are lost (Redis
  pub/sub isn't persistent/replayed), so live delivery stops, but message history is
  safe since it's written to Postgres independently before publishing. A production
  fix would be Redis Streams or a proper message queue (Kafka/RabbitMQ) for at-least-once
  delivery.
- *"Why not just use Socket.IO / a managed service like Pusher?"* — Valid alternative;
  I chose raw WebSockets + Redis to actually understand and demonstrate the scaling
  mechanics rather than delegate them to a library/vendor.
- *"How do you handle a user connected on two devices?"* — `ConnectionManager` tracks a
  `set` of WebSocket connections per user per room, so both devices get every broadcast.
- *"How would you scale the database?"* — Read replicas for message history reads,
  partitioning `messages` by room_id or time range if it got large, and moving to
  Alembic-managed migrations.
- *"Why JWT instead of sessions?"* — Stateless auth means any replica can validate a
  token without shared session storage — fits the horizontally-scaled design.
