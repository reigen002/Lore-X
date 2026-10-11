"""SQLite lifetime and transaction tests using disposable databases only."""
from contextlib import closing
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from rpgagents.conversation_store import ConversationStore


class ConversationStoreTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.database = str(Path(directory.name) / "history.sqlite3")
        self.connections = []
        real_connect = sqlite3.connect

        def connect(*args, **kwargs):
            connection = real_connect(*args, **kwargs)
            self.connections.append(connection)
            return connection

        # Keep real handles alive so garbage collection cannot hide a leak.
        self.addCleanup(lambda: [connection.close() for connection in self.connections])
        guard = patch("rpgagents.conversation_store.sqlite3.connect", side_effect=connect)
        guard.start()
        self.addCleanup(guard.stop)
        self.store = ConversationStore(self.database)

    def test_public_operations_close_every_connection(self):
        conversation_id = self.store.create_or_get_conversation("Valorant")
        self.store.add_message(conversation_id, "user", "Timing?")
        self.assertEqual(self.store.get_conversation(conversation_id)["game_name"], "Valorant")
        self.assertEqual(self.store.create_or_get_conversation("Valorant", conversation_id), conversation_id)
        self.assertEqual([row["content"] for row in self.store.get_messages(conversation_id)], ["Timing?"])
        self.assertEqual(len(self.store.list_conversations("Valorant")), 1)
        for connection in self.connections:
            with self.assertRaisesRegex(sqlite3.ProgrammingError, "closed database"):
                connection.execute("SELECT 1")

    def test_failed_transaction_rolls_back_and_closes_connection(self):
        conversation_id = self.store.create_or_get_conversation("Valorant")
        self.store.add_message(conversation_id, "user", "Committed")
        with self.assertRaises(sqlite3.OperationalError):
            with self.store._connect() as connection:
                connection.execute("INSERT INTO messages VALUES (?, ?, ?, ?, ?)",
                    ("rolled-back", conversation_id, "assistant", "Uncommitted", "2026-10-11T00:00:00"))
                connection.execute("INSERT INTO missing_fixture_table VALUES (1)")
        failed_connection = self.connections[-1]
        with closing(sqlite3.connect(self.database)) as reopened:
            self.assertEqual(reopened.execute("SELECT content FROM messages").fetchall(), [("Committed",)])
        with self.assertRaisesRegex(sqlite3.ProgrammingError, "closed database"):
            failed_connection.execute("SELECT 1")
