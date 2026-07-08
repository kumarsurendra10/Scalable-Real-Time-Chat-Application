# Scalable Real-Time Chat Application

FastAPI + WebSockets + Redis (pub/sub + cache) + PostgreSQL + Docker.

## Architecture

```
Client (browser/app)
      |
   WebSocket / REST
      |
   Nginx (load balancer)
      |
  ┌───┴───┬───────┬───────┐
 App-1   App-2   App-3   ...   <- FastAPI, stateless, N replicas
  └───┬───┴───┬───┴───┬───┘
      |       |       |
   Redis Pub/Sub (fans out messages to ALL replicas so any
                   client on any instance gets the broadcast)
      |
  PostgreSQL (users, rooms, messages, read receipts)
```

Why this scales: each FastAPI instance only holds websocket connections that
are *physically connected to it*. When a message arrives, it's published to
a Redis channel; every replica is subscribed and re-broadcasts to its own
local connections. So you can add more `app` replicas behind Nginx without
losing message delivery.

## Project structure

```
chat-app/
├── app/
│   ├── main.py              # FastAPI app, lifespan startup
│   ├── config.py            # env-based settings
│   ├── database.py          # async SQLAlchemy engine/session
│   ├── models.py            # User, Room, Message, ReadReceipt
│   ├── schemas.py           # Pydantic request/response models
│   ├── auth.py               # JWT + password hashing
│   ├── redis_client.py       # Redis connection pool
│   ├── websocket_manager.py  # connection registry + pub/sub fan-out
│   └── routers/
│       ├── auth.py           # /auth/register, /auth/login
│       └── chat.py           # /rooms, /rooms/{id}/messages, /ws/chat/{room_id}
├── Dockerfile
├── docker-compose.yml
├── nginx.conf
├── requirements.txt
└── .env.example
```

## 1. Local development (without Docker)

```bash
# 1. Create venv
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

# 2. Install deps
pip install -r requirements.txt

# 3. Run Postgres & Redis locally (or via docker just for these two)
docker run -d --name pg -e POSTGRES_USER=chatuser -e POSTGRES_PASSWORD=chatpass \
  -e POSTGRES_DB=chatdb -p 5432:5432 postgres:16-alpine
docker run -d --name redis -p 6379:6379 redis:7-alpine

# 4. Copy env file
cp .env.example .env
# edit .env -> point DATABASE_URL / REDIS_URL to localhost instead of service names:
# DATABASE_URL=postgresql+asyncpg://chatuser:chatpass@localhost:5432/chatdb
# REDIS_URL=redis://localhost:6379/0

# 5. Run the app
uvicorn app.main:app --reload
```

API docs auto-generated at: `http://localhost:8000/docs`

## 2. Testing the flow

```bash
# Register
curl -X POST http://localhost:8000/auth/register -H "Content-Type: application/json" \
  -d '{"username":"amit","email":"amit@test.com","password":"pass1234"}'

# Login (get JWT)
curl -X POST http://localhost:8000/auth/login \
  -d "username=amit&password=pass1234"

# Create a room (use the access_token from login)
curl -X POST http://localhost:8000/rooms -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"name":"General","is_group":true,"member_usernames":[]}'
```

Connect to WebSocket (e.g. using `wscat`):

```bash
npm install -g wscat
wscat -c "ws://localhost:8000/ws/chat/<ROOM_ID>?token=<TOKEN>"

# then send:
{"type":"message","content":"Hello everyone!"}
{"type":"typing"}
{"type":"read_receipt","message_id":"<MSG_ID>"}
```

## 3. Run everything with Docker Compose (recommended)

```bash
cp .env.example .env
# IMPORTANT: for docker-compose, keep hostnames as service names:
# DATABASE_URL=postgresql+asyncpg://chatuser:chatpass@postgres:5432/chatdb
# REDIS_URL=redis://redis:6379/0

docker compose up --build --scale app=3
```

This starts: Postgres, Redis, 3x FastAPI app containers, and Nginx as the
load balancer on port 80. Hit `http://localhost/docs` or open a WebSocket
to `ws://localhost/ws/chat/<room_id>?token=<TOKEN>` — Nginx will round-robin
you across replicas, and Redis pub/sub keeps everyone in sync.

To scale up/down live:
```bash
docker compose up --scale app=5 -d
```

## 4. Production deployment (end to end)

### Option A — Single VPS (DigitalOcean / AWS EC2 / Hetzner)

1. **Provision a VM** (Ubuntu 22.04, 2 vCPU / 4GB RAM is a fine start).
2. **Install Docker & Compose plugin:**
   ```bash
   curl -fsSL https://get.docker.com | sh
   sudo usermod -aG docker $USER
   ```
3. **Clone your repo onto the server:**
   ```bash
   git clone https://github.com/<you>/chat-app.git
   cd chat-app
   cp .env.example .env
   # set a strong JWT_SECRET_KEY, real DB creds
   ```
4. **Point a domain** (e.g. `chat.yourdomain.com`) at the VM's IP (A record).
5. **Add HTTPS** — easiest is Caddy or certbot+nginx. Simplest: swap the
   `nginx` service for [Caddy](https://caddyserver.com/) which does
   automatic Let's Encrypt TLS with a 3-line Caddyfile, or run certbot
   against the existing nginx.conf.
6. **Launch:**
   ```bash
   docker compose up -d --build --scale app=3
   ```
7. **Set up a systemd/cron watchdog or just rely on `restart: unless-stopped`**
   (already set in compose) so containers survive reboots/crashes.
8. **Logs & monitoring:**
   ```bash
   docker compose logs -f app
   docker stats
   ```

### Option B — Managed platforms (fastest to ship)

- **Railway / Render**: push repo → set env vars → they build from the
  Dockerfile automatically. Add a managed Postgres + Redis add-on from the
  same dashboard (no need to self-host those in Docker).
- **AWS**: ECS Fargate (containers) + RDS Postgres + ElastiCache Redis +
  an Application Load Balancer (ALB) with sticky-less routing — this
  mirrors the Nginx setup but managed. ALB supports WebSockets natively.
- **Google Cloud Run**: works for the REST API, but Cloud Run has request
  timeout limits that make it awkward for long-lived WebSockets — prefer
  GKE or Compute Engine + Docker Compose for the WS-heavy chat service.

### Production checklist
- [ ] Set a strong, random `JWT_SECRET_KEY`
- [ ] Restrict CORS `allow_origins` to your real frontend domain
- [ ] Put Nginx/ALB behind HTTPS (WSS for websockets)
- [ ] Use managed/backed-up Postgres in production (RDS, Cloud SQL, etc.)
- [ ] Turn on Redis persistence (AOF) or use managed Redis if presence/cache loss matters
- [ ] Add rate limiting on `/auth/login` and the WS endpoint (e.g. via Nginx `limit_req`)
- [ ] Add a CI pipeline (GitHub Actions) to build & push the Docker image on every push to `main`
- [ ] Add Alembic migrations instead of `create_all` for schema changes in prod

## 5. Suggested GitHub Actions (CI) — optional next step

Create `.github/workflows/deploy.yml` to build & push the image to Docker
Hub / GHCR on every push to `main`, then SSH into your VPS and run
`docker compose pull && docker compose up -d`. Happy to generate this
workflow file too if you want it.
