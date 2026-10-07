"""SharePoint discovery MCP server (FastMCP, Streamable HTTP on 127.0.0.1:8001).

Every request must carry a bearer token for api://<client-id>/access_as_user.
Each tool exchanges that token on-behalf-of the caller and reads Graph as them,
so SharePoint applies the caller's own permissions. Listing only, no content.

    uv run python -m mcp_server.server
"""

import asyncio
import logging
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import PurePosixPath

import httpx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.auth import AccessToken, TokenVerifier
from fastmcp.server.dependencies import get_access_token

import sp_graph

HOST, PORT = "127.0.0.1", 8001

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("mcp_server")


class EntraTokenVerifier(TokenVerifier):
    """Accept only tokens that sp_graph.validate_token accepts; anything else is a 401."""

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            claims = await asyncio.to_thread(sp_graph.validate_token, token)
        except sp_graph.AuthError as e:
            log.warning("rejected request: %s", e)
            return None
        return AccessToken(
            token=token,
            client_id=claims.get("appid") or claims.get("azp") or "",
            scopes=claims.get("scp", "").split(),
            expires_at=claims.get("exp"),
            subject=claims.get("oid"),
            claims=claims,
        )


mcp = FastMCP(
    name="sharepoint-discovery",
    instructions=(
        "Lists and describes SharePoint sites, libraries and files the signed-in user can access. "
        "Read-only metadata; file content is never read. Every file result has a SharePoint URL to cite."
    ),
    auth=EntraTokenVerifier(base_url=f"http://{HOST}:{PORT}"),
)

READ_ONLY = {"readOnlyHint": True, "openWorldHint": True}


async def _as_caller(tool: str, **args) -> str:
    """Log the call and return a Graph token for the calling user."""
    at = get_access_token()
    if at is None or not at.claims:
        raise ToolError("not authenticated")
    user = at.claims.get("preferred_username") or at.claims.get("upn") or at.claims["oid"]
    log.info("tool=%s caller=%s oid=%s args=%s", tool, user, at.claims["oid"], args)
    try:
        return await asyncio.to_thread(sp_graph.graph_token_for, at.token, at.claims)
    except sp_graph.AuthError as e:
        raise ToolError(str(e)) from None


def _graph_error(e: httpx.HTTPStatusError, what: str) -> ToolError:
    code = e.response.status_code
    if code in (403, 404):
        return ToolError(f"{what} was not found or you do not have access to it (HTTP {code}).")
    return ToolError(f"Microsoft Graph returned HTTP {code} for {what}.")


def _file_type(name: str) -> str:
    return PurePosixPath(name).suffix.lstrip(".").lower() or "(none)"


def _file_row(folder: str, item: dict, site: str | None = None, library: str | None = None) -> dict:
    row = {
        "name": item["name"],
        "folder": folder,
        "type": _file_type(item["name"]),
        "size": item.get("size", 0),
        "modified": item.get("lastModifiedDateTime"),
        "modified_by": ((item.get("lastModifiedBy") or {}).get("user") or {}).get("displayName"),
        "url": item.get("webUrl"),
        "drive_id": (item.get("parentReference") or {}).get("driveId"),
        "item_id": item["id"],
    }
    if site is not None:
        row = {"site": site, "library": library, **row}
    return row


async def _sites(gt: str) -> list[dict]:
    """Sites the user can see. Skips SharePoint Embedded containers (/contentstorage/), which are not sites."""
    sites = [s async for s in sp_graph.get_paged(gt, "sites?search=*")]
    return [s for s in sites if "/contentstorage/" not in (s.get("webUrl") or "")]


async def _all_files(gt: str, site_id: str | None = None) -> list[dict]:
    """Every file the user can see, optionally in one site, with site and library names."""
    if site_id:
        try:
            sites = [await sp_graph.get_json(gt, f"sites/{site_id}")]
        except httpx.HTTPStatusError as e:
            raise _graph_error(e, f"site {site_id}") from None
    else:
        sites = await _sites(gt)

    async def site_files(site: dict) -> list[dict]:
        site_name = site.get("displayName") or site.get("name")
        try:
            drives = [d async for d in sp_graph.get_paged(gt, f"sites/{site['id']}/drives")]
        except httpx.HTTPStatusError:
            return []  # a site listed by search but not readable by this user
        out = []
        for drive in drives:
            async for folder, item in sp_graph.walk_files(gt, drive["id"]):
                row = _file_row(folder, item, site_name, drive["name"])
                row["site_id"] = site["id"]
                out.append(row)
        return out

    # Sites are walked concurrently; one walk per site keeps Graph load modest.
    per_site = await asyncio.gather(*(site_files(s) for s in sites))
    return [row for rows in per_site for row in rows]


@mcp.tool(annotations=READ_ONLY)
async def list_sites() -> list[dict]:
    """List every SharePoint site the user can access, with its id, name and URL.

    Use this first when the user asks which sites exist, or when you need a site id
    for list_libraries, search_files or inventory_summary.
    """
    gt = await _as_caller("list_sites")
    sites = await _sites(gt)
    return sorted(
        ({"site_id": s["id"], "name": s.get("displayName") or s.get("name"), "url": s.get("webUrl")} for s in sites),
        key=lambda s: (s["name"] or "").lower(),
    )


@mcp.tool(annotations=READ_ONLY)
async def list_libraries(site_id: str) -> list[dict]:
    """List the document libraries (drives) in one site, with drive id and name.

    Use this to get a drive id for list_files. site_id comes from list_sites.
    """
    gt = await _as_caller("list_libraries", site_id=site_id)
    try:
        drives = [d async for d in sp_graph.get_paged(gt, f"sites/{site_id}/drives")]
    except httpx.HTTPStatusError as e:
        raise _graph_error(e, f"site {site_id}") from None
    return [{"drive_id": d["id"], "name": d["name"], "url": d.get("webUrl")} for d in drives]


@mcp.tool(annotations=READ_ONLY)
async def list_files(drive_id: str, folder_path: str | None = None) -> list[dict]:
    """List every file in a library, including subfolders, or only under folder_path.

    Returns name, folder, type, size, modified, modified_by and url for each file.
    Use this to browse one library; to find files across sites by name, type or date,
    prefer search_files. To count files, use inventory_summary instead of counting this list.
    """
    gt = await _as_caller("list_files", drive_id=drive_id, folder_path=folder_path)
    try:
        item_id, base = "root", ""
        if folder_path and folder_path.strip("/"):
            base = folder_path.strip("/")
            folder = await sp_graph.get_json(gt, f"drives/{drive_id}/root:/{base}")
            item_id = folder["id"]
        return [_file_row(f, item) async for f, item in sp_graph.walk_files(gt, drive_id, item_id, base)]
    except httpx.HTTPStatusError as e:
        raise _graph_error(e, f"library {drive_id}" + (f" folder '{folder_path}'" if folder_path else "")) from None


@mcp.tool(annotations=READ_ONLY)
async def search_files(
    name_contains: str | None = None,
    file_type: str | None = None,
    modified_after: str | None = None,
    site_id: str | None = None,
) -> list[dict]:
    """Find files by file name, type, modification date and site, across every site the user can access.

    - name_contains: case-insensitive text that must appear in the file name.
    - file_type: file extension such as "pdf" or "docx".
    - modified_after: ISO date (YYYY-MM-DD); only files modified on or after it.
    - site_id: limit to one site (from list_sites).
    All filters are optional and combined with AND. Matches on names and metadata only,
    never on file content. An empty list means no file matched.
    """
    gt = await _as_caller("search_files", name_contains=name_contains, file_type=file_type,
                          modified_after=modified_after, site_id=site_id)
    after = None
    if modified_after:
        try:
            after = datetime.fromisoformat(modified_after)
        except ValueError:
            raise ToolError("modified_after must be an ISO date such as 2026-09-01") from None
        if after.tzinfo is None:
            after = after.replace(tzinfo=timezone.utc)
    ext = file_type.lower().lstrip(".") if file_type else None
    text = name_contains.lower() if name_contains else None

    def keep(r: dict) -> bool:
        if text and text not in r["name"].lower():
            return False
        if ext and r["type"] != ext:
            return False
        if after and datetime.fromisoformat(r["modified"]) < after:
            return False
        return True

    return [r for r in await _all_files(gt, site_id) if keep(r)]


@mcp.tool(annotations=READ_ONLY)
async def get_file_metadata(drive_id: str, item_id: str) -> dict:
    """Get full metadata for one file: name, path, size, type, created and modified (when and by whom), and URL.

    drive_id and item_id come from list_files or search_files results.
    """
    gt = await _as_caller("get_file_metadata", drive_id=drive_id, item_id=item_id)
    try:
        item = await sp_graph.get_json(gt, f"drives/{drive_id}/items/{item_id}")
    except httpx.HTTPStatusError as e:
        raise _graph_error(e, f"file {item_id}") from None
    parent = item.get("parentReference") or {}
    return {
        "name": item.get("name"),
        "path": (parent.get("path") or "").split("root:", 1)[-1].lstrip("/"),
        "type": _file_type(item.get("name", "")),
        "mime_type": (item.get("file") or {}).get("mimeType"),
        "size": item.get("size"),
        "created": item.get("createdDateTime"),
        "created_by": ((item.get("createdBy") or {}).get("user") or {}).get("displayName"),
        "modified": item.get("lastModifiedDateTime"),
        "modified_by": ((item.get("lastModifiedBy") or {}).get("user") or {}).get("displayName"),
        "url": item.get("webUrl"),
        "drive_id": parent.get("driveId"),
        "item_id": item.get("id"),
        "site_id": parent.get("siteId"),
    }


@mcp.tool(annotations=READ_ONLY)
async def inventory_summary(site_id: str | None = None) -> dict:
    """Count files and total size, grouped by site, by library and by file type.

    Always use this for any question about how many files there are or how much space they use;
    the counts are computed exactly here, so do not count file lists yourself.
    Optionally limit to one site (site_id from list_sites).
    """
    gt = await _as_caller("inventory_summary", site_id=site_id)
    rows = await _all_files(gt, site_id)

    def group(keyfn):
        out = defaultdict(lambda: {"files": 0, "bytes": 0})
        for r in rows:
            g = out[keyfn(r)]
            g["files"] += 1
            g["bytes"] += r["size"] or 0
        return dict(sorted(out.items()))

    by_site_type = defaultdict(lambda: defaultdict(int))
    for r in rows:
        by_site_type[r["site"]][r["type"]] += 1

    return {
        "total_files": len(rows),
        "total_bytes": sum(r["size"] or 0 for r in rows),
        "by_site": group(lambda r: r["site"]),
        "by_library": group(lambda r: f"{r['site']} / {r['library']}"),
        "by_type": group(lambda r: r["type"]),
        "by_site_and_type": {s: dict(sorted(t.items())) for s, t in sorted(by_site_type.items())},
        "note": "Sites with no files do not appear in the groups.",
    }


if __name__ == "__main__":
    mcp.run(transport="http", host=HOST, port=PORT)
