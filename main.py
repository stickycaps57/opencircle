from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from fastapi.responses import FileResponse
import os

# from .dependencies import get_query_token, get_token_header
# from .internal import admin
from routers import (
    account,
    resource,
    user,
    post,
    event,
    rsvp,
    comment,
    organization,
    shares,
    notification,
    two_factor_auth,
    report,
)

# app = FastAPI(dependencies=[Depends(get_query_token)])
app = FastAPI()
app.include_router(account.router)
app.include_router(resource.router)
app.include_router(user.router)
app.include_router(post.router)
app.include_router(event.router)
app.include_router(rsvp.router)
app.include_router(comment.router)
app.include_router(organization.router)
app.include_router(shares.router)
app.include_router(notification.router)
app.include_router(two_factor_auth.router)
app.include_router(report.router)

# app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

@app.get("/uploads/{file_path:path}")
async def serve_file(file_path: str):
    response = FileResponse(f"uploads/{file_path}")
    return response

# Configure CORS
frontend_url = os.getenv("FRONTEND_URL", "http://localhost:5173")
origins = [
    frontend_url,
    "http://localhost:5173",  # Fallback for local development
    "http://127.0.0.1:5173",  # Fallback for local development
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    return RedirectResponse(url="/docs")
