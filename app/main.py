from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import auth, rooms, users
from app.core.config import settings
from app.db.database import init_models
from app.ws.routes import router as ws_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_models()
    yield


app = FastAPI(title=settings.APP_NAME, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(users.router)
app.include_router(rooms.router)
app.include_router(ws_router)


@app.get("/health")
async def health():
    """Used by Docker healthcheck + Nginx upstream checks."""
    return {"status": "ok", "instance": settings.INSTANCE_ID}


@app.get("/")
async def root():
    return {"message": f"{settings.APP_NAME} is running", "instance": settings.INSTANCE_ID}
