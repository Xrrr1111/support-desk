# Support Desk

A staff-only support workflow over order records and policy documents. Questions query an order and rank policy evidence using character bigrams. If either source is missing, the system creates a human-review ticket rather than inventing an answer. When configured, it drafts through the AI Gateway and accepts the result only if it cites a retrieved policy and repeats the verified order ID; otherwise it falls back to a clearly labeled template.

Run with `pip install -r requirements.txt`, set a random `SUPPORT_STAFF_TOKEN`, and execute `uvicorn backend.app:app --host 127.0.0.1 --port 8200`. Open `http://127.0.0.1:8200/` for the staff console, or `/docs` for the API. Run `python -m pytest -q` for tests.

Optional model variables: `SUPPORT_GATEWAY_URL`, `SUPPORT_GATEWAY_KEY`, and `SUPPORT_MODEL`. The service stores orders, policies, tickets, and inquiry records in `SUPPORT_DB` (SQLite by default). All bundled/example data is synthetic; real use requires consent, access control, data retention rules, backup, and a real pilot review. This is an MVP candidate, not a proven pilot.
