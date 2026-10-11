# Main-based backend reliability

Base: origin/main at 62a59c3cab198af19547f5505cefb4abcfa7c1bf. This port is separate from the dirty develop checkout. It adapts validation and safe errors to main's existing APIs, with no retrieval/provider feature port or lockfile change.

## Request and outcome contracts

Required game_name and query for /ask, game_name and message for /chat, and game_name for /conversations are trimmed and nonblank. HTTP 422 occurs before generation, search/provider calls or writes. Optional title, conversation_id and game-filter fields retain their existing behavior; UUID validation was not introduced.

The result (/ask) and answer (/chat) fields remain strings. Main retrieves cached/web snippets and invokes Groq formatting. A formatting exception returns the raw snippets. Empty retrieval can return No information found. Handled initialization/retrieval errors return safe text. These outcomes can use HTTP 200; it does not certify that an answer exists or is correct. Unhandled API errors return generic HTTP 500 detail. The API and retrieval-boundary exception handlers changed here retain the original exception and traceback. Existing lower-level web-search diagnostics are unchanged. Unknown history reads still return 404.

There is no typed outcome discriminator. There is also no MCP module, route, or console entry point at this main SHA, so no MCP implementation or MCP test was imported.

## Conversation and connection lifetime

Each conversation/message operation has its own transaction. A user message commits before generation; a subsequent failure can leave a partial turn. Retrying with the same conversation ID appends another user message and, on success, an assistant message. No idempotency or whole-turn atomicity is claimed. Game-name metadata is not an ownership or cross-game isolation boundary.

Main's sqlite3 connection context handled commit/rollback but did not close the handle. The focused regression retains real connections, then tries SELECT after public operations and failed transactions. Both tests failed on unmodified main because those handles remained usable. Failed-transaction rollback already worked. The small context-manager fix preserves transaction behavior and adds guaranteed closure; the regression also checks rollback against reopened temporary state.

## Offline verification

Use an installed environment and run from this worktree's repository root:

~~~powershell
python -m unittest discover -s backend/rpgagents/tests -p 'test_api_reliability.py'
python -m unittest discover -s backend/rpgagents/tests -p 'test_conversation_store.py'
python -m unittest discover -s backend/rpgagents/tests -p 'test_*.py'
git diff --check
~~~

The tests prepend this worktree's source directory and verify main's loaded location, avoiding an editable install of develop. API modules are loaded with a temporary ConversationStore factory before module execution. External search/provider dependencies are mocked, normal Chroma/embedding/network access is guarded, and SQLite files are disposable. SQL trace callbacks plus generation/provider spies prove invalid inputs perform no work; HTTP responses, tracebacks and reopened message rows verify failures and retries.

API fixture connections allow cross-thread cleanup because TestClient uses a worker thread and pre-fix handles must be retained to demonstrate the leak. Production sqlite3 thread settings are unchanged.

Main contains no pre-existing automated test directory. Its relevant offline suite is the new reliability suite; unmerged develop tests are excluded. No live tests or MCP transport are included; passing fixtures do not establish live-provider availability, factual accuracy, performance or production readiness.

The executed environment reuses the existing Python 3.11.14 virtual environment. A clean installation of main's lockfile was not performed and no dependency versions were changed. The temporary review runner separately hashes the original checkout and normal SQLite/Chroma stores, and keeps logs and exact test counts outside both source trees.
