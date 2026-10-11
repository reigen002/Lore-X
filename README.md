# Lore-X :Gaming Assistant - Embeddable Game Sidebar

**An intelligent, embeddable game sidebar powered by RAG, Web Search, and Smart LLM Fallback.**

The **RPG Gaming Assistant** is a full-stack application with a resizable, toggleable sidebar UI that works in-game. It answers game-related questions using a hybrid approach: cached knowledge (ChromaDB), web search (Serper API + DuckDuckGo), and AI synthesis (Groq), with intelligent fallback when API rate limits are reached.

## Key Features

*   **🎮 Embeddable Sidebar Widget**: Resizable, toggleable right-side panel with gaming aesthetic - works in any browser or game overlay.
*   **💬 Persistent Conversations**: Chat history stored per-game with SQLite, survives restarts and sessions.
*   **🧠 Hybrid Intelligence**:
    *   **Local First**: ChromaDB RAG searches cached game data (instant, free)
    *   **Web Fallback**: Serper API + DuckDuckGo for non-cached queries
    *   **Auto-Caching**: Web results automatically indexed for future queries
*   **⚡ Smart LLM Switching**:
    *   **Primary**: Groq qwen/qwen3.6-27b formats retrieved snippets
    *   **Fallback**: Raw retrieved snippets if formatting fails, including rate limits
    *   **Failure Contract**: Handled failures can remain HTTP 200 strings; see the contract below
*   **🔍 RAG Pipeline**:
    *   Semantic search with a 0.45 distance threshold; this does not establish factual accuracy
    *   Automatic web indexing on first query
    *   Self-healing system that caches successful results

## 🚀 Quick Start

### Prerequisites

| Component | Requirement |
|-----------|------------|
| **Python** | 3.10–3.13 |
| **Groq API Key** | [Get here](https://console.groq.com/keys) |
| **Serper API Key** | [Get here](https://serper.dev/) |

### Installation & Setup

1. **Clone repository**
   ```bash
   git clone <your-repo>
   cd Lore-X
   ```

2. **Create virtual environment**
   ```bash
   python -m venv .venv
   .venv\Scripts\Activate.ps1  # Windows
   source .venv/bin/activate  # Mac/Linux
   ```

3. **Install dependencies**
   ```bash
   # Run from the repository root, where pyproject.toml lives
   python -m pip install -e .
   ```

4. **Configure API keys** (create `.env` in project root)
   ```env
    GROQ_API_KEY=your_key_here
   SERPER_API_KEY=your_key_here
   CHROMA_DB_PATH=./chroma_db
   ```

## 🎮 Running the Application

### **Terminal 1: Start Backend API**
```bash
python -m uvicorn rpgagents.api:app --app-dir backend/rpgagents/src --env-file .env --host 127.0.0.1 --port 8000
```
✅ Backend: **http://127.0.0.1:8000**  
📖 API Docs: **http://127.0.0.1:8000/docs**

### **Terminal 2: Start Frontend Server**
```bash
cd frontend
python -m http.server 3000
```
✅ Frontend: **http://localhost:3000**

### Usage
1. Open browser to `http://localhost:3000`
2. Enter game name (e.g., "Valorant", "Elden Ring")
3. Type your question
4. Read the formatted answer, raw snippets, or failure text returned by the backend

## Backend request and failure contract

Required game names, questions and messages are trimmed and must be nonblank. Invalid required text returns HTTP 422 before search, provider calls or writes. Existing string response fields are preserved: HTTP 200 can carry a formatted answer, raw snippets, no-information text or a handled safe search-failure message. Unexpected API errors return HTTP 500 with generic detail while server logs retain diagnostic tracebacks.

Chat commits the user message before generation and the assistant message afterward. Failures can leave partial turns, and retries append messages. There is no idempotency or whole-turn-atomicity guarantee. The SQLite connection fix closes each operation's connection; it does not change this persistence contract.

This main-based checkout has no MCP server or entry point. No unmerged retrieval/provider implementation was imported. See [main backend reliability](docs/MAIN_BACKEND_RELIABILITY.md) for current behavior, offline commands, setup limits and the SQLite regression.

## 🏗️ Architecture

```
┌──────────────────────────────────────────────────┐
│        Frontend (Port 3000)                       │
│  HTML/CSS/JS Sidebar + LocalStorage State        │
└────────────────┬─────────────────────────────────┘
                 │ HTTP POST /chat
                 ↓
┌──────────────────────────────────────────────────┐
│      Backend (Port 8000 - FastAPI)               │
├──────────────────────────────────────────────────┤
│                                                   │
│   Retrieve cached snippets or search the web      │
│   Groq formats the retrieved snippets             │
│   Formatting failure returns raw snippets         │
│       ↓                                           │
│   GameSearchTool                                  │
│   ├─ ChromaDB (cached)     [Fast ⚡]             │
│   └─ Serper + DuckDuckGo   [Web Search]          │
│       ↓                                           │
│   Conversation Store (SQLite)                    │
│       ↓                                           │
│   Response + ID                                  │
└──────────────────────────────────────────────────┘
                 ↑
      ← JSON Response
                 │
        ┌────────┴──────────┐
        ↓                   ↓
   Frontend Updates    ChromaDB Indexes
   Message List        Web Results
```

## 🪟 Embeddable Widget Behavior

* **Sidebar Toggle**: Click button or press `Ctrl+K` to open/close
* **Game Selection**: Set game name at top
* **Conversation History**: Persists per game in SQLite
* **Message Storage**: User + Assistant messages stored with timestamps
* **Auto-Save**: State saved to localStorage
* **Responsive**: Adjusts width (min 280px, max 600px) via drag


## ⚙️ Configuration

### Relevance Threshold (ChromaDB Distance)
**Current**: `0.45`
- Cached snippets below this distance are eligible for return; no eligible snippets trigger web fallback.
- The displayed distance-derived percentage is not a calibrated probability of factual correctness.

Adjust in: [src/rpgagents/tools/game_search_tool.py](backend/rpgagents/src/rpgagents/tools/game_search_tool.py#L86)

### Response Format
The HTTP formatter requests 2–4 sentences and a source URL when present. Raw-snippet and failure-string fallbacks keep their existing formats. See [main.py](backend/rpgagents/src/rpgagents/main.py).

### LLM Temperature
The HTTP formatter uses temperature 0.2. The separate CrewAI CLI uses temperature 0.3 in [crew.py](backend/rpgagents/src/rpgagents/crew.py).

## 📂 Project Structure

```
Lore-X/
├── README.md (this file)
├── .env (API keys configuration)
├── .venv/ (Python virtual environment)
├── pyproject.toml (package metadata and dependencies)
├── chroma_db/ (default cache when launched from the repository root)
│
├── frontend/
│   ├── index.html          (sidebar UI)
│   ├── styles.css          (gaming aesthetic theme)
│   ├── script.js           (interactivity + API integration)
│   └── README.md           (frontend docs)
│
└── backend/
    ├── knowledge/conversations.sqlite3 (message history)
    └── rpgagents/
        ├── README.md       (backend-specific docs)
        │
        ├── output/                        (generated guides)
        │
        └── src/rpgagents/
            ├── main.py                    (CLI + API startup)
            ├── api.py                     (FastAPI endpoints)
            ├── crew.py                    (CrewAI agents)
            ├── conversation_store.py      (SQLite storage)
            │
            ├── config/
            │   ├── agents.yaml            (agent definitions)
            │   └── tasks.yaml             (task definitions)
            │
            └── tools/
                ├── game_search_tool.py    (RAG + fallback logic)
                └── web_search_tool.py     (Serper + DuckDuckGo)
```

## ✍️ Author

*   **Reigen002** - *Initial work* - [GitHub Profile](https://github.com/reigen002)

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

Copyright (c) 2026 Reigen002. All rights reserved.
