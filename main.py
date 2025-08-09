from fastapi import FastAPI

# from .dependencies import get_query_token, get_token_header
# from .internal import admin
from routers import account, resource, user, session, post, event, rsvp, comment

# app = FastAPI(dependencies=[Depends(get_query_token)])
app = FastAPI()
app.include_router(account.router)
app.include_router(resource.router)
app.include_router(user.router)
app.include_router(session.router)
app.include_router(post.router)
app.include_router(event.router)
app.include_router(rsvp.router)
app.include_router(comment.router)


@app.get("/")
async def root():
    return {"message": "Hello Bigger Applications!"}
