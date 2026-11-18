"""Do not print on stdout: MCP owns that stream."""
from mcp.server.fastmcp import FastMCP

mcp = FastMCP('first-ticket-server')

@mcp.tool()
def get_demo_ticket(ticket_id: int) -> dict:
    """Return a fictional support ticket for the MCP learning exercise."""
    return {'id': ticket_id, 'subject': 'Cannot log in',
            'body': 'The password reset email has not arrived.', 'status': 'open'}

if __name__ == '__main__':
    mcp.run(transport='stdio')
