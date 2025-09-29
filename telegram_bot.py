# telegram_bot.py
import os
import json
import re
import asyncio
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)
from telegram.constants import ChatAction

from ai_services import (
    setup_ai_service,
    get_ai_completion,
    get_and_format_mcp_tools,
    close_mcp_client,
    mcp_call_tool,
    SYSTEM_PROMPT,
)

# FIX 1: Custom JSON Serializer for Pydantic/FastMCP Objects
def pydantic_json_default(obj):
    """Converts a Pydantic object or custom class instance to a serializable dictionary or string."""
    if hasattr(obj, 'model_dump'):
        # Pydantic V2 serialization
        return obj.model_dump()
    if hasattr(obj, 'dict'):
        # Pydantic V1 serialization (fallback)
        return obj.dict()
    
    # CRITICAL FALLBACK: If it's still a non-basic object, convert it to a string.
    # This prevents the TypeError from crashing the program loop.
    if not isinstance(obj, (dict, list, str, int, float, bool, type(None))):
         return str(obj) 
    
    # If all else fails, raise the original error for standard json types
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")

async def start_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        'Hello! I am an AI assistant powered by OpenRouter. I can now use tools to help you. Ask me anything.'
    )

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    chat_id = message.chat_id
    text = message.text

    if not text:
        return
    
    # --- NEW: Aggressive ID Extraction from User Message Text ---
    # Look for a number that follows an ID keyword or is at the end of the message.
    rescued_id_from_text = None
    # Regex: (user|dealer|report|order|id) followed by a number, OR a standalone number at the end
    match = re.search(r'(?:user|dealer|report|dvr|tvr|sales order|sales|order|id)\s*#?\s*(\d+)|(\d+)\s*$', text, re.IGNORECASE)
    if match:
        id_str = match.group(1) or match.group(2)
        try:
            rescued_id_from_text = int(id_str)
            print(f"  -> Host Rescue: Found potential ID {rescued_id_from_text} in user text.")
        except ValueError:
            pass
    # --- END NEW ID EXTRACTION ---

    print(f'🧠 Processing agent request for chat {chat_id}: "{text}"')
    try:
        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ]
        
        tools = context.bot_data.get('mcp_tools', [])

        while True:
            ai_response_message = await asyncio.to_thread(get_ai_completion, messages, tools)
            
            if not ai_response_message:
                raise ValueError("Failed to get a response from the AI.")

            messages.append(ai_response_message)
            tool_calls = ai_response_message.get("tool_calls")

            if not tool_calls:
                break

            for tool_call in tool_calls:
                function_name = tool_call['function']['name']
                try:
                    function_args = json.loads(tool_call['function']['arguments'])

                     # The LLM sometimes hallucinates metadata into the arguments.
                    CLEAN_KEYS = [
                        'inputSchema', 
                        'name', 
                        'parameters',
                        'title',         
                        'description',   
                        'outputSchema',  
                        'icons',         
                        '_meta',         
                        'annotations',
                        'required',    
                    ]
                    # This filters out the LLM's hallucinated metadata and None values.
                    cleaned_args = {
                        k: v for k, v in function_args.items() 
                        if k not in CLEAN_KEYS and v is not None
                    }
                    
                    # --- ULTIMATE CRITICAL ID RESCUE LOGIC ---
                    if function_name in ['get_user_by_id', 'get_dealer_by_id', 
                                         'get_dvr_report_by_id', 'get_tvr_report_by_id', 'get_sales_order_by_id']:
                        
                        # If the necessary ID is missing, attempt all levels of rescue.
                        if not cleaned_args:
                            
                            # Determine the correct key name based on the function
                            rescue_key = None
                            if 'user_by_id' in function_name: rescue_key = 'user_id'
                            elif 'dealer_by_id' in function_name: rescue_key = 'dealer_id'
                            elif 'dvr_report_by_id' in function_name: rescue_key = 'reportId'
                            elif 'tvr_report_by_id' in function_name: rescue_key = 'reportId'
                            elif 'sales_order_by_id' in function_name: rescue_key = 'orderId'
                            
                            id_value_from_args = None
                            
                            # Rescue attempt 1: Search raw LLM args for any integer
                            if function_args:
                                for v in function_args.values():
                                    if isinstance(v, int):
                                        id_value_from_args = v
                                        break
                            
                            # Final Rescue attempt 2: Use the ID extracted from the original user text
                            final_id_value = id_value_from_args or rescued_id_from_text

                            if final_id_value is not None and rescue_key is not None:
                                cleaned_args[rescue_key] = final_id_value
                                print(f"  -> Final ID Injection: Using ID {final_id_value} from {'raw LLM args' if id_value_from_args else 'user message text'}.")
                            
                        # If the necessary ID is STILL missing (after all rescues), fail and instruct the LLM
                        if not cleaned_args:
                            print(f"  -> Tool call failed: LLM failed to provide the required ID for {function_name}.")
                            # This will be sent back to the LLM to try one last time.
                            raise ValueError(f"Required ID parameter missing. Please extract the ID from the user's message and provide it as an integer.")
                    # --- END ULTIMATE CRITICAL ID RESCUE LOGIC ---
                    
                    print(f"  -> Calling tool: {function_name} with args {cleaned_args}")
                    
                    # This handles the custom object returned by mcp_call_tool (fastmcp.Client.call_tool)
                    tool_result = await mcp_call_tool(function_name, cleaned_args)
                    
                    # FIX 2: Use the custom default serializer to handle Pydantic objects.
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call['id'],
                        "content": json.dumps(tool_result, default=pydantic_json_default),
                    })

                except Exception as e:
                    print(f"  -> Tool call failed: {e}")
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call['id'],
                        "content": f"Error executing tool {function_name}: {e}",
                    })
        
        final_answer = messages[-1].get('content')

        if final_answer:
            await message.reply_text(final_answer)
        else:
            await message.reply_text("Sorry, I couldn't come up with a response.")

    except Exception as error:
        print(f"💥 Failed to get AI response for chat {chat_id}: {error}")
        await message.reply_text(
            "Sorry, I'm having trouble connecting to my brain right now. Please try again later."
        )

# FIX: Create a proper async function for post_init
async def post_init_setup(app: Application):
    """
    This function runs once after the bot is initialized.
    It fetches the tools and stores them in the bot's data context.
    """
    app.bot_data['mcp_tools'] = await get_and_format_mcp_tools()

def main():
    print("🚀 Starting agent bot...")
    load_dotenv()
    
    setup_ai_service()
    
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise ValueError("FATAL ERROR: TELEGRAM_BOT_TOKEN is not set in your .env file.")

    app_builder = Application.builder().token(token)
    
    # FIX: Pass the new async setup function to post_init
    app_builder.post_init(post_init_setup)
    
    app = app_builder.build()

    app.add_handler(CommandHandler("start", start_command_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

    try:
        print(f"✅ Telegram Bot is polling for messages...")
        app.run_polling()
    finally:
        print("🛑 Shutting down. Closing MCP client...")
        asyncio.run(close_mcp_client())

if __name__ == "__main__":
    main()