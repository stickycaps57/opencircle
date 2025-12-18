import sys
import os

# Add the parent directory to the path so we can import our modules
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.insert(0, parent_dir)

try:
    # Import the FastAPI app from main.py
    from main import app
except ImportError as e:
    # If there's an import error, create a minimal FastAPI app
    from fastapi import FastAPI
    app = FastAPI()
    
    @app.get("/")
    async def root():
        return {"error": f"Import error: {str(e)}", "message": "Please check your dependencies"}

# Vercel expects the app to be available directly