import json
import re
from typing import Dict, Any, Tuple, Optional

from ai_services import mcp_call_tool, pydantic_json_default 
from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ChatAction

# Regex to find the hidden JSON payload wrapped in the markers
PAYLOAD_REGEX = re.compile(r'\[TOOL_ARGS_JSON\](.*?)\[/TOOL_ARGS_JSON\]', re.DOTALL)

STORED_PAYLOAD_KEY = 'pending_tool_payload'
STORED_TOOL_NAME_KEY = 'pending_tool_name'

# --- Small safety rails ---
MAX_PAYLOAD_CHARS = 50_000  # hard cap to avoid LLM dumping a novel
ALLOWED_POST_TOOLS = {'post_tvr_report', 'post_dvr_report', 'post_sales_order'}  # expand as needed

def _pick_tool_name(payload: Dict[str, Any]) -> str:
    """
    Prefer explicit hint in payload: {"__tool": "post_dvr_report"}
    Fallback to heuristics (original logic).
    """
    hint = payload.get('__tool')
    if isinstance(hint, str) and hint in ALLOWED_POST_TOOLS:
        return hint

    # Heuristics
    if 'siteNameConcernedPerson' in payload and 'clientsRemarks' in payload:
        return 'post_tvr_report'
    if 'dealerTotalPotential' in payload and 'todayCollectionRupees' in payload:
        return 'post_dvr_report'
    if 'orderTotal' in payload and 'estimatedDelivery' in payload:
        return 'post_sales_order'

    # Last-resort default stays the same, but log it
    print("  -> Host Warning: Tool name heuristic fallback triggered.")
    return 'post_sales_order'

def _guard_payload(json_text: str) -> Optional[Dict[str, Any]]:
    """
    Validate size and parse JSON safely. Return dict or None on failure.
    """
    if len(json_text) > MAX_PAYLOAD_CHARS:
        print(f"  -> Host Warning: Payload too large ({len(json_text)} chars).")
        return None
    try:
        obj = json.loads(json_text)
        if not isinstance(obj, dict):
            print("  -> Host Warning: Payload is not a JSON object.")
            return None
        return obj
    except json.JSONDecodeError as e:
        print(f"  -> Host Warning: JSON parse error: {e}")
        return None

# ### CORE FUNCTIONS (Platform-Agnostic Logic for both Telegram & Web) ###

async def execute_pending_post_core(user_state: Dict[str, Any]) -> Tuple[bool, str, Dict[str, Any] | None]:
    """
    Executes a pending POST request stored in the user_state (Turn 2).
    Returns: (was_executed, response_text, tool_result)
    """
    pending_payload = user_state.pop(STORED_PAYLOAD_KEY, None)
    pending_tool_name = user_state.pop(STORED_TOOL_NAME_KEY, None)

    if pending_payload and pending_tool_name:
        print(f"  -> Host Bypass: Executing stored tool call: {pending_tool_name} with payload.")
        try:
            tool_result = await mcp_call_tool(pending_tool_name, pending_payload)

            # Avoid markdown since Telegram parse_mode isn't set by default
            header = f"✔ {pending_tool_name.replace('_', ' ').title()} submitted.\n\n"
            body = json.dumps(tool_result, indent=2, default=pydantic_json_default)
            return True, header + body, tool_result

        except Exception as e:
            error_msg = f"✖ Submission failed for {pending_tool_name}:\n{e}"
            print(f"  -> Host Execution Error: {error_msg}")
            return True, error_msg, None

    return False, "", None

def check_and_store_post_request_core(final_answer: str, user_state: Dict[str, Any]) -> Tuple[bool, str, str | None, Dict[str, Any] | None]:
    """
    Checks LLM output for hidden payload, stores it, and returns cleaned text.
    Returns: (is_confirmation_request, display_text, tool_name, payload)
    """
    if not final_answer or "[TOOL_ARGS_JSON]" not in final_answer:
        return (False, final_answer, None, None)

    payload_match = PAYLOAD_REGEX.search(final_answer)
    if not payload_match:
        return (False, final_answer, None, None)

    json_string = payload_match.group(1).strip()
    payload = _guard_payload(json_string)
    if payload is None:
        # Leave text unchanged; let the front-end or user see the LLM’s message
        print("  -> Host Warning: Failed to parse or validate JSON payload from LLM response.")
        return (False, final_answer, None, None)

    tool_name = _pick_tool_name(payload)

    user_state[STORED_PAYLOAD_KEY] = payload
    user_state[STORED_TOOL_NAME_KEY] = tool_name
    print(f"  -> Host Capture: Stored payload for {tool_name} in user_state.")

    # Strip markers from user-visible text
    display_answer = PAYLOAD_REGEX.sub('', final_answer).strip()
    return (True, display_answer, tool_name, payload)

# ### TELEGRAM WRAPPERS ###

async def handle_post_execution_reply(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    Turn 2: user replies 'Y' to execute stored POST.
    """
    text = update.message.text or ""
    if text.strip().upper() != 'Y':
        return False

    if not context.user_data.get(STORED_PAYLOAD_KEY):
        return False

    chat_id = update.message.chat_id
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

    was_executed, response_text, _ = await execute_pending_post_core(context.user_data)

    if was_executed:
        # No markdown parse mode set; keep plain text
        await update.message.reply_text(response_text)
        return True

    return False

def handle_post_confirmation_request(final_answer: str, context: ContextTypes.DEFAULT_TYPE) -> Tuple[bool, str]:
    """
    Turn 1: detect payload, stash it, and return cleaned display text.
    """
    is_confirmation_request, display_answer, _, _ = check_and_store_post_request_core(final_answer, context.user_data)
    return (is_confirmation_request, display_answer)
