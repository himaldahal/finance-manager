import calendar
import datetime
from decimal import Decimal

from app import budgeting, services
from app.models import Budget, Category, Contribution, Goal, Transaction

from .base import AppTestCase, today


class BudgetMathTests(AppTestCase):
    def setUp(self):
        super().setUp()
        self.month = today().replace(day=1)

    def budget(self, category=None, amount="100", month=None, **kw):
        return Budget.objects.create(user=self.user, category=category, month=month or self.month, amount=Decimal(amount), **kw)

    def test_spent_percent_levels(self):
        self.budget(self.cat(), "100")
        self.tx(amount="50")
        item = budgeting.status(self.user, self.month)["categories"][0]
        self.assertEqual((item["spent"], item["remaining"], item["percent"], item["level"]), (Decimal("50.00"), Decimal("50.00"), 50.0, "ok"))
        self.tx(amount="35")
        self.assertEqual(budgeting.status(self.user, self.month)["categories"][0]["level"], "warn")
        self.tx(amount="20")
        item = budgeting.status(self.user, self.month)["categories"][0]
        self.assertEqual(item["level"], "over")
        self.assertTrue(item["over"])
        self.assertEqual(item["remaining"], Decimal("-5.00"))

    def test_custom_warn_threshold(self):
        self.budget(self.cat(), "100", warn_percent=50)
        self.tx(amount="55")
        self.assertEqual(budgeting.status(self.user, self.month)["categories"][0]["level"], "warn")

    def test_overall_budget_counts_everything(self):
        self.budget(None, "200")
        self.tx(amount="30")
        self.tx(amount="20", category=self.cat(name="Health"))
        self.tx(amount="999", kind="income")
        data = budgeting.status(self.user, self.month)
        self.assertEqual(data["overall"]["spent"], Decimal("50.00"))
        self.assertEqual(data["totals"]["all_spent"], Decimal("50.00"))

    def test_sub_category_rolls_up_into_parent(self):
        parent = self.cat()
        child = Category.objects.create(user=self.user, name="Snacks", parent=parent, kind="expense")
        self.budget(parent, "100")
        self.tx(amount="10", category=child)
        self.tx(amount="5", category=parent)
        self.assertEqual(budgeting.status(self.user, self.month)["categories"][0]["spent"], Decimal("15.00"))

    def test_other_months_and_users_do_not_count(self):
        self.budget(self.cat(), "100")
        self.tx(amount="40", date=services.add_months(self.month, -1))
        self.tx(user=self.other, amount="40")
        self.assertEqual(budgeting.status(self.user, self.month)["categories"][0]["spent"], Decimal("0.00"))

    def test_deleted_transactions_ignored(self):
        self.budget(self.cat(), "100")
        t = self.tx(amount="40")
        services.delete_transactions(self.user, Transaction.objects.filter(pk=t.pk))
        self.assertEqual(budgeting.status(self.user, self.month)["categories"][0]["spent"], Decimal("0.00"))

    def test_rollover_carries_unspent_money(self):
        prev = services.add_months(self.month, -1)
        self.budget(self.cat(), "100", month=prev, rollover=True)
        self.tx(amount="30", date=prev)
        self.budget(self.cat(), "100", rollover=True)
        item = budgeting.status(self.user, self.month)["categories"][0]
        self.assertEqual((item["carry"], item["available"]), (Decimal("70.00"), Decimal("170.00")))

    def test_rollover_chain_and_gap_reset(self):
        m1, m2 = services.add_months(self.month, -2), services.add_months(self.month, -1)
        self.budget(self.cat(), "100", month=m1, rollover=True)
        self.budget(self.cat(), "100", month=m2, rollover=True)
        self.budget(self.cat(), "100", rollover=True)
        self.assertEqual(budgeting.status(self.user, self.month)["categories"][0]["carry"], Decimal("200.00"))
        Budget.objects.filter(month=m2).delete()
        self.assertEqual(budgeting.status(self.user, self.month)["categories"][0]["carry"], Decimal("0.00"))

    def test_no_rollover_when_disabled(self):
        prev = services.add_months(self.month, -1)
        self.budget(self.cat(), "100", month=prev)
        self.budget(self.cat(), "100")
        self.assertEqual(budgeting.status(self.user, self.month)["categories"][0]["carry"], Decimal("0.00"))

    def test_projection_and_safe_per_day(self):
        days = calendar.monthrange(self.month.year, self.month.month)[1]
        mid = self.month.replace(day=10)
        self.budget(None, "3100")
        self.tx(amount="1000", date=mid)
        item = budgeting.status(self.user, self.month, today=mid)["overall"]
        self.assertEqual(item["projected"], (Decimal("1000") / 10 * days).quantize(Decimal("0.01")))
        left = days - 10 + 1
        self.assertEqual(item["safe_per_day"], (Decimal("2100") / left).quantize(Decimal("0.01")))
        self.assertEqual(item["projected_over"], item["projected"] > Decimal("3100"))

    def test_past_and_future_month_pace(self):
        past = services.add_months(self.month, -1)
        self.budget(None, "100", month=past)
        self.tx(amount="30", date=past)
        item = budgeting.status(self.user, past, today=today())["overall"]
        self.assertEqual((item["projected"], item["safe_per_day"]), (Decimal("30.00"), Decimal("0.00")))
        future = services.add_months(self.month, 1)
        self.budget(None, "310", month=future)
        item = budgeting.status(self.user, future, today=today())["overall"]
        self.assertEqual(item["projected"], Decimal("0.00"))
        self.assertGreater(item["safe_per_day"], 0)

    def test_weekly_breakdown(self):
        self.budget(None, "310")
        self.tx(amount="10", date=self.month.replace(day=2))
        self.tx(amount="20", date=self.month.replace(day=9))
        weekly = budgeting.status(self.user, self.month)["overall"]["weekly"]
        self.assertEqual(weekly[0], Decimal("10.00"))
        self.assertEqual(weekly[1], Decimal("20.00"))
        self.assertAlmostEqual(float(sum(budgeting.status(self.user, self.month)["overall"]["weekly_limit"])), 310.0, delta=0.1)

    def test_copy_month_skips_existing(self):
        self.budget(self.cat(), "100")
        self.budget(None, "500")
        target = services.add_months(self.month, 1)
        self.assertEqual(budgeting.copy_month(self.user, self.month, target), 2)
        self.assertEqual(budgeting.copy_month(self.user, self.month, target), 0)
        self.assertEqual(Budget.objects.filter(month=target).count(), 2)

    def test_history(self):
        self.budget(None, "100", month=services.add_months(self.month, -1))
        self.tx(amount="150", date=services.add_months(self.month, -1))
        rows = budgeting.history(self.user, 3)
        self.assertEqual(len(rows), 3)
        self.assertTrue(rows[1]["over"])
        self.assertEqual(rows[1]["percent"], 150.0)
        self.assertIsNone(rows[2]["limit"])

    def test_notifications(self):
        self.budget(self.cat(), "100")
        self.tx(amount="120")
        texts = [n["text"] for n in budgeting.notifications(self.user)]
        self.assertTrue(any("over budget" in t for t in texts))
        self.assertTrue(any("below zero" in t for t in texts))


class GoalMathTests(AppTestCase):
    def goal(self, target="1000", date=None):
        return Goal.objects.create(user=self.user, name="G", target_amount=Decimal(target), target_date=date)

    def test_progress_and_required_monthly(self):
        g = self.goal("1200", today() + datetime.timedelta(days=60))
        Contribution.objects.create(goal=g, amount=Decimal("200"))
        Contribution.objects.create(goal=g, amount=Decimal("-50"))
        info = budgeting.goal_summary(g)
        self.assertEqual((info["saved"], info["remaining"], info["percent"]), (Decimal("150.00"), Decimal("1050.00"), 12.5))
        self.assertEqual(info["required_monthly"], Decimal("525.00"))
        self.assertFalse(info["complete"])

    def test_complete_overdue_and_no_date(self):
        g = self.goal("100", today() - datetime.timedelta(days=5))
        self.assertTrue(budgeting.goal_summary(g)["overdue"])
        Contribution.objects.create(goal=g, amount=Decimal("100"))
        info = budgeting.goal_summary(g)
        self.assertTrue(info["complete"])
        self.assertFalse(info["overdue"])
        self.assertEqual(info["percent"], 100.0)
        self.assertIsNone(budgeting.goal_summary(self.goal())["required_monthly"])

    def test_percent_capped(self):
        g = self.goal("100")
        Contribution.objects.create(goal=g, amount=Decimal("250"))
        self.assertEqual(budgeting.goal_summary(g)["percent"], 100.0)
