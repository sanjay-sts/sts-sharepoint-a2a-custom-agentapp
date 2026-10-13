"""LangGraph tool-calling agent whose only tools come from the SharePoint MCP server.

The caller's bearer token is attached to a fastmcp Client built for that one
request; the client, its tools and the graph are discarded afterwards, so two
users' requests can never share a token.
"""

import logging
from datetime import datetime, timezone
import os
import warnings
from collections.abc import AsyncIterator

from fastmcp import Client
from langchain.agents import create_agent

with warnings.catch_warnings():
    warnings.simplefilter("ignore")  # langchain.mcp is beta; chosen deliberately
    from langchain.mcp import MCPAdapter

from agent.model import make_model

MCP_URL = os.environ.get("MCP_URL", "http://127.0.0.1:8001/mcp")

SYSTEM_PROMPT = """\
Today is {today} (UTC). Use this date for any "last N days" or "recent" question; never assume another date.

You answer questions about which files exist in the user's SharePoint sites.
You can list and describe files; you cannot read their contents.

Rules:
- Every factual claim (site names, file names, folders, dates, authors, sizes) must come from a tool result in this conversation. Never guess or rely on memory.
- For any count or total, call inventory_summary and report its numbers. Do not count lists yourself, and do not state a total or count unless it came from inventory_summary.
- To find files by name, type, date or site, prefer search_files. Use list_sites to resolve a site name to its id.
- Cite every file you mention with its SharePoint URL as a Markdown link: [file name](url).
- If the tools return nothing that matches, say plainly that nothing was found. Do not suggest that a file might exist elsewhere.
- Results reflect only what the signed-in user has access to; you cannot see other users' files.
- Be concise. Use short lists or tables for multiple files.
"""

log = logging.getLogger("agent")
_model = None


def _get_model():
    global _model
    if _model is None:
        _model = make_model()  # stateless and token-free, safe to share
    return _model


async def stream_answer(question: str, user_token: str) -> AsyncIterator[dict]:
    """Run the agent for one question as the token's user.

    Yields {"type": "tool", "name": ...} when a tool is called and
    {"type": "text", "text": ...} for each piece of the answer.
    """
    client = Client(MCP_URL, auth=user_token)  # per request: this user's token only
    async with MCPAdapter(client) as adapter:
        tools = await adapter.list_tools()
        today = datetime.now(timezone.utc).date().isoformat()
        graph = create_agent(_get_model(), tools, system_prompt=SYSTEM_PROMPT.format(today=today))
        async for chunk, meta in graph.astream(
            {"messages": [{"role": "user", "content": question}]},
            stream_mode="messages",
        ):
            if meta.get("langgraph_node") != "model":
                continue
            for call in getattr(chunk, "tool_call_chunks", None) or []:
                if call.get("name"):
                    yield {"type": "tool", "name": call["name"]}
            text = chunk.text if isinstance(chunk.text, str) else chunk.text()
            if text:
                yield {"type": "text", "text": text}
