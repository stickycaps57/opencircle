from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse

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

app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

# Configure CORS
origins = [
    "http://localhost:5173",
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
