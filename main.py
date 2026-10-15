"""Entry-point index for the SharePoint discovery agent proof of concept.

Run the individual pieces directly; this file only checks configuration.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

REQUIRED = ["TENANT_ID", "CLIENT_ID", "CLIENT_SECRET"]

COMMANDS = """\
  uv run scripts/list_sites.py    Inventory every site, library and file (device-code sign-in)
"""


def main():
    load_dotenv(Path(__file__).resolve().parent / ".env")
    missing = [k for k in REQUIRED if not os.environ.get(k)]
    print("Config:", "OK" if not missing else f"missing {', '.join(missing)}")
    print("\nCommands:\n" + COMMANDS)


if __name__ == "__main__":
    main()
