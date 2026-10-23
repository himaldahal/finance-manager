import datetime
import json
import re
from decimal import Decimal

from django.core.cache import cache
from django.test import Client, override_settings
from django.urls import reverse

from app import services
from app.models import (
    Account, Budget, Category, CategoryRule, Contribution, Goal, LedgerEntry, Person, RecurringTransaction, SavedView, Tag,
    Transaction, Transfer,
)

from .base import AppTestCase, PASSWORD, today


class LoginRequiredTests(AppTestCase):
    PAGES = ["dashboard", "transactions", "accounts", "categories", "budgets", "goals", "recurring", "analytics", "reports",
             "settings", "export", "import", "welcome", "digest", "trash", "people", "backup", "backup_export"]

    def test_pages_redirect_to_login(self):
        anon = Client()
        for name in self.PAGES:
            r = anon.get(reverse(name))
            self.assertEqual(r.status_code, 302, name)
            self.assertTrue(r["Location"].startswith(reverse("login")), name)

    def test_api_returns_401_json(self):
        anon = Client()
        for name in ("api_summary", "api_analytics", "api_transactions", "api_categories", "api_accounts", "api_budgets", "api_goals",
                     "api_recurring", "api_search", "api_insights", "api_trash", "api_people", "api_tags", "api_rules", "api_views",
                     "api_notifications", "api_onboarding", "api_activity", "api_transfers"):
            r = anon.get(reverse(name))
            self.assertEqual(r.status_code, 401, name)
            self.assertFalse(r.json()["ok"])

    def test_post_only_pages_require_login(self):
        anon = Client()
        for name in ("change_password", "import_confirm", "import_cancel", "lock_month", "erase_data", "delete_account"):
            r = anon.post(reverse(name))
            self.assertEqual(r.status_code, 302, name)
            self.assertIn("/login/", r["Location"])


class IdorTests(AppTestCase):
    """Every object endpoint must answer 404 for another user's objects."""

    def setUp(self):
        super().setUp()
        o = self.other
        self.o_tx = self.tx(user=o)
        self.o_cat = self.cat(o, "Health")
        self.o_acct = self.account(o)
        self.o_budget = Budget.objects.create(user=o, category=self.o_cat, month=today().replace(day=1), amount=Decimal("10"))
        self.o_goal = Goal.objects.create(user=o, name="G", target_amount=Decimal("10"))
        self.o_contrib = Contribution.objects.create(goal=self.o_goal, amount=Decimal("5"))
        self.o_rec = RecurringTransaction.objects.create(user=o, name="R", amount=Decimal("5"), kind="expense", category=self.o_cat,
                                                         start_date=today(), next_due=today() + datetime.timedelta(days=20))
        self.o_rule = CategoryRule.objects.create(user=o, pattern="zz", category=self.o_cat)
        self.o_tag = Tag.objects.create(user=o, name="secret")
        self.o_view = SavedView.objects.create(user=o, name="v", query="")
        self.o_person = Person.objects.create(user=o, name="Bob")
        self.o_entry = LedgerEntry.objects.create(person=self.o_person, kind="lent", amount=Decimal("5"), date=today())
        b = Account.objects.create(user=o, name="Other", type="cash")
        self.o_transfer = Transfer.objects.create(user=o, from_account=self.o_acct, to_account=b, amount=Decimal("1"), date=today())

    def assert404(self, response, label=""):
        self.assertEqual(response.status_code, 404, label)

    def test_transactions(self):
        url = reverse("api_transaction", args=[self.o_tx.pk])
        self.assert404(self.client.get(url))
        self.assert404(self.post(url, self.payload()))
        self.assert404(self.delete(url))
        self.assert404(self.post(reverse("api_transaction_restore", args=[self.o_tx.pk])))
        self.assert404(self.client.get(reverse("api_transaction_history", args=[self.o_tx.pk])))
        self.assertTrue(Transaction.objects.filter(pk=self.o_tx.pk).exists())

    def test_bulk_never_touches_foreign_rows(self):
        mine = self.tx()
        for action in ("delete", "reconcile", "restore"):
            self.assert404(self.post(reverse("api_transactions_bulk"), {"action": action, "ids": [mine.pk, self.o_tx.pk]}), action)
        self.assert404(self.post(reverse("api_transactions_bulk"), {"action": "category", "ids": [self.o_tx.pk], "category": self.cat().pk}))
        self.assertTrue(Transaction.objects.filter(pk=mine.pk).exists())
        self.assertFalse(Transaction.objects.get(pk=self.o_tx.pk).reconciled)

    def test_foreign_references_in_payloads(self):
        self.assertEqual(self.post(reverse("api_transactions"), self.payload(category=self.o_cat.pk)).status_code, 422)
        self.assertEqual(self.post(reverse("api_transactions"), self.payload(account=self.o_acct.pk)).status_code, 422)
        t = self.tx()
        r = self.post(reverse("api_transaction", args=[t.pk]), self.payload(category=self.o_cat.pk))
        self.assertEqual(r.status_code, 422)
        t.refresh_from_db()
        self.assertNotEqual(t.category_id, self.o_cat.pk)

    def test_categories_accounts(self):
        for name, obj in (("api_category", self.o_cat), ("api_account", self.o_acct)):
            url = reverse(name, args=[obj.pk])
            self.assert404(self.client.get(url), name)
            self.assert404(self.post(url, {"name": "x"}), name)
            self.assert404(self.delete(url), name)
        self.assert404(self.delete(reverse("api_transfer", args=[self.o_transfer.pk])))

    def test_budgets_goals_recurring(self):
        self.assert404(self.delete(reverse("api_budget", args=[self.o_budget.pk])))
        for name, obj in (("api_goal", self.o_goal), ("api_recurring_item", self.o_rec)):
            url = reverse(name, args=[obj.pk])
            self.assert404(self.client.get(url), name)
            self.assert404(self.post(url, {}), name)
            self.assert404(self.delete(url), name)
        self.assert404(self.post(reverse("api_goal_contribute", args=[self.o_goal.pk]), {"amount": "5", "date": today().isoformat()}))
        self.assert404(self.delete(reverse("api_contribution", args=[self.o_contrib.pk])))
        self.assert404(self.post(reverse("api_recurring_toggle", args=[self.o_rec.pk])))

    def test_rules_tags_views_people(self):
        for name, obj in (("api_rule", self.o_rule), ("api_tag", self.o_tag), ("api_view", self.o_view), ("api_person", self.o_person)):
            url = reverse(name, args=[obj.pk])
            self.assert404(self.delete(url), name)
        self.assert404(self.post(reverse("api_rule", args=[self.o_rule.pk]), {"pattern": "xx", "category": self.cat().pk}))
        self.assert404(self.post(reverse("api_tag", args=[self.o_tag.pk]), {"name": "x"}))
        self.assert404(self.post(reverse("api_person", args=[self.o_person.pk]), {"name": "x"}))
        self.assert404(self.post(reverse("api_person_entry", args=[self.o_person.pk]), {"kind": "lent", "amount": "5"}))
        self.assert404(self.delete(reverse("api_entry", args=[self.o_entry.pk])))
        self.assert404(self.delete(reverse("api_trash_item", args=[self.o_tx.pk])))

    def test_list_endpoints_never_leak(self):
        self.o_tx.name = "SECRET-TX"
        self.o_tx.payee = "SECRET-PAYEE"
        self.o_tx.save()
        for name in ("api_transactions", "api_categories", "api_accounts", "api_tags", "api_rules", "api_views", "api_budgets",
                     "api_goals", "api_recurring", "api_people", "api_transfers", "api_trash", "api_activity", "api_insights"):
            self.assertNotIn(b"SECRET", self.client.get(reverse(name)).content, name)
        self.assertEqual(self.json(self.client.get(reverse("api_search"), {"q": "SECRET"}))["groups"], [])
        self.assertEqual(self.json(self.client.get(reverse("api_suggest"), {"type": "payee", "q": "SECRET"}))["items"], [])
        self.assertEqual(self.json(self.client.get(reverse("api_suggest"), {"type": "tag", "q": "secret"}))["items"], [])
        export = b"".join(self.client.get(reverse("export")).streaming_content)
        self.assertNotIn(b"SECRET", export)
        self.assertNotIn(b"SECRET", self.client.get(reverse("backup_export")).content)

    def test_filter_params_cannot_reach_foreign_data(self):
        for params in ({"category": self.o_cat.pk}, {"account": self.o_acct.pk}, {"tag": self.o_tag.pk}):
            self.assertEqual(self.json(self.client.get(reverse("api_transactions"), params))["count"], 0)

    def test_reconcile_and_pages(self):
        self.assert404(self.client.get(reverse("api_reconcile"), {"account": self.o_acct.pk}))
        t = self.tx()
        self.assertEqual(self.client.get(reverse("transactions"), {"category": self.o_cat.pk}).context["paginator"].count, 0)


class CsrfAndMethodTests(AppTestCase):
    def test_csrf_enforced_on_every_mutation(self):
        client = self.csrf_client()
        t = self.tx()
        urls = [
            reverse("api_transactions"), reverse("api_transaction", args=[t.pk]), reverse("api_transactions_bulk"),
            reverse("api_transaction_split"), reverse("api_categories"), reverse("api_accounts"), reverse("api_transfers"),
            reverse("api_rules"), reverse("api_views"), reverse("api_budgets"), reverse("api_budget_copy"), reverse("api_goals"),
            reverse("api_recurring"), reverse("api_people"), reverse("api_trash_empty"), reverse("api_sample_data"), reverse("api_onboarding"),
            reverse("logout"), reverse("change_password"), reverse("import_cancel"), reverse("lock_month"), reverse("erase_data"),
            reverse("delete_account"), reverse("backup"), reverse("settings"), reverse("welcome"),
        ]
        for url in urls:
            r = client.post(url, "{}", content_type="application/json")
            self.assertEqual(r.status_code, 403, url)
        self.assertEqual(client.delete(reverse("api_transaction", args=[t.pk])).status_code, 403)
        self.assertTrue(Transaction.objects.filter(pk=t.pk).exists())

    def test_csrf_token_header_is_accepted(self):
        client = self.csrf_client()
        token = client.get(reverse("dashboard")).cookies["csrftoken"].value
        r = client.post(reverse("api_transactions"), json.dumps(self.payload()), content_type="application/json", HTTP_X_CSRFTOKEN=token)
        self.assertEqual(r.status_code, 201)

    def test_method_restrictions(self):
        t = self.tx()
        cases = [
            ("get", reverse("api_transaction_restore", args=[t.pk])), ("get", reverse("api_transactions_bulk")),
            ("put", reverse("api_transactions")), ("delete", reverse("api_transactions")), ("post", reverse("api_summary")),
            ("post", reverse("api_analytics")), ("get", reverse("api_budget_copy")), ("delete", reverse("api_budgets")),
            ("get", reverse("api_trash_empty")), ("post", reverse("api_search")), ("patch", reverse("api_transaction", args=[t.pk])),
        ]
        for method, url in cases:
            r = getattr(self.client, method)(url)
            self.assertEqual(r.status_code, 405, (method, url))
            self.assertIn("Allow", r)

    def test_logout_is_post_only(self):
        self.assertEqual(self.client.get(reverse("logout")).status_code, 405)
        self.assertEqual(self.client.post(reverse("logout")).status_code, 302)
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 302)

    def test_page_method_restrictions(self):
        for name in ("change_password", "import_cancel", "import_confirm", "lock_month", "erase_data", "delete_account"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 405, name)
        self.assertEqual(self.client.post(reverse("export")).status_code, 405)
        self.assertEqual(self.client.post(reverse("backup_export")).status_code, 405)


class XssAndInjectionTests(AppTestCase):
    PAYLOAD = '<script>alert(1)</script><img src=x onerror=alert(2)>'

    def test_stored_raw_rendered_escaped(self):
        t = self.tx(name=self.PAYLOAD, payee=self.PAYLOAD, note=self.PAYLOAD)
        services.save_transaction(t, tags=["<b>tag</b>"])
        self.assertEqual(Transaction.objects.get(pk=t.pk).name, self.PAYLOAD)
        html = self.client.get(reverse("transactions")).content.decode()
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertNotIn("<img src=x", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertIn("&lt;b&gt;tag&lt;/b&gt;", html)

    def test_api_returns_raw_json_only(self):
        r = self.post(reverse("api_transactions"), self.payload(name=self.PAYLOAD))
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r["Content-Type"], "application/json")
        self.assertEqual(self.json(r)["transaction"]["name"], self.PAYLOAD)

    def test_category_and_profile_fields_escaped_in_pages(self):
        Category.objects.create(user=self.user, name=self.PAYLOAD[:50], kind="both")
        html = self.client.get(reverse("transactions")).content.decode()
        self.assertNotIn("<script>alert(1)", html)
        self.user.first_name = self.PAYLOAD[:60]
        self.user.save()
        self.assertNotIn("<script>alert(1)", self.client.get(reverse("settings")).content.decode())

    def test_import_preview_escapes(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        csv = f"date,type,name,category,amount\n{today().isoformat()},expense,\"{self.PAYLOAD}\",Groceries,5\n"
        self.client.post(reverse("import"), {"file": SimpleUploadedFile("a.csv", csv.encode())})
        html = self.client.get(reverse("import")).content.decode()
        self.assertNotIn("<script>alert(1)</script>", html)

    def test_no_inline_scripts_or_handlers_in_pages(self):
        for name in ("dashboard", "transactions", "categories", "budgets", "goals", "accounts", "recurring", "analytics", "reports",
                     "settings", "import", "trash", "people", "backup", "digest"):
            html = self.client.get(reverse(name)).content.decode()
            for script in re.findall(r"<script\b([^>]*)>", html):
                self.assertTrue("src=" in script or 'type="application/json"' in script, (name, script))
            self.assertNotRegex(html, r"\son[a-z]+\s*=", name)
            self.assertNotIn("javascript:", html, name)
            self.assertNotRegex(html, r'<[^>]+\sstyle="', name)
            self.assertNotRegex(html, r"https?://(?!www\.w3\.org)", name)

    def test_search_term_is_not_reflected_as_html(self):
        r = self.client.get(reverse("api_search"), {"q": self.PAYLOAD})
        self.assertEqual(r["Content-Type"], "application/json")


class CsvInjectionTests(AppTestCase):
    def test_export_neutralises_formulas(self):
        t = self.tx(name="=HYPERLINK(\"http://evil\")", payee="+SUM(A1)", note="@cmd")
        services.save_transaction(t, tags=["-tag"])
        body = b"".join(self.client.get(reverse("export")).streaming_content).decode("utf-8-sig")
        self.assertIn("\"'=HYPERLINK", body)
        self.assertIn("'+SUM(A1)", body)
        self.assertIn("'@cmd", body)
        self.assertIn("'-tag", body)

    def test_report_export_neutralises_formulas(self):
        self.tx(name="x", payee="=EVIL()")
        body = b"".join(self.client.get(reverse("report_export"), {"report": "payees"}).streaming_content).decode("utf-8-sig")
        self.assertIn("'=EVIL()", body)

    def test_safe_cell_unit(self):
        from app.csvio import safe_cell, unsafe_cell
        for bad in ("=1", "+1", "-1", "@a", "\tx"):
            self.assertTrue(safe_cell(bad).startswith("'"))
        self.assertEqual(safe_cell("plain"), "plain")
        self.assertEqual(safe_cell(None), "")
        self.assertEqual(unsafe_cell("'=1"), "=1")
        self.assertEqual(unsafe_cell("'hello"), "'hello")


class RateLimitTests(AppTestCase):
    def setUp(self):
        super().setUp()
        cache.clear()
        self.client.logout()

    def attempt(self, password="wrong", username="alice"):
        return self.client.post(reverse("login"), {"username": username, "password": password})

    def test_lockout_after_failures_even_with_correct_password(self):
        for _ in range(5):
            self.assertEqual(self.attempt().status_code, 200)
        r = self.attempt()
        self.assertEqual(r.status_code, 429)
        self.assertContains(r, "Too many failed", status_code=429)
        self.assertEqual(self.attempt(PASSWORD).status_code, 429)

    def test_success_resets_counter(self):
        for _ in range(3):
            self.attempt()
        self.assertEqual(self.attempt(PASSWORD).status_code, 302)
        self.client.logout()
        for _ in range(4):
            self.assertEqual(self.attempt().status_code, 200)

    def test_other_users_not_locked_out(self):
        for _ in range(6):
            self.attempt()
        self.assertEqual(self.attempt(PASSWORD, "mallory").status_code, 302)

    def test_username_is_case_insensitive(self):
        self.assertEqual(self.attempt(PASSWORD, "ALICE").status_code, 302)

    @override_settings(LOGIN_MAX_ATTEMPTS=2)
    def test_throttle_unit(self):
        from app.ratelimit import Throttle
        t = Throttle("unit", 2, 60)
        self.assertFalse(t.blocked("x"))
        t.hit("x")
        t.hit("x")
        self.assertTrue(t.blocked("x"))
        t.reset("x")
        self.assertEqual(t.count("x"), 0)

    def test_registration_throttle(self):
        from app import views
        for i in range(views.register_by_ip.limit):
            r = self.client.post(reverse("register"), {
                "full_name": "N", "username": f"user{i}", "email": f"u{i}@e.com", "password1": PASSWORD, "password2": PASSWORD})
            self.assertEqual(r.status_code, 302, i)
            self.client.logout()
        r = self.client.post(reverse("register"), {"full_name": "N", "username": "late", "email": "l@e.com",
                                                   "password1": PASSWORD, "password2": PASSWORD})
        self.assertEqual(r.status_code, 429)

    def test_username_check_throttle(self):
        from app import views
        for _ in range(views.username_check.limit):
            self.assertEqual(self.client.get(reverse("username_available"), {"u": "nobody"}).status_code, 200)
        self.assertEqual(self.client.get(reverse("username_available"), {"u": "nobody"}).status_code, 429)


class HeadersTests(AppTestCase):
    def test_csp_and_security_headers(self):
        r = self.client.get(reverse("dashboard"))
        csp = r["Content-Security-Policy"]
        self.assertIn("default-src 'self'", csp)
        self.assertNotIn("unsafe-inline", csp)
        self.assertNotIn("unsafe-eval", csp)
        self.assertIn("frame-ancestors 'none'", csp)
        self.assertEqual(r["X-Frame-Options"], "DENY")
        self.assertEqual(r["X-Content-Type-Options"], "nosniff")
        self.assertEqual(r["Referrer-Policy"], "same-origin")
        self.assertIn("Permissions-Policy", r)

    def test_admin_gets_relaxed_style_only(self):
        r = self.client.get("/admin/login/")
        self.assertIn("style-src 'self' 'unsafe-inline'", r["Content-Security-Policy"])
        self.assertNotIn("script-src 'self' 'unsafe-inline'", r["Content-Security-Policy"])

    def test_api_responses_not_cached(self):
        self.assertIn("no-cache", self.client.get(reverse("api_summary"))["Cache-Control"])

    def test_cookies_flags(self):
        from django.conf import settings
        self.assertTrue(settings.SESSION_COOKIE_HTTPONLY)
        self.assertEqual(settings.SESSION_COOKIE_SAMESITE, "Lax")
        self.assertEqual(settings.X_FRAME_OPTIONS, "DENY")
        self.assertTrue(settings.SECURE_CONTENT_TYPE_NOSNIFF)


class AmountEdgeTests(AppTestCase):
    def test_huge_and_tiny_amounts(self):
        ok = self.post(reverse("api_transactions"), self.payload(amount="999999999.99", kind="income", category=self.cat(name="Salary").pk))
        self.assertEqual(ok.status_code, 201)
        self.assertEqual(self.post(reverse("api_transactions"), self.payload(amount="0.01")).status_code, 201)
        self.assertEqual(self.post(reverse("api_transactions"), self.payload(amount="1" * 40)).status_code, 422)
        self.assertEqual(self.post(reverse("api_transactions"), self.payload(name="x" * 121)).status_code, 422)
        self.assertEqual(self.post(reverse("api_transactions"), self.payload(note="x" * 1001)).status_code, 422)
        self.assertEqual(self.post(reverse("api_transactions"), self.payload(payee="x" * 81)).status_code, 422)

    def test_name_is_trimmed(self):
        r = self.post(reverse("api_transactions"), self.payload(name="   Tea   "))
        self.assertEqual(self.json(r)["transaction"]["name"], "Tea")
