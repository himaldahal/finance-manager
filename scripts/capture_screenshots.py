#!/usr/bin/env python3
"""Capture the README screenshots with headless Chromium.

Starts the development server on a free port with a throwaway SQLite database seeded with demo data,
signs in by injecting a session cookie through the Chromium DevTools protocol (no login backdoor is
added to the app), and saves PNG files to docs/screenshots/.

    python scripts/capture_screenshots.py [--only dashboard,transactions]

Chromium is found automatically (override with CHROMIUM=/path). Only the standard library and Pillow
(optional, used to shrink large PNG files) are required.
"""
import argparse
import base64
import json
import os
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "screenshots"
DESKTOP = (1280, 800)
MOBILE = (390, 844)
MAX_BYTES = 400 * 1024


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def find_chromium():
    for candidate in (os.environ.get("CHROMIUM"), "/snap/bin/chromium", "/usr/bin/chromium-browser", "/usr/bin/chromium",
                      "/usr/bin/google-chrome"):
        if candidate and os.path.exists(candidate):
            return candidate
    sys.exit("Chromium not found. Set CHROMIUM=/path/to/chromium.")


class DevTools:
    """Just enough of the Chrome DevTools protocol over a hand-rolled WebSocket."""

    def __init__(self, url):
        parts = urlparse(url)
        host, port, path = parts.hostname, parts.port, parts.path
        self.sock = socket.create_connection((host, port), timeout=30)
        key = base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall((f"GET {path} HTTP/1.1\r\nHost: {host}:{port}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                           f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            buf += self.sock.recv(1)
        self.next_id = 0
        self.events = []

    def _send(self, text):
        data = text.encode()
        header = bytearray([0x81])
        n = len(data)
        if n < 126:
            header.append(0x80 | n)
        elif n < 65536:
            header.append(0x80 | 126)
            header += struct.pack(">H", n)
        else:
            header.append(0x80 | 127)
            header += struct.pack(">Q", n)
        mask = os.urandom(4)
        header += mask
        self.sock.sendall(bytes(header) + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))

    def _read(self, n):
        buf = b""
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("DevTools connection closed")
            buf += chunk
        return buf

    def _recv(self):
        message = b""
        while True:
            b1, b2 = self._read(2)
            opcode = b1 & 0x0F
            length = b2 & 0x7F
            if length == 126:
                length = struct.unpack(">H", self._read(2))[0]
            elif length == 127:
                length = struct.unpack(">Q", self._read(8))[0]
            payload = self._read(length)
            if opcode == 0x8:
                raise ConnectionError("DevTools closed")
            if opcode in (0x1, 0x0, 0x2):
                message += payload
                if b1 & 0x80:
                    return json.loads(message)

    def call(self, method, **params):
        self.next_id += 1
        mine = self.next_id
        self._send(json.dumps({"id": mine, "method": method, "params": params}))
        while True:
            msg = self._recv()
            if msg.get("id") == mine:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg.get("result", {})
            if "method" in msg:
                self.events.append(msg["method"])

    def eval(self, expression, await_promise=False):
        result = self.call("Runtime.evaluate", expression=expression, returnByValue=True, awaitPromise=await_promise)
        if "exceptionDetails" in result:
            raise RuntimeError(f"JS error in {expression[:80]!r}: {result['exceptionDetails'].get('text')} {result['exceptionDetails'].get('exception', {}).get('description', '')}")
        return result.get("result", {}).get("value")

    def wait_for(self, expression, timeout=15):
        end = time.time() + timeout
        while time.time() < end:
            if self.eval(expression):
                return True
            time.sleep(0.15)
        return False


def run(cmd, env, **kwargs):
    return subprocess.run(cmd, env=env, cwd=ROOT, check=True, capture_output=True, text=True, **kwargs)


def shrink(path):
    if path.stat().st_size <= MAX_BYTES:
        return
    try:
        from PIL import Image
    except ImportError:
        print(f"  note: {path.name} is {path.stat().st_size // 1024} KB (install Pillow to shrink)")
        return
    image = Image.open(path).convert("RGB")
    image.quantize(colors=128, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE).save(path, optimize=True)
    print(f"  shrunk {path.name} to {path.stat().st_size // 1024} KB")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", help="comma separated screenshot names")
    args = parser.parse_args()
    only = set(args.only.split(",")) if args.only else None

    work = Path(tempfile.mkdtemp(prefix="fm-shots-"))
    home_share = Path.home() / "snap" / "chromium" / "common"
    profile_root = home_share if home_share.exists() else work
    profile = Path(tempfile.mkdtemp(prefix="fm-profile-", dir=profile_root))
    upload_dir = profile_root if profile_root == home_share else work
    csv_path = upload_dir / "fm-import-example.csv"
    csv_path.write_text(
        "date,type,name,category,amount,payee,account,tags,note\n"
        "2026-09-02,expense,Weekly groceries,Groceries,3200.00,Bhat-Bhateni,Main account,essential,\n"
        "2026-09-03,expense,Cafe Mitini lunch,,640.00,Cafe Mitini,,,Lunch with the team\n"
        "2026-09-05,income,Freelance logo project,Freelance,15000.00,Client,Main account,work,\n"
        "2026-09-07,expense,Gym bag,Fitness,2800.00,Daraz,Cash,treat,New category\n"
        "2026-09-09,expense,Broken row,Groceries,not-a-number,,,,\n"
        "2026-09-11,expense,Internet plan,Internet,1500.00,WorldLink,Main account,essential,\n", encoding="utf-8")

    port, debug_port = free_port(), free_port()
    env = dict(os.environ, DEBUG="1", SECRET_KEY="screenshots-only-key", DATABASE_PATH=str(work / "demo.sqlite3"),
               ALLOWED_HOSTS="127.0.0.1,localhost", PYTHONPATH=str(ROOT), PYTHONDONTWRITEBYTECODE="1")
    py = sys.executable
    run([py, "manage.py", "migrate", "-v0"], env)
    run([py, "manage.py", "seed_demo"], env)
    def make_session(username, create=False):
        code = (
            "import os,django;os.environ['DJANGO_SETTINGS_MODULE']='expensemanager.settings';django.setup();"
            "from django.test import Client;from django.contrib.auth import get_user_model;"
            "from app import services;"
            "U=get_user_model();"
            f"u=U.objects.filter(username='{username}').first() or U.objects.create_user('{username}', password='x-Long-pass-91');"
            + ("services.set_up_new_user(u);" if create else "") +
            "c=Client(HTTP_HOST='localhost');c.force_login(u);"
            "print(c.cookies['sessionid'].value)")
        return run([py, "-c", code], env).stdout.strip().splitlines()[-1]

    session = make_session("demo")
    newcomer = make_session("newcomer", create=True)

    server = subprocess.Popen([py, "manage.py", "runserver", f"127.0.0.1:{port}", "--noreload"], env=env, cwd=ROOT,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    browser = None
    try:
        base = f"http://127.0.0.1:{port}"
        for _ in range(80):
            try:
                urllib.request.urlopen(base + "/login/", timeout=1)
                break
            except Exception:
                time.sleep(0.25)
        browser = subprocess.Popen([
            find_chromium(), "--headless=new", "--no-sandbox", "--disable-gpu", "--hide-scrollbars",
            f"--remote-debugging-port={debug_port}", f"--user-data-dir={profile}", "--remote-allow-origins=*",
            "--force-device-scale-factor=1", "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        target = None
        for _ in range(80):
            try:
                req = urllib.request.Request(f"http://127.0.0.1:{debug_port}/json/new?about:blank", method="PUT")
                target = json.load(urllib.request.urlopen(req, timeout=2))
                break
            except Exception:
                time.sleep(0.25)
        if target is None:
            sys.exit("Could not connect to Chromium.")
        cdp = DevTools(target["webSocketDebuggerUrl"])
        for domain in ("Page", "Runtime", "Network", "DOM"):
            cdp.call(f"{domain}.enable")
        OUT.mkdir(parents=True, exist_ok=True)

        def viewport(size, mobile=False):
            cdp.call("Emulation.setDeviceMetricsOverride", width=size[0], height=size[1], deviceScaleFactor=1, mobile=mobile)

        def go(path, ready="document.querySelectorAll('.loading').length === 0", wait=0.4):
            cdp.call("Page.navigate", url=base + path)
            time.sleep(0.5)
            cdp.wait_for("document.readyState === 'complete'")
            cdp.wait_for(ready)
            time.sleep(wait)

        def shot(name, full=False, size=DESKTOP, mobile=False, max_height=2600):
            if only and name not in only:
                return
            viewport(size, mobile)
            time.sleep(0.2)
            if full:
                height = cdp.eval("Math.min(document.documentElement.scrollHeight, %d)" % max_height)
                viewport((size[0], max(size[1], int(height))), mobile)
                time.sleep(0.4)
            data = cdp.call("Page.captureScreenshot", format="png")["data"]
            path = OUT / f"{name}.png"
            path.write_bytes(base64.b64decode(data))
            shrink(path)
            print(f"saved {path.relative_to(ROOT)} ({path.stat().st_size // 1024} KB)")
            viewport(size, mobile)

        def click(selector):
            cdp.eval(f"document.querySelector({json.dumps(selector)}).click()")

        def fill(selector, value):
            cdp.eval(f"(() => {{ const el = document.querySelector({json.dumps(selector)}); el.focus(); el.value = {json.dumps(value)};"
                     "el.dispatchEvent(new Event('input', {bubbles: true})); el.dispatchEvent(new Event('change', {bubbles: true})); })()")

        # --- signed out pages
        viewport(DESKTOP)
        go("/login/", ready="true")
        shot("login")
        go("/register/", ready="true")
        fill("#id_full_name", "Asha Gurung")
        fill("#id_username", "asha")
        fill("#id_email", "asha@example.com")
        fill("#id_password1", "river-Lamp-42-bridge")
        fill("#id_password2", "river-Lamp-42-bridge")
        click("[data-pw-toggle]")
        shot("register")

        # register page with problems, then valid
        go("/register/", ready="true")
        fill("#id_full_name", "Asha")
        fill("#id_username", "demo")
        fill("#id_email", "asha@")
        fill("#id_password1", "asha12")
        fill("#id_password2", "asha13")
        time.sleep(1.0)
        click("#id_email")
        cdp.eval("document.getElementById('id_email').blur()")
        shot("register-invalid", full=True)
        go("/register/", ready="true")
        fill("#id_full_name", "Asha")
        fill("#id_username", "asha-g")
        fill("#id_email", "asha@example.com")
        fill("#id_password1", "river-Lamp-42-bridge")
        fill("#id_password2", "river-Lamp-42-bridge")
        time.sleep(1.0)
        shot("register-valid", full=True)

        # --- first run for a brand new user
        cdp.call("Network.setCookie", name="sessionid", value=newcomer, domain="127.0.0.1", path="/")
        go("/", ready="true")
        shot("welcome", full=True)

        # --- signed in
        cdp.call("Network.setCookie", name="sessionid", value=session, domain="127.0.0.1", path="/")
        go("/")
        fill("#quick-input", "lunch 450 dining")
        click("#quick-add button[type=submit]")
        time.sleep(1.0)
        shot("dashboard", full=True)

        go("/transactions/?type=expense&date_from=2026-07-01&sort=-amount&page_size=10&min_amount=1000", ready="true")
        shot("transactions", full=True)

        go("/transactions/", ready="true")
        click("button[data-new-transaction]")
        time.sleep(0.4)
        fill("#tx-name", "Pathao ride to office")
        fill("#tx-amount", "420")
        fill("#tx-tags", "work")
        time.sleep(0.8)
        shot("add-transaction")

        go("/transactions/", ready="true")
        cdp.eval("""document.querySelector('.inline-cat') && 0""")
        go("/transactions/", ready="true")
        click("#reconcile summary")
        shot("transactions-tools")

        go("/accounts/")
        shot("accounts", full=True)
        go("/categories/")
        shot("categories", full=True)
        click("#new-category")
        time.sleep(0.4)
        shot("category-dialog")
        go("/budgets/")
        time.sleep(0.6)
        shot("budgets", full=True)
        go("/goals/")
        shot("goals", full=True)
        go("/people/")
        shot("people", full=True)
        go("/digest/", ready="true")
        shot("digest", full=True)
        go("/backup/", ready="true")
        shot("backup")
        # delete something so the trash has content, then show it
        go("/transactions/", ready="true")
        cdp.eval("""(async () => { const t = document.querySelector('meta[name=csrf-token]').content;
          const r = await fetch('/api/transactions/?page_size=3').then(x => x.json());
          for (const tx of r.transactions.slice(0, 2)) await fetch('/api/transactions/' + tx.id + '/', {method: 'DELETE', headers: {'X-CSRFToken': t}});
        })()""", await_promise=True)
        time.sleep(0.5)
        go("/trash/")
        shot("trash", full=True)
        go("/recurring/")
        shot("recurring", full=True)
        go("/analytics/", ready="document.querySelectorAll('[data-chart] svg').length >= 8")
        time.sleep(0.5)
        shot("analytics", full=True, max_height=3600)
        go("/reports/", ready="true")
        shot("reports", full=True, max_height=3000)

        go("/import/", ready="true")
        cdp.call("DOM.getDocument")
        node = cdp.call("DOM.querySelector", nodeId=cdp.call("DOM.getDocument")["root"]["nodeId"], selector="input[type=file]")["nodeId"]
        cdp.call("DOM.setFileInputFiles", files=[str(csv_path)], nodeId=node)
        click("form[enctype] button[type=submit]")
        time.sleep(1.2)
        cdp.wait_for("document.readyState === 'complete'")
        shot("import-preview", full=True)

        go("/settings/", ready="true")
        shot("settings", full=True)

        go("/", ready="true")
        cdp.eval("document.body.dispatchEvent(new KeyboardEvent('keydown', {key: '/', bubbles: true}))")
        time.sleep(0.4)
        fill("#search-input", "dining last month over 500")
        time.sleep(1.2)
        shot("search")

        # --- sidebar: expanded, collapsed rail
        go("/budgets/")
        shot("sidebar-expanded")
        click("#sidebar-collapse")
        time.sleep(0.6)
        cdp.eval("document.querySelector('.nav a[data-tip=\"Goals\"]').dispatchEvent(new MouseEvent('mouseover', {bubbles: true}))")
        shot("sidebar-collapsed")
        click("#sidebar-collapse")

        # --- mobile
        go("/")
        shot("mobile-dashboard", full=True, size=MOBILE, mobile=True)
        go("/transactions/?type=expense", ready="true")
        shot("mobile-transactions", full=True, size=MOBILE, mobile=True)
        go("/analytics/", ready="document.querySelectorAll('[data-chart] svg').length >= 8")
        time.sleep(0.5)
        shot("mobile-analytics", full=True, size=MOBILE, mobile=True, max_height=4200)
        go("/")
        click("#nav-toggle")
        time.sleep(0.5)
        shot("mobile-drawer", size=MOBILE, mobile=True)
        click("#scrim")
        go("/budgets/")
        shot("mobile-budgets", full=True, size=MOBILE, mobile=True)
    finally:
        for proc in (browser, server):
            if proc:
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()
        shutil.rmtree(work, ignore_errors=True)
        shutil.rmtree(profile, ignore_errors=True)
        try:
            csv_path.unlink()
        except OSError:
            pass


if __name__ == "__main__":
    main()
