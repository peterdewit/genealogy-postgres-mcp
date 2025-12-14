# Genealogy Database MCP Server

## Purpose

This MCP server provides a **structured, persistent database backend** for AI agents performing genealogical research.

Its role is to store and retrieve **people, relationships, events, locations, and evidence** discovered by agents while working in digital archives, historical websites, and historical documents.

This server is intentionally **not** a full genealogy application.  
It is a **research memory and evidence store** optimized for AI-assisted workflows.

---

## Core Capabilities

### People
- Create, update, fetch, and search persons
- Store basic identity information (names, dates)

### Relationships
- Parent/child, spouse, and other person-to-person links
- Query family groups and relationship networks

### Events
- Births, baptisms, marriages, deaths, etc.
- Link people to events with roles

### Locations
- Normalized place storage
- Searchable to reduce duplication

### Assertions & Sources
- Store claims about people or relationships
- Attach source references (URLs, archive IDs, citations)
- Enables later verification or review

---

## What This Server Is *Not*

- ❌ A GEDCOM replacement  
- ❌ A full genealogy UI  
- ❌ An automated truth engine  
- ❌ A workflow or task manager  

Those concerns can be layered on later if and when needed.

---

## MCP Usage

### Transport

- **Streamable HTTP**

### Endpoint
```
http://<container>:8000/mcp
```

### Typical Agent Flow

1. Search for an existing person
2. Create a new person if none exists
3. Add relationships and events
4. Store assertions with source references
5. Retrieve family groups for context
6. Repeat as new evidence is found

The MCP server is designed to support **many small, iterative writes**, not monolithic imports.

---

## Available Tool Categories

### Person Tools
- `create_person`
- `get_person`
- `search_persons`
- `update_person`

### Relationship Tools
- `create_relationship`
- `list_relationships`
- `get_family_group`

### Event Tools
- `create_event`
- `link_person_event`
- `get_events_for_person`

### Location Tools
- `create_location`
- `search_locations`

### Assertion & Source Tools
- `add_assertion`
- `list_assertions`
- `link_source_to_person`
- `list_sources_for_person`

Tool names are intentionally explicit and table-specific to maintain MCP compatibility.

---

## Database Backend

- **PostgreSQL**
- UUID primary keys
- Minimal constraints to allow uncertain data
- Schema optimized for:
  - search
  - linking
  - later enrichment

The database is expected to grow organically as research progresses.

---

## Technical Architecture

- Python 3.11
- FastMCP (Model Context Protocol)
- ASGI application served via Uvicorn
- Stateless MCP layer
- Persistent PostgreSQL storage

### Why ASGI

ASGI allows:
- Concurrent agent connections
- Streaming transports
- Future extensibility without refactoring

---

## Deployment

Typically deployed via Docker Compose alongside:

- PostgreSQL
- MCPO, MCPHub, MetaMCP or direct to client with MCP support

The MCP server is intended to be **long-running and stable**, not frequently rebuilt.

---

## Schema Evolution

Schema changes are expected but should follow these rules:

- Additive changes only where possible
- No destructive migrations without backups
- Avoid embedding workflow state unless necessary


