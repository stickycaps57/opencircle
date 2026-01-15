from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from fastapi.responses import FileResponse
import os
import traceback


# from .dependencies import get_query_token, get_token_header
# from .internal import admin

print("Starting to import routers...")

try:
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
    print("All routers imported successfully")
except Exception as e:
    print(f"Error importing routers: {str(e)}")
    print(f"Traceback: {traceback.format_exc()}")
    raise

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
frontend_url = os.getenv("FRONTEND_URL", "http://opencircle-fe.s3-website-ap-southeast-1.amazonaws.com")
origins = [
    frontend_url,
    "http://opencircle-fe.s3-website-ap-southeast-1.amazonaws.com",
    "https://opencircle-fe.s3-website-ap-southeast-1.amazonaws.com",
    "http://localhost:5173",  # Fallback for local development
    "http://127.0.0.1:5173",  # Fallback for local development
]

# Add production URL explicitly
if (frontend_url != "http://opencircle-fe.s3-website-ap-southeast-1.amazonaws.com" 
    and frontend_url != "https://opencircle-fe.s3-website-ap-southeast-1.amazonaws.com"):
    origins.append("http://opencircle-fe.s3-website-ap-southeast-1.amazonaws.com")
    origins.append("https://opencircle-fe.s3-website-ap-southeast-1.amazonaws.com")

print(f"CORS origins configured: {origins}")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if os.getenv("ENVIRONMENT") == "development" else origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    return RedirectResponse(url="/docs")
