# 🎮 Backend - RPG Gaming Assistant API

**FastAPI backend with CrewAI multi-agent system, ChromaDB RAG, and smart rate limit fallback.**

Core backend service that powers the game assistant sidebar widget. Handles intelligent search routing, conversation persistence, and seamless LLM fallback when API quotas are exhausted.

## ✨ Key Features

*   **FastAPI REST API**: Six domain operations, plus health and widget routes
*   **🧠 Intelligent Query Routing**:
  *   **HTTP path**: Retrieve cached/web snippets, then invoke Groq formatting
    *   **Formatting failure**: Return raw snippets with the existing HTTP 200 response
    *   **CLI path**: Separate CrewAI agent workflow
*   **Hybrid Search Engine**:
    *   **ChromaDB RAG**: Semantic search on cached game data (instant, free)
    *   **Web Search**: Serper API + DuckDuckGo for non-cached queries
    *   **Auto-Indexing**: Web results automatically cached for future queries
    *   **Relevance Filter**: 0.45 distance threshold; factual accuracy is not established by this setting
*   **Persistent Conversations**:
    *   SQLite database with game-level separation
    *   Message history with timestamps
    *   Indexed queries for fast retrieval
*   **Multi-Agent Workflow**:
    *   **Researcher Agent**: Searches and gathers information
    *   **Game Expert Agent**: Formats answers to 1-3 sentences max

## 🚀 Quick Start

### Prerequisites
| Component | Version |
|-----------|---------|
| **Python** | 3.10–3.13 |
| **Groq API Key** | [Get here](https://console.groq.com/keys) |
| **Serper API Key** | [Get here](https://serper.dev/) |

### Installation

1. **Install dependencies from the repository root** (where the package metadata lives)
   ```bash
   python -m pip install -e .
   ```

2. **Configure API keys** (create `.env` in project root)
   ```env
  GROQ_API_KEY=your_key_here
   SERPER_API_KEY=your_key_here
   CHROMA_DB_PATH=./chroma_db
   ```

### Run Backend

From the repository root in the activated environment:

~~~powershell
python -m uvicorn rpgagents.api:app --app-dir backend/rpgagents/src --env-file .env --host 127.0.0.1 --port 8000
~~~

Create the root .env first. A configured CHROMA_DB_PATH remains relative to the launch directory in this main-based implementation; no shared-path migration is included. The interactive CrewAI CLI can be launched with python -m rpgagents.main after installation.

API documentation: http://127.0.0.1:8000/docs. The current widget asset is absent, so GET /widget returns 404; serve the separate frontend directory for the sidebar.

See [main backend reliability](../../docs/MAIN_BACKEND_RELIABILITY.md) for the tested request/failure contract and offline commands. There is no MCP server or console entry point on this baseline.

## 📡 API Endpoints

### Chat Endpoint (Main)
```
POST /chat

Request:
{
  "game_name": "Valorant",
  "message": "best agent for beginners?",
  "conversation_id": "optional-uuid"  # Auto-generated if omitted
}

Response:
{
  "conversation_id": "550e8400-e29b-41d4-a716-446655440000",
  "game_name": "Valorant",
  "answer": "Phoenix, Sage, and Brimstone are great for beginners...",
  "timestamp": "2026-05-02T12:34:56.789Z"
}
```

### Conversation Management

```
POST /conversations
Create new conversation

GET /conversations?game_name=Valorant
List conversations by game

GET /conversations/{conversation_id}
Get single conversation details

GET /conversations/{conversation_id}/messages
Fetch all messages in conversation
```

### Widget
```
GET /widget
Currently returns 404 because the expected static asset is absent
```

## 🧠 Query Processing Pipeline

POST /chat validates required text, creates or reuses a conversation, and commits the user message. quick_search invokes rag_then_format: GameSearchTool retrieves cached snippets or performs its existing web fallback, then Groq formats the retrieved text. Formatting exceptions return raw snippets. An escaping retrieval/initialization failure invokes direct search; its errors now return safe text. The assistant string is committed separately.

POST /ask uses the same answer path without conversation writes. Neither endpoint has a typed outcome discriminator: handled no-information and search-failure strings can still use HTTP 200. Unexpected API exceptions use safe HTTP 500 JSON and server tracebacks.

Retrying an existing conversation appends another user message and, on success, an assistant message. A generation exception can leave the first user message committed. No idempotency or whole-turn atomicity is implemented. The connection-lifetime fix preserves these separate commits.

The existing distance threshold and indexing behavior are unchanged. This patch adds no BM25/vector fusion, expanded context, corrective web rounds, provider admission logic or evidence assessment.

## 🏗️ Architecture

### Directory Structure
```
src/rpgagents/
├── main.py                    # Entry point, CLI, API startup
├── api.py                     # Six domain operations plus health/widget
├── crew.py                    # CrewAI agents definition
├── conversation_store.py      # SQLite conversation storage
│
├── config/
│   ├── agents.yaml            # Agent personality/roles
│   └── tasks.yaml             # Task descriptions/outputs
│
└── tools/
    ├── game_search_tool.py    # RAG search + fallback logic
    └── web_search_tool.py     # Serper API + DuckDuckGo
```

### Database Schema

#### conversations table
```sql
CREATE TABLE conversations (
    id TEXT PRIMARY KEY,
    game_name TEXT NOT NULL,
    title TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX idx_conversations_game ON conversations(game_name);
```

#### messages table
```sql
CREATE TABLE messages (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    role TEXT NOT NULL,  -- 'user' or 'assistant'
    content TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(conversation_id) REFERENCES conversations(id)
);
CREATE INDEX idx_messages_conversation ON messages(conversation_id, created_at);
```

Location: <repository root>/backend/knowledge/conversations.sqlite3. Game names are metadata and filters; existing conversation IDs are not checked against the request game.

### ChromaDB Structure

**Location**: `chroma_db/`

**Collections**: One per game
- `game_valorant`
- `game_hollow_knight`
- `game_elden_ring`
- etc.

**Documents**: Web search results, indexed automatically
- **Metadata**: game_id and source
- **Embedding**: Sentence Transformers (all-MiniLM-L6-v2)
- **Distance Threshold**: 0.45 (strict relevance filter)

## ⚙️ Configuration

### Relevance Threshold (RAG)
**File**: [tools/game_search_tool.py](src/rpgagents/tools/game_search_tool.py#L86)
**Current**: `0.45`
- Cached snippets below this distance are eligible for return; no eligible snippets trigger web fallback.
- The displayed distance-derived percentage is not a calibrated probability of factual correctness.

### Response Format and LLM Settings

The HTTP path requests a 2–4 sentence answer from Groq qwen/qwen3.6-27b at temperature 0.2 with max_tokens=2048. Formatting failures preserve raw snippets. The separate CrewAI CLI uses its task configuration and a Groq LLM at temperature 0.3. Provider/model configuration is unchanged by this reliability patch.

### Web Search
**Primary**: Serper API (google.serper.dev)
**Fallback**: DuckDuckGo (ddgs package)
**Filters**:
- Language: English only
- Domains: Prefer trusted gaming wikis; other unblocked results may also be included
- Blocks: Non-English sites (baidu.com, qq.com, etc.)

## 🔄 Error Handling

Required game_name, query and message fields are trimmed and must contain at least one character. Missing, incompatible or blank required text returns 422 before search/provider calls or database writes. Optional titles, filters and IDs retain their previous contract.

HTTP 200 can contain formatted text, raw snippet fallback, no-information text or safe handled search-error text. Formatting exceptions, including rate limits, return raw snippets and log a traceback. Unexpected /ask, /chat and CRUD exceptions produce safe HTTP 500 JSON; diagnostic details remain server-side. Unknown conversation reads still return 404; an unknown ID supplied to /chat creates a new conversation.

Each message commits separately. Retries append; partial turns remain possible. The connection context closes SQLite handles after success or failure without making a whole turn atomic. There is no MCP interface on this main-based checkout.

## 📊 Technologies

| Component | Technology | Purpose |
|-----------|-----------|---------|
| **API** | FastAPI 0.104+ | REST endpoints |
| **Server** | Uvicorn | ASGI server |
| **RAG** | ChromaDB | Semantic search |
| **Embeddings** | Sentence Transformers | Vector generation |
| **Search** | Serper API + DuckDuckGo | Web search |
| **Web Scraping** | BeautifulSoup4 | Extract search results |
| **LLM** | Groq qwen/qwen3.6-27b | Response formatting |
| **Agents** | CrewAI | Multi-agent orchestration |
| **Database** | SQLite | Message storage |
| **Task Queue** | Optional: Celery/Redis | Async processing |

## 🧪 Testing

### Test Chat Endpoint
```bash
curl -X POST http://127.0.0.1:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"game_name":"Valorant","message":"best agent for beginners?"}'
```

### Test Caching
This is an optional live observation, outside the offline reliability suite. With a previously unindexed game, inspect the web-search and indexing logs on the first query. Repeat the query and inspect whether eligible cached snippets were returned. A repeat query can still search again if cached snippets fail the distance filter; no hit rate or speedup is claimed.

### Offline Reliability Tests

From the repository root in the activated environment:

~~~powershell
python -m unittest discover -s backend/rpgagents/tests -p 'test_api_reliability.py'
python -m unittest discover -s backend/rpgagents/tests -p 'test_conversation_store.py'
python -m unittest discover -s backend/rpgagents/tests -p 'test_*.py'
~~~

Tests use temporary SQLite, mocked external calls, and guards against normal Chroma access and model downloads. They assert client responses, diagnostic tracebacks and committed state; invalid-input tests also inspect SQL traces for attempted writes. No live quota exhaustion is needed. Main had no pre-existing automated suite; these tests do not import develop's evaluator or its live tests.

### Check Database
```bash
sqlite3 -readonly backend/knowledge/conversations.sqlite3
sqlite> SELECT * FROM conversations;
sqlite> SELECT * FROM messages;
```

### Monitor ChromaDB
```python
from chromadb import Client
client = Client()
collection = client.get_collection("game_valorant")
print(f"Documents in collection: {collection.count()}")
```

## 🚀 Production Deployment

### Optimizations
1. **Disable reload**: Remove `reload=True` in main.py
2. **Use Gunicorn**: `gunicorn src.rpgagents.api:app --workers 4`
3. **Environment Variables**: Use `python-dotenv` (already integrated)
4. **Database**: Consider migrating from SQLite to PostgreSQL for multi-user
5. **Caching**: Add Redis for query result caching

### Security
1. Enable CORS only for trusted domains
2. Add API key authentication for `/chat` endpoint
3. Rate limit endpoints (FastAPI middleware)
4. Validate input length (prevent injection)
5. Use HTTPS in production

### Scaling
1. Implement request queuing (Celery + Redis)
2. Shard ChromaDB collections by game/region
3. Cache Groq responses in Redis
4. Use connection pooling for SQLite → PostgreSQL
5. Monitor API quota usage

## 📝 Known Limitations

1. **ChromaDB Size**: In-memory by default, grows with cached queries
   - Solution: Implement periodic cleanup or use persistent backend

2. **Groq Rate Limits**: Vary by plan and model
  - Solution: Automatic fallback works ✅ or upgrade tier

3. **Serper Quota**: Limited free tier calls
   - Solution: Prioritize cached searches, upgrade if needed

4. **SQLite Concurrency**: Not ideal for multi-user
   - Solution: Use PostgreSQL in production

## 🔧 Troubleshooting

### "Cannot find module rpgagents"
```bash
cd backend/rpgagents
pip install -e . --force-reinstall --no-deps
```

### "429 RESOURCE_EXHAUSTED"
- ✅ Expected - system auto-falls back
- Check logs for confirmation
- Upgrade API tier if frequently hitting limit

### "No results found"
1. Verify ChromaDB is initialized: `ls chroma_db/`
2. Check distance threshold isn't too strict
3. Try web search with: `SERPER_API_KEY` set

### "API won't start"
1. Verify port 8000 is free: `lsof -i :8000`
2. Check Python version: `python --version` (need 3.10+)
3. Verify dependencies: `pip list | grep fastapi`

## 📄 License

MIT License - See [LICENSE](../../LICENSE) file
