"""Main's HTTP and retrieval error contracts; no live providers or normal stores."""
import importlib.util
from contextlib import closing
from pathlib import Path
import re
import sqlite3
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

SOURCE = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SOURCE))
# Main's crew import loads dotenv. Do not read the user's credentials in tests.
with patch("dotenv.load_dotenv"), patch("socket.create_connection", side_effect=AssertionError("Network forbidden")):
    from rpgagents import main
    from rpgagents.conversation_store import ConversationStore
    from rpgagents.tools.game_search_tool import GameSearchTool
from fastapi.testclient import TestClient


class ApiReliabilityTests(unittest.TestCase):
    def setUp(self):
        self.assertEqual(Path(main.__file__).resolve().parent, (SOURCE / "rpgagents").resolve())
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.database = str(Path(directory.name) / "history.sqlite3")
        self.connections = []
        self.statements = []
        real_connect = sqlite3.connect

        def connect(*args, **kwargs):
            # TestClient owns a worker thread; retained fixture handles need
            # cross-thread cleanup while reproducing main's pre-fix leak.
            kwargs.setdefault("check_same_thread", False)
            connection = real_connect(*args, **kwargs)
            connection.set_trace_callback(self.statements.append)
            self.connections.append(connection)
            return connection

        self.addCleanup(lambda: [connection.close() for connection in self.connections])
        for guard in (
            patch("rpgagents.conversation_store.sqlite3.connect", side_effect=connect),
            patch("dotenv.load_dotenv"),
            patch("socket.create_connection", side_effect=AssertionError("Network forbidden")),
            patch("requests.sessions.Session.request", side_effect=AssertionError("Live HTTP forbidden")),
            patch("chromadb.PersistentClient", side_effect=AssertionError("Normal Chroma forbidden")),
            patch("chromadb.utils.embedding_functions.SentenceTransformerEmbeddingFunction",
                  side_effect=AssertionError("Model downloads forbidden")),
        ):
            guard.start()
            self.addCleanup(guard.stop)
        self.provider = self.start_patch(patch("groq.Groq", side_effect=AssertionError("Live provider forbidden")))
        self.search = self.start_patch(patch.object(main, "GameSearchTool", side_effect=AssertionError("Unmocked search forbidden")))
        self.store = ConversationStore(self.database)
        alias = "rpgagents._main_port_api"
        spec = importlib.util.spec_from_file_location(alias, SOURCE / "rpgagents/api.py")
        self.api = importlib.util.module_from_spec(spec)
        self.start_patch(patch.dict(sys.modules, {alias: self.api}))
        with patch("rpgagents.conversation_store.ConversationStore", return_value=self.store):
            spec.loader.exec_module(self.api)
        self.client = TestClient(self.api.app, raise_server_exceptions=False)
        self.addCleanup(self.client.close)
        self.statements.clear()

    def start_patch(self, guard):
        result = guard.start()
        self.addCleanup(guard.stop)
        return result

    def rows(self, query, parameters=()):
        with closing(sqlite3.connect(self.database)) as connection:
            return connection.execute(query, parameters).fetchall()

    def assert_no_side_effects(self, generate):
        generate.assert_not_called()
        self.search.assert_not_called()
        self.provider.assert_not_called()
        self.assertEqual(self.rows("SELECT count(*) FROM conversations"), [(0,)])
        self.assertEqual(self.rows("SELECT count(*) FROM messages"), [(0,)])
        self.assertEqual([sql for sql in self.statements if re.match(
            r"^\s*(INSERT|UPDATE|DELETE|REPLACE|CREATE|ALTER|DROP)\b", sql, re.I)], [])

    def test_blank_required_text_is_422_before_search_provider_or_writes(self):
        with patch.object(self.api, "quick_search", wraps=main.quick_search) as generate:
            for route, payload, fields in (
                ("/ask", {"game_name": "Valorant", "query": "Timing?"}, ("game_name", "query")),
                ("/chat", {"game_name": "Valorant", "message": "Timing?"}, ("game_name", "message")),
                ("/conversations", {"game_name": "Valorant"}, ("game_name",)),
            ):
                for field in fields:
                    for blank in ("", " ", "\t\r\n", "\u00a0"):
                        with self.subTest(route=route, field=field, blank=blank):
                            response = self.client.post(route, json={**payload, field: blank})
                            self.assertEqual(response.status_code, 422)
                            self.assertIn(["body", field], [error["loc"] for error in response.json()["detail"]])
            self.assert_no_side_effects(generate)

    def test_missing_and_invalid_required_fields_have_no_side_effects(self):
        with patch.object(self.api, "quick_search", wraps=main.quick_search) as generate:
            for payload in ({}, {"game_name": "Valorant"}, {"game_name": None, "query": "Timing?"},
                            {"game_name": "Valorant", "query": 123}, {"game_name": [], "query": "Timing?"}):
                with self.subTest(payload=payload):
                    self.assertEqual(self.client.post("/ask", json=payload).status_code, 422)
            self.assert_no_side_effects(generate)

    def test_valid_required_text_is_trimmed_in_response_and_committed_history(self):
        with patch.object(self.api, "quick_search", return_value="Answer"):
            response = self.client.post("/chat", json={"game_name": " Valorant ", "message": " Timing? "})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["game_name"], "Valorant")
        self.assertEqual(self.rows("SELECT game_name FROM conversations"), [("Valorant",)])
        self.assertEqual(self.rows("SELECT role, content FROM messages ORDER BY created_at"),
                         [("user", "Timing?"), ("assistant", "Answer")])

    def test_escaping_api_exceptions_are_safe_and_logged_with_tracebacks(self):
        private = "private fixture generation diagnostic"
        with patch.object(self.api, "quick_search", side_effect=RuntimeError(private)):
            for route, payload in (
                ("/ask", {"game_name": "Valorant", "query": "Timing?"}),
                ("/chat", {"game_name": "Valorant", "message": "Timing?"}),
            ):
                with self.subTest(route=route), self.assertLogs(self.api.logger, level="ERROR") as logs:
                    response = self.client.post(route, json=payload)
                self.assertEqual(response.status_code, 500)
                self.assertEqual(response.json(), {"detail": "Unable to process your request. Please try again later."})
                self.assertNotIn(private, response.text)
                self.assertIn("Traceback", "\n".join(logs.output))
                self.assertIn(private, "\n".join(logs.output))
        self.assertEqual(self.rows("SELECT role, content FROM messages"), [("user", "Timing?")])

    def test_real_crud_database_failure_is_safe_and_logged_without_writes(self):
        private = "private fixture database diagnostic"
        with closing(sqlite3.connect(self.database)) as connection:
            connection.execute("CREATE TRIGGER fail_conversation BEFORE INSERT ON conversations "
                               "BEGIN SELECT RAISE(ABORT, 'private fixture database diagnostic'); END")
        with self.assertLogs(self.api.logger, level="ERROR") as logs:
            response = self.client.post("/conversations", json={"game_name": "Valorant"})
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json(), {"detail": "Unable to process your request. Please try again later."})
        self.assertNotIn(private, response.text)
        self.assertIn("Traceback", "\n".join(logs.output))
        self.assertIn(private, "\n".join(logs.output))
        self.assertEqual(self.rows("SELECT count(*) FROM conversations"), [(0,)])
        self.assertEqual(self.rows("SELECT count(*) FROM messages"), [(0,)])

    def test_failed_generation_and_retry_preserve_append_only_partial_turns(self):
        created = self.client.post("/conversations", json={"game_name": "Valorant"})
        conversation_id = created.json()["id"]
        payload = {"game_name": "Valorant", "message": "Timing?", "conversation_id": conversation_id}
        with patch.object(self.api, "quick_search", side_effect=RuntimeError("private generation diagnostic")):
            failed = self.client.post("/chat", json=payload)
        self.assertEqual(failed.status_code, 500)
        self.assertNotIn("private generation diagnostic", failed.text)
        self.assertEqual(self.rows("SELECT role, content FROM messages"), [("user", "Timing?")])
        with patch.object(self.api, "quick_search", return_value="Answer"):
            retried = self.client.post("/chat", json=payload)
        self.assertEqual(retried.status_code, 200)
        self.assertEqual(retried.json()["conversation_id"], conversation_id)
        self.assertEqual(self.rows("SELECT role, content FROM messages ORDER BY created_at"),
                         [("user", "Timing?"), ("user", "Timing?"), ("assistant", "Answer")])

    def test_tool_initialization_failure_is_safe_http_200_with_server_traceback(self):
        private = "private fixture initialization diagnostic"
        with patch.object(main, "GameSearchTool", side_effect=RuntimeError(private)), self.assertLogs(main.logger) as logs:
            response = self.client.post("/ask", json={"game_name": "Valorant", "query": "Timing?"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["result"], "Search temporarily unavailable. Please try again later.")
        self.assertNotIn(private, response.text)
        self.assertIn("Traceback", "\n".join(logs.output))
        self.assertIn(private, "\n".join(logs.output))
        self.provider.assert_not_called()
        self.assertEqual(self.rows("SELECT count(*) FROM conversations"), [(0,)])

    def test_internal_retrieval_failure_is_safe_before_formatting(self):
        private = "private fixture collection diagnostic"
        tool = GameSearchTool.model_construct()
        tool._chroma_client = MagicMock()
        tool._chroma_client.list_collections.side_effect = RuntimeError(private)
        with patch.object(main, "GameSearchTool", return_value=tool), patch.object(
            GameSearchTool, "_ingest_local_files"
        ), self.assertLogs("rpgagents.tools.game_search_tool", level="ERROR") as logs:
            response = self.client.post("/ask", json={"game_name": "Valorant", "query": "Timing?"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["result"], "Error searching local docs. Please try again later.")
        self.assertNotIn(private, response.text)
        self.assertIn("Traceback", "\n".join(logs.output))
        self.assertIn(private, "\n".join(logs.output))
        self.provider.assert_not_called()

    def test_formatting_exception_preserves_raw_snippet_fallback_and_logs_traceback(self):
        private = "private fixture provider diagnostic"
        snippets = "Known source fact.\nSource: guide.txt"
        tool = MagicMock()
        tool._run.return_value = snippets
        client = MagicMock()
        client.chat.completions.create.side_effect = RuntimeError(private)
        with patch.object(main, "GameSearchTool", return_value=tool), patch(
            "groq.Groq", return_value=client
        ), self.assertLogs(main.logger) as logs:
            response = self.client.post("/chat", json={"game_name": "Valorant", "message": "Timing?"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["answer"], snippets)
        self.assertNotIn(private, response.text)
        self.assertIn("Traceback", "\n".join(logs.output))
        self.assertIn(private, "\n".join(logs.output))
        self.assertEqual(self.rows("SELECT role, content FROM messages ORDER BY created_at"),
                         [("user", "Timing?"), ("assistant", snippets)])

    def test_recovered_outer_exception_keeps_diagnostics_out_of_answer(self):
        private = "private fixture primary search diagnostic"
        tool = MagicMock()
        tool._run.return_value = "Fallback evidence"
        with patch.object(main, "rag_then_format", side_effect=RuntimeError(private)), patch.object(
            main, "GameSearchTool", return_value=tool
        ), self.assertLogs(main.logger) as logs:
            response = self.client.post("/ask", json={"game_name": "Valorant", "query": "Timing?"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["result"], "Fallback evidence")
        self.assertNotIn(private, response.text)
        self.assertIn("Traceback", "\n".join(logs.output))
        self.assertIn(private, "\n".join(logs.output))
        self.provider.assert_not_called()

    def test_empty_retrieval_remains_http_200_without_provider_call(self):
        tool = MagicMock()
        tool._run.return_value = ""
        with patch.object(main, "GameSearchTool", return_value=tool):
            response = self.client.post("/ask", json={"game_name": "Valorant", "query": "Timing?"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["result"], "No information found.")
        self.provider.assert_not_called()
        self.assertEqual(self.rows("SELECT count(*) FROM messages"), [(0,)])

    def test_formatted_success_uses_main_response_schema_and_commits_both_messages(self):
        tool = MagicMock()
        tool._run.return_value = "Source snippets"
        client = MagicMock()
        client.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="<think>Internal</think>Known answer."))])
        with patch.object(main, "GameSearchTool", return_value=tool), patch("groq.Groq", return_value=client):
            response = self.client.post("/chat", json={"game_name": "Valorant", "message": "Timing?"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.json()), {"conversation_id", "game_name", "answer", "timestamp"})
        self.assertEqual(response.json()["answer"], "Known answer.")
        self.assertEqual(self.rows("SELECT role, content FROM messages ORDER BY created_at"),
                         [("user", "Timing?"), ("assistant", "Known answer.")])
