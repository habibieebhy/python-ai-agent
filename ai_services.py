# ai_services.py
import os
import logging
import asyncio
from typing import Optional, Any, Dict, List
from dotenv import load_dotenv

from openai import OpenAI
from fastmcp import Client
from ai_prompt_helper import get_system_prompt  # prompt helper

load_dotenv()

# -------------------- Config --------------------
SYSTEM_PROMPT = get_system_prompt()

OPENAI_API_KEY = (os.getenv("OPENAI_API_KEY") or "").strip()
OPENAI_MODEL = "gpt-5-nano"

FASTMCP_URL = os.getenv("FASTMCP_URL", "https://brixta-mycoco-mcp.fastmcp.app/mcp")
FASTMCP_LABEL = "brixta-mycoco-mcp"

logger = logging.getLogger("ai_services")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s: %(message)s"))
    logger.addHandler(handler)
logger.setLevel(logging.INFO)

# -------------------- Utility --------------------
def pydantic_json_default(obj):
    """
    Converts a Pydantic object or custom class instance to a serializable dict/string.
    Keeps your JSON dumps from exploding when it sees models.
    """
    if hasattr(obj, 'model_dump'):
        return obj.model_dump()          # Pydantic v2
    if hasattr(obj, 'dict'):
        return obj.dict()                # Pydantic v1
    if not isinstance(obj, (dict, list, str, int, float, bool, type(None))):
        return str(obj)
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")

# ---------------- OpenAI client -----------------
_openai_client: Optional[OpenAI] = None

def _ensure_openai_client() -> OpenAI:
    if _openai_client is None:
        raise RuntimeError("OpenAI client not initialized. Call setup_ai_service() first.")
    return _openai_client

def setup_ai_service():
    global _openai_client
    if _openai_client is not None:
        logger.info("✅ OpenAI service already initialized.")
        return
    if not OPENAI_API_KEY:
        raise RuntimeError("FATAL: OPENAI_API_KEY is not set.")
    _openai_client = OpenAI(api_key=OPENAI_API_KEY)
    logger.info("✅ OpenAI Client initialized (Responses API)")

# ---------------- Responses + MCP ----------------
def _messages_to_responses_input(messages: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """
    Convert chat-completions-style messages to Responses 'input' format.
    Keep roles, coerce content to str, drop any tool plumbing.
    """
    out: List[Dict[str, str]] = []
    for m in messages or []:
        role = (m.get("role") or "user").strip()
        content = m.get("content")
        if content is None:
            text = ""
        elif isinstance(content, list):
            # Flatten text parts if someone fed in a parts array
            parts = []
            for p in content:
                if isinstance(p, dict) and "text" in p:
                    parts.append(str(p.get("text") or ""))
                elif isinstance(p, str):
                    parts.append(p)
            text = " ".join(parts)
        else:
            text = str(content)
        out.append({"role": role, "content": text})
    return out

def _extract_text_from_responses(resp) -> str:
    """
    Prefer .output_text; fallback to scanning .output list.
    """
    txt = getattr(resp, "output_text", None)
    if isinstance(txt, str) and txt.strip():
        return txt
    chunks: List[str] = []
    for part in getattr(resp, "output", []) or []:
        if getattr(part, "type", "") == "message":
            for c in getattr(part, "content", []) or []:
                if getattr(c, "type", "") in ("output_text", "text"):
                    chunks.append(getattr(c, "text", "") or "")
    return "".join(chunks).strip()

def get_ai_completion(messages: List[Dict[str, Any]], tools: Optional[List[Dict[str, Any]]] = None) -> Optional[Dict[str, Any]]:
    """
    Primary entry used by ChatService.
    Uses OpenAI Responses API with a Remote MCP server.
    Returns: {"role": "assistant", "content": "..."}  (no tool_calls ever)
    """
    client = _ensure_openai_client()

    # Build input from your conversation history.
    # If your ChatService already prepends SYSTEM_PROMPT as a system message,
    # great. If not, we prepend it here.
    needs_system = True
    for m in messages:
        if (m.get("role") == "system") and (m.get("content") or "").strip():
            needs_system = False
            break

    msgs = messages[:] if messages else []
    if needs_system and SYSTEM_PROMPT:
        msgs = [{"role": "system", "content": SYSTEM_PROMPT}] + msgs

    inputs = _messages_to_responses_input(msgs)

    try:
        logger.info(f"🤖 Sending request to Responses API ({OPENAI_MODEL}) via MCP...")
        resp = client.responses.create(
            model=OPENAI_MODEL,
            tools=[
                {
                    "type": "mcp",
                    "server_label": FASTMCP_LABEL,
                    "server_url": FASTMCP_URL,
                    "require_approval": "never",
                }
            ],
            input=inputs,
        )
    except Exception as e:
        logger.error(f"💥 OpenAI Responses API Error: {e}")
        return None

    text = _extract_text_from_responses(resp)
    logger.info("✅ AI Response Received.")
    return {"role": "assistant", "content": text}

# ---------------- FastMCP direct client (optional) ----------------
# You kept these; leaving them intact in case other parts use them.
_mcp_client: Optional[Client] = None
_mcp_lock = asyncio.Lock()

async def setup_mcp_client(mcp_url: Optional[str] = None) -> Client:
    global _mcp_client
    url = mcp_url or FASTMCP_URL
    async with _mcp_lock:
        if _mcp_client is not None:
            return _mcp_client
        client = Client(url)
        await client.__aenter__()
        _mcp_client = client
        logger.info("✅ Connected to FastMCP: %s", url)
        return client

async def close_mcp_client():
    global _mcp_client
    async with _mcp_lock:
        if _mcp_client is not None:
            try:
                await _mcp_client.__aexit__(None, None, None)
            finally:
                _mcp_client = None
                logger.info("🛑 FastMCP client closed")

def _ensure_mcp() -> Client:
    if _mcp_client is None:
        raise RuntimeError("FastMCP client not initialized. Call setup_mcp_client() first.")
    return _mcp_client

async def mcp_ping() -> Any:
    return await _ensure_mcp().ping()

async def mcp_list_tools() -> Any:
    return await _ensure_mcp().list_tools()

async def mcp_list_resources() -> Any:
    return await _ensure_mcp().list_resources()

async def mcp_list_prompts() -> Any:
    return await _ensure_mcp().list_prompts()

async def mcp_call_tool(tool_name: str, params: Dict[str, Any]) -> Any:
    return await _ensure_mcp().call_tool(tool_name, params)

async def get_and_format_mcp_tools() -> List[Dict[str, Any]]:
    logger.info("🛠️ Fetching and formatting tools from MCP server...")
    try:
        mcp_client = await setup_mcp_client()
        mcp_tools = await mcp_client.list_tools()
        formatted_tools = []
        for tool in mcp_tools:
            formatted_tools.append({
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.model_json_schema(),
                }
            })
        logger.info(f"✅ Found and formatted {len(formatted_tools)} tools.")
        return formatted_tools
    except Exception as e:
        logger.error(f"💥 Failed to fetch tools from MCP: {e}")
        return []
