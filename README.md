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
    *   **Primary**: Groq llama-3.1-70b-versatile for formatted, concise responses (1-3 sentences)
    *   **Fallback**: Direct search (no LLM) if rate limit (429) is hit
    *   **Auto-Recovery**: Seamlessly switches without user intervention
*   **🔍 RAG Pipeline**:
    *   Semantic search with strict 0.45 distance threshold (high precision)
    *   Automatic web indexing on first query
    *   Self-healing system that caches successful results

## 🚀 Quick Start

### Prerequisites

| Component | Requirement |
|-----------|------------|
| **Python** | 3.10+ |
| **Groq API Key** | [Get here](https://console.groq.com/keys) |
| **Serper API Key** | [Get here](https://serper.dev/) |

### Installation & Setup

1. **Clone repository**
   ```bash
   git clone <your-repo>
   cd ai_gamming_assistant
   ```

2. **Create virtual environment**
   ```bash
   python -m venv .venv
   .venv\Scripts\Activate.ps1  # Windows
   source .venv/bin/activate  # Mac/Linux
   ```

3. **Install dependencies**
   ```bash
   cd backend/rpgagents
   pip install -e .
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
cd backend/rpgagents
python main.py api
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
4. Get instant responses from cached data or web search

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
│  ┌─ Try CrewAI Crew (with LLM)                   │
│  │   ├─ Researcher Agent                         │
│  │  └─ Game Expert Agent (formats)               │
│  │                                                │
│  │  On 429 Rate Limit:                           │
│  └─ Fallback to Direct Search (no LLM)           │
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
      ← JSON Response (streaming)
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
**Current**: `0.45` (very strict, high precision)
- Distance < 0.45 = confidence > 0.55 (return result)
- Distance > 0.45 = trigger web search

Adjust in: [src/rpgagents/tools/game_search_tool.py](backend/rpgagents/src/rpgagents/tools/game_search_tool.py#L86)

### Response Format
File: [config/tasks.yaml](backend/rpgagents/src/rpgagents/config/tasks.yaml)

Default: **1-3 sentences maximum**
- Direct answer first
- Key details/tips
- Source URL

### LLM Temperature
**Current**: `0.3` (more deterministic)

Adjust in: [crew.py](backend/rpgagents/src/rpgagents/crew.py) - Controls creativity/randomness

## 📂 Project Structure

```
ai_gamming_assistant/
├── README.md (this file)
├── .env (API keys configuration)
├── .venv/ (Python virtual environment)
│
├── frontend/
│   ├── index.html          (sidebar UI)
│   ├── styles.css          (gaming aesthetic theme)
│   ├── script.js           (interactivity + API integration)
│   └── README.md           (frontend docs)
│
└── backend/
    └── rpgagents/
        ├── README.md       (backend-specific docs)
        ├── pyproject.toml  (dependencies)
        │
        ├── chroma_db/                     (ChromaDB cache)
        │   └── [game collections]
        │
        ├── knowledge/
        │   └── conversations.sqlite3      (message history)
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
