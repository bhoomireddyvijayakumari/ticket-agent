"""Local stdio MCP server. Never print non-protocol data to stdout."""
from mcp.server.fastmcp import FastMCP
from . import store

mcp = FastMCP("ticket-service")

@mcp.tool()
def get_ticket(ticket_id: int) -> dict:
    """Read a ticket snapshot with its version."""
    return store.get(ticket_id)

@mcp.tool()
def list_pending(limit: int = 100) -> list[dict]:
    """List unprocessed open tickets in ID order."""
    return store.pending(limit)

@mcp.tool()
def search_knowledge_base(query: str) -> list[dict]:
    """Search curated support articles using keywords; returns article IDs."""
    return store.search(query)

@mcp.tool()
def apply_analysis(ticket_id: int, expected_version: int, analysis: dict, dry_run: bool = True) -> dict:
    """Validate analysis, enforce policy, and preview or atomically update one ticket."""
    return store.apply(ticket_id, expected_version, analysis, dry_run)

if __name__ == '__main__':
    store.init()
    mcp.run(transport='stdio')
