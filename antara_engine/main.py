"""
Main FastAPI application for Antarā Engine
"""

from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List, Optional
import json
import asyncio
import logging

from database import get_db, create_tables, User, ChatMessage, Memory, WorldNode
from chat_service import chat_service
from config import ALLOWED_ORIGINS, DEBUG

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create FastAPI app
app = FastAPI(
    title="Antarā Engine",
    description="The backend engine for the Antarā prototype - A mystical AI companion",
    version="1.0.0",
    debug=DEBUG
)

# Configure CORS
logger.info(f"CORS allowed origins: {ALLOWED_ORIGINS}")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Pydantic models for API
class ChatRequest(BaseModel):
    message: str
    user_id: str

class ChatResponse(BaseModel):
    response: str
    user_id: str
    node_id: Optional[int] = None

class WorldNodeResponse(BaseModel):
    id: int
    title: str
    summary: str
    created_at: str

class MemoryResponse(BaseModel):
    id: int
    text: str
    importance: float
    timestamp: str

class UserCreate(BaseModel):
    user_id: str
    username: str

class UserAction(BaseModel):
    action_text: str

# Startup event
@app.on_event("startup")
async def startup_event():
    """Initialize database and create tables"""
    create_tables()
    logger.info("Antarā Engine started successfully")

# Root endpoint
@app.get("/")
async def root():
    """Root endpoint - API information"""
    return {
        "service": "Antarā Engine",
        "version": "1.0.0",
        "status": "running",
        "description": "The backend engine for the Antarā prototype - A mystical AI companion",
        "endpoints": {
            "health": "/health",
            "chat": "/chat",
            "users": "/users",
            "world": "/world/{user_id}",
            "memories": "/memories/{user_id}"
        }
    }

# Health check endpoint
@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "service": "antara-engine"}

# User management endpoints
@app.post("/users", response_model=dict)
async def create_user(user: UserCreate, db: Session = Depends(get_db)):
    """Create a new user"""
    try:
        # Check if user already exists
        existing_user = db.query(User).filter(User.user_id == user.user_id).first()
        if existing_user:
            return {"message": "User already exists", "user_id": user.user_id}
        
        # Create new user
        db_user = User(user_id=user.user_id, username=user.username)
        db.add(db_user)
        db.commit()
        
        return {"message": "User created successfully", "user_id": user.user_id}
        
    except Exception as e:
        logger.error(f"Error creating user: {e}")
        raise HTTPException(status_code=500, detail="Failed to create user")

@app.get("/users/{user_id}")
async def get_user(user_id: str, db: Session = Depends(get_db)):
    """Get user information"""
    user = db.query(User).filter(User.user_id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    return {
        "user_id": user.user_id,
        "username": user.username,
        "created_at": user.created_at.isoformat()
    }

# Chat endpoints
@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, db: Session = Depends(get_db)):
    """Process chat message and return AI response"""
    try:
        # Ensure user exists
        user = db.query(User).filter(User.user_id == request.user_id).first()
        if not user:
            # Create user if doesn't exist
            user = User(user_id=request.user_id, username=f"user_{request.user_id}")
            db.add(user)
            db.commit()
        
        # Save user message
        await chat_service.save_message(request.user_id, "user", request.message, db)
        
        # Generate AI response
        ai_response, node_id = await chat_service.generate_response(request.message, request.user_id, db)

        # Save AI response
        await chat_service.save_message(request.user_id, "assistant", ai_response, db)

        return ChatResponse(response=ai_response, user_id=request.user_id, node_id=node_id)
        
    except Exception as e:
        logger.error(f"Error in chat endpoint: {e}")
        raise HTTPException(status_code=500, detail="Failed to process chat message")

@app.get("/chat/{user_id}/history")
async def get_chat_history(user_id: str, limit: int = 50, db: Session = Depends(get_db)):
    """Get chat history for a user"""
    try:
        messages = db.query(ChatMessage).filter(
            ChatMessage.user_id == user_id
        ).order_by(ChatMessage.timestamp.desc()).limit(limit).all()
        
        return [
            {
                "id": msg.id,
                "role": msg.role,
                "content": msg.content,
                "timestamp": msg.timestamp.isoformat()
            }
            for msg in reversed(messages)
        ]
        
    except Exception as e:
        logger.error(f"Error getting chat history: {e}")
        raise HTTPException(status_code=500, detail="Failed to get chat history")

# Feature #3: World Map endpoints
@app.get("/world/{user_id}", response_model=List[WorldNodeResponse])
async def get_world_nodes(user_id: str, db: Session = Depends(get_db)):
    """Get all world nodes for a user's inner world map"""
    try:
        nodes = db.query(WorldNode).filter(
            WorldNode.user_id == user_id
        ).order_by(WorldNode.created_at.desc()).all()

        return [
            WorldNodeResponse(
                id=node.id,
                title=node.title,
                summary=node.summary,
                created_at=node.created_at.isoformat()
            )
            for node in nodes
        ]

    except Exception as e:
        logger.error(f"Error getting world nodes: {e}")
        raise HTTPException(status_code=500, detail="Failed to get world nodes")

# Feature #4: Memory Sanctum endpoints
@app.get("/memories/{user_id}", response_model=List[MemoryResponse])
async def get_memories(user_id: str, db: Session = Depends(get_db)):
    """Get all memories for a user"""
    try:
        memories = db.query(Memory).filter(
            Memory.user_id == user_id
        ).order_by(Memory.timestamp.desc()).all()

        return [
            MemoryResponse(
                id=memory.id,
                text=memory.text,
                importance=memory.importance,
                timestamp=memory.timestamp.isoformat()
            )
            for memory in memories
        ]

    except Exception as e:
        logger.error(f"Error getting memories: {e}")
        raise HTTPException(status_code=500, detail="Failed to get memories")

@app.delete("/memory/{memory_id}")
async def delete_memory(memory_id: int, db: Session = Depends(get_db)):
    """Delete a specific memory"""
    try:
        memory = db.query(Memory).filter(Memory.id == memory_id).first()
        if not memory:
            raise HTTPException(status_code=404, detail="Memory not found")

        db.delete(memory)
        db.commit()

        return {"message": "Memory deleted successfully", "memory_id": memory_id}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting memory: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete memory")

# Action anchoring endpoint
@app.post("/world-nodes/{node_id}/action")
async def save_user_action(
    node_id: int,
    user_action: UserAction,
    db: Session = Depends(get_db)
):
    """Save a user action to a specific world node"""
    try:
        result = await chat_service.anchor_action_to_node(node_id, user_action.action_text, db)
        return result

    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error saving user action: {e}")
        raise HTTPException(status_code=500, detail="Failed to save user action")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
