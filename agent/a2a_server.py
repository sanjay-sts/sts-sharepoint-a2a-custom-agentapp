"""A2A server for the SharePoint discovery agent (a2a-sdk, JSON-RPC, 127.0.0.1:8002).

- The agent card is public (GET /.well-known/agent-card.json).
- Every other request needs a valid bearer token for api://<client-id>/access_as_user,
  otherwise 401. The token is passed unchanged to the agent, which forwards it to MCP.
- Tasks are stored per user (owner = token oid), so one user cannot read another's tasks.
- CORS allows only SHAREPOINT_ORIGIN (e.g. https://contoso.sharepoint.com).

    uv run python -m agent.a2a_server
"""

import asyncio
import logging
import os

import uvicorn
from a2a.helpers import get_message_text, new_task_from_user_message, new_text_message, new_text_part
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore, TaskUpdater
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    AgentSkill,
    HTTPAuthSecurityScheme,
    SecurityRequirement,
    SecurityScheme,
    TaskState,
)
from starlette.applications import Starlette
from starlette.authentication import SimpleUser
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse

import sp_graph
from agent.graph import stream_answer
from agent.model import credential_problem

HOST, PORT = "127.0.0.1", 8002
PUBLIC_URL = f"http://{HOST}:{PORT}"
SHAREPOINT_ORIGIN = os.environ["SHAREPOINT_ORIGIN"].rstrip("/")
CARD_PATH = "/.well-known/agent-card.json"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("a2a_server")

AGENT_CARD = AgentCard(
    name="SharePoint discovery agent",
    description="Answers questions about which files exist in the signed-in user's SharePoint sites. "
                "Lists and describes files; never reads file content.",
    version="0.1.0",
    default_input_modes=["text/plain"],
    default_output_modes=["text/markdown"],
    capabilities=AgentCapabilities(streaming=True),
    supported_interfaces=[AgentInterface(protocol_binding="JSONRPC", url=PUBLIC_URL, protocol_version="1.0")],
    security_schemes={
        "entra": SecurityScheme(http_auth_security_scheme=HTTPAuthSecurityScheme(
            scheme="bearer", bearer_format="JWT",
            description=f"Entra ID access token for api://{sp_graph.CLIENT_ID}/access_as_user",
        )),
    },
    security_requirements=[SecurityRequirement(schemes={"entra": {"list": []}})],
    skills=[AgentSkill(
        id="sharepoint-discovery",
        name="SharePoint file discovery",
        description="Find, list, count and describe files in the SharePoint sites you can access, "
                    "with links to each file. Results reflect your own SharePoint permissions.",
        tags=["sharepoint", "files", "search"],
        examples=["What sites can you see?", "How many files are in each site, by type?",
                  "List the PDFs in Test site 1 modified in the last 30 days"],
    )],
)


class DiscoveryAgentExecutor(AgentExecutor):
    """Runs the LangGraph agent for one message and maps its output to A2A events."""

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        headers = context.call_context.state.get("headers", {})
        token = headers.get("authorization", "").removeprefix("Bearer ").strip()
        user = context.call_context.state.get("caller", "?")

        task = context.current_task
        if not task:
            task = new_task_from_user_message(context.message)
            await event_queue.enqueue_event(task)
        updater = TaskUpdater(event_queue=event_queue, task_id=task.id, context_id=task.context_id)
        await updater.update_status(TaskState.TASK_STATE_WORKING, message=new_text_message("Working..."))

        question = get_message_text(context.message)
        log.info("message caller=%s task=%s question=%r", user, task.id, question)
        first = True
        try:
            async for ev in stream_answer(question, token):
                if ev["type"] == "tool":
                    await updater.update_status(TaskState.TASK_STATE_WORKING,
                                                message=new_text_message(f"Calling {ev['name']}..."))
                else:
                    await updater.add_artifact([new_text_part(ev["text"], media_type="text/markdown")],
                                               artifact_id="answer", name="answer",
                                               append=not first, last_chunk=False)
                    first = False
            await updater.add_artifact([new_text_part("", media_type="text/markdown")],
                                       artifact_id="answer", name="answer", append=not first, last_chunk=True)
            await updater.update_status(TaskState.TASK_STATE_COMPLETED)
        except Exception as e:
            problem = credential_problem(e)
            log.error("task=%s caller=%s failed: %s", task.id, user, problem or type(e).__name__)
            if not problem:
                log.exception("agent error")
            text = f"ERROR_AWS_CREDENTIALS: {problem}" if problem else \
                f"The agent failed while answering ({type(e).__name__}). Check the agent and MCP server logs."
            await updater.update_status(TaskState.TASK_STATE_FAILED, message=new_text_message(text))

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise NotImplementedError("Cancel is not supported.")


class BearerAuthMiddleware:
    """401 unless the request carries a valid token; the agent card and CORS preflight are public."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] == "OPTIONS" or \
                (scope["method"] == "GET" and scope["path"] == CARD_PATH):
            return await self.app(scope, receive, send)
        auth = dict(scope["headers"]).get(b"authorization", b"").decode()
        token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
        try:
            claims = await asyncio.to_thread(sp_graph.validate_token, token)
        except sp_graph.AuthError as e:
            log.warning("401 %s %s: %s", scope["method"], scope["path"], e)
            resp = JSONResponse({"error": "unauthorized", "detail": str(e)}, status_code=401,
                                headers={"WWW-Authenticate": 'Bearer error="invalid_token"'})
            return await resp(scope, receive, send)
        # The SDK scopes stored tasks by user name; the oid makes that per user.
        scope["user"] = SimpleUser(claims["oid"])
        scope["auth"] = claims.get("preferred_username") or claims.get("upn") or claims["oid"]
        return await self.app(scope, receive, send)


class _CallerContextBuilder:
    """Default context plus the caller's display identity for logs."""

    def __init__(self):
        from a2a.server.routes import DefaultServerCallContextBuilder
        self._default = DefaultServerCallContextBuilder()

    def build(self, request):
        ctx = self._default.build(request)
        ctx.state["caller"] = request.scope.get("auth")
        return ctx


def build_app() -> Starlette:
    handler = DefaultRequestHandler(
        agent_executor=DiscoveryAgentExecutor(),
        task_store=InMemoryTaskStore(),
        agent_card=AGENT_CARD,
    )
    routes = [*create_agent_card_routes(AGENT_CARD),
              *create_jsonrpc_routes(handler, "/", context_builder=_CallerContextBuilder())]
    return Starlette(routes=routes, middleware=[
        Middleware(CORSMiddleware, allow_origins=[SHAREPOINT_ORIGIN], allow_methods=["GET", "POST", "OPTIONS"],
                   allow_headers=["Authorization", "Content-Type", "A2A-Version", "A2A-Extensions"]),
        Middleware(BearerAuthMiddleware),
    ])


app = build_app()

if __name__ == "__main__":
    uvicorn.run(app, host=HOST, port=PORT)
