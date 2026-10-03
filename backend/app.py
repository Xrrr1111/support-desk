from __future__ import annotations

import os
import re
import secrets
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field


DATABASE = Path(os.environ.get("SUPPORT_DB", "support.sqlite3"))
STAFF_TOKEN = os.environ.get("SUPPORT_STAFF_TOKEN", "")
GATEWAY_URL = os.environ.get("SUPPORT_GATEWAY_URL", "")
GATEWAY_KEY = os.environ.get("SUPPORT_GATEWAY_KEY", "")
MODEL = os.environ.get("SUPPORT_MODEL", "")

app = FastAPI(title="Support Desk", version="0.1.0")


@app.get("/", include_in_schema=False)
def console() -> FileResponse:
    return FileResponse(Path(__file__).resolve().parents[1] / "frontend" / "index.html")


@app.get("/console.js", include_in_schema=False)
def console_script() -> FileResponse:
    return FileResponse(Path(__file__).resolve().parents[1] / "frontend" / "console.js", media_type="text/javascript")


@app.get("/console.css", include_in_schema=False)
def console_styles() -> FileResponse:
    return FileResponse(Path(__file__).resolve().parents[1] / "frontend" / "console.css", media_type="text/css")


class OrderCreate(BaseModel):
    order_id: str = Field(pattern=r"^[A-Za-z0-9-]{3,40}$")
    status: str = Field(min_length=1, max_length=80)
    note: str = Field(default="", max_length=500)


class PolicyCreate(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    body: str = Field(min_length=10, max_length=10000)


class Question(BaseModel):
    order_id: str = Field(pattern=r"^[A-Za-z0-9-]{3,40}$")
    question: str = Field(min_length=3, max_length=1000)


class TicketUpdate(BaseModel):
    status: str = Field(pattern=r"^(open|resolved)$")
    resolution: str = Field(default="", max_length=1000)


@contextmanager
def connection():
    DATABASE.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DATABASE, timeout=10)
    db.row_factory = sqlite3.Row
    try:
        yield db
    finally:
        db.close()


def init_database() -> None:
    with connection() as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS orders(order_id TEXT PRIMARY KEY,status TEXT NOT NULL,note TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS policies(id INTEGER PRIMARY KEY,title TEXT NOT NULL,body TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS tickets(
              id INTEGER PRIMARY KEY,order_id TEXT NOT NULL,question TEXT NOT NULL,
              reason TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'open',resolution TEXT NOT NULL DEFAULT '',
              created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS inquiries(
              id INTEGER PRIMARY KEY,order_id TEXT NOT NULL,question TEXT NOT NULL,
              answer TEXT NOT NULL,source_ids TEXT NOT NULL,ticket_id INTEGER,
              mode TEXT NOT NULL,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        db.commit()


@app.on_event("startup")
def startup() -> None:
    init_database()


def require_staff(authorization: str | None) -> None:
    if not STAFF_TOKEN or not authorization or not secrets.compare_digest(authorization, f"Bearer {STAFF_TOKEN}"):
        raise HTTPException(401, "Invalid staff token")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/orders", status_code=201)
def upsert_order(body: OrderCreate, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    require_staff(authorization)
    with connection() as db:
        db.execute(
            "INSERT INTO orders(order_id,status,note) VALUES(?,?,?) ON CONFLICT(order_id) DO UPDATE SET status=excluded.status,note=excluded.note",
            (body.order_id, body.status, body.note),
        )
        db.commit()
    return body.model_dump()


@app.get("/api/orders")
def list_orders(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    require_staff(authorization)
    with connection() as db:
        rows = db.execute("SELECT * FROM orders ORDER BY order_id").fetchall()
    return {"orders": [dict(row) for row in rows]}


@app.post("/api/policies", status_code=201)
def add_policy(body: PolicyCreate, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    require_staff(authorization)
    with connection() as db:
        cursor = db.execute("INSERT INTO policies(title,body) VALUES(?,?)", (body.title, body.body))
        db.commit()
    return {"id": cursor.lastrowid, **body.model_dump()}


@app.get("/api/policies")
def list_policies(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    require_staff(authorization)
    with connection() as db:
        rows = db.execute("SELECT * FROM policies ORDER BY id DESC").fetchall()
    return {"policies": [dict(row) for row in rows]}


def search_terms(value: str) -> set[str]:
    words = {word for word in re.findall(r"[a-z]{3,}", value.lower()) if word not in {"the", "and", "for", "there", "with", "what", "where", "when", "how", "can", "get", "does", "have", "order"}}
    chinese = re.findall(r"[\u4e00-\u9fff]+", value)
    return words | {part[index : index + 2] for part in chinese for index in range(len(part) - 1)}


def retrieve(question: str, policies: list[sqlite3.Row]) -> list[dict[str, Any]]:
    terms = search_terms(question)
    ranked = []
    for policy in policies:
        title_matches = terms & search_terms(policy["title"])
        body_matches = terms & search_terms(policy["body"])
        score = len(title_matches) * 3 + len(body_matches)
        if title_matches or len(body_matches) >= 2:
            ranked.append((score, {"id": policy["id"], "title": policy["title"], "excerpt": policy["body"][:700]}))
    ranked.sort(key=lambda item: (-item[0], item[1]["id"]))
    return [item for _, item in ranked[:3]]


async def draft_with_model(question: str, order: dict[str, Any], sources: list[dict[str, Any]]) -> str | None:
    if not all((GATEWAY_URL, GATEWAY_KEY, MODEL)):
        return None
    evidence = "\n".join(f"[{source['id']}] {source['title']}: {source['excerpt']}" for source in sources)
    prompt = f"Order facts: {order}. Policy evidence: {evidence}. User question: {question}. Answer only from these facts; cite policy IDs."
    try:
        async with httpx.AsyncClient(timeout=30) as http:
            response = await http.post(
                GATEWAY_URL.rstrip("/") + "/v1/chat/completions",
                headers={"Authorization": f"Bearer {GATEWAY_KEY}", "Idempotency-Key": secrets.token_hex(16)},
                json={"model": MODEL, "messages": [{"role": "system", "content": "Do not invent order facts or policy rules."}, {"role": "user", "content": prompt}], "max_tokens": 350},
            )
            response.raise_for_status()
            answer = response.json()["choices"][0]["message"]["content"]
        if any(f"[{source['id']}]" in answer for source in sources) and order["order_id"] in answer:
            return answer
    except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError):
        return None
    return None


@app.post("/api/ask")
async def ask(body: Question, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    require_staff(authorization)
    with connection() as db:
        order_row = db.execute("SELECT * FROM orders WHERE order_id=?", (body.order_id,)).fetchone()
        policies = db.execute("SELECT * FROM policies").fetchall()
    order = dict(order_row) if order_row else None
    sources = retrieve(body.question, policies)
    if order and sources:
        model_answer = await draft_with_model(body.question, order, sources)
        answer = model_answer or f"Order {order['order_id']} status: {order['status']}. {order['note']} Relevant policy: {sources[0]['title']} [{sources[0]['id']}]."
        mode = "model" if model_answer else "verified-template"
        ticket_id = None
    else:
        reason = "order not found" if not order else "no relevant policy found"
        answer = "Insufficient verified information. Handed off for staff review."
        sources = []
        mode = "handoff"
        with connection() as db:
            cursor = db.execute("INSERT INTO tickets(order_id,question,reason) VALUES(?,?,?)", (body.order_id, body.question, reason))
            ticket_id = cursor.lastrowid
            db.commit()
    with connection() as db:
        cursor = db.execute(
            "INSERT INTO inquiries(order_id,question,answer,source_ids,ticket_id,mode) VALUES(?,?,?,?,?,?)",
            (body.order_id, body.question, answer, ",".join(str(source["id"]) for source in sources), ticket_id, mode),
        )
        db.commit()
    return {"inquiry_id": cursor.lastrowid, "answer": answer, "order": order, "sources": sources, "ticket_id": ticket_id, "mode": mode}


@app.get("/api/tickets")
def list_tickets(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    require_staff(authorization)
    with connection() as db:
        rows = db.execute("SELECT * FROM tickets ORDER BY id DESC").fetchall()
    return {"tickets": [dict(row) for row in rows]}


@app.patch("/api/tickets/{ticket_id}")
def update_ticket(ticket_id: int, body: TicketUpdate, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    require_staff(authorization)
    with connection() as db:
        updated = db.execute("UPDATE tickets SET status=?,resolution=? WHERE id=?", (body.status, body.resolution, ticket_id))
        db.commit()
    if not updated.rowcount:
        raise HTTPException(404, "Ticket not found")
    return {"id": ticket_id, **body.model_dump()}
