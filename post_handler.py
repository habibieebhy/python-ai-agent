# post_handler.py
import json
import re
from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ChatAction
from typing import Dict, Any, Tuple

# Import tool caller and serializer from ai_services as it is now the central service utility file
from ai_services import mcp_call_tool, pydantic_json_default 

# --- Constants for Stored State & Regex ---
# Regex to find the hidden JSON payload wrapped in the markers
PAYLOAD_REGEX = re.compile(r'\[TOOL_ARGS_JSON\](.*?)\[/TOOL_ARGS_JSON\]', re.DOTALL)

STORED_PAYLOAD_KEY = 'pending_tool_payload'
STORED_TOOL_NAME_KEY = 'pending_tool_name'

async def handle_post_execution_reply(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    Handles the user's 'Y' reply to execute a pending POST request (Turn 2).
    If 'Y' is detected and a payload is stored, it executes the tool call directly,
    bypassing the LLM for this turn.
    Returns True if execution was attempted (success or failure), False otherwise.
    """
    text = update.message.text
    if text.strip().upper() != 'Y':
        return False

    # Retrieve and clear the pending state from context.user_data
    pending_payload = context.user_data.pop(STORED_PAYLOAD_KEY, None)
    pending_tool_name = context.user_data.pop(STORED_TOOL_NAME_KEY, None)
    chat_id = update.message.chat_id

    if pending_payload and pending_tool_name:
        print(f"  -> Host Bypass: Executing stored tool call: {pending_tool_name} with payload.")
        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
        try:
            # The stored payload is already a clean dictionary of arguments
            tool_result = await mcp_call_tool(pending_tool_name, pending_payload)
            
            # Report success to user
            response_text = f"✅ **{pending_tool_name.replace('_', ' ').title()} successfully submitted!**\n\n"
            
            # Use the imported serializer for clean JSON output
            response_text += json.dumps(tool_result, indent=2, default=pydantic_json_default)
            
            await update.message.reply_text(response_text)
            return True
        except Exception as e:
            # If execution fails, report the error directly
            error_msg = f"❌ Submission Failed for {pending_tool_name}:\n{e}"
            print(f"  -> Host Execution Error: {error_msg}")
            await update.message.reply_text(error_msg)
            return True # Execution was attempted, so we return True

    # 'Y' was sent, but no payload was found (let the LLM handle this unusual turn)
    return False

def handle_post_confirmation_request(final_answer: str, context: ContextTypes.DEFAULT_TYPE) -> Tuple[bool, str]:
    """
    Checks the LLM's final response for the hidden JSON payload (Turn 1).
    If found, it extracts and stores the payload for later execution.
    Returns (was_payload_found, display_text).
    """
    # Check for the hidden JSON payload from the LLM's final response
    payload_match = PAYLOAD_REGEX.search(final_answer)
    
    if payload_match:
        # Found the hidden payload! This is Turn 1 (Confirmation Request)
        json_string = payload_match.group(1).strip()
        
        # Attempt to parse and store the JSON payload
        try:
            stored_payload: Dict[str, Any] = json.loads(json_string)
            
            # --- Robust Heuristic to Determine Target POST Tool Name based on Unique Required Fields ---
            
            # 1. TVR (Technical Visit Report): Highly unique fields for site/client
            if 'siteNameConcernedPerson' in stored_payload and 'clientsRemarks' in stored_payload:
                target_tool = 'post_tvr_report'
            
            # 2. DVR (Daily Visit Report): Highly unique fields for dealer potential/collection
            elif 'dealerTotalPotential' in stored_payload and 'todayCollectionRupees' in stored_payload:
                target_tool = 'post_dvr_report'
            
            # 3. Sales Order: Unique fields for order total and delivery date
            elif 'orderTotal' in stored_payload and 'estimatedDelivery' in stored_payload:
                 target_tool = 'post_sales_order'
            
            else:
                 # Default fallback if the payload doesn't fit a clear signature
                 target_tool = 'post_sales_order' 
                 print("  -> Host Warning: Tool name heuristic fallback triggered.")

            context.user_data[STORED_PAYLOAD_KEY] = stored_payload
            context.user_data[STORED_TOOL_NAME_KEY] = target_tool
            print(f"  -> Host Capture: Stored payload for {target_tool} in user_data.")
            
            # Remove the JSON marker from the final output before displaying to the user
            display_answer = PAYLOAD_REGEX.sub('', final_answer).strip()
            return (True, display_answer)
            
        except json.JSONDecodeError:
            print(f"  -> Host Warning: Failed to parse JSON payload from LLM response.")
            # If parsing fails, return the full, uncleaned text
            pass
            
    return (False, final_answer)
