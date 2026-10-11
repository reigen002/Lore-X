"""RPG Gaming Assistant - Dynamic Multi-Game Support"""
"""
Commands - netstat -ano | findstr :8000
# grab the PID from last column, then:
taskkill /PID <PID> /F
"""
import sys
import os
import warnings
import logging
import subprocess
import webbrowser
from datetime import datetime

warnings.filterwarnings("ignore", category=SyntaxWarning, module="pysbd")
warnings.filterwarnings("ignore", category=DeprecationWarning)

logger = logging.getLogger(__name__)

from rpgagents.crew import Rpgagents
from rpgagents.tools.game_search_tool import GameSearchTool


def direct_search(game_name: str, query: str) -> str:
    """Direct search using GameSearchTool - NO LLM CALLS (faster, free)"""
    try:
        tool = GameSearchTool()
        return tool._run(game_name=game_name, query=query)
    except Exception:
        logger.exception("Direct search failed")
        return "Search temporarily unavailable. Please try again later."


def run():

    """Interactive mode - ask user for game and query"""
    print("\n" + "=" * 70)
    print("🎮 RPG GAMING ASSISTANT - Universal Game Guide")
    print("=" * 70)
    print("Supports ANY RPG game: Hollow Knight, Elden Ring, Dark Souls,")
    print("Skyrim, Baldur's Gate 3, and many more!")
    print("=" * 70)

    # Get game name
    game_name = input(
        "\n📌 Enter the game name (e.g., 'Hollow Knight', 'Elden Ring'): "
    ).strip().replace('\ufeff', '')

    if not game_name:
        print("❌ Game name is required.")
        return 1

    # Get query
    print(f"\n💡 Example queries for {game_name}:")
    print("   - Where to find [item name]")
    print("   - How to defeat [boss name]")
    print("   - Best build for [class/playstyle]")
    print("   - Location of [area/NPC]")

    query = input(f"\n❓ What would you like to know about {game_name}? ").strip().replace('\ufeff', '')

    if not query:
        print("❌ Query is required.")
        return 1

    print(f"\n🔍 Searching: '{query}' for {game_name}...")
    print("=" * 70 + "\n")

    inputs = {
        'game_name': game_name,
        'query': query,
        'current_year': str(datetime.now().year)
    }

    try:
        # --- SMART PROVIDER SWITCHING ---
        # 1. Perform a pre-search to determine if data is local or requires web
        print(f"\n🔍 Checking knowledge base for query...")
        
        # Extracted logic for readability and testing
        # --- CLOUD-ONLY MODE ---
        # We now rely on the Agent to perform the search using its tools.
        print(f"\n🚀 Starting Agent Crew (Cloud-Only)...")
        
        # Initialize with default (Groq)
        rpg_agents = Rpgagents()
        result = rpg_agents.crew().kickoff(inputs=inputs)
        result_text = result.raw if hasattr(result, 'raw') else str(result)
                         
        print("\n" + "=" * 70)
        print("📖 YOUR GAME GUIDE")
        print("=" * 70)
        print(result_text)
        print("=" * 70)

        # Save to file in root 'output' folder
        # Determine path helper: src/rpgagents/main.py -> backend/rpgagents/output
        script_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.abspath(os.path.join(script_dir, '..', '..'))
        output_dir = os.path.join(project_root, 'output')
        
        os.makedirs(output_dir, exist_ok=True)

        filename = f"guide_{game_name.lower().replace(' ', '_')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
        file_path = os.path.join(output_dir, filename)
        
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(result_text)
        print(f"\n💾 Guide saved to: {file_path}")

        return 0

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return 1


def rag_then_format(game_name: str, query: str) -> str:
    """
    Two-step pipeline with strict role separation:
      Step 1 — Pure RAG retrieval via GameSearchTool (ChromaDB → web fallback).
               Zero LLM calls — no agent loop, no tool-calling decisions by LLM.
      Step 2 — Groq LLM called exactly once with retrieved snippets to format
               a clean answer. LLM receives pre-retrieved text; it cannot search.
    Falls back to raw snippets if LLM formatting fails (rate limit, etc).
    """
    # ── Step 1: RAG retrieval — no LLM involved ─────────────────────────────
    logger.info(f"📚 RAG retrieval: '{query}' for '{game_name}'")
    tool = GameSearchTool()
    raw_snippets = tool._run(game_name=game_name, query=query)

    if not raw_snippets or raw_snippets.startswith("Error"):
        logger.warning("RAG retrieval returned no usable results")
        return raw_snippets or "No information found."

    # ── Step 2: LLM for formatting only — receives snippets, cannot search ──
    try:
        from groq import Groq
        client = Groq(api_key=os.getenv("GROQ_API_KEY"))

        prompt = (
            f"You are a concise RPG game guide assistant for {game_name}.\n"
            f"Using ONLY the retrieved information below, answer the player's question "
            f"in 2–4 sentences. End with 'Source: <url>' if a URL is present.\n"
            f"Do NOT add any information not present in the snippets.\n\n"
            f"Player question: {query}\n\n"
            f"Retrieved information:\n{raw_snippets}\n\n"
            f"Answer:"
        )

        response = client.chat.completions.create(
            model="qwen/qwen3.6-27b",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=2048,
        )
        formatted = response.choices[0].message.content.strip()
        # Strip <think>...</think> reasoning blocks (qwen reasoning model outputs these)
        import re
        formatted = re.sub(r"<think>.*?</think>", "", formatted, flags=re.DOTALL).strip()
        logger.info(f"✅ LLM formatted answer ({len(formatted)} chars)")
        return formatted

    except Exception:
        logger.exception("LLM formatting failed; returning raw snippets")
        return raw_snippets


def crew_search(game_name: str, query: str):
    """Full CrewAI agent loop — used only by train/replay/test CLI commands."""
    inputs = {
        'game_name': game_name,
        'query': query,
        'current_year': str(datetime.now().year)
    }
    try:
        result = Rpgagents().crew().kickoff(inputs=inputs)
        return result.raw if hasattr(result, 'raw') else str(result)
    except Exception as e:
        error_msg = str(e)
        if "429" in error_msg or "RESOURCE_EXHAUSTED" in error_msg or "quota" in error_msg.lower():
            logger.warning(f"⚠️ Rate limit hit, falling back to direct RAG: {error_msg}")
            return direct_search(game_name, query)
        raise


def quick_search(game_name: str, query: str):
    """
    Primary API search path.
    Retrieval: GameSearchTool (ChromaDB → web) — zero LLM.
    Formatting: Groq LLM called once on already-retrieved snippets.
    """
    try:
        return rag_then_format(game_name, query)
    except Exception:
        logger.exception("rag_then_format failed; falling back to direct search")
        return direct_search(game_name, query)


def start_api(host: str = "127.0.0.1", port: int = 8000):
    """Start the FastAPI server"""
    import uvicorn
    from rpgagents.api import app
    
    print(f"🚀 Starting RPG Gaming Assistant API on {host}:{port}")
    print(f"📖 API Docs available at http://{host}:{port}/docs")
    print(f"📊 ReDoc available at http://{host}:{port}/redoc")
    
    uvicorn.run(app, host=host, port=port, reload=False)


def train():
    """Train the crew for a given number of iterations."""
    inputs = {
        "game_name": "Hollow Knight",
        "query": "How to get the Mantis Claw",
        'current_year': str(datetime.now().year)
    }
    try:
        Rpgagents().crew().train(
            n_iterations=int(sys.argv[1]),
            filename=sys.argv[2],
            inputs=inputs
        )
        return 0
    except Exception as e:
        print(f"❌ Training error: {e}")
        return 1


def replay():
    """Replay the crew execution from a specific task."""
    try:
        Rpgagents().crew().replay(task_id=sys.argv[1])
        return 0
    except Exception as e:
        print(f"❌ Replay error: {e}")
        return 1


def test():
    """Test the crew with sample queries."""
    test_cases = [
        ("Hollow Knight", "Where to find Mantis Claw"),
        ("Elden Ring", "Best staff for sorcerer build"),
        ("Dark Souls 3", "How to defeat Nameless King"),
    ]

    print("🧪 Running test cases...\n")

    for game, query in test_cases:
        print(f"Testing: {game} - {query}")
        try:
            result = quick_search(game, query)
            print(f"✅ Success - {len(result)} characters")
        except Exception as e:
            print(f"❌ Failed: {e}")
        print("-" * 50)

    return 0


def start_all(backend_host: str = "127.0.0.1", backend_port: int = 8000, frontend_port: int = 3000):
    """Start both backend API and frontend server together"""
    import time
    
    print("\n" + "=" * 70)
    print("🎮 RPG GAMING ASSISTANT - Full Stack Startup")
    print("=" * 70)
    
    # Get the project root
    script_dir = os.path.dirname(os.path.abspath(__file__))
    backend_dir = script_dir  # Backend working directory (where main.py is)
    frontend_dir = os.path.abspath(os.path.join(script_dir, '..', '..', '..', '..', 'frontend'))
    
    print(f"\n📁 Backend directory: {backend_dir}")
    print(f"📁 Frontend directory: {frontend_dir}")
    
    processes = []
    
    try:
        # Start backend API using direct command (more reliable)
        print(f"\n🚀 Starting Backend API on {backend_host}:{backend_port}...")
        backend_process = subprocess.Popen(
            [sys.executable, "main.py", "api"],
            cwd=backend_dir
        )
        processes.append(("Backend API", backend_process))
        print("✅ Backend API process started")
        
        # Wait for backend to be ready
        time.sleep(5)
        
        # Start frontend server
        print(f"\n🚀 Starting Frontend Server on http://localhost:{frontend_port}...")
        frontend_process = subprocess.Popen(
            [sys.executable, "-m", "http.server", str(frontend_port)],
            cwd=frontend_dir
        )
        processes.append(("Frontend Server", frontend_process))
        print("✅ Frontend Server process started")
        
        # Wait a moment then open browser
        time.sleep(2)
        print("\n" + "=" * 70)
        print("✅ BOTH SERVERS ARE RUNNING!")
        print("=" * 70)
        print(f"🌐 Frontend:    http://localhost:{frontend_port}")
        print(f"📖 Backend API: http://{backend_host}:{backend_port}")
        print(f"📊 API Docs:    http://{backend_host}:{backend_port}/docs")
        print("\n⌨️  Press Ctrl+C to stop both servers")
        print("=" * 70 + "\n")
        
        # Try to open browser
        try:
            webbrowser.open(f"http://localhost:{frontend_port}")
            print("🌐 Opening browser...")
        except Exception as e:
            print(f"⚠️  Could not auto-open browser: {e}")
        
        # Keep processes running
        while True:
            time.sleep(1)
            # Check if any process has died
            for name, proc in processes:
                if proc.poll() is not None:
                    print(f"\n❌ {name} has stopped unexpectedly")
                    # Kill remaining processes
                    for _, p in processes:
                        try:
                            p.terminate()
                        except:
                            pass
                    return 1
    
    except KeyboardInterrupt:
        print("\n\n🛑 Shutting down servers...")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        return 1
    finally:
        # Clean up processes
        for name, proc in processes:
            try:
                print(f"⏹️  Stopping {name}...")
                proc.terminate()
                proc.wait(timeout=5)
                print(f"✅ {name} stopped")
            except subprocess.TimeoutExpired:
                print(f"⚠️  Force killing {name}...")
                proc.kill()
            except Exception as e:
                print(f"⚠️  Error stopping {name}: {e}")
        
        print("\n✅ All servers stopped. Goodbye!")
    
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1:
        command = sys.argv[1]
        if command == "api":
            start_api()
        elif command == "all":
            sys.exit(start_all())
        elif command == "train":
            sys.exit(train())
        elif command == "replay":
            sys.exit(replay())
        elif command == "test":
            sys.exit(test())
        else:
            print(f"Unknown command: {command}")
            print("Available commands: api, all, train, replay, test")
            sys.exit(1)

    sys.exit(run())

