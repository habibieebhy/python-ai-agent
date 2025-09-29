Python AI Agent Telegram Bot with FastMCP Tool Integration
This project is a sophisticated Telegram bot powered by a large language model (LLM) through the OpenRouter API. It functions as an intelligent agent capable of using external tools via a FastMCP (Fast Microservice Control Plane) server to perform complex tasks, such as retrieving business data or executing actions based on user requests.

The agent is specifically designed to be a "friendly, professional, and highly efficient business data assistant," guided by a detailed system prompt that governs its behavior, tool usage, and interaction style.

Key Features
Intelligent AI Agent: Utilizes powerful language models via OpenRouter to understand and process user requests in natural language.

Dynamic Tool Use: Connects to a FastMCP server to dynamically fetch and use a set of available tools (APIs) for data retrieval and other actions.

Robust System Prompting: Employs a carefully crafted system prompt that defines the AI's persona, rules for tool usage, data handling, and user interaction, ensuring accuracy and efficiency.

Telegram Integration: Seamlessly interacts with users through the popular Telegram messaging platform.

Advanced Error Handling: Includes intelligent "ID Rescue Logic" to correct common LLM mistakes, such as failing to provide required IDs for tool calls, by extracting them from the user's message history.

Asynchronous Operations: Built with asyncio to handle multiple requests and tool calls efficiently.

How It Works
The bot operates in a continuous loop to process user messages, making decisions and calling tools until it can provide a final answer.

User Message: A user sends a message to the Telegram bot.

AI Completion Request: The message is sent to the OpenRouter API along with the system prompt and the list of available tools from the FastMCP server.

Tool Call Generation: The AI analyzes the request and, if necessary, generates a "tool call"—a JSON object specifying which function to run and with what arguments.

Tool Execution: The bot parses the tool call, invokes the corresponding function on the FastMCP server, and captures the result.

Response Formulation: The tool's result is sent back to the AI, which uses this new information to either call another tool or formulate a final, human-readable response.

Final Answer: The final answer is sent back to the user on Telegram.

Setup and Installation
Prerequisites
Python 3.8+

A Telegram Bot Token

An OpenRouter API Key

Access to a running FastMCP server instance

Of course. Based on a thorough review of all the files in your project, here is a comprehensive and well-structured README.md file that you can use.

Python AI Agent Telegram Bot with FastMCP Tool Integration
This project is a sophisticated Telegram bot powered by a large language model (LLM) through the OpenRouter API. It functions as an intelligent agent capable of using external tools via a FastMCP (Fast Microservice Control Plane) server to perform complex tasks, such as retrieving business data or executing actions based on user requests.

The agent is specifically designed to be a "friendly, professional, and highly efficient business data assistant," guided by a detailed system prompt that governs its behavior, tool usage, and interaction style.

Key Features
Intelligent AI Agent: Utilizes powerful language models via OpenRouter to understand and process user requests in natural language.

Dynamic Tool Use: Connects to a FastMCP server to dynamically fetch and use a set of available tools (APIs) for data retrieval and other actions.

Robust System Prompting: Employs a carefully crafted system prompt that defines the AI's persona, rules for tool usage, data handling, and user interaction, ensuring accuracy and efficiency.

Telegram Integration: Seamlessly interacts with users through the popular Telegram messaging platform.

Advanced Error Handling: Includes intelligent "ID Rescue Logic" to correct common LLM mistakes, such as failing to provide required IDs for tool calls, by extracting them from the user's message history.

Asynchronous Operations: Built with asyncio to handle multiple requests and tool calls efficiently.

How It Works
The bot operates in a continuous loop to process user messages, making decisions and calling tools until it can provide a final answer.

User Message: A user sends a message to the Telegram bot.

AI Completion Request: The message is sent to the OpenRouter API along with the system prompt and the list of available tools from the FastMCP server.

Tool Call Generation: The AI analyzes the request and, if necessary, generates a "tool call"—a JSON object specifying which function to run and with what arguments.

Tool Execution: The bot parses the tool call, invokes the corresponding function on the FastMCP server, and captures the result.

Response Formulation: The tool's result is sent back to the AI, which uses this new information to either call another tool or formulate a final, human-readable response.

Final Answer: The final answer is sent back to the user on Telegram.

Setup and Installation
Prerequisites
Python 3.8+

A Telegram Bot Token

An OpenRouter API Key

Access to a running FastMCP server instance

1. Clone the Repository
Bash

git clone <your-repo-url>
cd <your-repo-directory>
2. Create a Virtual Environment
It's highly recommended to use a virtual environment to manage dependencies.

Bash

python -m venv venv
source venv/bin/activate  # On Windows, use `venv\Scripts\activate`
3. Install Dependencies
Install all the required Python packages from the requirements.txt file.

Bash

pip install -r requirements.txt
4. Configure Environment Variables
Create a .env file in the root of the project. This file will store your secret keys and configuration settings. You can use the .gitignore file as a reference, which prevents the .env file from being committed.

Populate your .env file with the following:

Code snippet

# Your Telegram Bot API token from BotFather
TELEGRAM_BOT_TOKEN="YOUR_TELEGRAM_BOT_TOKEN"

# Your API key for OpenRouter
OPENROUTER_API_KEY="YOUR_OPENROUTER_API_KEY"

# (Optional) The URL of your FastMCP server
FASTMCP_URL="https://your-fastmcp-instance.cloud/mcp"

# (Optional) For identifying traffic to OpenRouter
YOUR_SITE_URL="http://your-app-url.com"
YOUR_SITE_NAME="YourAppName"
Usage
To start the bot, simply run the telegram_bot.py script from your terminal:

Bash

python telegram_bot.py
The bot will start polling for new messages. You can now open Telegram and interact with your bot.

Project Structure
.
├── telegram_bot.py      # Main application entry point, handles Telegram events and conversation loop.
├── ai_services.py       # Manages communication with the OpenRouter LLM and the FastMCP tool server.
├── ai_prompt_helper.py  # Defines the core system prompt and behavioral rules for the AI agent.
├── requirements.txt     # A list of all Python dependencies for the project.
├── .env                 # (You need to create this) Stores secret keys and environment variables.
└── .gitignore           # Specifies files and directories to be ignored by Git.