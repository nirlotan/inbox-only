#!/usr/bin/env python3
"""Ship Inbox to TestFlight so any iPhone can install it from a public link.

    ./release.py           build, upload and publish a new TestFlight build
    ./release.py status    show the latest build, its review state and expiry

Run it on a Mac with Xcode, from the repo folder. The first run asks for what
it can't work out itself (your App Store Connect API key, contact details for
Apple's beta review, ...) and remembers the answers in
~/.config/inbox-only/release.json. Passwords are never saved.

What it does, in order:
  1. checks Xcode, Homebrew and XcodeGen
  2. registers the bundle ID and, once, walks you through creating the app
     record in App Store Connect (Apple's API can't create apps)
  3. builds, signs and uploads the app with your API key
  4. waits for Apple to process the build
  5. fills in TestFlight test information and beta review details
  6. adds the build to an internal group (you can install right away) and to
     a public-link group, and submits it for beta review
  7. puts the public TestFlight link on the install page and pushes it

TestFlight builds expire after 90 days. Run this again before then (every
2-3 months) and testers get the new build automatically.

Uses only Python's standard library and the `openssl` that ships with macOS.
"""
from __future__ import annotations

import base64
import getpass
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import webbrowser
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
CONFIG = Path.home() / ".config" / "inbox-only" / "release.json"
KEYS_DIR = Path.home() / ".appstoreconnect" / "private_keys"
API = os.environ.get("ASC_API_BASE", "https://api.appstoreconnect.apple.com")
LOCALE = "en-US"
PUBLIC_GROUP = "Public"
TEAM_GROUP = "Team"

BETA_DESCRIPTION = (
    "Inbox is a calm way to use your Instagram direct messages. It opens straight "
    "into your inbox and blocks the feed, reels, stories and every video, so you "
    "can reply to friends without getting pulled into scrolling. Chats, photos, "
    "voice messages and message requests all keep working."
)
WHAT_TO_TEST = (
    "Sign in, open a chat, send a message and a photo, and play a voice message. "
    "Check that videos and shared reels show as blocked and that the feed, reels "
    "and profiles can't be opened."
)
REVIEW_NOTES = (
    "Inbox shows the user's own Instagram direct messages (instagram.com/direct) "
    "in a web view and hides videos, reels, stories and the feed to help people "
    "message without endless scrolling. Sign in with the demo Instagram account "
    "provided. Nothing is collected or sent anywhere except Instagram itself."
)


# --------------------------------------------------------------------------- ui

def say(text: str = "") -> None:
    print(text, flush=True)


def step(text: str) -> None:
    say(f"\n\033[1m▸ {text}\033[0m")


def fail(text: str) -> None:
    say(f"\n\033[31m✗ {text}\033[0m")
    sys.exit(1)


def ask(question: str, default: str | None = None, check=None, secret: bool = False) -> str:
    hint = f" [{default}]" if default else ""
    while True:
        prompt = f"  {question}{hint}: "
        value = getpass.getpass(prompt) if secret else input(prompt)
        value = value.strip() or (default or "")
        if not value:
            say("    (required)")
            continue
        if check and not check(value):
            say("    That doesn't look right, try again.")
            continue
        return value


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=True, **kw)


def output(cmd: list[str]) -> str:
    return subprocess.run(cmd, check=True, capture_output=True, text=True, cwd=ROOT).stdout.strip()


# ----------------------------------------------------------------------- config

def load_config() -> dict:
    if CONFIG.exists():
        return json.loads(CONFIG.read_text())
    return {}


def save_config(cfg: dict) -> None:
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    CONFIG.write_text(json.dumps(cfg, indent=2))
    CONFIG.chmod(0o600)


def project_setting(name: str) -> str:
    match = re.search(rf"^\s*{name}:\s*([^\s#]+)", (ROOT / "ios/project.yml").read_text(), re.M)
    return match.group(1).strip("\"'") if match else ""


def setup_api_key(cfg: dict) -> None:
    if cfg.get("key_id") and Path(cfg.get("key_path", "")).exists():
        return
    step("App Store Connect API key (one time)")
    say("  The script signs, uploads and sets up TestFlight with an API key.")
    say("  1. In the page that opens, click + (or 'Generate API Key').")
    say("  2. Name it 'Inbox release' and choose Access: Admin.")
    say("  3. Download the .p8 file (Apple lets you download it only once).")
    say("  The Issuer ID is shown above the list of keys.")
    webbrowser.open("https://appstoreconnect.apple.com/access/integrations/api")
    path = ask(
        "Drag the downloaded AuthKey_….p8 file here",
        check=lambda p: Path(p.strip("'\" ").replace("\\ ", " ")).expanduser().is_file(),
    )
    src = Path(path.strip("'\" ").replace("\\ ", " ")).expanduser()
    guess = re.match(r"AuthKey_([A-Z0-9]+)\.p8$", src.name)
    key_id = ask("Key ID", guess.group(1) if guess else None, lambda v: re.fullmatch(r"[A-Z0-9]{10}", v))
    issuer = ask(
        "Issuer ID",
        check=lambda v: re.fullmatch(r"[0-9a-f-]{36}", v.lower()) is not None,
    )
    KEYS_DIR.mkdir(parents=True, exist_ok=True)
    dest = KEYS_DIR / f"AuthKey_{key_id}.p8"
    if src.resolve() != dest.resolve():
        shutil.copyfile(src, dest)
    dest.chmod(0o600)
    cfg.update(key_id=key_id, issuer_id=issuer.lower(), key_path=str(dest))
    save_config(cfg)


def setup_basics(cfg: dict) -> None:
    if not cfg.get("team_id"):
        step("Your Apple developer team (one time)")
        say("  Find it at developer.apple.com/account → Membership details → Team ID.")
        cfg["team_id"] = ask("Team ID", check=lambda v: re.fullmatch(r"[A-Z0-9]{10}", v)).upper()
    if not cfg.get("bundle_prefix"):
        cfg["bundle_prefix"] = project_setting("BUNDLE_ID_PREFIX") or "com.example"
    save_config(cfg)


# -------------------------------------------------------------------------- api

class ApiError(Exception):
    def __init__(self, status: int, method: str, path: str, body: str):
        self.status = status
        try:
            errors = json.loads(body).get("errors", [])
            detail = "; ".join(e.get("detail") or e.get("title", "") for e in errors)
        except ValueError:
            detail = body[:300]
        super().__init__(f"{method} {path} → {status}: {detail}")


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def der_to_raw(der: bytes) -> bytes:
    """Converts openssl's DER ECDSA signature into JWT's 64-byte r||s."""
    if der[0] != 0x30:
        raise ValueError("unexpected signature format")
    i = 3 if der[1] & 0x80 else 2  # skip SEQUENCE header (P-256 sigs are short)
    parts = []
    for _ in range(2):
        if der[i] != 0x02:
            raise ValueError("unexpected signature format")
        length = der[i + 1]
        value = der[i + 2:i + 2 + length].lstrip(b"\x00")
        parts.append(value.rjust(32, b"\x00"))
        i += 2 + length
    return b"".join(parts)


class Api:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self._token = ""
        self._token_time = 0.0

    def token(self) -> str:
        if time.time() - self._token_time < 600:
            return self._token
        now = int(time.time())
        header = {"alg": "ES256", "kid": self.cfg["key_id"], "typ": "JWT"}
        payload = {"iss": self.cfg["issuer_id"], "iat": now, "exp": now + 1080, "aud": "appstoreconnect-v1"}
        signing_input = f"{b64url(json.dumps(header).encode())}.{b64url(json.dumps(payload).encode())}"
        der = subprocess.run(
            ["openssl", "dgst", "-sha256", "-sign", self.cfg["key_path"]],
            input=signing_input.encode(), capture_output=True, check=True,
        ).stdout
        self._token = f"{signing_input}.{b64url(der_to_raw(der))}"
        self._token_time = time.time()
        return self._token

    def call(self, method: str, path: str, body: dict | None = None, params: dict | None = None) -> dict:
        url = API + path + (f"?{urlencode(params)}" if params else "")
        data = json.dumps(body).encode() if body is not None else None
        req = Request(url, data=data, method=method, headers={
            "Authorization": f"Bearer {self.token()}",
            "Content-Type": "application/json",
        })
        try:
            with urlopen(req, timeout=60) as res:
                raw = res.read()
                return json.loads(raw) if raw else {}
        except HTTPError as e:
            raise ApiError(e.code, method, path, e.read().decode(errors="replace")) from None

    def get(self, path: str, **params) -> dict:
        return self.call("GET", path, params=params or None)

    def create(self, kind: str, attributes: dict, relationships: dict | None = None) -> dict:
        data = {"type": kind, "attributes": attributes}
        if relationships:
            data["relationships"] = {
                name: {"data": {"type": t, "id": i}} for name, (t, i) in relationships.items()
            }
        return self.call("POST", f"/v1/{kind}", {"data": data})["data"]

    def update(self, kind: str, ident: str, attributes: dict) -> dict:
        body = {"data": {"type": kind, "id": ident, "attributes": attributes}}
        return self.call("PATCH", f"/v1/{kind}/{ident}", body)["data"]


# ----------------------------------------------------------------- the steps

def check_tools() -> None:
    step("Checking tools")
    if sys.platform != "darwin":
        fail("Run this on a Mac.")
    if not shutil.which("xcodebuild") or subprocess.run(
        ["xcodebuild", "-version"], capture_output=True
    ).returncode != 0:
        fail("Xcode isn't set up. Install Xcode from the App Store, open it once, then run:\n"
             "  sudo xcode-select -s /Applications/Xcode.app")
    if not shutil.which("xcodegen"):
        if not shutil.which("brew"):
            fail("Homebrew is needed to install XcodeGen. Install it from https://brew.sh, then run this again.")
        say("  Installing XcodeGen…")
        run(["brew", "install", "xcodegen"])
    say("  " + output(["xcodebuild", "-version"]).splitlines()[0] + ", XcodeGen ready")


def check_key(api: Api) -> None:
    step("Checking the API key")
    try:
        api.get("/v1/apps", limit=1)
    except ApiError as e:
        if e.status in (401, 403):
            fail(f"App Store Connect rejected the key ({e}).\n"
                 f"  Check the Key ID / Issuer ID, or delete {CONFIG} to enter them again.")
        raise
    say("  Key works")


def ensure_bundle_id(api: Api, bundle_id: str) -> None:
    found = api.get("/v1/bundleIds", **{"filter[identifier]": bundle_id})["data"]
    if any(b["attributes"]["identifier"] == bundle_id for b in found):
        return
    say(f"  Registering bundle ID {bundle_id}")
    api.create("bundleIds", {"identifier": bundle_id, "name": "Inbox Only", "platform": "IOS"})


def ensure_app(api: Api, bundle_id: str) -> dict:
    step("Finding the app in App Store Connect")
    ensure_bundle_id(api, bundle_id)
    while True:
        apps = api.get("/v1/apps", **{"filter[bundleId]": bundle_id})["data"]
        if apps:
            say(f"  Found \"{apps[0]['attributes']['name']}\"")
            return apps[0]
        say("  Apple's API can't create the app record, so this one step is by hand.")
        say("  In the page that opens, click + → New App and fill in:")
        say("    Platforms:         iOS")
        say("    Name:              anything unique without \"Instagram\", e.g. \"Inbox: Calm DMs\"")
        say("    Primary language:  English (U.S.)")
        say(f"    Bundle ID:         {bundle_id}")
        say("    SKU:               inbox-only")
        say("    User access:       Full Access")
        webbrowser.open("https://appstoreconnect.apple.com/apps")
        input("  Press Enter once you've clicked Create… ")


def build_and_upload(cfg: dict, build_number: str) -> None:
    step(f"Building and uploading build {build_number} (takes a few minutes)")
    out = ROOT / "build" / "release"
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    run(["xcodegen", "generate", "--quiet"], cwd=ROOT / "ios")

    auth = [
        "-allowProvisioningUpdates",
        "-authenticationKeyPath", cfg["key_path"],
        "-authenticationKeyID", cfg["key_id"],
        "-authenticationKeyIssuerID", cfg["issuer_id"],
    ]
    archive = out / "InboxOnly.xcarchive"
    say("  Archiving…")
    run([
        "xcodebuild", "archive", "-quiet",
        "-project", str(ROOT / "ios/InboxOnly.xcodeproj"), "-scheme", "InboxOnly",
        "-configuration", "Release", "-destination", "generic/platform=iOS",
        "-archivePath", str(archive), *auth,
        f"DEVELOPMENT_TEAM={cfg['team_id']}",
        f"BUNDLE_ID_PREFIX={cfg['bundle_prefix']}",
        f"CURRENT_PROJECT_VERSION={build_number}",
    ])

    # Xcode 15.3 renamed "app-store" to "app-store-connect".
    major = int(re.search(r"Xcode (\d+)", output(["xcodebuild", "-version"])).group(1))
    options = out / "ExportOptions.plist"
    options.write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>method</key><string>{"app-store-connect" if major >= 16 else "app-store"}</string>
  <key>destination</key><string>upload</string>
  <key>teamID</key><string>{cfg['team_id']}</string>
  <key>signingStyle</key><string>automatic</string>
  <key>uploadSymbols</key><true/>
  <key>manageAppVersionAndBuildNumber</key><false/>
</dict>
</plist>
""")
    say("  Signing and uploading…")
    run([
        "xcodebuild", "-exportArchive", "-quiet",
        "-archivePath", str(archive), "-exportPath", str(out),
        "-exportOptionsPlist", str(options), *auth,
    ])
    say("  Uploaded")


def wait_for_build(api: Api, app_id: str, build_number: str) -> dict:
    step("Waiting for Apple to process the build (usually 5-20 minutes)")
    deadline = time.time() + 90 * 60
    last = ""
    while time.time() < deadline:
        builds = api.get("/v1/builds", **{"filter[app]": app_id, "filter[version]": build_number})["data"]
        state = builds[0]["attributes"]["processingState"] if builds else "NOT_VISIBLE_YET"
        if state != last:
            say(f"  {time.strftime('%H:%M')}  {state.replace('_', ' ').lower()}")
            last = state
        if state == "VALID":
            return builds[0]
        if state in ("FAILED", "INVALID"):
            fail("Apple rejected the build while processing it. Check the email Apple sent "
                 "to the account holder for the reason.")
        time.sleep(30)
    fail("The build is still processing after 90 minutes. Run ./release.py again later "
         "and choose to finish this build.")


def ensure_test_info(api: Api, cfg: dict, app_id: str, pages: str) -> None:
    step("TestFlight test information")
    if not cfg.get("feedback_email"):
        cfg["feedback_email"] = ask("Email for tester feedback", check=lambda v: "@" in v)
        save_config(cfg)
    attrs = {
        "description": BETA_DESCRIPTION,
        "feedbackEmail": cfg["feedback_email"],
        "marketingUrl": pages + "/",
        "privacyPolicyUrl": pages + "/privacy.html",
    }
    existing = [
        loc for loc in api.get(f"/v1/apps/{app_id}/betaAppLocalizations")["data"]
        if loc["attributes"]["locale"] == LOCALE
    ]
    if existing:
        api.update("betaAppLocalizations", existing[0]["id"], attrs)
    else:
        api.create("betaAppLocalizations", {"locale": LOCALE, **attrs}, {"app": ("apps", app_id)})
    say("  Description, feedback email and privacy policy set")

    detail = api.get(f"/v1/apps/{app_id}/betaAppReviewDetail")["data"]
    current = detail["attributes"]
    if current.get("contactEmail") and current.get("demoAccountName"):
        say("  Beta review contact and demo account already set")
        return

    say("\n  Apple reviews the first public build. Their reviewer needs a contact")
    say("  and an Instagram account to sign in with. Use a spare Instagram account")
    say("  made for this, not your personal one. The password goes straight to")
    say("  Apple and isn't saved on this Mac.")
    contact = cfg.setdefault("contact", {})
    contact["first"] = ask("Your first name", contact.get("first"))
    contact["last"] = ask("Your last name", contact.get("last"))
    contact["email"] = ask("Your email", contact.get("email") or cfg["feedback_email"], lambda v: "@" in v)
    contact["phone"] = ask("Your phone, with country code (e.g. +972 50 123 4567)", contact.get("phone"))
    save_config(cfg)
    demo_user = ask("Demo Instagram username")
    demo_pass = ask("Demo Instagram password", secret=True)
    api.update("betaAppReviewDetails", detail["id"], {
        "contactFirstName": contact["first"],
        "contactLastName": contact["last"],
        "contactEmail": contact["email"],
        "contactPhone": contact["phone"],
        "demoAccountRequired": True,
        "demoAccountName": demo_user,
        "demoAccountPassword": demo_pass,
        "notes": REVIEW_NOTES,
    })
    say("  Beta review details saved")


def prepare_build(api: Api, build: dict) -> None:
    if build["attributes"].get("usesNonExemptEncryption") is None:
        api.update("builds", build["id"], {"usesNonExemptEncryption": False})
    locs = api.get(f"/v1/builds/{build['id']}/betaBuildLocalizations")["data"]
    mine = [loc for loc in locs if loc["attributes"]["locale"] == LOCALE]
    if mine:
        api.update("betaBuildLocalizations", mine[0]["id"], {"whatsNew": WHAT_TO_TEST})
    else:
        api.create("betaBuildLocalizations", {"locale": LOCALE, "whatsNew": WHAT_TO_TEST},
                   {"build": ("builds", build["id"])})


def find_group(api: Api, app_id: str, name: str) -> dict | None:
    groups = api.get(f"/v1/apps/{app_id}/betaGroups", limit=200)["data"]
    return next((g for g in groups if g["attributes"]["name"] == name), None)


def ensure_team_group(api: Api, cfg: dict, app_id: str) -> None:
    """Internal testers install without waiting for Apple's review."""
    try:
        group = find_group(api, app_id, TEAM_GROUP)
        if not group:
            group = api.create("betaGroups", {
                "name": TEAM_GROUP, "isInternalGroup": True, "hasAccessToAllBuilds": True,
            }, {"app": ("apps", app_id)})
            contact = cfg.get("contact") or {}
            email = contact.get("email") or cfg.get("feedback_email")
            if email:
                api.call("POST", "/v1/betaTesters", {"data": {
                    "type": "betaTesters",
                    "attributes": {"email": email, "firstName": contact.get("first", ""),
                                   "lastName": contact.get("last", "")},
                    "relationships": {"betaGroups": {"data": [{"type": "betaGroups", "id": group["id"]}]}},
                }})
                say(f"  Invited {email} as an internal tester (check your email)")
        say(f"  Internal group \"{TEAM_GROUP}\" gets every build right away")
    except ApiError as e:
        say(f"  (Skipped the internal group: {e})")
        say("  You can add yourself under TestFlight → Internal Testing in App Store Connect.")


def ensure_public_group(api: Api, app_id: str, build_id: str) -> str:
    group = find_group(api, app_id, PUBLIC_GROUP)
    if not group:
        group = api.create("betaGroups", {
            "name": PUBLIC_GROUP, "publicLinkEnabled": True, "publicLinkLimitEnabled": False,
        }, {"app": ("apps", app_id)})
    elif not group["attributes"].get("publicLinkEnabled"):
        group = api.update("betaGroups", group["id"], {"publicLinkEnabled": True, "publicLinkLimitEnabled": False})

    try:
        api.call("POST", f"/v1/betaGroups/{group['id']}/relationships/builds",
                 {"data": [{"type": "builds", "id": build_id}]})
    except ApiError as e:
        if e.status != 409:  # already in the group
            raise
    link = group["attributes"].get("publicLink") or api.get(f"/v1/betaGroups/{group['id']}")["data"]["attributes"].get("publicLink")
    if not link:
        fail("App Store Connect didn't return a public link for the Public group.")
    return link


def submit_for_review(api: Api, build_id: str) -> str:
    existing = api.get("/v1/betaAppReviewSubmissions", **{"filter[build]": build_id})["data"]
    if not existing:
        try:
            api.create("betaAppReviewSubmissions", {}, {"build": ("builds", build_id)})
        except ApiError as e:
            if e.status != 409:
                raise
    detail = api.get(f"/v1/builds/{build_id}/buildBetaDetail")["data"]["attributes"]
    return detail.get("externalBuildState", "UNKNOWN")


def publish_page(release: dict) -> None:
    step("Updating the install page")
    path = ROOT / "docs" / "release.json"
    path.write_text(json.dumps(release, indent=2) + "\n")
    try:
        run(["git", "add", str(path)], cwd=ROOT)
        if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=ROOT).returncode == 0:
            say("  Already up to date")
            return
        run(["git", "commit", "-q", "-m", f"Release build {release['build']} to TestFlight"], cwd=ROOT)
        run(["git", "pull", "-q", "--rebase"], cwd=ROOT)
        run(["git", "push", "-q"], cwd=ROOT)
        say("  Pushed (GitHub Pages updates in a minute or two)")
    except subprocess.CalledProcessError:
        say("  Couldn't push to GitHub. Run `gh auth login` (or `brew install gh` first),")
        say("  then `git push`. The TestFlight link itself already works.")


def pages_url() -> str:
    remote = output(["git", "remote", "get-url", "origin"])
    slug = re.sub(r"\.git$", "", re.sub(r"^(git@github\.com:|https://github\.com/)", "", remote))
    owner, repo = slug.split("/", 1)
    return f"https://{owner.lower()}.github.io/{repo}"


def human_state(state: str) -> str:
    return {
        "WAITING_FOR_BETA_REVIEW": "waiting for Apple's beta review (usually under a day)",
        "IN_BETA_REVIEW": "in Apple's beta review",
        "BETA_APPROVED": "approved: anyone with the link can install",
        "READY_FOR_BETA_TESTING": "ready: anyone with the link can install",
        "IN_BETA_TESTING": "live: anyone with the link can install",
        "BETA_REJECTED": "rejected by beta review: see App Store Connect → TestFlight for the reason",
        "MISSING_EXPORT_COMPLIANCE": "missing export compliance",
        "PROCESSING_EXCEPTION": "processing problem",
    }.get(state, state.replace("_", " ").lower())


# ------------------------------------------------------------------------ main

def release(cfg: dict) -> None:
    check_tools()
    setup_basics(cfg)
    setup_api_key(cfg)
    api = Api(cfg)
    check_key(api)

    bundle_id = f"{cfg['bundle_prefix']}.InboxOnly"
    app = ensure_app(api, bundle_id)
    pages = pages_url()

    # A build uploaded by an earlier, interrupted run can be finished instead.
    build_number = cfg.get("pending_build")
    if build_number and input(f"\n  Finish publishing build {build_number} from last time? [Y/n] ").strip().lower() in ("", "y", "yes"):
        say(f"  Continuing with build {build_number}")
    else:
        build_number = time.strftime("%Y%m%d%H%M")
        build_and_upload(cfg, build_number)
        cfg["pending_build"] = build_number
        save_config(cfg)
    build = wait_for_build(api, app["id"], build_number)

    ensure_test_info(api, cfg, app["id"], pages)
    step("Publishing the build")
    prepare_build(api, build)
    ensure_team_group(api, cfg, app["id"])
    link = ensure_public_group(api, app["id"], build["id"])
    state = submit_for_review(api, build["id"])
    say(f"  Public link: {link}")
    say(f"  Status: {human_state(state)}")

    cfg.pop("pending_build", None)
    save_config(cfg)

    publish_page({
        "testflight": link,
        "version": project_setting("MARKETING_VERSION") or "1.0.0",
        "build": build_number,
        "expires": build["attributes"].get("expirationDate"),
    })

    say("\n\033[1mDone.\033[0m")
    say(f"  Install page:     {pages}/")
    say(f"  TestFlight link:  {link}")
    say("  Check review progress any time with: ./release.py status")
    say("  Run ./release.py again within 90 days so the app doesn't expire.")


def status(cfg: dict) -> None:
    if not cfg.get("key_id"):
        fail("Nothing released yet. Run ./release.py first.")
    api = Api(cfg)
    bundle_id = f"{cfg['bundle_prefix']}.InboxOnly"
    apps = api.get("/v1/apps", **{"filter[bundleId]": bundle_id})["data"]
    if not apps:
        fail(f"No app with bundle ID {bundle_id} in App Store Connect yet.")
    builds = api.get("/v1/builds", **{"filter[app]": apps[0]["id"], "sort": "-uploadedDate", "limit": 1})["data"]
    if not builds:
        fail("No builds uploaded yet.")
    build = builds[0]
    detail = api.get(f"/v1/builds/{build['id']}/buildBetaDetail")["data"]["attributes"]
    group = find_group(api, apps[0]["id"], PUBLIC_GROUP)
    say(f"Build {build['attributes']['version']} uploaded {build['attributes']['uploadedDate'][:10]}")
    say(f"  Status:   {human_state(detail.get('externalBuildState', 'UNKNOWN'))}")
    say(f"  Expires:  {(build['attributes'].get('expirationDate') or '?')[:10]}")
    if group and group["attributes"].get("publicLink"):
        say(f"  Link:     {group['attributes']['publicLink']}")


def main() -> None:
    os.chdir(ROOT)
    cfg = load_config()
    try:
        if sys.argv[1:] == ["status"]:
            status(cfg)
        elif sys.argv[1:]:
            say(__doc__)
        else:
            release(cfg)
    except KeyboardInterrupt:
        say("\nStopped. Run ./release.py again to continue; your answers are remembered.")
        sys.exit(130)
    except ApiError as e:
        fail(f"App Store Connect said no: {e}")
    except subprocess.CalledProcessError as e:
        hint = ""
        if e.cmd and e.cmd[0] == "xcodebuild":
            hint = ("\n  Signing errors usually mean the API key isn't an Admin key. Create one with "
                    f"Admin access and delete {CONFIG} to enter it.")
        fail(f"`{' '.join(map(str, e.cmd[:3]))} …` failed (see the output above).{hint}")


if __name__ == "__main__":
    main()
