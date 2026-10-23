import datetime
import re
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, override_settings
from django.urls import reverse

from app import services
from app.models import Account, Budget, Category, MonthLock, Profile, Transaction

from .base import AppTestCase, PASSWORD, today

User = get_user_model()


class PageTests(AppTestCase):
    def test_every_page_renders(self):
        for name in ("dashboard", "transactions", "accounts", "categories", "budgets", "goals", "recurring", "analytics", "reports",
                     "settings", "import", "trash", "people", "backup", "digest"):
            r = self.client.get(reverse(name))
            self.assertEqual(r.status_code, 200, name)
            self.assertContains(r, 'lang="en"')
            self.assertContains(r, 'id="main"')
            self.assertContains(r, "Skip to content")

    def test_logout_form_is_post_with_csrf(self):
        html = self.client.get(reverse("dashboard")).content.decode()
        self.assertRegex(html, r'<form method="post" action="/logout/">\s*<input type="hidden" name="csrfmiddlewaretoken"')

    def test_money_template_uses_profile(self):
        profile = services.get_profile(self.user)
        profile.currency_symbol, profile.number_format = "$", "intl"
        profile.save()
        services.forget_profile(self.user)
        self.tx(amount="1234.5")
        self.assertContains(self.client.get(reverse("transactions")), "-$1,234.50")

    def test_transactions_page_filters_and_fragment(self):
        for i in range(30):
            self.tx(amount=str(i + 1), name=f"Thing {i}")
        r = self.client.get(reverse("transactions"), {"q": "Thing 1", "page_size": 10})
        self.assertEqual(r.context["paginator"].count, 11)
        r = self.client.get(reverse("transactions"), {"fragment": "1", "sort": "amount"})
        self.assertNotContains(r, "<html")
        self.assertContains(r, 'id="results-inner"')
        self.assertContains(r, 'aria-sort="ascending"')
        self.assertContains(self.client.get(reverse("transactions"), {"page": 2}), "Previous")

    def test_empty_states(self):
        self.assertContains(self.client.get(reverse("transactions")), "No transactions yet")
        self.tx()
        self.assertContains(self.client.get(reverse("transactions"), {"q": "zzzz"}), "No matching transactions")

    def test_dashboard_applies_due_recurring(self):
        from app.models import RecurringTransaction
        RecurringTransaction.objects.create(user=self.user, name="Gym", amount=Decimal("5"), kind="expense", category=self.cat(),
                                            start_date=today(), next_due=today(), account=self.account())
        self.client.get(reverse("dashboard"))
        self.assertTrue(Transaction.objects.filter(name="Gym").exists())

    def test_digest_and_analytics_filters_markup(self):
        self.assertContains(self.client.get(reverse("analytics")), 'id="r-category"')
        self.assertContains(self.client.get(reverse("digest")), "Weekly digest")


class SidebarMarkupTests(AppTestCase):
    def test_sidebar_markup_and_attributes(self):
        html = self.client.get(reverse("dashboard")).content.decode()
        self.assertIn('id="sidebar"', html)
        self.assertRegex(html, r'id="nav-toggle"[^>]*aria-controls="sidebar"[^>]*aria-expanded="false"')
        self.assertRegex(html, r'id="sidebar-collapse"[^>]*aria-controls="sidebar"[^>]*aria-expanded="true"')
        self.assertIn('aria-label="Collapse sidebar"', html)
        self.assertIn('class="scrim"', html)
        self.assertIn("sidebar-init.js", html)
        for key in ("money", "plan", "reports", "settings"):
            self.assertRegex(html, rf'data-group="{key}"')
            self.assertRegex(html, rf'aria-controls="grp-{key}"')
            self.assertIn(f'id="grp-{key}"', html)

    def test_links_have_text_and_tooltip_for_rail(self):
        html = self.client.get(reverse("transactions")).content.decode()
        self.assertRegex(html, r'<a href="/transactions/" aria-current="page" data-tip="Transactions">.*?<span class="nav-text">Transactions</span></a>')
        self.assertIn('data-tip="Sign out"', html)

    def test_at_most_seven_top_level_items(self):
        html = self.client.get(reverse("dashboard")).content.decode()
        nav = html[html.index('<nav class="nav"'):html.index("</nav>")]
        top_links = len(re.findall(r'^\s{8}<a ', nav, re.M))
        groups = len(re.findall(r'class="nav-group"', nav))
        self.assertLessEqual(top_links + groups, 7)

    def test_help_dialog_lists_sidebar_shortcut(self):
        self.assertContains(self.client.get(reverse("dashboard")), "<kbd>[</kbd>")

    def test_bottom_nav_and_fab(self):
        html = self.client.get(reverse("dashboard")).content.decode()
        self.assertIn('class="bottom-nav"', html)
        self.assertIn('class="fab"', html)

    def test_static_assets_exist(self):
        from django.contrib.staticfiles import finders
        for path in ("app/js/sidebar-init.js", "app/js/layout.js", "app/css/app.css", "app/icons/sprite.svg", "app/icons/LICENSE",
                     "app/js/password.js", "app/js/register.js", "app/js/common-passwords.js"):
            self.assertIsNotNone(finders.find(path), path)

    def test_css_has_collapsed_and_drawer_rules(self):
        from django.contrib.staticfiles import finders
        css = open(finders.find("app/css/app.css"), encoding="utf-8").read()
        self.assertIn('html[data-sidebar="collapsed"]', css)
        self.assertIn("html:not(.js) .sidebar", css)
        self.assertIn("prefers-reduced-motion", css)
        js = open(finders.find("app/js/layout.js"), encoding="utf-8").read()
        for needle in ("localStorage", "inert", "Escape", "aria-expanded", "event.key === '['"):
            self.assertIn(needle, js)

    def test_icon_tag(self):
        from django.template import Context, Template
        out = Template('{% icon "wallet" %}{% icon "nope" %}').render(Context())
        self.assertIn('href="/static/app/icons/sprite.svg#wallet"', out)
        self.assertEqual(out.count("<svg"), 1)


class SettingsPageTests(AppTestCase):
    def valid(self, **kw):
        d = {"display_name": "Alice Smith", "currency_code": "usd", "currency_symbol": "$", "number_format": "indian",
             "allow_negative_balance": "no", "secondary_currency_code": "", "secondary_rate": ""}
        d.update(kw)
        return d

    def test_save_settings(self):
        r = self.client.post(reverse("settings"), self.valid())
        self.assertRedirects(r, reverse("settings"))
        profile = Profile.objects.get(user=self.user)
        self.assertEqual((profile.currency_code, profile.number_format, profile.allow_negative_balance), ("USD", "indian", False))
        self.user.refresh_from_db()
        self.assertEqual((self.user.first_name, self.user.last_name), ("Alice", "Smith"))

    def test_single_word_display_name(self):
        self.client.post(reverse("settings"), self.valid(display_name="Cher"))
        self.user.refresh_from_db()
        self.assertEqual((self.user.first_name, self.user.last_name), ("Cher", ""))

    def test_validation(self):
        for bad in ({"currency_code": "US"}, {"currency_code": "12$"}, {"currency_symbol": "a b"}, {"number_format": "zz"},
                    {"secondary_currency_code": "EUR"}, {"secondary_rate": "2"}, {"secondary_currency_code": "EU", "secondary_rate": "1"}):
            r = self.client.post(reverse("settings"), self.valid(**bad))
            self.assertEqual(r.status_code, 200, bad)
            self.assertTrue(r.context["form"].errors, bad)

    def test_secondary_currency(self):
        self.client.post(reverse("settings"), self.valid(secondary_currency_code="eur", secondary_rate="0.0071"))
        profile = Profile.objects.get(user=self.user)
        self.assertEqual(profile.secondary_currency_code, "EUR")
        self.assertEqual(profile.secondary_rate, Decimal("0.0071"))
        self.assertEqual(self.json(self.client.get(reverse("api_summary")))["secondary"]["code"], "EUR")

    def test_change_password(self):
        r = self.client.post(reverse("change_password"), {"old_password": PASSWORD, "new_password1": "new-Secret-pass-99", "new_password2": "new-Secret-pass-99"})
        self.assertRedirects(r, reverse("settings"))
        self.assertEqual(self.client.get(reverse("settings")).status_code, 200)  # session kept
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("new-Secret-pass-99"))

    def test_change_password_errors_are_inline(self):
        r = self.client.post(reverse("change_password"), {"old_password": "bad", "new_password1": "short", "new_password2": "short"})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "field-error")
        self.assertNotContains(r, "<ul><li>Your password")

    def test_password_fields_markup(self):
        html = self.client.get(reverse("settings")).content.decode()
        self.assertEqual(html.count("data-pw-toggle"), 3)
        self.assertIn('aria-pressed="false"', html)
        self.assertIn('aria-label="Show password"', html)
        self.assertIn("data-strength", html)
        self.assertIn('data-match="id_new_password1"', html)
        self.assertIn('data-min-length="10"', html)
        self.assertNotIn("Your password can’t be too similar", html)
        self.assertNotIn("Your password must contain at least", html)

    def test_lock_and_reopen_month(self):
        month = today().strftime("%Y-%m")
        self.client.post(reverse("lock_month"), {"month": month, "action": "close"})
        self.assertTrue(MonthLock.objects.filter(user=self.user).exists())
        self.assertContains(self.client.get(reverse("settings")), "Reopen")
        r = self.post(reverse("api_transactions"), self.payload())
        self.assertEqual(r.status_code, 422)
        self.assertIn("closed", self.json(r)["message"])
        self.client.post(reverse("lock_month"), {"month": month, "action": "reopen"})
        self.assertFalse(MonthLock.objects.exists())
        self.assertEqual(self.post(reverse("api_transactions"), self.payload()).status_code, 201)

    def test_lock_validation(self):
        self.client.post(reverse("lock_month"), {"month": "junk", "action": "close"})
        future = services.add_months(today().replace(day=1), 3).strftime("%Y-%m")
        self.client.post(reverse("lock_month"), {"month": future, "action": "close"})
        self.assertFalse(MonthLock.objects.exists())

    def test_closed_month_blocks_bulk_and_delete_and_transfers(self):
        t = self.tx()
        MonthLock.objects.create(user=self.user, month=today().replace(day=1))
        self.assertEqual(self.delete(reverse("api_transaction", args=[t.pk])).status_code, 422)
        r = self.post(reverse("api_transactions_bulk"), {"action": "category", "ids": [t.pk], "category": self.cat(name="Health").pk})
        self.assertEqual(r.status_code, 422)

    def test_erase_data_needs_confirmation(self):
        self.tx()
        self.client.post(reverse("erase_data"), {"confirm": "no", "password": PASSWORD})
        self.assertEqual(Transaction.objects.count(), 1)
        self.client.post(reverse("erase_data"), {"confirm": "ERASE", "password": "wrong"})
        self.assertEqual(Transaction.objects.count(), 1)
        self.client.post(reverse("erase_data"), {"confirm": "ERASE", "password": PASSWORD})
        self.assertEqual(Transaction.objects.count(), 0)
        self.assertTrue(self.user.categories.exists())
        self.assertTrue(User.objects.filter(pk=self.user.pk).exists())
        self.assertTrue(Account.objects.filter(user=self.user).exists())

    def test_delete_account(self):
        self.tx()
        self.client.post(reverse("delete_account"), {"confirm": "wrong", "password": PASSWORD})
        self.assertTrue(User.objects.filter(pk=self.user.pk).exists())
        self.client.post(reverse("delete_account"), {"confirm": "alice", "password": PASSWORD})
        self.assertFalse(User.objects.filter(pk=self.user.pk).exists())
        self.assertEqual(Transaction.all_objects.filter(user=self.user.pk).count(), 0)
        self.assertTrue(User.objects.filter(pk=self.other.pk).exists())
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 302)


class WelcomeFlowTests(AppTestCase):
    def setUp(self):
        super().setUp()
        self.newbie = self.make_user("newbie", setup=False)
        self.client.force_login(self.newbie)

    def form(self, **kw):
        d = {"currency_code": "npr", "currency_symbol": "Rs", "number_format": "indian", "main_name": "Everyday", "main_opening": "1500",
             "cash": "on", "cash_opening": "200", "categories": ["Groceries", "Salary", "Rent"], "monthly_budget": "30000"}
        d.update(kw)
        return d

    def test_dashboard_redirects_until_setup(self):
        self.assertRedirects(self.client.get(reverse("dashboard")), reverse("welcome"))

    def test_setup_flow_ends_on_dashboard_with_data(self):
        r = self.client.post(reverse("welcome"), self.form())
        self.assertRedirects(r, reverse("dashboard"))
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 200)
        names = set(self.newbie.categories.values_list("name", flat=True))
        self.assertEqual(names, {"Groceries", "Salary", "Rent"})
        accounts = {a.name: a.opening_balance for a in self.newbie.accounts.all()}
        self.assertEqual(accounts, {"Everyday": Decimal("1500.00"), "Cash": Decimal("200.00")})
        self.assertEqual(Budget.objects.get(user=self.newbie).amount, Decimal("30000.00"))
        self.assertEqual(services.balance_for(self.newbie), Decimal("1700.00"))
        self.assertEqual(self.json(self.client.get(reverse("api_summary")))["balance"], "1700.00")

    def test_sample_data_option(self):
        self.client.post(reverse("welcome"), self.form(sample_data="on"))
        self.assertGreater(Transaction.objects.filter(user=self.newbie).count(), 50)
        self.assertTrue(services.get_profile(self.newbie).setup_done)
        self.assertEqual(Transaction.objects.filter(user=self.user).count(), 0)

    def test_skip(self):
        self.client.post(reverse("welcome"), {"skip": "1"})
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 200)
        self.assertTrue(self.newbie.categories.exists())

    def test_validation_errors_shown(self):
        r = self.client.post(reverse("welcome"), self.form(currency_code="x", main_name=""))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "field-error")
        self.assertFalse(services.get_profile(self.newbie).setup_done)

    def test_existing_data_kept_categories_in_use_not_deleted(self):
        t = self.tx(user=self.newbie, category=self.cat(self.newbie, "Dining out"))
        self.client.post(reverse("welcome"), self.form(categories=["Salary"]))
        self.assertTrue(Category.objects.filter(user=self.newbie, name="Dining out").exists())


class TrashAndDigestPageTests(AppTestCase):
    def test_trash_page_and_flow(self):
        t = self.tx(name="Gone")
        self.delete(reverse("api_transaction", args=[t.pk]))
        self.assertEqual(self.client.get(reverse("trash")).status_code, 200)
        self.assertEqual(Transaction.objects.count(), 0)

    def test_digest_numbers(self):
        self.tx(amount="40")
        self.tx(amount="100", kind="income")
        r = self.client.get(reverse("digest"))
        self.assertEqual(r.context["d"]["expense"], Decimal("40.00"))
        self.assertEqual(r.context["d"]["count"], 2)
