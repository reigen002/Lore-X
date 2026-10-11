"""Local game documentation search tool with optional caching"""
from crewai.tools import BaseTool
from pydantic import BaseModel, Field, PrivateAttr
import chromadb
import os
import logging

logger = logging.getLogger(__name__)

class GameSearchInput(BaseModel):
    game_name: str = Field(description="Full game name (e.g., 'Hollow Knight', 'Elden Ring')")
    query: str = Field(description="Search query about game mechanics, items, locations, etc.")


class GameSearchTool(BaseTool):
    name: str = "Search Game Information"
    description: str = (
        "Primary search tool. Searches local documentation cache first, then the web as fallback. "
        "Always use this tool for any game query. "
        "Input: 'game_name' (e.g. 'Hollow Knight') and 'query' (e.g. 'how to get void heart'). "
        "Returns concise answer snippets with source citations. DO NOT echo the raw output — "
        "synthesize the facts into your response."
    )
    args_schema: type[BaseModel] = GameSearchInput

    # Max characters per snippet shown to the agent
    _SNIPPET_LIMIT: int = 300
    # Max number of snippets to return (keeps agent context tight)
    _MAX_SNIPPETS: int = 3

    _chroma_client: chromadb.PersistentClient = PrivateAttr()
    _embeddings: object = PrivateAttr()

    def __init__(self, **data):
        super().__init__(**data)

        # Initialize ChromaDB
        db_path = os.getenv("CHROMA_DB_PATH", "./chroma_db")
        self._chroma_client = chromadb.PersistentClient(path=db_path)

        # Initialize embeddings (using sentence-transformers for local, free embeddings)
        try:
            from chromadb.utils import embedding_functions
            self._embeddings = embedding_functions.SentenceTransformerEmbeddingFunction(
                model_name="all-MiniLM-L6-v2"
            )
        except Exception as e:
            logger.warning(f"Failed to load embeddings: {e}")
            self._embeddings = None

    @staticmethod
    def _is_nav_chunk(text: str) -> bool:
        """Return True if text looks like a wiki navigation menu, not article prose."""
        import re
        # Strip whitespace and count characters
        stripped = text.strip()
        if len(stripped) < 80:
            return True  # Too short to be useful prose
        # Nav menus have many consecutive UppercaseWord tokens with no sentence structure
        # e.g. "WorldWorld InformationLocationsGreymane Camp..."
        # Heuristic: if >40% of 'words' are CamelCase/AllCaps and there are no sentence-ending chars
        words = re.findall(r'[A-Za-z]+', stripped)
        if not words:
            return True
        upper_words = sum(1 for w in words if w[0].isupper() and len(w) > 2)
        has_sentence = bool(re.search(r'[.!?]', stripped))
        nav_ratio = upper_words / len(words)
        # Nav if >60% uppercase-starting words AND no sentence punctuation
        return nav_ratio > 0.60 and not has_sentence

    def _run(self, game_name: str, query: str) -> str:
        """Search indexed game documentation"""
        try:
            # Normalize to get game_id
            game_id = game_name
            normalized_game_id = game_id.lower().replace(" ", "_").replace("-", "_")
            
            # 0. AUTO-INGEST LOCAL FILES
            # Check if there are any new local files to ingest before searching
            self._ingest_local_files(normalized_game_id)
            
            collection_name = f"game_{normalized_game_id}"

            # Check if collection exists
            existing_collections = [c.name for c in self._chroma_client.list_collections()]
            
            # Helper to perform the vector search
            def perform_search(coll_name, n: int = 5):
                collection = self._chroma_client.get_collection(
                    name=coll_name,
                    embedding_function=self._embeddings
                )
                result = collection.query(
                    query_texts=[query],
                    n_results=n,
                    include=["documents", "metadatas", "distances"]
                )
                if result['distances'] and result['distances'][0]:
                    logger.info(f"🔍 Search Distances: {result['distances'][0]}")
                return result

            if collection_name in existing_collections:
                results = perform_search(collection_name, n=5)

                # Lower distance = better match.
                # Threshold 0.45: 0.3-0.4 = excellent, 0.4-0.5 = good, 0.5+ = poor
                best_distance = (
                    results['distances'][0][0]
                    if results['distances'] and results['distances'][0]
                    else 1.0
                )

                if best_distance > 0.45:
                    logger.warning(
                        f"Local result relevance low (distance {best_distance:.4f} > 0.45). "
                        "Triggering Web Search fallback."
                    )
                    # Fall through to web search logic below
                else:
                    # Collect chunks that meet the confidence threshold
                    valid_snippets = []
                    for doc, dist, meta in zip(
                        results['documents'][0],
                        results['distances'][0],
                        results['metadatas'][0],
                    ):
                        if dist < 0.45:
                            source = meta.get('source', 'local cache')
                            snippet = doc.strip()[: self._SNIPPET_LIMIT]
                            if len(doc.strip()) > self._SNIPPET_LIMIT:
                                snippet += "..."
                            conf_pct = int((1 - dist) * 100)
                            valid_snippets.append(
                                f"{snippet}\n   — Source: {source} (confidence {conf_pct}%)"
                            )

                    if valid_snippets:
                        logger.info(
                            f"✅ Returning {len(valid_snippets)} local cache hits (dist < 0.45)"
                        )
                        bullets = "\n".join(
                            f"• {s}" for s in valid_snippets[: self._MAX_SNIPPETS]
                        )
                        return (
                            f"Relevant information about {game_name} from local cache:\n"
                            f"{bullets}"
                        )
                    else:
                        logger.warning(
                            f"⚠️ No chunks met threshold. Best: {best_distance:.4f}. "
                            "Falling back to web search."
                        )
                        # Fall through to web search logic below

            # --- Fallback: No local docs or no results found ---
            # Trigger web search
            logger.info(f"Checking web for '{game_id}'...")
            from rpgagents.tools.web_search_tool import WebSearchTool
            web_tool = WebSearchTool()
            
            # Use the original game_id (which might be "Hollow Knight") for web search
            web_results = web_tool.search(game_id, query)
            
            if not web_results:
                 return (
                    f"No local documentation indexed for '{normalized_game_id}' and web search returned no results. "
                    f"Available games: {', '.join([c.replace('game_', '') for c in existing_collections if c.startswith('game_')])}. "
                )

            # Index the found results
            docs_to_index = [r['content'] for r in web_results]
            sources_to_index = [r['href'] for r in web_results]
            
            logger.info(f"Indexing {len(docs_to_index)} new documents for {normalized_game_id}")
            self.index_documents(normalized_game_id, docs_to_index, sources_to_index)
            
            # Search the freshly-indexed collection
            results = perform_search(collection_name, n=5)

            if not results['documents'] or not results['documents'][0]:
                return "Indexed new content but search yielded no results. This is unexpected."

            # Build plain-prose bullets — skip nav-menu chunks, cap at _MAX_SNIPPETS
            snippets = []
            for doc, metadata in zip(
                results['documents'][0], results['metadatas'][0]
            ):
                text = doc.strip()
                if self._is_nav_chunk(text):
                    logger.debug("Skipping nav-menu chunk")
                    continue
                source = metadata.get(
                    'source', web_results[0]['href'] if web_results else 'web'
                )
                snippet = text[: self._SNIPPET_LIMIT]
                if len(text) > self._SNIPPET_LIMIT:
                    snippet += "..."
                snippets.append(f"{snippet}  (source: {source})")
                if len(snippets) >= self._MAX_SNIPPETS:
                    break

            if not snippets:
                # All chunks were nav menus — return the raw snippet from the first web result
                fallback = web_results[0]['content'][: self._SNIPPET_LIMIT] if web_results else ""
                source_url = web_results[0]['href'] if web_results else ''
                return (
                    f"Information about {game_name}:\n"
                    f"• {fallback}  (source: {source_url})"
                )

            bullets = "\n".join(f"• {s}" for s in snippets)
            return (
                f"Relevant information about {game_name} from the web:\n"
                f"{bullets}"
            )

        except Exception:
            logger.exception("Local search failed")
            return "Error searching local docs. Please try again later."

    def _ingest_local_files(self, game_id: str):
        """Scan data/raw/{game_id} for .txt files and ingest them."""
        import glob
        
        # Paths
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
        raw_data_dir = os.path.join(project_root, 'data', 'raw', game_id)
        
        if not os.path.exists(raw_data_dir):
            return

        txt_files = glob.glob(os.path.join(raw_data_dir, "*.txt"))
        if not txt_files:
            return

        logger.info(f"Found {len(txt_files)} local text files for '{game_id}'. Ingesting...")
        
        documents = []
        sources = []
        
        for txt_file in txt_files:
            try:
                with open(txt_file, 'r', encoding='utf-8') as f:
                    content = f.read().replace('\r', '')
                    if content.strip():
                        documents.append(content)
                        sources.append(os.path.basename(txt_file))
            except Exception as e:
                logger.error(f"Error reading {txt_file}: {e}")

        if documents:
            self.index_documents(game_id, documents, sources)
            logger.info(f"Successfully ingested local files: {sources}")

    def index_documents(self, game_id: str, documents: list[str], sources: list[str]) -> str:
        """Index documents for a game (for caching web results)"""
        try:
            from langchain_text_splitters import RecursiveCharacterTextSplitter

            game_id = game_id.lower().replace(" ", "_").replace("-", "_")
            collection_name = f"game_{game_id}"

            # Get or create collection
            collection = self._chroma_client.get_or_create_collection(
                name=collection_name,
                embedding_function=self._embeddings
            )

            # Split documents into chunks. 1000 chars provides better context for complete items.
            splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)

            all_chunks = []
            all_metadatas = []
            all_ids = []

            for doc, source in zip(documents, sources):
                chunks = splitter.split_text(doc)
                for j, chunk in enumerate(chunks):
                    all_chunks.append(chunk)
                    all_metadatas.append({"source": source, "game_id": game_id})
                    # Create a unique ID based on source and index to avoid duplicates if re-indexed often
                    safe_source = source.replace(" ", "_").replace(".", "_")
                    all_ids.append(f"{game_id}_{safe_source}_{len(all_ids)}_{j}")

            if all_chunks:
                # Use upsert to handle re-runs gracefully
                collection.upsert(
                    documents=all_chunks,
                    metadatas=all_metadatas,
                    ids=all_ids
                )

            return f"Indexed {len(all_chunks)} chunks for '{game_id}'"

        except Exception as e:
            logger.error(f"Indexing error: {e}")
            return f"Error indexing: {str(e)}"

