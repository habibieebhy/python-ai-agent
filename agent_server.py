# agent_server.py (Updated Version)

import os
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from openai import OpenAI
import httpx  # 👈 Import httpx
import json

load_dotenv()

# --- 1. NEW MCP HTTP CLIENT ---
# This class uses httpx to communicate with your MCP server's API endpoints.
class MCPClient:
    def __init__(self, base_url: str):
        # Ensure the base URL doesn't end with a slash
        self.base_url = base_url.rstrip('/')
        self.client = httpx.AsyncClient()

    async def list_tools(self):
        """Sends a POST request to the /list_tools endpoint."""
        url = f"{self.base_url}/list_tools"
        response = await self.client.post(url, json={})
        response.raise_for_status()  # Raise an exception for bad status codes
        return response.json()

    async def call_tool(self, tool_name: str, args: dict):
        """Sends a POST request to the /call_tool endpoint."""
        url = f"{self.base_url}/call_tool"
        payload = {"tool_name": tool_name, "arguments": args}
        response = await self.client.post(url, json=payload)
        response.raise_for_status()
        return response.json()

# --- 2. INITIALIZE CLIENTS & APP ---
app = FastAPI()

mcp_url = os.getenv("MCP_SERVER_URL")
openrouter_key = os.getenv("OPENROUTER_API_KEY")

if not mcp_url or not openrouter_key:
    raise RuntimeError("MCP_SERVER_URL and OPENROUTER_API_KEY must be set in .env")

# 👇 Use our new HTTP-based client
mcp_client = MCPClient(mcp_url)

llm_client = OpenAI(
  base_url="https://openrouter.ai/api/v1",
  api_key=openrouter_key,
  default_headers={
    "HTTP-Referer": os.getenv("YOUR_SITE_URL"),
    "X-Title": os.getenv("YOUR_SITE_NAME"),
  },
)

# --- 3. THE REST OF THE SERVER (No changes needed below this line) ---
@app.post("/chat")
async def handle_chat(user_message: str):
    print(f"💬 Received message: '{user_message}'")
    messages = [{"role": "user", "content": user_message}]
    
    try:
        tools_response = await mcp_client.list_tools() # 👈 This now works
        openai_formatted_tools = tools_response.get("tools", [])

        if not openai_formatted_tools:
            print("⚠️ No tools found on MCP server.")
        else:
            print(f"✅ Found {len(openai_formatted_tools)} tools.")

        response = llm_client.chat.completions.create(
            model="deepseek/deepseek-chat-v3.1:free",
            messages=messages,
            tools=openai_formatted_tools,
            tool_choice="auto",
        )
        response_message = response.choices[0].message
        
        if not response_message.tool_calls:
            print("✅ LLM responded directly.")
            return {"response": response_message.content}
        
        print("🛠️ LLM requested a tool call.")
        messages.append(response_message)
        
        tool_call = response_message.tool_calls[0]
        tool_name = tool_call.function.name
        tool_args = json.loads(tool_call.function.arguments)

        print(f"🤙 Calling tool '{tool_name}' with args: {tool_args}")

        tool_result = await mcp_client.call_tool(tool_name, tool_args) # 👈 This now works

        print(f"✔️ Tool result: {tool_result}")

        messages.append({
            "tool_call_id": tool_call.id,
            "role": "tool",
            "name": tool_name,
            "content": json.dumps(tool_result),
        })
        
        print("🗣️ Sending tool result to LLM for final response...")
        final_response = llm_client.chat.completions.create(
            model="deepseek/deepseek-chat-v3.1:free",
            messages=messages,
        )
        final_answer = final_response.choices[0].message.content
        return {"response": final_answer}

    except Exception as e:
        print(f"💥 An error occurred: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/")
def read_root():
    return {"status": "🤖 Python AI Agent is running"}