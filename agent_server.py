import asyncio
from fastmcp import Client

client = Client("https://brixta-mycoco-mcp.fastmcp.app/mcp")

async def main():
    """
    The core logic for interacting with the MCP server.
    This is where we will build our creative agent logic.
    """
    async with client:
        # Ensure client can connect
        await client.ping()

        # 1. Discover what tools are available on the server
        tools = await client.list_tools()
        print("--- Available Tools ---")
        print(tools)
        print("-" * 25)


        # 2. Execute a specific tool call (placeholder)
        #    You will need to replace "your_example_tool" with a real tool name
        #    and provide its required parameters.
        result = await client.call_tool("your_example_tool", {"param": "value"})

        print("\n--- Tool Result ---")
        print(result)

if __name__ == "__main__":
    # This ensures the main function runs only when the script is executed directly
    asyncio.run(main())

