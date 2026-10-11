from datetime import datetime
from typing import Annotated
import logging
import os

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, StringConstraints

from rpgagents.conversation_store import ConversationStore
from rpgagents.main import quick_search

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("RPG_API")

app = FastAPI(
    title="RPG Gaming Assistant API",
    description="High-performance SaaS API for RPG Game Guides",
    version="2.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

conversation_store = ConversationStore()
RequiredText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


@app.exception_handler(Exception)
async def unhandled_api_exception(request, exc):
    logger.exception("Unhandled API exception")
    return JSONResponse(
        status_code=500,
        content={"detail": "Unable to process your request. Please try again later."},
    )

class QueryRequest(BaseModel):
    game_name: RequiredText
    query: RequiredText

class QueryResponse(BaseModel):
    game: str
    query: str
    result: str
    timestamp: str


class ConversationCreateRequest(BaseModel):
    game_name: RequiredText
    title: str | None = None


class ConversationResponse(BaseModel):
    id: str
    game_name: str
    title: str
    created_at: str
    updated_at: str


class MessageResponse(BaseModel):
    id: str
    conversation_id: str
    role: str
    content: str
    created_at: str


class ChatRequest(BaseModel):
    game_name: RequiredText
    message: RequiredText
    conversation_id: str | None = None


class ChatResponse(BaseModel):
    conversation_id: str
    game_name: str
    answer: str
    timestamp: str

@app.get("/health")
def health_check():
    return {"status": "online", "model": "groq/qwen/qwen3.6-27b", "version": "2.0.0"}


@app.get("/widget")
def get_widget():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    widget_path = os.path.join(base_dir, "static", "game_slidebar.html")

    if not os.path.exists(widget_path):
        raise HTTPException(status_code=404, detail="Widget not found")

    return FileResponse(widget_path)

@app.post("/ask", response_model=QueryResponse)
def ask_question(request: QueryRequest):
    """
    Submit a game guide request and return the result synchronously.
    """
    try:
        logger.info(f"Processing query: {request.game_name} -> {request.query}")
        result = quick_search(request.game_name, request.query)
        return QueryResponse(
            game=request.game_name,
            query=request.query,
            result=result,
            timestamp=datetime.now().isoformat()
        )
    except Exception:
        logger.exception("Error processing query")
        raise HTTPException(status_code=500, detail="Unable to process your request. Please try again later.") from None


@app.post("/conversations", response_model=ConversationResponse)
def create_conversation(request: ConversationCreateRequest):
    conversation_id = conversation_store.create_or_get_conversation(
        game_name=request.game_name,
        title=request.title,
    )
    convo = conversation_store.get_conversation(conversation_id)
    if convo is None:
        raise HTTPException(status_code=500, detail="Unable to create conversation")
    return convo


@app.get("/conversations", response_model=list[ConversationResponse])
def list_conversations(game_name: str | None = None):
    return conversation_store.list_conversations(game_name=game_name)


@app.get("/conversations/{conversation_id}", response_model=ConversationResponse)
def get_conversation(conversation_id: str):
    convo = conversation_store.get_conversation(conversation_id)
    if convo is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return convo


@app.get("/conversations/{conversation_id}/messages", response_model=list[MessageResponse])
def get_conversation_messages(conversation_id: str):
    convo = conversation_store.get_conversation(conversation_id)
    if convo is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation_store.get_messages(conversation_id)


@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest):
    try:
        logger.info(f"Chat request: game={request.game_name}, message={request.message}")
        
        conversation_id = conversation_store.create_or_get_conversation(
            game_name=request.game_name,
            conversation_id=request.conversation_id,
            title=f"{request.game_name} chat",
        )
        logger.info(f"Conversation ID: {conversation_id}")

        conversation_store.add_message(conversation_id, "user", request.message)
        logger.info("User message stored")

        logger.info("Searching for answer...")
        answer = quick_search(request.game_name, request.message)
        logger.info(f"Answer received: {len(answer)} chars")

        conversation_store.add_message(conversation_id, "assistant", answer)

        return ChatResponse(
            conversation_id=conversation_id,
            game_name=request.game_name,
            answer=answer,
            timestamp=datetime.now().isoformat(),
        )
    except Exception:
        logger.exception("Error processing chat")
        raise HTTPException(status_code=500, detail="Unable to process your request. Please try again later.") from None



if __name__ == "__main__":
    import uvicorn
    # Allow running directly for testing
    uvicorn.run(app, host="0.0.0.0", port=8000)
