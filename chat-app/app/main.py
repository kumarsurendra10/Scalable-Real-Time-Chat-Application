from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import init_db
from app.websocket_manager import manager
from app.routers import auth, chat


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await manager.start_listener()
    yield


app = FastAPI(title="Scalable Real-Time Chat API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten this in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(chat.router)


@app.get("/health")
async def health_check():
    return {"status": "ok"}
