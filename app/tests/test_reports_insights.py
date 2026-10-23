import datetime
from decimal import Decimal

from django.urls import reverse

from app import insights, nlq, reports, services
from app.models import Account, Category, Goal, LedgerEntry, Person, RecurringTransaction, Transaction, Transfer

from .base import AppTestCase, today


class ReportTests(AppTestCase):
    def setUp(self):
        super().setUp()
        self.month = today().replace(day=1)
        self.prev = services.add_months(self.month, -1)

    def build(self, start=None, end=None):
        return reports.build(self.user, start or self.month, end or services.month_end(self.month))

    def test_totals_reconcile_with_transactions(self):
        self.tx(amount="100", kind="income", date=self.month)
        self.tx(amount="30", date=self.month)
        self.tx(amount="20", category=self.cat(name="Health"), date=self.month)
        self.tx(amount="500", date=self.prev)
        data = self.build()
        s = data["statement"]
        self.assertEqual((s["income_total"], s["expense_total"], s["net"]), (Decimal("100.00"), Decimal("50.00"), Decimal("50.00")))
        self.assertEqual(sum(r["amount"] for r in s["expenses"]), s["expense_total"])
        self.assertEqual(sum(r["amount"] for r in data["categories"]), data["category_total"])
        self.assertEqual(s["previous"]["expense"], Decimal("500.00"))
        self.assertEqual(s["savings_rate"], 50.0)
        self.assertEqual(s["changes"]["expense"], -90.0)
        self.assertAlmostEqual(sum(r["share"] for r in data["categories"]), 100.0, delta=0.2)
        self.assertEqual(data["trend"][0]["net"], Decimal("50.00"))

    def test_transfers_do_not_appear_as_income_or_expense(self):
        b = Account.objects.create(user=self.user, name="Cash", type="cash")
        services.create_transfer(Transfer(user=self.user, from_account=self.account(), to_account=b, amount=Decimal("40"), date=today()))
        data = self.build()
        self.assertEqual((data["statement"]["income_total"], data["statement"]["expense_total"]), (0, 0))
        flow = {r["name"]: r for r in data["cash_flow"]}
        self.assertEqual(flow["Cash"]["transfers_in"], Decimal("40.00"))
        self.assertEqual(flow["Main account"]["transfers_out"], Decimal("40.00"))
        self.assertEqual(sum(r["closing"] for r in data["cash_flow"]), services.balance_for(self.user))

    def test_cash_flow_closing_matches_account_balances(self):
        self.tx(amount="100", kind="income", date=self.prev)
        self.tx(amount="30", date=self.month)
        data = self.build()
        flow = data["cash_flow"][0]
        self.assertEqual((flow["opening"], flow["inflow"], flow["outflow"]), (Decimal("100.00"), Decimal("0.00"), Decimal("30.00")))
        self.assertEqual(flow["closing"], services.account_balances(self.user)[self.account().pk])

    def test_net_worth_series_ends_at_balance(self):
        self.tx(amount="100", kind="income", date=self.prev)
        self.tx(amount="30", date=self.month)
        data = self.build(self.prev, services.month_end(self.month))
        self.assertEqual([r["balance"] for r in data["net_worth"]], [Decimal("100.00"), Decimal("70.00")])

    def test_payees_and_tags(self):
        t = self.tx(amount="9", payee="Shop", date=self.month)
        services.save_transaction(t, tags=["x"])
        self.tx(amount="1", payee="Shop", date=self.month)
        data = self.build()
        self.assertEqual(data["payees"][0], {"name": "Shop", "amount": Decimal("10.00"), "count": 2})
        self.assertEqual(data["tags"][0]["name"], "x")
        self.assertEqual(data["tags"][0]["expense"], Decimal("9.00"))

    def test_other_users_excluded(self):
        self.tx(user=self.other, amount="999", payee="Secret", date=self.month)
        data = self.build()
        self.assertEqual(data["statement"]["expense_total"], 0)
        self.assertEqual(data["payees"], [])

    def test_yearly_granularity_for_long_ranges(self):
        data = reports.build(self.user, datetime.date(2020, 1, 1), datetime.date(2025, 12, 31))
        self.assertTrue(data["yearly"])

    def test_resolve_period_presets(self):
        t = datetime.date(2025, 5, 15)
        self.assertEqual(reports.resolve_period("last_month", None, None, t)[1:], (datetime.date(2025, 4, 1), datetime.date(2025, 4, 30)))
        self.assertEqual(reports.resolve_period("quarter", None, None, t)[1:], (datetime.date(2025, 4, 1), datetime.date(2025, 6, 30)))
        self.assertEqual(reports.resolve_period("year", None, None, t)[1:], (datetime.date(2025, 1, 1), datetime.date(2025, 12, 31)))
        self.assertEqual(reports.resolve_period("last_year", None, None, t)[1:], (datetime.date(2024, 1, 1), datetime.date(2024, 12, 31)))
        self.assertEqual(reports.resolve_period("custom", datetime.date(2025, 3, 5), datetime.date(2025, 3, 1), t)[1:],
                         (datetime.date(2025, 3, 1), datetime.date(2025, 3, 5)))
        self.assertEqual(reports.resolve_period("junk", None, None, t)[0], "this_month")
        self.assertEqual(reports.previous_range(datetime.date(2025, 3, 1), datetime.date(2025, 3, 31)),
                         (datetime.date(2025, 1, 29), datetime.date(2025, 2, 28)))

    def test_report_page_and_every_csv_export(self):
        self.tx(amount="30", payee="P", date=self.month)
        self.assertContains(self.client.get(reverse("reports")), "Income statement")
        self.assertEqual(self.client.get(reverse("reports"), {"preset": "year"}).status_code, 200)
        self.assertEqual(self.client.get(reverse("reports"), {"preset": "custom", "start": "junk", "end": "x"}).status_code, 200)
        for name, _ in reports.REPORTS:
            r = self.client.get(reverse("report_export"), {"report": name, "start": self.month.isoformat(), "end": today().isoformat(), "preset": "custom"})
            self.assertEqual(r.status_code, 200, name)
            text = b"".join(r.streaming_content).decode("utf-8-sig")
            self.assertGreaterEqual(len(text.splitlines()), 1, name)
            self.assertIn("attachment", r["Content-Disposition"])
        self.assertEqual(self.client.get(reverse("report_export"), {"report": "nope"}).status_code, 404)

    def test_csv_values_match_page_totals(self):
        self.tx(amount="30", date=self.month)
        text = b"".join(self.client.get(reverse("report_export"), {"report": "income_statement"}).streaming_content).decode("utf-8-sig")
        self.assertIn("Total expenses,30.00", text)
        self.assertIn("Net,Net income,-30.00", text)

    def test_print_stylesheet_and_markup(self):
        html = self.client.get(reverse("reports")).content.decode()
        self.assertIn("data-print", html)
        self.assertIn("no-print", html)
        from django.contrib.staticfiles import finders
        self.assertIn("@media print", open(finders.find("app/css/app.css"), encoding="utf-8").read())

    def test_change_helper(self):
        self.assertIsNone(reports.change(Decimal("5"), Decimal("0")))
        self.assertEqual(reports.change(Decimal("150"), Decimal("100")), 50.0)


class InsightTests(AppTestCase):
    def setUp(self):
        super().setUp()
        self.month = today().replace(day=1)

    def test_unusual_spending_flagged(self):
        for i in (1, 2, 3):
            self.tx(amount="100", date=services.add_months(self.month, -i))
        self.tx(amount="400", date=self.month)
        found = insights.unusual(self.user, today())
        self.assertEqual(found[0]["name"], "Groceries")
        self.assertEqual(found[0]["percent"], 400)
        self.tx(user=self.other, amount="9999", date=self.month)
        self.assertEqual(len(insights.unusual(self.user, today())), 1)

    def test_unusual_not_flagged_when_normal(self):
        for i in (1, 2, 3):
            self.tx(amount="100", date=services.add_months(self.month, -i))
        self.tx(amount="120", date=self.month)
        self.assertEqual(insights.unusual(self.user, today()), [])

    def test_subscription_detector(self):
        for i in range(4):
            self.tx(amount="9.99", name="Streaming", payee="NetStream", date=services.add_months(self.month, -i).replace(day=3))
        self.tx(amount="50", name="One off", date=self.month)
        self.tx(amount="10", name="Wobbly", date=services.add_months(self.month, -1))
        self.tx(amount="40", name="Wobbly", date=services.add_months(self.month, -2))
        self.tx(amount="90", name="Wobbly", date=services.add_months(self.month, -3))
        subs = insights.subscriptions(self.user, today())
        self.assertEqual([s["name"] for s in subs], ["NetStream"])
        self.assertFalse(subs[0]["tracked"])
        RecurringTransaction.objects.create(user=self.user, name="Streaming", amount=Decimal("9.99"), kind="expense",
                                            category=self.cat(), start_date=today(), next_due=today(), account=self.account())
        self.assertTrue(insights.subscriptions(self.user, today())[0]["tracked"])

    def test_two_a_month_is_not_a_subscription_but_three_per_month_neither(self):
        for i in range(4):
            for d in (2, 3, 4):
                self.tx(amount="5", name="Coffee", date=services.add_months(self.month, -i).replace(day=d))
        self.assertEqual(insights.subscriptions(self.user, today()), [])

    def test_movers(self):
        prev = services.add_months(self.month, -1)
        self.tx(amount="10", date=prev)
        self.tx(amount="50", date=self.month)
        self.tx(amount="80", category=self.cat(name="Health"), date=prev)
        m = insights.movers(self.user, today())
        self.assertEqual(m["up"][0]["name"], "Groceries")
        self.assertEqual(m["up"][0]["change"], Decimal("40.00"))

    def test_bills_due_soon_and_overdue(self):
        RecurringTransaction.objects.create(user=self.user, name="Rent", amount=Decimal("5"), kind="expense", category=self.cat(),
                                            start_date=today(), next_due=today() + datetime.timedelta(days=2), account=self.account())
        RecurringTransaction.objects.create(user=self.user, name="Later", amount=Decimal("5"), kind="expense", category=self.cat(),
                                            start_date=today(), next_due=today() + datetime.timedelta(days=40), account=self.account())
        RecurringTransaction.objects.create(user=self.other, name="Foreign", amount=Decimal("5"), kind="expense", category=self.cat(self.other),
                                            start_date=today(), next_due=today(), account=self.account(self.other))
        bills = insights.bills(self.user, today())
        self.assertEqual([b["name"] for b in bills], ["Rent"])
        texts = [s["text"] for s in insights.sentences(self.user, today())]
        self.assertTrue(any("Rent" in t and "due in 2 days" in t for t in texts))

    def test_debt_due_appears_in_bills(self):
        p = Person.objects.create(user=self.user, name="Sita")
        LedgerEntry.objects.create(person=p, kind="lent", amount=Decimal("100"), date=today(), due_date=today() + datetime.timedelta(days=3))
        bills = insights.bills(self.user, today())
        self.assertEqual(bills[0]["type"], "debt")
        self.assertIn("owes you", bills[0]["name"])

    def test_sentences_in_plain_language(self):
        from app.models import Budget
        Budget.objects.create(user=self.user, category=self.cat(), month=self.month, amount=Decimal("100"))
        self.tx(amount="62", date=today())
        texts = [s["text"] for s in insights.sentences(self.user, today())]
        self.assertTrue(any(t.startswith("You have spent 62% of your Groceries budget with") for t in texts), texts)
        self.tx(amount="60", date=today())
        texts = [s["text"] for s in insights.sentences(self.user, today())]
        self.assertTrue(any("over your Groceries budget by" in t for t in texts), texts)

    def test_vs_last_month_sentence(self):
        prev = services.add_months(self.month, -1)
        self.tx(amount="100", date=prev.replace(day=1))
        self.tx(amount="50", date=today())
        texts = [s["text"] for s in insights.sentences(self.user, today())]
        self.assertTrue(any("less than at this point last month" in t for t in texts), texts)

    def test_goal_progress_and_endpoint(self):
        g = Goal.objects.create(user=self.user, name="Trip", target_amount=Decimal("100"))
        g.contributions.create(amount=Decimal("25"))
        self.assertEqual(insights.goal_progress(self.user)[0]["percent"], 25.0)
        data = self.json(self.client.get(reverse("api_insights")))
        for key in ("sentences", "movers", "subscriptions", "bills", "goals", "secondary"):
            self.assertIn(key, data)

    def test_weekly_digest(self):
        self.tx(amount="40", date=today())
        self.tx(amount="10", date=today() - datetime.timedelta(days=8))
        d = insights.weekly_digest(self.user, today())
        self.assertEqual((d["expense"], d["prev_expense"], d["expense_change"]), (Decimal("40.00"), Decimal("10.00"), 300))
        self.assertEqual(d["biggest"].amount, Decimal("40.00"))
        self.assertEqual(d["categories"][0]["total"], Decimal("40.00"))


class NaturalLanguageTests(AppTestCase):
    def parse(self, q, today_=datetime.date(2025, 6, 15)):
        cats = [{"id": 1, "name": "Groceries"}, {"id": 2, "name": "Dining out / Coffee"}]
        return nlq.parse(q, cats, [{"id": 7, "name": "Cash"}], [{"id": 9, "name": "work"}], today_)

    def test_category_date_amount(self):
        params, parts = self.parse("groceries last month over 500")
        self.assertEqual(params["category"], "1")
        self.assertEqual((params["date_from"], params["date_to"]), ("2025-05-01", "2025-05-31"))
        self.assertEqual(params["min_amount"], "500")
        self.assertNotIn("q", params)
        self.assertIn("last month", parts)

    def test_ranges_and_types(self):
        self.assertEqual(self.parse("spent this year")[0]["type"], "expense")
        self.assertEqual(self.parse("income in march")[0]["date_from"], "2025-03-01")
        self.assertEqual(self.parse("coffee in december")[0]["date_from"], "2024-12-01")
        self.assertEqual(self.parse("anything in july 2023")[0]["date_to"], "2023-07-31")
        self.assertEqual(self.parse("yesterday")[0]["date_from"], "2025-06-14")
        self.assertEqual(self.parse("last week")[0]["date_from"], "2025-06-02")
        self.assertEqual(self.parse("this week")[0]["date_from"], "2025-06-09")
        self.assertEqual(self.parse("today")[0]["date_to"], "2025-06-15")

    def test_amount_phrases(self):
        self.assertEqual(self.parse("under 1,000")[0]["max_amount"], "1000")
        self.assertEqual(self.parse("less than 20.5")[0]["max_amount"], "20.5")
        p = self.parse("between 10 and 5")[0]
        self.assertEqual((p["min_amount"], p["max_amount"]), ("5", "10"))
        self.assertEqual(self.parse("more than 99")[0]["min_amount"], "99")

    def test_free_text_tags_accounts_notes(self):
        p, _ = self.parse("uber #work cash with notes")
        self.assertEqual((p["q"], p["tag"], p["account"], p["has_notes"]), ("uber", "9", "7", "1"))

    def test_subcategory_and_prefix_match(self):
        self.assertEqual(self.parse("coffee")[0]["category"], "2")
        self.assertEqual(self.parse("groc")[0]["category"], "1")

    def test_plain_text_is_not_structured(self):
        p, parts = self.parse("hello world")
        self.assertEqual(p, {"q": "hello world"})

    def test_filters_work_end_to_end(self):
        prev = services.add_months(today().replace(day=1), -1)
        self.tx(amount="600", date=prev)
        self.tx(amount="50", date=prev)
        self.tx(amount="700", date=today())
        url = self.json(self.client.get(reverse("api_search"), {"q": "groceries last month over 500"}))["groups"][0]["items"][0]["url"]
        self.assertEqual(self.json(self.client.get(url.replace("/transactions/", reverse("api_transactions"))))["count"], 1)
