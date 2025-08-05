from fastapi import FastAPI

# from .dependencies import get_query_token, get_token_header
# from .internal import admin
from routers import account, resource, user, session

# app = FastAPI(dependencies=[Depends(get_query_token)])
app = FastAPI()
app.include_router(account.router)
app.include_router(resource.router)
app.include_router(user.router)
app.include_router(session.router)


@app.get("/")
async def root():
    return {"message": "Hello Bigger Applications!"}
