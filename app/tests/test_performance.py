"""A simple performance budget: the CSS and JavaScript each page needs must stay small."""
import gzip
import re

from django.contrib.staticfiles import finders
from django.urls import reverse

from .base import AppTestCase

RAW_BUDGET = 115 * 1024      # uncompressed bytes of CSS plus JavaScript per page
GZIP_BUDGET = 40 * 1024      # what actually crosses the wire with compression


def static_bytes(url):
    path = finders.find(url.replace("/static/", "", 1))
    with open(path, "rb") as handle:
        return handle.read()


def page_assets(html):
    """Every stylesheet, script and (recursively) imported module a page loads."""
    pending = re.findall(r'(?:href|src)="(/static/[^"]+\.(?:css|js))"', html)
    seen = {}
    while pending:
        url = pending.pop()
        if url in seen:
            continue
        data = static_bytes(url)
        seen[url] = data
        if url.endswith(".js"):
            base = url.rsplit("/", 1)[0]
            for module in re.findall(r"from '\./([^']+\.js)'", data.decode("utf-8")):
                pending.append(f"{base}/{module}")
    return seen


class PerformanceBudgetTests(AppTestCase):
    def test_every_page_stays_within_budget(self):
        names = ("dashboard", "transactions", "accounts", "categories", "budgets", "goals", "recurring", "analytics", "reports",
                 "settings", "import", "trash", "people", "backup", "digest")
        for name in names:
            assets = page_assets(self.client.get(reverse(name)).content.decode())
            raw = sum(len(b) for b in assets.values())
            compressed = sum(len(gzip.compress(b)) for b in assets.values())
            self.assertLess(raw, RAW_BUDGET, f"{name}: {raw} bytes raw")
            self.assertLess(compressed, GZIP_BUDGET, f"{name}: {compressed} bytes gzipped")

    def test_scripts_are_modules_or_tiny_and_deferred(self):
        html = self.client.get(reverse("dashboard")).content.decode()
        self.assertIn('<script type="module"', html)       # modules are deferred by the browser
        self.assertIn("sidebar-init.js", html)              # the only blocking script, a few hundred bytes
        self.assertLess(len(static_bytes("/static/app/js/sidebar-init.js")), 600)

    def test_no_external_requests_needed_by_pages(self):
        for name in ("dashboard", "analytics", "reports"):
            html = self.client.get(reverse(name)).content.decode()
            self.assertNotRegex(html, r'(?:href|src)="https?://')
