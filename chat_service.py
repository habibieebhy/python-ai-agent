# chat-service.py
import json, asyncio
from typing import Dict, Any, List, Tuple, Optional
from ai_services import get_ai_completion, mcp_call_tool, SYSTEM_PROMPT, pydantic_json_default
from post_handler import check_and_store_post_request_core, execute_pending_post_core

class ChatService:
    def __init__(self):
        # adapter provides user_state dict per user, we won’t store globally here
        pass

    async def handle(self, user_state: Dict[str, Any], text: str) -> Tuple[str, bool]:
        """
        Returns (display_text, awaiting_confirmation)
        awaiting_confirmation=True means we stashed a POST payload and expect user to send 'Y'
        """
        # per-user message history
        messages: List[Dict[str, Any]] = user_state.setdefault("messages", [{"role":"system","content": SYSTEM_PROMPT}])
        messages.append({"role":"user","content": text})

        tools = user_state.get("mcp_tools", [])  # adapter can prefill at login/init

        while True:
            ai_msg = await asyncio.to_thread(get_ai_completion, messages, tools)
            if not ai_msg:
                return ("Model returned nothing. Try again.", False)

            messages.append(ai_msg)
            tool_calls = ai_msg.get("tool_calls") or []
            if not tool_calls:
                final_text = ai_msg.get("content") or "..."
                # Turn 1: check for hidden POST payload and stash it
                is_conf, display, _, _ = check_and_store_post_request_core(final_text, user_state)
                return (display, is_conf)

            # tool loop
            for tc in tool_calls:
                fn = tc["function"]["name"]
                raw = tc["function"].get("arguments") or "{}"
                try: args = json.loads(raw)
                except: args = {}

                # scrub LLM junk
                CLEAN = {"inputSchema","name","parameters","title","description","outputSchema","icons","_meta","annotations","required"}
                args = {k:v for k,v in args.items() if k not in CLEAN and v is not None}

                try:
                    result = await mcp_call_tool(fn, args)
                    messages.append({
                        "role":"tool",
                        "tool_call_id": tc["id"],
                        "content": json.dumps(result, default=pydantic_json_default)
                    })
                except Exception as e:
                    messages.append({
                        "role":"tool",
                        "tool_call_id": tc["id"],
                        "content": f"Error executing tool {fn}: {e}"
                    })
            # loop continues to let model read tool results

    async def confirm_post(self, user_state: Dict[str, Any]) -> str:
        """Turn 2: execute stored POST if present."""
        executed, response, _ = await execute_pending_post_core(user_state)
        if executed: return response
        return "Nothing to submit."
