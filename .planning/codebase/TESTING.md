# Testing Patterns

**Analysis Date:** 2026-03-28

## Test Framework

**Runner:**
- Python `unittest`
- No custom test config file is committed

**Assertion Library:**
- Built-in `unittest` assertions such as `assertEqual`, `assertTrue`, `assertIn`, and `assertRaises`
- Mocking through `unittest.mock.patch`

**Run Commands:**
```bash
python backend/tests/test_prd_smoke.py              # Run the backend smoke suite from repo root
python -m unittest backend.tests.test_prd_smoke     # Alternative unittest invocation
```

## Test File Organization

**Location:**
- Automated backend coverage lives in `backend/tests/`
- Manual browser verification lives in `tests/manual-smoke-checklist.md`

**Naming:**
- Automated test file currently follows `test_*.py`: `backend/tests/test_prd_smoke.py`
- No frontend test naming convention exists because no frontend runner is configured

**Structure:**
```text
backend/
  tests/
    test_prd_smoke.py
tests/
  manual-smoke-checklist.md
```

## Test Structure

**Suite Organization:**
```python
class PRDSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ...

    def tearDown(self) -> None:
        ...

    def create_completed_document(...):
        ...

    def test_auth_bypass_allows_register_and_login_under_rls(self) -> None:
        ...
```

**Patterns:**
- Tests are class-based under a single `PRDSmokeTests` suite in `backend/tests/test_prd_smoke.py`
- The suite provides helper/factory methods for users, folders, documents, and conversations
- `tearDown()` truncates core tables after each test to keep the database clean
- Many tests exercise real DB behavior with selective mocking only at external boundaries

## Mocking

**Framework:**
- `unittest.mock.patch`
- Direct patching of service functions or provider clients

**Patterns:**
```python
with patch("app.services.chat.retrieve_relevant_chunks", return_value=[]), patch(
    "app.services.chat.client.chat.completions.create",
    side_effect=fake_stream_create,
):
    events = list(stream_conversation_reply(...))
```

**What to Mock:**
- External LLM/provider calls in `backend/app/services/chat.py`, `metadata.py`, `embeddings.py`, and `web_search.py`
- OCR/parser dependency failures
- PII entity detection when tests need deterministic redaction behavior

**What NOT to Mock:**
- Core SQLAlchemy models and request-context behavior
- RLS-scoped data access where the tests are explicitly verifying DB behavior
- KB tool primitives when the goal is to verify real path/search behavior

## Fixtures and Factories

**Test Data:**
```python
def register_account(self, email: str | None = None, password: str = "Test123456!") -> tuple[uuid.UUID, str]:
    ...

def create_completed_document(self, *, user_id: uuid.UUID, filename: str, ...) -> tuple[uuid.UUID, uuid.UUID]:
    ...
```

**Location:**
- Factory helpers are kept inline in `backend/tests/test_prd_smoke.py`
- Temporary files use `tempfile.TemporaryDirectory()`
- The suite mutates a real database rather than loading static fixture files

## Coverage

**Requirements:**
- No explicit line or branch coverage threshold is configured
- Coverage emphasis is on backend smoke/integration scenarios, not exhaustive unit isolation

**Configuration:**
- No coverage tool config is committed
- There is no CI gate enforcing minimum coverage

**View Coverage:**
```bash
# No automated coverage command is defined in the repo today.
```

## Test Types

**Unit Tests:**
- Limited
- The current automated suite leans more toward integration and behavior verification than small isolated units

**Integration Tests:**
- Primary automated pattern
- Examples in `backend/tests/test_prd_smoke.py` verify auth, RLS, ingestion, KB tools, web fallback, sub-agent routing, workspace SQL, and redaction flows against real DB state

**E2E Tests:**
- Manual only
- `tests/manual-smoke-checklist.md` covers upload flows, SSE status, citations, metadata filters, web fallback, OCR behavior, and deletion workflows

## Common Patterns

**Async/Streaming Testing:**
```python
events = list(stream_document_status(str(document_id), str(user_id), poll_interval_seconds=0))
self.assertTrue(events[0].startswith("event: document"))
```

**Error Testing:**
```python
with self.assertRaises(ParserDependencyError):
    parse_document_file(docx_path, docx_path.name)
```

**Database Context Setup:**
```python
with SessionLocal() as db:
    bind_current_user_context(db, str(user_id))
    ...
```

**Provider Failure Simulation:**
- Mock OpenAI SDK exceptions such as `APIConnectionError` and `NotFoundError`
- Patch search and redaction services for deterministic fallback behavior

---
*Testing analysis: 2026-03-28*
*Update when test patterns change*
