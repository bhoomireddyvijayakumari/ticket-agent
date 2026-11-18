import asyncio
import sys
from pathlib import Path
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def main():
    server_path = Path(__file__).with_name('02_tiny_server.py')
    # The client launches a SECOND Python process for the server.
    params = StdioServerParameters(command=sys.executable, args=[str(server_path)])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as client:
            await client.initialize()
            catalog = await client.list_tools()
            print('Available tools:', [tool.name for tool in catalog.tools])
            result = await client.call_tool('get_demo_ticket', {'ticket_id': 101})
            if result.isError:
                raise RuntimeError('Demo MCP tool failed')
            for block in result.content:
                if block.type == 'text':
                    print(block.text)

if __name__ == '__main__':
    asyncio.run(main())
