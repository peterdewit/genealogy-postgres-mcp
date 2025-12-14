#!/usr/bin/env python3
"""
Genealogy DB MCP Server (v2 SAFE)

This version is designed to avoid MCP session-negotiation failures by:
- Avoiding generic "entity/table" parameters (no dynamic SQL table names).
- Avoiding complex parameter types (no List[...] arguments in tool signatures).
- Keeping tool signatures simple (str/int/float/bool).

What it adds (safely):
- Verification workflow (person/relationship/assertion) with fixed SQL per table
- Review queues (list_unreviewed_*)
- "Reject" workflow (soft reject via status='rejected')
- Research notes (requires table research_note)
- Bulk status updates using comma-separated UUIDs (bulk_*)

Minimum expected tables (existing from your working setup):
- person(id, first_name, middle_name, last_name, [status], [status_notes])
- location(id, name)
- event(id, type)
- relationship(id, person_id_a, person_id_b, type, [status], [status_notes])
- assertion(id, subject_table, subject_id, field_name, asserted_value, [status], [status_notes])

Optional tables (tools will error at runtime if missing, but MCP will still connect):
- person_event(person_id, event_id, role)
- research_note(id, person_id, note, source_url, created_at)
"""
import os
import uuid
from typing import Any, Dict, Optional, List

import psycopg2
from psycopg2.extras import RealDictCursor
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("genealogy_db")

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

DB = {
    "host": os.getenv("DB_HOST", "genealogy-postgres"),
    "port": int(os.getenv("DB_PORT", "5432")),
    "dbname": os.getenv("DB_NAME", os.getenv("PGDATABASE", "genealogy")),
    "user": os.getenv("DB_USER", os.getenv("PGUSER", "genealogy")),
    "password": os.getenv("DB_PASSWORD", os.getenv("PGPASSWORD", "genealogy")),
}

def db_conn():
    if DATABASE_URL:
        return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    return psycopg2.connect(**DB, cursor_factory=RealDictCursor)

def ok(data: Any) -> Dict[str, Any]:
    return {"status": "ok", "data": data}

def err(code: str, details: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {"status": "error", "error": code, "details": details or {}}

def _uuid() -> str:
    return str(uuid.uuid4())

def _parse_uuid_csv(uuid_csv: str) -> List[str]:
    """
    Parse a comma-separated list of UUID strings.
    Returns only non-empty trimmed tokens.
    """
    if not uuid_csv:
        return []
    parts = [p.strip() for p in uuid_csv.split(",")]
    return [p for p in parts if p]

# -------------------------
# PERSON
# -------------------------

@mcp.tool()
def create_person(first_name: str = "", middle_name: str = "", last_name: str = ""):
    if not first_name and not last_name:
        return err("missing_name")
    pid = _uuid()
    with db_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO person (id, first_name, middle_name, last_name) VALUES (%s,%s,%s,%s)",
            (pid, first_name or None, middle_name or None, last_name or None),
        )
    return ok({"person_id": pid})

@mcp.tool()
def get_person(person_id: str):
    with db_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM person WHERE id=%s", (person_id,))
        row = cur.fetchone()
    return ok(row) if row else err("not_found")

@mcp.tool()
def search_persons(query: str, limit: int = 20):
    like = f"%{query}%"
    limit = max(1, min(int(limit), 200))
    with db_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT *
            FROM person
            WHERE coalesce(first_name,'') ILIKE %s
               OR coalesce(middle_name,'') ILIKE %s
               OR coalesce(last_name,'') ILIKE %s
            ORDER BY last_name NULLS LAST, first_name NULLS LAST
            LIMIT %s
            """,
            (like, like, like, limit),
        )
        rows = cur.fetchall()
    return ok({"count": len(rows), "persons": rows})

@mcp.tool()
def update_person(person_id: str, first_name: str = "", middle_name: str = "", last_name: str = ""):
    with db_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE person
            SET first_name = COALESCE(NULLIF(%s,''), first_name),
                middle_name = COALESCE(NULLIF(%s,''), middle_name),
                last_name  = COALESCE(NULLIF(%s,''), last_name)
            WHERE id=%s
            """,
            (first_name, middle_name, last_name, person_id),
        )
        if cur.rowcount == 0:
            return err("not_found")
    return ok({"person_id": person_id})

# -------------------------
# LOCATION
# -------------------------

@mcp.tool()
def create_location(name: str):
    if not name:
        return err("missing_name")
    lid = _uuid()
    with db_conn() as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO location (id, name) VALUES (%s,%s)", (lid, name))
    return ok({"location_id": lid})

@mcp.tool()
def search_locations(query: str, limit: int = 20):
    like = f"%{query}%"
    limit = max(1, min(int(limit), 200))
    with db_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM location WHERE name ILIKE %s ORDER BY name LIMIT %s",
            (like, limit),
        )
        rows = cur.fetchall()
    return ok({"count": len(rows), "locations": rows})

# -------------------------
# EVENT
# -------------------------

@mcp.tool()
def create_event(event_type: str):
    if not event_type:
        return err("missing_type")
    eid = _uuid()
    with db_conn() as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO event (id, type) VALUES (%s,%s)", (eid, event_type))
    return ok({"event_id": eid})

@mcp.tool()
def link_person_event(person_id: str, event_id: str, role: str = "subject"):
    with db_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO person_event (person_id, event_id, role)
            VALUES (%s,%s,%s)
            ON CONFLICT (person_id, event_id) DO UPDATE SET role=EXCLUDED.role
            """,
            (person_id, event_id, role),
        )
    return ok({"person_id": person_id, "event_id": event_id, "role": role})

@mcp.tool()
def get_events_for_person(person_id: str, limit: int = 100):
    limit = max(1, min(int(limit), 500))
    with db_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT e.*, pe.role
            FROM person_event pe
            JOIN event e ON e.id = pe.event_id
            WHERE pe.person_id = %s
            ORDER BY e.type
            LIMIT %s
            """,
            (person_id, limit),
        )
        rows = cur.fetchall()
    return ok({"count": len(rows), "events": rows})

# -------------------------
# RELATIONSHIP
# -------------------------

@mcp.tool()
def create_relationship(person_id_a: str, person_id_b: str, relation_type: str):
    if not relation_type:
        return err("missing_type")
    rid = _uuid()
    with db_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO relationship (id, person_id_a, person_id_b, type) VALUES (%s,%s,%s,%s)",
            (rid, person_id_a, person_id_b, relation_type),
        )
    return ok({"relationship_id": rid})

@mcp.tool()
def list_relationships(person_id: str, limit: int = 200):
    limit = max(1, min(int(limit), 500))
    with db_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT *
            FROM relationship
            WHERE person_id_a = %s OR person_id_b = %s
            ORDER BY type
            LIMIT %s
            """,
            (person_id, person_id, limit),
        )
        rows = cur.fetchall()
    return ok({"count": len(rows), "relationships": rows})

@mcp.tool()
def get_family_group(person_id: str):
    with db_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM person WHERE id=%s", (person_id,))
        person = cur.fetchone()
        if not person:
            return err("not_found")

        cur.execute(
            "SELECT * FROM relationship WHERE person_id_a=%s OR person_id_b=%s",
            (person_id, person_id),
        )
        rels = cur.fetchall()

        parents: List[str] = []
        children: List[str] = []
        spouses: List[str] = []

        parent_types = {"parent", "father", "mother"}
        child_types = {"child", "son", "daughter"}
        spouse_types = {"spouse", "partner"}

        for r in rels:
            t = (r.get("type") or "").lower()
            a = r.get("person_id_a")
            b = r.get("person_id_b")

            if t in spouse_types:
                other = b if a == person_id else a
                if other:
                    spouses.append(other)
                continue

            if t in parent_types:
                if b == person_id and a:
                    parents.append(a)
                elif a == person_id and b:
                    children.append(b)
                continue

            if t in child_types:
                if a == person_id and b:
                    parents.append(b)
                elif b == person_id and a:
                    children.append(a)
                continue

        parents = sorted(set(parents))
        children = sorted(set(children))
        spouses = sorted(set(spouses))

        def _fetch_people(ids: List[str]) -> List[Dict[str, Any]]:
            if not ids:
                return []
            cur.execute("SELECT * FROM person WHERE id = ANY(%s::uuid[])", (ids,))
            return cur.fetchall()

        return ok({
            "person": person,
            "parents": _fetch_people(parents),
            "children": _fetch_people(children),
            "spouses": _fetch_people(spouses),
        })

# -------------------------
# ASSERTION / EVIDENCE
# -------------------------

@mcp.tool()
def add_assertion(subject_table: str, subject_id: str, field_name: str, asserted_value: str):
    if not subject_table or not subject_id or not field_name:
        return err("missing_fields")
    aid = _uuid()
    with db_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO assertion (id, subject_table, subject_id, field_name, asserted_value) VALUES (%s,%s,%s,%s,%s)",
            (aid, subject_table, subject_id, field_name, asserted_value),
        )
    return ok({"assertion_id": aid})

@mcp.tool()
def list_assertions(subject_table: str, subject_id: str, limit: int = 200):
    limit = max(1, min(int(limit), 500))
    with db_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT *
            FROM assertion
            WHERE subject_table=%s AND subject_id=%s
            ORDER BY id
            LIMIT %s
            """,
            (subject_table, subject_id, limit),
        )
        rows = cur.fetchall()
    return ok({"count": len(rows), "assertions": rows})

@mcp.tool()
def link_source_to_person(person_id: str, source_ref: str):
    # Store a source reference as a normal assertion (no new tables needed)
    return add_assertion("person", person_id, "source_link", source_ref)

@mcp.tool()
def list_sources_for_person(person_id: str, limit: int = 200):
    limit = max(1, min(int(limit), 500))
    with db_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT asserted_value AS source_ref
            FROM assertion
            WHERE subject_table='person' AND subject_id=%s AND field_name='source_link'
            LIMIT %s
            """,
            (person_id, limit),
        )
        rows = cur.fetchall()
    return ok({"count": len(rows), "sources": rows})

# =========================================================
# V2 SAFE ADDITIONS (NO GENERIC ENTITY/TABLE ARGUMENTS)
# =========================================================

# -------------------------
# STATUS / REVIEW (PERSON)
# -------------------------

@mcp.tool()
def mark_person_verified(person_id: str, notes: str = ""):
    with db_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE person
            SET status='verified',
                status_notes = COALESCE(NULLIF(%s,''), status_notes)
            WHERE id=%s
            """,
            (notes, person_id),
        )
        if cur.rowcount == 0:
            return err("not_found")
    return ok({"person_id": person_id, "status": "verified"})

@mcp.tool()
def mark_person_rejected(person_id: str, reason: str = ""):
    with db_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE person
            SET status='rejected',
                status_notes = COALESCE(NULLIF(%s,''), status_notes)
            WHERE id=%s
            """,
            (reason, person_id),
        )
        if cur.rowcount == 0:
            return err("not_found")
    return ok({"person_id": person_id, "status": "rejected"})

@mcp.tool()
def list_unreviewed_persons(limit: int = 50):
    limit = max(1, min(int(limit), 500))
    with db_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT *
            FROM person
            WHERE status IS NULL OR status='unreviewed'
            LIMIT %s
            """,
            (limit,),
        )
        rows = cur.fetchall()
    return ok({"count": len(rows), "persons": rows})

@mcp.tool()
def bulk_mark_persons_verified(person_ids_csv: str):
    ids = _parse_uuid_csv(person_ids_csv)
    if not ids:
        return err("no_ids")
    with db_conn() as conn, conn.cursor() as cur:
        cur.execute("UPDATE person SET status='verified' WHERE id = ANY(%s::uuid[])", (ids,))
    return ok({"count": len(ids), "status": "verified"})

@mcp.tool()
def bulk_mark_persons_rejected(person_ids_csv: str, reason: str = ""):
    ids = _parse_uuid_csv(person_ids_csv)
    if not ids:
        return err("no_ids")
    with db_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE person
            SET status='rejected',
                status_notes = COALESCE(NULLIF(%s,''), status_notes)
            WHERE id = ANY(%s::uuid[])
            """,
            (reason, ids),
        )
    return ok({"count": len(ids), "status": "rejected"})

# -------------------------
# STATUS / REVIEW (RELATIONSHIP)
# -------------------------

@mcp.tool()
def mark_relationship_verified(relationship_id: str, notes: str = ""):
    with db_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE relationship
            SET status='verified',
                status_notes = COALESCE(NULLIF(%s,''), status_notes)
            WHERE id=%s
            """,
            (notes, relationship_id),
        )
        if cur.rowcount == 0:
            return err("not_found")
    return ok({"relationship_id": relationship_id, "status": "verified"})

@mcp.tool()
def mark_relationship_rejected(relationship_id: str, reason: str = ""):
    with db_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE relationship
            SET status='rejected',
                status_notes = COALESCE(NULLIF(%s,''), status_notes)
            WHERE id=%s
            """,
            (reason, relationship_id),
        )
        if cur.rowcount == 0:
            return err("not_found")
    return ok({"relationship_id": relationship_id, "status": "rejected"})

@mcp.tool()
def list_unreviewed_relationships(limit: int = 50):
    limit = max(1, min(int(limit), 500))
    with db_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT *
            FROM relationship
            WHERE status IS NULL OR status='unreviewed'
            LIMIT %s
            """,
            (limit,),
        )
        rows = cur.fetchall()
    return ok({"count": len(rows), "relationships": rows})

# -------------------------
# STATUS / REVIEW (ASSERTION)
# -------------------------

@mcp.tool()
def mark_assertion_verified(assertion_id: str, notes: str = ""):
    with db_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE assertion
            SET status='verified',
                status_notes = COALESCE(NULLIF(%s,''), status_notes)
            WHERE id=%s
            """,
            (notes, assertion_id),
        )
        if cur.rowcount == 0:
            return err("not_found")
    return ok({"assertion_id": assertion_id, "status": "verified"})

@mcp.tool()
def mark_assertion_rejected(assertion_id: str, reason: str = ""):
    with db_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE assertion
            SET status='rejected',
                status_notes = COALESCE(NULLIF(%s,''), status_notes)
            WHERE id=%s
            """,
            (reason, assertion_id),
        )
        if cur.rowcount == 0:
            return err("not_found")
    return ok({"assertion_id": assertion_id, "status": "rejected"})

@mcp.tool()
def list_unreviewed_assertions(limit: int = 50):
    limit = max(1, min(int(limit), 500))
    with db_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT *
            FROM assertion
            WHERE status IS NULL OR status='unreviewed'
            LIMIT %s
            """,
            (limit,),
        )
        rows = cur.fetchall()
    return ok({"count": len(rows), "assertions": rows})

# -------------------------
# RESEARCH NOTES (OPTIONAL TABLE)
# -------------------------

@mcp.tool()
def save_research_note(person_id: str, note: str, source_url: str = ""):
    if not note:
        return err("missing_note")
    nid = _uuid()
    with db_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO research_note (id, person_id, note, source_url)
            VALUES (%s,%s,%s,NULLIF(%s,''))
            """,
            (nid, person_id, note, source_url),
        )
    return ok({"note_id": nid})

@mcp.tool()
def list_research_notes(person_id: str, limit: int = 100):
    limit = max(1, min(int(limit), 500))
    with db_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT *
            FROM research_note
            WHERE person_id=%s
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (person_id, limit),
        )
        rows = cur.fetchall()
    return ok({"count": len(rows), "notes": rows})

@mcp.tool()
def search_research_notes(query: str, limit: int = 100):
    like = f"%{query}%"
    limit = max(1, min(int(limit), 500))
    with db_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT *
            FROM research_note
            WHERE note ILIKE %s
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (like, limit),
        )
        rows = cur.fetchall()
    return ok({"count": len(rows), "notes": rows})

# -------------------------
# ASGI
# -------------------------
app = mcp.streamable_http_app()
