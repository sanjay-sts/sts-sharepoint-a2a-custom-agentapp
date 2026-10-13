# sts-sharepoint-a2a-custom-agentapp
PoC to integrate SharePoint with A2A agent and react style frontend

## Configuration

Copy `.env.example` to `.env` in the repo root and fill in the values. `.env` is gitignored; every module loads it from the project root.

```
cp .env.example .env
uv run main.py   # prints "Config: OK" once the required Entra values are set
```
