import sys
import os

# Add the parent directory to the path so we can import our modules
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.insert(0, parent_dir)

try:
    # Import the FastAPI app from main.py
    from main import app
    
    # Add a health check endpoint for debugging
    @app.get("/api/health")
    async def health_check():
        return {
            "status": "healthy",
            "message": "API is running",
            "environment": os.getenv("VERCEL_ENV", "unknown")
        }
        
except ImportError as e:
    # If there's an import error, create a minimal FastAPI app
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware
    
    app = FastAPI()
    
    # Add CORS for debugging
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    @app.get("/")
    async def root():
        return {
            "error": f"Import error: {str(e)}", 
            "message": "Please check your dependencies",
            "environment": os.getenv("VERCEL_ENV", "unknown")
        }
    
    @app.get("/api/health")
    async def health_check():
        return {
            "status": "error",
            "error": f"Import error: {str(e)}",
            "environment": os.getenv("VERCEL_ENV", "unknown")
        }

# Vercel expects the app to be available directly