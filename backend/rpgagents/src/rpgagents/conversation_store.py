import os
import sqlite3
from contextlib import closing, contextmanager
from datetime import datetime
from typing import Any, Dict, Iterator, List, Optional
from uuid import uuid4


class ConversationStore:
    """Persists game conversations and messages in a local SQLite database."""

    def __init__(self, db_path: Optional[str] = None) -> None:
        if db_path is None:
            module_dir = os.path.dirname(os.path.abspath(__file__))
            project_root = os.path.abspath(os.path.join(module_dir, "..", "..", ".."))
            data_dir = os.path.join(project_root, "knowledge")
            os.makedirs(data_dir, exist_ok=True)
            db_path = os.path.join(data_dir, "conversations.sqlite3")

        self.db_path = db_path
        self._initialize()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        # sqlite3's transaction context commits/rolls back but does not close.
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            with conn:
                yield conn

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY,
                    game_name TEXT NOT NULL,
                    title TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(conversation_id) REFERENCES conversations(id)
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_conversations_game
                ON conversations(game_name)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_messages_conversation
                ON messages(conversation_id, created_at)
                """
            )
            conn.commit()

    def create_or_get_conversation(
        self,
        game_name: str,
        conversation_id: Optional[str] = None,
        title: Optional[str] = None,
    ) -> str:
        now = datetime.utcnow().isoformat()

        if conversation_id:
            existing = self.get_conversation(conversation_id)
            if existing is not None:
                return conversation_id

        conversation_id = str(uuid4())
        title = title or f"{game_name} session"

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO conversations (id, game_name, title, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (conversation_id, game_name, title, now, now),
            )
            conn.commit()

        return conversation_id

    def get_conversation(self, conversation_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, game_name, title, created_at, updated_at FROM conversations WHERE id = ?",
                (conversation_id,),
            ).fetchone()

        if row is None:
            return None

        return dict(row)

    def add_message(self, conversation_id: str, role: str, content: str) -> Dict[str, Any]:
        message_id = str(uuid4())
        created_at = datetime.utcnow().isoformat()

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO messages (id, conversation_id, role, content, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (message_id, conversation_id, role, content, created_at),
            )
            conn.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ?",
                (created_at, conversation_id),
            )
            conn.commit()

        return {
            "id": message_id,
            "conversation_id": conversation_id,
            "role": role,
            "content": content,
            "created_at": created_at,
        }

    def get_messages(self, conversation_id: str) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, conversation_id, role, content, created_at
                FROM messages
                WHERE conversation_id = ?
                ORDER BY created_at ASC
                """,
                (conversation_id,),
            ).fetchall()

        return [dict(row) for row in rows]

    def list_conversations(self, game_name: Optional[str] = None) -> List[Dict[str, Any]]:
        query = "SELECT id, game_name, title, created_at, updated_at FROM conversations"
        params: List[Any] = []

        if game_name:
            query += " WHERE lower(game_name) = lower(?)"
            params.append(game_name)

        query += " ORDER BY updated_at DESC"

        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()

        return [dict(row) for row in rows]
