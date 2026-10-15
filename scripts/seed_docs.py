"""Seed SharePoint with known test documents for the Work IQ recall test.

Each document matches by exactly one designed route, recorded in
seed_manifest.csv:
  keyword    "policy" in the filename and body
  metadata   neutral filename and body, DocType column = "Policy"
  semantic   body about an HR topic with no policy vocabulary anywhere
  distractor unrelated content
Sites in NO_ACCESS are negative controls: their seeds must never show up in
svc-discovery's results.

Uploads use app-only Graph (client credentials of the app in .env, which needs
the Sites.ReadWrite.All application permission). The index check signs in
svc-discovery by device code.

    uv run scripts/seed_docs.py --check    # token roles and site lookup only
    uv run scripts/seed_docs.py            # create column, upload, write manifest
    uv run scripts/seed_docs.py --wait     # poll search as svc until seeds are indexed
    uv run scripts/seed_docs.py --status   # one search as svc, per-seed found / not found
    uv run scripts/seed_docs.py --delete   # remove the WorkIQSeed folder everywhere
"""

import argparse
import csv
import io
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import quote, urlparse

import httpx
import jwt
import msal
from docx import Document
from dotenv import load_dotenv
from fpdf import FPDF
from openpyxl import Workbook

sys.path.insert(0, str(Path(__file__).resolve().parent))
from list_sites import get_token  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = ROOT / "seed_manifest.csv"
GRAPH = "https://graph.microsoft.com/v1.0"
FOLDER = "WorkIQSeed"
MARKER = "seedrun20261015"

# Site name -> server-relative path on the tenant in SHAREPOINT_ORIGIN.
SITE_PATHS = {
    "Mark 8 Project Team": "/sites/Mark8ProjectTeam75",
    "ragnestedgrouptest": "/sites/ragnestedgrouptest",
    "sts it services": "/sites/stsitservices",
    "Test site 1": "/sites/Testsite1",
    "testing team": "/sites/testingteam",
    "mytesthrsite": "/sites/mytesthrsite",
    "Communication site": "",  # the tenant root site
}
# Sites svc-discovery cannot open: their seeds must never appear in its results.
# Empty for the recall test (svc-discovery reads every site); the isolation
# test comes later.
NO_ACCESS: set[str] = set()
NEGATIVE = "Communication site"

# Words that would let a non-keyword seed match a policy keyword search.
POLICY_WORDS = re.compile(r"polic|procedur|guideline|handbook|\brules?\b|regulation", re.I)

MANIFEST_FIELDS = [
    "seed_id", "route", "site", "filename", "format", "doctype", "dup_group",
    "chain", "chain_date", "drive_id", "item_id", "url", "expected_visible_to_svc",
]

EXPENSE_BODY = (
    "This expense reimbursement policy explains which work costs the company repays and how to claim them. "
    "Under this policy, staff submit receipts within 30 days of purchase through the finance portal. "
    "Meals with clients are repaid up to 60 pounds per person. Mileage is repaid at 45 pence per mile for the "
    "first 10,000 miles each year. Alcohol, personal entertainment and fines are never repaid. "
    "Managers approve claims within five working days. Finance pays approved claims in the next payroll run. "
    "Questions about this policy go to the finance team."
)
LEAVE_BODY = (
    "Everyone gets 25 days of paid holiday each year, plus public holidays. Book time off in the HR system at "
    "least two weeks ahead, and check with your manager before booking more than ten days in a row. "
    "If you are ill, call your manager before 9am on the first day. After seven days off sick you need a "
    "note from your doctor. Parents can take up to 52 weeks of maternity or adoption leave and two weeks of "
    "paternity leave at full pay. You may carry up to five unused holiday days into the next year."
)
TRAVEL_BASE = (
    "This travel policy covers booking and paying for business trips. Book all flights and hotels through the "
    "company travel desk. Economy class is standard for flights under six hours. Hotels must cost less than "
    "180 pounds per night in London and 120 pounds elsewhere."
)

# (seed_id, route, site, filename, doctype, dup_group, chain, chain_date, body)
SEEDS = [
    # Mark 8 Project Team
    ("K01", "keyword", "Mark 8 Project Team", "Information security policy.docx", "", "", "", "",
     "This information security policy sets out how we protect company data. Lock your screen when you leave "
     "your desk. Use the password manager and turn on multi-factor sign-in for every account. Report lost "
     "laptops or phones to the IT service desk within one hour. Breaches of this policy may lead to "
     "disciplinary action."),
    ("M01", "metadata", "Mark 8 Project Team", "Document R-101.docx", "Policy", "", "", "",
     "Reference R-101. Owner: Operations. Review cycle: annual. Version 1.0, approved in March. "
     "This page records the reference number, owner and review date for the filing index."),
    ("S04", "semantic", "Mark 8 Project Team", "What the company pays for you.xlsx", "", "", "", "",
     "On top of your salary, the company pays into a pension at 6 percent of salary when you pay in 4 percent. "
     "Private medical cover is included for you and your children. Life cover pays four times your salary. "
     "You can buy a bike through salary sacrifice and get a free eye test every two years. "
     "The yearly benefits window opens in November, when you can change your choices."),
    ("X01", "distractor", "Mark 8 Project Team", "Canteen menu week 41.txt", "", "", "", "",
     "Monday: tomato soup and cheese toastie. Tuesday: chicken curry with rice. Wednesday: vegetable lasagne. "
     "Thursday: fish and chips. Friday: pizza day. Salad bar open every day from 12 until 2."),
    ("M07", "metadata", "Mark 8 Project Team", "Reference pack.pdf", "Policy", "", "", "",
     "Reference pack 7. Owner: Central services. Issued: June. Next review: June next year. "
     "Contact the central services mailbox to request the printed version."),
    # ragnestedgrouptest
    ("K02", "keyword", "ragnestedgrouptest", "Expense reimbursement policy.docx", "", "D1", "", "",
     EXPENSE_BODY),
    ("M02", "metadata", "ragnestedgrouptest", "Team reference sheet.xlsx", "Policy", "", "", "",
     "Team reference sheet. Reference: R-214. Owner: Team lead. Last checked: April. Status: current."),
    ("S03", "semantic", "ragnestedgrouptest", "How we treat each other.pdf", "", "", "", "",
     "We expect everyone to treat colleagues, customers and suppliers with respect. Harassment, bullying and "
     "discrimination of any kind are not acceptable. Do not accept gifts worth more than 50 pounds. Declare any "
     "conflict of interest to your manager. If you see behaviour that worries you, speak to your manager or "
     "use the confidential speak-up line. Serious misconduct can lead to dismissal."),
    ("X02", "distractor", "ragnestedgrouptest", "Laptop asset list.xlsx", "", "", "", "",
     "Asset tag, model, owner, purchase year. LT-0012 ThinkPad T14 J Smith 2023. LT-0013 ThinkPad T14 A Khan "
     "2023. LT-0020 MacBook Air M3 R Patel 2024. LT-0031 Surface Laptop 6 L Chen 2025."),
    ("K07", "keyword", "ragnestedgrouptest", "Acceptable use policy.txt", "", "", "", "",
     "This acceptable use policy covers company laptops, phones, email and internet access. Personal use is "
     "allowed in moderation outside working hours. Do not install unapproved software. Do not use company "
     "email to send chain letters or offensive material. IT may monitor use to enforce this policy."),
    # sts it services
    ("K04", "keyword", "sts it services", "Travel policy v1.pdf", "", "", "C1", "2024-03-01",
     f"Travel policy version 1. Effective date: 1 March 2024. {TRAVEL_BASE} Rail travel is first class for "
     "journeys over three hours."),
    ("K05", "keyword", "sts it services", "Travel policy v2.pdf", "", "", "C1", "2025-02-01",
     f"Travel policy version 2. Effective date: 1 February 2025. Supersedes version 1. {TRAVEL_BASE} Rail "
     "travel is standard class for all journeys."),
    ("K06", "keyword", "sts it services", "Travel policy v3.pdf", "", "", "C1", "2026-06-01",
     f"Travel policy version 3. Effective date: 1 June 2026. Supersedes version 2. {TRAVEL_BASE} Rail travel "
     "is standard class for all journeys. Trips abroad need approval from a director two weeks in advance."),
    ("M03", "metadata", "sts it services", "Working draft 7.docx", "Policy", "", "", "",
     "Working draft 7. Reference: R-330. Owner: IT services. Prepared for the quarterly review meeting. "
     "Comments to the IT services mailbox by the end of the month."),
    ("S07", "semantic", "sts it services", "Working from home.pdf", "", "", "", "",
     "You can work from home up to three days a week if your role allows it and your manager agrees. "
     "Be reachable on Teams between 10am and 4pm. The company provides a laptop, a screen and a chair, and pays "
     "a 26 pound monthly allowance towards heating and internet. Make sure your home workspace is safe and "
     "that confidential papers are locked away. Come to the office for team days each Tuesday."),
    # Test site 1
    ("S01", "semantic", "Test site 1", "Time away from work.docx", "", "D2", "", "", LEAVE_BODY),
    ("M04", "metadata", "Test site 1", "Notes 2026-03.txt", "Policy", "", "", "",
     "Notes 2026-03. Reference: R-412. Owner: Administration. Filed with the March records. No changes since "
     "the previous issue."),
    ("S08", "semantic", "Test site 1", "Getting money back for work purchases.txt", "", "", "", "",
     "If you pay for something for work with your own money, keep the receipt and claim it back through the "
     "finance portal within 30 days. Taxis are repaid when public transport is not practical. Working lunches "
     "with customers are repaid up to 60 pounds a head. Your manager approves the claim and the money arrives "
     "with your next salary payment."),
    ("X03", "distractor", "Test site 1", "Summer party notes.docx", "", "", "", "",
     "Summer party planning notes. Venue: the riverside marquee. Date: second Friday in July. Budget: 4,000 "
     "pounds. Band booked from 7pm. Vegetarian and vegan options agreed with the caterer. Raffle prizes still "
     "needed."),
    ("K08", "keyword", "Test site 1", "Data retention policy.xlsx", "", "", "", "",
     "Data retention policy. Customer contracts: keep for 7 years after the contract ends. Payroll records: "
     "6 years. Job applications from unsuccessful candidates: 6 months. CCTV footage: 30 days. This policy is "
     "reviewed every year by the data protection officer."),
    # testing team
    ("K03", "keyword", "testing team", "Expense reimbursement policy - final.docx", "", "D1", "", "",
     EXPENSE_BODY.replace("five working days", "five working days of submission")),
    ("M05", "metadata", "testing team", "Summary sheet B.xlsx", "Policy", "", "", "",
     "Summary sheet B. Reference: R-518. Owner: Testing team. Revision 2. Approved by the team lead."),
    ("S05", "semantic", "testing team", "Your first week.txt", "", "", "", "",
     "Welcome to the company. On your first day, collect your laptop and pass from reception at 9am. Your "
     "manager will introduce you to the team and your buddy, who will help you settle in. During the first "
     "week, complete the online training modules, set up your payroll and pension details, and book a "
     "meeting with your manager to agree your goals for the first three months."),
    ("X04", "distractor", "testing team", "Printer setup.pdf", "", "", "", "",
     "To add the second floor printer, open Settings, then Printers, then Add device. Choose PRN-2F-01. "
     "If the printer does not appear, connect to the office Wi-Fi first. Toner is in the cupboard next to the "
     "kitchen."),
    ("X05", "distractor", "testing team", "Quarterly sales figures.xlsx", "", "", "", "",
     "Quarter, region, revenue. Q1 North 1.2m. Q1 South 0.9m. Q2 North 1.4m. Q2 South 1.1m. Q3 North 1.3m. "
     "Q3 South 1.2m."),
    # mytesthrsite
    ("S02", "semantic", "mytesthrsite", "Time away from work - team copy.docx", "", "D2", "", "",
     LEAVE_BODY.replace("Book time off", "Please book time off")),
    ("M06", "metadata", "mytesthrsite", "Office reference.pdf", "Policy", "", "", "",
     "Office reference. Reference: R-603. Owner: People team. Version 3. Kept with the site records."),
    ("S06", "semantic", "mytesthrsite", "Staying safe in the warehouse.docx", "", "", "", "",
     "Wear safety boots and a high-visibility vest at all times in the warehouse. Only trained and certified "
     "staff may drive forklifts. Keep walkways clear and report spills straight away. Lift with your knees, "
     "and ask for help with anything over 20 kilograms. Fire exits are marked in green; know your nearest one. "
     "Report every accident or near miss to the site supervisor the same day."),
    ("X06", "distractor", "mytesthrsite", "Meeting room booking.txt", "", "", "", "",
     "Meeting rooms on the third floor: Oak seats 6, Elm seats 10, Birch seats 20. Book through Outlook. "
     "Cancel bookings you no longer need so others can use the room."),
    ("M08", "metadata", "mytesthrsite", "Notes Q2.txt", "Policy", "", "", "",
     "Notes Q2. Reference: R-688. Owner: People team. Filed with the second quarter records."),
    # Communication site: negative control, svc-discovery has no access
    ("N01", "keyword", NEGATIVE, "Whistleblowing policy.docx", "", "", "", "",
     "This whistleblowing policy explains how to raise concerns about wrongdoing safely. You can report to "
     "your manager, to the ethics officer, or anonymously through the speak-up line. We protect anyone who "
     "raises a genuine concern under this policy from retaliation."),
    ("N02", "metadata", NEGATIVE, "Reference R-900.pdf", "Policy", "", "", "",
     "Reference R-900. Owner: Communications. Version 1. Filed with the communications records."),
    ("N03", "semantic", NEGATIVE, "Caring for family members.txt", "", "", "", "",
     "If someone who depends on you is ill or needs care, you can take up to five days of paid carer's leave "
     "each year. Tell your manager as early as you can. Longer breaks can be arranged as unpaid time off or "
     "by changing your working hours for a while."),
]


def check_seeds():
    """Each seed must match only its own route by wording."""
    ids = [s[0] for s in SEEDS]
    assert len(ids) == len(set(ids)), "duplicate seed ids"
    for seed_id, route, _site, filename, doctype, *_rest, body in SEEDS:
        stem = Path(filename).stem
        if route == "keyword":
            assert "policy" in stem.lower() and "policy" in body.lower(), seed_id
        else:
            assert not POLICY_WORDS.search(stem + " " + body), f"{seed_id} has policy vocabulary"
        assert (doctype == "Policy") == (route == "metadata"), seed_id


def render(filename: str, body: str) -> bytes:
    """Build the file bytes for a seed; the title is the filename stem."""
    title = Path(filename).stem
    text = f"{body}\n\nRef {MARKER}"
    ext = Path(filename).suffix.lower()
    buf = io.BytesIO()
    if ext == ".txt":
        return f"{title}\n\n{text}\n".encode("utf-8")
    if ext == ".docx":
        doc = Document()
        doc.core_properties.title = title
        doc.add_heading(title, level=1)
        for para in text.split("\n\n"):
            doc.add_paragraph(para)
        doc.save(buf)
    elif ext == ".xlsx":
        wb = Workbook()
        ws = wb.active
        ws.title = "Sheet1"
        ws["A1"] = title
        for i, para in enumerate(text.split("\n\n"), start=3):
            ws.cell(row=i, column=1, value=para)
        wb.properties.title = title
        wb.save(buf)
    elif ext == ".pdf":
        pdf = FPDF()
        pdf.set_title(title)
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 14)
        pdf.multi_cell(0, 8, title, new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", size=11)
        pdf.multi_cell(0, 6, text, new_x="LMARGIN", new_y="NEXT")
        pdf.output(buf)
    else:
        raise ValueError(ext)
    return buf.getvalue()


def app_token() -> str:
    load_dotenv(ROOT / ".env")
    app = msal.ConfidentialClientApplication(
        os.environ["CLIENT_ID"],
        authority=f"https://login.microsoftonline.com/{os.environ['TENANT_ID']}",
        client_credential=os.environ["CLIENT_SECRET"],
    )
    result = app.acquire_token_for_client(scopes=["https://graph.microsoft.com/.default"])
    if "access_token" not in result:
        sys.exit(f"App-only token failed: {result.get('error')}: {result.get('error_description')}")
    return result["access_token"]


def token_roles(token: str) -> list[str]:
    """Role names from the token's claims; the token itself is never printed."""
    return sorted(jwt.decode(token, options={"verify_signature": False}).get("roles", []))


def resolve_sites(client: httpx.Client) -> dict[str, dict]:
    """Map each site name to its Graph site by URL path, checking the display name."""
    host = urlparse(os.environ["SHAREPOINT_ORIGIN"]).hostname
    sites = {}
    for name, path in SITE_PATHS.items():
        resp = client.get(f"{GRAPH}/sites/{host}:{path}" if path else f"{GRAPH}/sites/{host}")
        resp.raise_for_status()
        site = resp.json()
        if site.get("displayName") != name:
            sys.exit(f"Site at '{path or '/'}' is named '{site.get('displayName')}', expected '{name}'")
        drive = client.get(f"{GRAPH}/sites/{site['id']}/drive")
        drive.raise_for_status()
        lst = client.get(f"{GRAPH}/drives/{drive.json()['id']}/list", params={"$select": "id"})
        lst.raise_for_status()
        sites[name] = {"id": site["id"], "url": site["webUrl"], "drive_id": drive.json()["id"],
                       "list_id": lst.json()["id"]}
    return sites


def ensure_doctype(client: httpx.Client, site: dict) -> str:
    url = f"{GRAPH}/sites/{site['id']}/lists/{site['list_id']}/columns"
    resp = client.get(url, params={"$select": "name"})
    resp.raise_for_status()
    if any(c["name"] == "DocType" for c in resp.json()["value"]):
        return "exists"
    resp = client.post(url, json={"name": "DocType", "displayName": "DocType", "text": {}})
    resp.raise_for_status()
    return "created"


def upload(client: httpx.Client, site: dict, seed: tuple) -> dict:
    seed_id, route, site_name, filename, doctype, dup, chain, chain_date, body = seed
    path = quote(f"{FOLDER}/{filename}")
    resp = client.put(f"{GRAPH}/drives/{site['drive_id']}/root:/{path}:/content",
                      content=render(filename, body))
    resp.raise_for_status()
    item = resp.json()
    item_url = f"{GRAPH}/drives/{site['drive_id']}/items/{item['id']}"
    if doctype:
        client.patch(f"{item_url}/listItem/fields", json={"DocType": doctype}).raise_for_status()
    if chain_date:
        r = client.patch(item_url, json={"fileSystemInfo": {"lastModifiedDateTime": f"{chain_date}T09:00:00Z"}})
        if r.status_code >= 400:
            print(f"  {seed_id}: could not set date (HTTP {r.status_code}); date stays in the body only")
    return {
        "seed_id": seed_id, "route": route, "site": site_name, "filename": filename,
        "format": Path(filename).suffix.lstrip("."), "doctype": doctype, "dup_group": dup,
        "chain": chain, "chain_date": chain_date, "drive_id": site["drive_id"], "item_id": item["id"],
        "url": item.get("webUrl", ""), "expected_visible_to_svc": "no" if site_name in NO_ACCESS else "yes",
    }


def cmd_check(client: httpx.Client, roles: list[str]):
    print(f"App-only token roles: {', '.join(roles) or '(none)'}")
    if "Sites.ReadWrite.All" not in roles and "Sites.FullControl.All" not in roles:
        sys.exit("Missing application permission Sites.ReadWrite.All on the app; nothing written.")
    for name, site in resolve_sites(client).items():
        print(f"{name:22} {site['url']}  drive {site['drive_id'][:12]}...")


def cmd_seed(client: httpx.Client):
    check_seeds()
    sites = resolve_sites(client)
    for name, site in sites.items():
        print(f"{name}: DocType column {ensure_doctype(client, site)}")
    rows = []
    for seed in SEEDS:
        rows.append(upload(client, sites[seed[2]], seed))
        print(f"  {seed[0]} {seed[1]:10} {seed[2]:20} {seed[3]}")
    with MANIFEST_PATH.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=MANIFEST_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"\n{len(rows)} seed(s) written to {MANIFEST_PATH.name}")


def cmd_delete(client: httpx.Client):
    for name, site in resolve_sites(client).items():
        r = client.get(f"{GRAPH}/drives/{site['drive_id']}/root:/{FOLDER}")
        if r.status_code == 404:
            print(f"{name}: no {FOLDER} folder")
            continue
        r.raise_for_status()
        client.delete(f"{GRAPH}/drives/{site['drive_id']}/items/{r.json()['id']}").raise_for_status()
        print(f"{name}: deleted {FOLDER}")


def search_marker(client: httpx.Client) -> list[dict]:
    hits, start = [], 0
    while True:
        body = {"requests": [{"entityTypes": ["driveItem"], "query": {"queryString": MARKER},
                              "from": start, "size": 50}]}
        resp = client.post(f"{GRAPH}/search/query", json=body)
        resp.raise_for_status()
        containers = resp.json()["value"][0]["hitsContainers"]
        page = [h["resource"] for c in containers for h in c.get("hits", [])]
        hits += page
        if not page or not any(c.get("moreResultsAvailable") for c in containers):
            return hits
        start += len(page)


def cmd_status():
    rows = list(csv.DictReader(MANIFEST_PATH.open(encoding="utf-8")))
    with httpx.Client(headers={"Authorization": f"Bearer {get_token('svc')}"}, timeout=60) as client:
        found = {h.get("id") for h in search_marker(client)}
    for r in rows:
        hit = r["item_id"] in found
        flag = "  <-- LEAK" if hit and r["expected_visible_to_svc"] == "no" else ""
        print(f"{r['seed_id']} {r['site']:20} expected {r['expected_visible_to_svc']:3} "
              f"found {'yes' if hit else 'no':3}{flag}")


def cmd_wait(minutes: int):
    rows = list(csv.DictReader(MANIFEST_PATH.open(encoding="utf-8")))
    expected = {r["item_id"]: r for r in rows if r["expected_visible_to_svc"] == "yes"}
    negative = {r["item_id"]: r for r in rows if r["expected_visible_to_svc"] == "no"}
    token = get_token("svc")
    deadline = time.monotonic() + minutes * 60
    with httpx.Client(headers={"Authorization": f"Bearer {token}"}, timeout=60) as client:
        while True:
            found = {h.get("id") for h in search_marker(client)}
            leaked = sorted(negative[i]["seed_id"] for i in found & negative.keys())
            if leaked:
                sys.exit(f"STOP: svc-discovery search returned no-access seeds {leaked}")
            got = found & expected.keys()
            print(f"{time.strftime('%H:%M:%S')} indexed {len(got)}/{len(expected)}, "
                  f"no-access hits 0", flush=True)
            if len(got) == len(expected):
                return
            if time.monotonic() > deadline:
                missing = sorted(r["seed_id"] for i, r in expected.items() if i not in got)
                sys.exit(f"Timed out; not yet indexed: {missing}")
            time.sleep(120)


def main():
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--check", action="store_true", help="show token roles and resolve sites only")
    group.add_argument("--wait", action="store_true", help="poll search as svc until seeds are indexed")
    group.add_argument("--status", action="store_true", help="one search as svc, per-seed result")
    group.add_argument("--delete", action="store_true", help=f"delete the {FOLDER} folder on every site")
    parser.add_argument("--minutes", type=int, default=60, help="--wait timeout")
    args = parser.parse_args()

    if args.wait:
        return cmd_wait(args.minutes)
    if args.status:
        return cmd_status()
    token = app_token()
    with httpx.Client(headers={"Authorization": f"Bearer {token}"}, timeout=60) as client:
        if args.check:
            cmd_check(client, token_roles(token))
        elif args.delete:
            cmd_delete(client)
        else:
            if "Sites.ReadWrite.All" not in token_roles(token):
                sys.exit("Missing application permission Sites.ReadWrite.All; run --check.")
            cmd_seed(client)


if __name__ == "__main__":
    main()
