import datetime
from decimal import Decimal

from django.test import override_settings
from django.urls import reverse

from app import services
from app.models import Account, Category, CategoryRule, Contribution, Goal, SavedView, Tag, Transaction

from .base import AppTestCase, today


class TransactionApiTests(AppTestCase):
    def test_create_and_list(self):
        r = self.post(reverse("api_transactions"), self.payload(tags=["work", "lunch"], payee="Cafe"))
        self.assertEqual(r.status_code, 201)
        data = self.json(r)
        self.assertEqual(data["transaction"]["amount"], "12.50")
        self.assertEqual(sorted(data["transaction"]["tags"]), ["lunch", "work"])
        self.assertEqual(data["balance"], "-12.50")
        self.assertIn("warning", data)
        listing = self.json(self.client.get(reverse("api_transactions")))
        self.assertEqual(listing["count"], 1)
        self.assertEqual(listing["totals"]["expense"], "12.50")

    def test_form_encoded_create(self):
        r = self.client.post(reverse("api_transactions"), {"name": "Tea", "amount": "3", "date": today().isoformat(),
                                                           "kind": "expense", "category": self.cat().pk})
        self.assertEqual(r.status_code, 201)

    def test_validation_errors_are_field_keyed(self):
        r = self.post(reverse("api_transactions"), self.payload(amount="-5", name=""))
        self.assertEqual(r.status_code, 422)
        errors = self.json(r)["errors"]
        self.assertIn("amount", errors)
        self.assertIn("name", errors)

    def test_rejects_bad_amounts(self):
        for bad in ("0", "-1", "abc", "1e9", "1000000000", "12.345", "NaN", "Infinity", ""):
            r = self.post(reverse("api_transactions"), self.payload(amount=bad))
            self.assertEqual(r.status_code, 422, bad)
        self.assertEqual(Transaction.objects.count(), 0)

    def test_rejects_bad_dates(self):
        far = (today() + datetime.timedelta(days=90)).isoformat()
        for bad in ("1900-01-01", far, "not-a-date", ""):
            self.assertEqual(self.post(reverse("api_transactions"), self.payload(date=bad)).status_code, 422, bad)

    def test_category_rules_fill_blank_category(self):
        CategoryRule.objects.create(user=self.user, pattern="bhat", category=self.cat(name="Groceries"))
        r = self.post(reverse("api_transactions"), self.payload(name="Bhat Bhateni run", category=""))
        self.assertEqual(r.status_code, 201)
        self.assertEqual(self.json(r)["transaction"]["category"]["name"], "Groceries")

    def test_blank_category_without_rule_is_an_error(self):
        r = self.post(reverse("api_transactions"), self.payload(category=""))
        self.assertEqual(r.status_code, 422)
        self.assertIn("category", self.json(r)["errors"])

    def test_category_kind_mismatch(self):
        r = self.post(reverse("api_transactions"), self.payload(category=self.cat(name="Salary").pk))
        self.assertEqual(r.status_code, 422)

    def test_malformed_json(self):
        r = self.client.post(reverse("api_transactions"), "{not json", content_type="application/json")
        self.assertEqual(r.status_code, 400)
        r = self.client.post(reverse("api_transactions"), "[1]", content_type="application/json")
        self.assertEqual(r.status_code, 400)

    def test_oversized_body(self):
        r = self.client.post(reverse("api_transactions"), '{"name": "' + "x" * 70000 + '"}', content_type="application/json")
        self.assertEqual(r.status_code, 413)

    def test_update_and_delete_and_restore(self):
        t = self.tx(amount="5")
        url = reverse("api_transaction", args=[t.pk])
        r = self.post(url, self.payload(amount="9.00", name="Changed"))
        self.assertEqual(r.status_code, 200)
        t.refresh_from_db()
        self.assertEqual((t.amount, t.name), (Decimal("9.00"), "Changed"))
        self.assertEqual(self.delete(url).status_code, 200)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.post(reverse("api_transaction_restore", args=[t.pk])).status_code, 200)
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_update_keeps_tags_when_omitted(self):
        t = self.tx()
        services.save_transaction(t, tags=["keep"])
        payload = self.payload()
        payload.pop("tags")
        self.post(reverse("api_transaction", args=[t.pk]), payload)
        self.assertEqual([x.name for x in t.tags.all()], ["keep"])

    @override_settings(ALLOW_NEGATIVE_BALANCE=False)
    def test_overdraft_returns_clear_422_not_silent(self):
        r = self.post(reverse("api_transactions"), self.payload(amount="50"))
        self.assertEqual(r.status_code, 422)
        self.assertIn("below zero", self.json(r)["message"])
        self.assertEqual(Transaction.objects.count(), 0)

    def test_filters_sort_pagination(self):
        for i in range(30):
            self.tx(amount=str(i + 1), name=f"Item {i}")
        self.tx(amount="500", kind="income", name="Pay", payee="Acme", note="bonus")
        r = self.json(self.client.get(reverse("api_transactions"), {"page_size": 10, "sort": "amount"}))
        self.assertEqual(len(r["transactions"]), 10)
        self.assertEqual(r["pages"], 4)
        self.assertEqual(r["transactions"][0]["amount"], "1.00")
        for query, expected in (({"type": "income"}, 1), ({"q": "Acme"}, 1), ({"min_amount": 25}, 7), ({"max_amount": 3}, 3),
                                ({"has_notes": 1}, 1), ({"payee": "acme"}, 1), ({"date_from": today().isoformat()}, 31),
                                ({"date_to": "2000-01-01"}, 0), ({"category": self.cat(name="Salary").pk}, 1)):
            self.assertEqual(self.json(self.client.get(reverse("api_transactions"), query))["count"], expected, query)

    def test_invalid_filter_values_are_ignored(self):
        self.tx()
        r = self.client.get(reverse("api_transactions"), {"min_amount": "x", "date_from": "bad", "sort": "evil", "page": "-3",
                                                          "page_size": "9999", "type": "zzz", "category": "q"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.json(r)["count"], 1)
        self.assertEqual(self.json(r)["page_size"], 25)

    def test_tag_and_account_filters(self):
        t = self.tx()
        services.save_transaction(t, tags=["x"])
        self.tx(name="no tag")
        tag = Tag.objects.get(user=self.user)
        self.assertEqual(self.json(self.client.get(reverse("api_transactions"), {"tag": tag.pk}))["count"], 1)
        other_account = Account.objects.create(user=self.user, name="Cash", type="cash")
        self.assertEqual(self.json(self.client.get(reverse("api_transactions"), {"account": other_account.pk}))["count"], 0)

    def test_bulk_actions(self):
        a, b = self.tx(), self.tx()
        url = reverse("api_transactions_bulk")
        health = self.cat(name="Health")
        self.assertEqual(self.post(url, {"action": "category", "ids": [a.pk, b.pk], "category": health.pk}).status_code, 200)
        self.assertEqual(Transaction.objects.filter(category=health).count(), 2)
        self.assertEqual(self.post(url, {"action": "reconcile", "ids": [a.pk]}).status_code, 200)
        a.refresh_from_db()
        self.assertTrue(a.reconciled)
        self.assertEqual(self.post(url, {"action": "delete", "ids": [a.pk, b.pk]}).status_code, 200)
        self.assertEqual(Transaction.objects.count(), 0)
        self.assertEqual(self.post(url, {"action": "restore", "ids": [a.pk, b.pk]}).status_code, 200)
        self.assertEqual(Transaction.objects.count(), 2)

    def test_bulk_validation(self):
        url = reverse("api_transactions_bulk")
        self.assertEqual(self.post(url, {"action": "nuke", "ids": [1]}).status_code, 400)
        self.assertEqual(self.post(url, {"action": "delete", "ids": []}).status_code, 400)
        self.assertEqual(self.post(url, {"action": "delete", "ids": ["x"]}).status_code, 400)
        self.assertEqual(self.post(url, {"action": "delete", "ids": list(range(600))}).status_code, 400)
        t = self.tx()
        salary = self.cat(name="Salary")
        self.assertEqual(self.post(url, {"action": "category", "ids": [t.pk], "category": salary.pk}).status_code, 422)
        self.assertEqual(self.post(url, {"action": "category", "ids": [t.pk], "category": ""}).status_code, 422)

    def test_split(self):
        r = self.post(reverse("api_transaction_split"), {
            "name": "Market", "date": today().isoformat(), "kind": "expense", "amount": "50",
            "splits": [{"category": self.cat(name="Groceries").pk, "amount": "30"}, {"category": self.cat(name="Health").pk, "amount": "20"}]})
        self.assertEqual(r.status_code, 201)
        self.assertEqual(len(self.json(r)["transactions"]), 2)
        self.assertTrue(all(t["split"] for t in self.json(r)["transactions"]))

    def test_split_validation(self):
        url = reverse("api_transaction_split")
        base = {"name": "M", "date": today().isoformat(), "kind": "expense"}
        g = self.cat(name="Groceries").pk
        self.assertEqual(self.post(url, {**base, "splits": [{"category": g, "amount": "5"}]}).status_code, 422)
        self.assertEqual(self.post(url, {**base, "amount": "99", "splits": [{"category": g, "amount": "5"}, {"category": g, "amount": "5"}]}).status_code, 422)
        self.assertEqual(self.post(url, {**base, "splits": [{"category": g, "amount": "-5"}, {"category": g, "amount": "5"}]}).status_code, 422)
        foreign = self.cat(self.other).pk
        self.assertEqual(self.post(url, {**base, "splits": [{"category": foreign, "amount": "5"}, {"category": g, "amount": "5"}]}).status_code, 422)
        self.assertEqual(Transaction.objects.count(), 0)

    def test_history_and_activity(self):
        t = self.tx()
        services.save_transaction(t)
        t.name = "Renamed"
        services.save_transaction(t)
        data = self.json(self.client.get(reverse("api_transaction_history", args=[t.pk])))
        self.assertTrue(any(e["action"] == "updated" for e in data["entries"]))
        self.assertTrue(self.json(self.client.get(reverse("api_activity")))["entries"])

    def test_trash_endpoints(self):
        t = self.tx()
        self.delete(reverse("api_transaction", args=[t.pk]))
        data = self.json(self.client.get(reverse("api_trash")))
        self.assertEqual(len(data["transactions"]), 1)
        self.assertEqual(data["transactions"][0]["days_left"], 30)
        self.assertEqual(self.delete(reverse("api_trash_item", args=[t.pk])).status_code, 200)
        self.assertFalse(Transaction.all_objects.filter(pk=t.pk).exists())
        t2 = self.tx()
        self.delete(reverse("api_transaction", args=[t2.pk]))
        self.assertEqual(self.json(self.post(reverse("api_trash_empty")))["removed"], 1)

    def test_reconcile_endpoint(self):
        t = self.tx(amount="40", kind="income")
        self.post(reverse("api_transactions_bulk"), {"action": "reconcile", "ids": [t.pk]})
        data = self.json(self.client.get(reverse("api_reconcile"), {"account": self.account().pk}))
        self.assertEqual(data["cleared"], "40.00")
        self.assertEqual(data["unreconciled"], 0)
        self.assertEqual(self.client.get(reverse("api_reconcile"), {"account": "zz"}).status_code, 404)


class CategoryApiTests(AppTestCase):
    def test_crud(self):
        r = self.post(reverse("api_categories"), {"name": "Pets", "kind": "expense", "color": "teal", "icon": "paw-print"})
        self.assertEqual(r.status_code, 201)
        pk = self.json(r)["category"]["id"]
        r = self.post(reverse("api_category", args=[pk]), {"name": "Pet care", "kind": "expense", "color": "blue", "icon": "tag"})
        self.assertEqual(self.json(r)["category"]["name"], "Pet care")
        self.assertEqual(self.delete(reverse("api_category", args=[pk])).status_code, 200)

    def test_duplicate_names_case_insensitive(self):
        r = self.post(reverse("api_categories"), {"name": " groceries ", "kind": "both", "color": "gray", "icon": "tag"})
        self.assertEqual(r.status_code, 422)
        self.assertIn("already", self.json(r)["errors"]["name"][0])

    def test_invalid_color_icon_kind(self):
        for bad in ({"color": "neon"}, {"icon": "skull"}, {"kind": "x"}):
            data = {"name": "Z", "kind": "both", "color": "gray", "icon": "tag", **bad}
            self.assertEqual(self.post(reverse("api_categories"), data).status_code, 422, bad)

    def test_sub_category_rules(self):
        parent = self.cat(name="Groceries")
        r = self.post(reverse("api_categories"), {"name": "Snacks", "kind": "expense", "color": "gray", "icon": "tag", "parent": parent.pk})
        self.assertEqual(r.status_code, 201)
        child = self.json(r)["category"]
        self.assertEqual(child["full_name"], "Groceries / Snacks")
        # a grandchild is not allowed, nor making a parent a child
        r = self.post(reverse("api_categories"), {"name": "Deep", "kind": "expense", "color": "gray", "icon": "tag", "parent": child["id"]})
        self.assertEqual(r.status_code, 422)
        r = self.post(reverse("api_category", args=[parent.pk]), {"name": "Groceries", "kind": "both", "color": "gray", "icon": "tag",
                                                                  "parent": self.cat(name="Rent").pk})
        self.assertEqual(r.status_code, 422)

    def test_cannot_use_other_users_parent(self):
        r = self.post(reverse("api_categories"), {"name": "X", "kind": "both", "color": "gray", "icon": "tag", "parent": self.cat(self.other).pk})
        self.assertEqual(r.status_code, 422)

    def test_kind_change_blocked_when_conflicting(self):
        cat = self.cat(name="Other")
        self.tx(category=cat, kind="income")
        r = self.post(reverse("api_category", args=[cat.pk]), {"name": "Other", "kind": "expense", "color": "gray", "icon": "tag"})
        self.assertEqual(r.status_code, 422)

    def test_delete_requires_reassign_when_used(self):
        cat = self.cat()
        t = self.tx(category=cat)
        url = reverse("api_category", args=[cat.pk])
        self.assertEqual(self.delete(url).status_code, 409)
        target = self.cat(name="Health")
        self.assertEqual(self.delete(url + f"?reassign_to={target.pk}").status_code, 200)
        t.refresh_from_db()
        self.assertEqual(t.category, target)

    def test_delete_reassign_validation(self):
        cat = self.cat()
        self.tx(category=cat)
        url = reverse("api_category", args=[cat.pk])
        self.assertEqual(self.delete(url + f"?reassign_to={cat.pk}").status_code, 422)
        self.assertEqual(self.delete(url + f"?reassign_to={self.cat(self.other).pk}").status_code, 422)
        self.assertEqual(self.delete(url + "?reassign_to=abc").status_code, 422)
        income_only = self.cat(name="Salary")
        self.assertEqual(self.delete(url + f"?reassign_to={income_only.pk}").status_code, 422)

    def test_delete_unused_removes_trashed_rows(self):
        cat = self.cat()
        t = self.tx(category=cat)
        services.delete_transactions(self.user, Transaction.objects.filter(pk=t.pk))
        self.assertEqual(self.delete(reverse("api_category", args=[cat.pk])).status_code, 200)
        self.assertFalse(Transaction.all_objects.filter(pk=t.pk).exists())

    def test_usage_counts(self):
        self.tx()
        self.tx()
        rows = {c["name"]: c for c in self.json(self.client.get(reverse("api_categories")))["categories"]}
        self.assertEqual(rows["Groceries"]["count"], 2)


class AccountApiTests(AppTestCase):
    def test_crud_and_balances(self):
        r = self.post(reverse("api_accounts"), {"name": "Cash", "type": "cash", "opening_balance": "250.50"})
        self.assertEqual(r.status_code, 201)
        data = self.json(self.client.get(reverse("api_accounts")))
        self.assertEqual(data["total"], "250.50")
        pk = [a for a in data["accounts"] if a["name"] == "Cash"][0]["id"]
        r = self.post(reverse("api_account", args=[pk]), {"name": "Pocket", "type": "wallet", "opening_balance": "0", "archived": True})
        self.assertTrue(self.json(r)["account"]["archived"])
        self.assertEqual(self.delete(reverse("api_account", args=[pk])).status_code, 200)

    def test_duplicate_and_busy_and_last_account(self):
        self.assertEqual(self.post(reverse("api_accounts"), {"name": "main ACCOUNT", "type": "bank"}).status_code, 422)
        acct = self.account()
        self.tx()
        self.assertEqual(self.delete(reverse("api_account", args=[acct.pk])).status_code, 409)
        Transaction.all_objects.all().delete()
        self.assertEqual(self.delete(reverse("api_account", args=[acct.pk])).status_code, 409)  # the last one

    def test_transfers(self):
        a = self.account()
        b = Account.objects.create(user=self.user, name="Cash", type="cash")
        r = self.post(reverse("api_transfers"), {"from_account": a.pk, "to_account": b.pk, "amount": "25", "date": today().isoformat()})
        self.assertEqual(r.status_code, 201)
        pk = self.json(r)["transfer"]["id"]
        self.assertEqual(services.balance_for(self.user), Decimal("0.00"))
        self.assertEqual(services.account_balances(self.user)[b.pk], Decimal("25.00"))
        self.assertEqual(self.delete(reverse("api_transfer", args=[pk])).status_code, 200)
        same = self.post(reverse("api_transfers"), {"from_account": a.pk, "to_account": a.pk, "amount": "1", "date": today().isoformat()})
        self.assertEqual(same.status_code, 422)
        foreign = self.account(self.other)
        bad = self.post(reverse("api_transfers"), {"from_account": a.pk, "to_account": foreign.pk, "amount": "1", "date": today().isoformat()})
        self.assertEqual(bad.status_code, 422)

    def test_transfers_are_not_income_or_expense(self):
        a = self.account()
        b = Account.objects.create(user=self.user, name="Cash", type="cash")
        self.post(reverse("api_transfers"), {"from_account": a.pk, "to_account": b.pk, "amount": "25", "date": today().isoformat()})
        summary = self.json(self.client.get(reverse("api_summary")))
        self.assertEqual((summary["income"], summary["expense"]), ("0.00", "0.00"))


class RulesTagsViewsApiTests(AppTestCase):
    def test_rules_crud_and_suggest(self):
        r = self.post(reverse("api_rules"), {"pattern": "uber", "category": self.cat(name="Transport").pk, "priority": 5, "active": True})
        self.assertEqual(r.status_code, 201)
        pk = self.json(r)["rule"]["id"]
        s = self.json(self.client.get(reverse("api_rule_suggest"), {"text": "Uber trip", "kind": "expense"}))
        self.assertEqual(s["category"]["name"], "Transport")
        self.assertIsNone(self.json(self.client.get(reverse("api_rule_suggest"), {"text": "nothing"}))["category"])
        r = self.post(reverse("api_rule", args=[pk]), {"pattern": "lyft", "category": self.cat(name="Transport").pk})
        self.assertEqual(self.json(r)["rule"]["pattern"], "lyft")
        self.assertEqual(self.post(reverse("api_rules"), {"pattern": "x", "category": self.cat(name="Transport").pk}).status_code, 422)
        self.assertEqual(self.delete(reverse("api_rule", args=[pk])).status_code, 200)

    def test_tags(self):
        t = self.tx()
        services.save_transaction(t, tags=["a"])
        tag = Tag.objects.get()
        self.assertEqual(self.json(self.client.get(reverse("api_tags")))["tags"][0]["count"], 1)
        self.assertEqual(self.post(reverse("api_tag", args=[tag.pk]), {"name": "b"}).status_code, 200)
        self.assertEqual(self.post(reverse("api_tag", args=[tag.pk]), {"name": ""}).status_code, 422)
        Tag.objects.create(user=self.user, name="dup")
        self.assertEqual(self.post(reverse("api_tag", args=[tag.pk]), {"name": "DUP"}).status_code, 422)
        self.assertEqual(self.delete(reverse("api_tag", args=[tag.pk])).status_code, 200)

    def test_tag_limits(self):
        r = self.post(reverse("api_transactions"), self.payload(tags=[f"t{i}" for i in range(11)]))
        self.assertEqual(r.status_code, 422)
        r = self.post(reverse("api_transactions"), self.payload(tags=["x" * 31]))
        self.assertEqual(r.status_code, 422)

    def test_suggest(self):
        self.tx(payee="Bhat Bhateni")
        self.tx(payee="Bhat Bhateni")
        services.save_transaction(self.tx(), tags=["weekend"])
        self.assertEqual(self.json(self.client.get(reverse("api_suggest"), {"type": "payee", "q": "bhat"}))["items"], ["Bhat Bhateni"])
        self.assertEqual(self.json(self.client.get(reverse("api_suggest"), {"type": "tag", "q": "week"}))["items"], ["weekend"])
        self.assertEqual(self.client.get(reverse("api_suggest"), {"type": "zzz"}).status_code, 400)

    def test_saved_views(self):
        r = self.post(reverse("api_views"), {"name": "Big food", "query": "?type=expense&min_amount=500"})
        self.assertEqual(r.status_code, 201)
        views = self.json(r)["views"]
        self.assertEqual(views[0]["query"], "type=expense&min_amount=500")
        self.assertEqual(self.post(reverse("api_views"), {"name": "big food", "query": ""}).status_code, 422)
        self.assertEqual(self.delete(reverse("api_view", args=[views[0]["id"]])).status_code, 200)


class BudgetGoalApiTests(AppTestCase):
    def test_budget_upsert_overall_and_copy(self):
        month = today().strftime("%Y-%m")
        r = self.post(reverse("api_budgets"), {"category": self.cat().pk, "month": month, "amount": "100", "rollover": True, "warn_percent": 70})
        self.assertEqual(r.status_code, 201)
        self.assertEqual(self.json(r)["budgets"][0]["warn_percent"], 70)
        r = self.post(reverse("api_budgets"), {"category": "", "month": month, "amount": "500"})
        self.assertEqual(self.json(r)["overall"]["limit"], "500.00")
        r = self.post(reverse("api_budgets"), {"category": self.cat().pk, "month": month, "amount": "150"})
        self.assertEqual(len(self.json(r)["budgets"]), 1)
        self.assertEqual(self.json(r)["budgets"][0]["limit"], "150.00")
        nxt = services.add_months(today().replace(day=1), 1).strftime("%Y-%m")
        r = self.post(reverse("api_budget_copy"), {"from": month, "to": nxt})
        self.assertEqual(self.json(r)["copied"], 2)
        r = self.post(reverse("api_budget_copy"), {"from": month, "to": nxt})
        self.assertEqual(self.json(r)["copied"], 0)
        self.assertEqual(self.post(reverse("api_budget_copy"), {"from": month, "to": month}).status_code, 400)

    def test_budget_validation(self):
        month = today().strftime("%Y-%m")
        for data in ({"category": self.cat(name="Salary").pk, "month": month, "amount": "5"},
                     {"category": self.cat().pk, "month": "2025-13", "amount": "5"},
                     {"category": self.cat().pk, "month": month, "amount": "0"},
                     {"category": self.cat().pk, "month": month, "amount": "5", "warn_percent": 100},
                     {"category": self.cat(self.other).pk, "month": month, "amount": "5"}):
            self.assertEqual(self.post(reverse("api_budgets"), data).status_code, 422, data)

    def test_budget_history(self):
        r = self.json(self.client.get(reverse("api_budget_history"), {"months": 3}))
        self.assertEqual(len(r["months"]), 3)
        self.assertEqual(len(self.json(self.client.get(reverse("api_budget_history"), {"months": "x"}))["months"]), 12)

    def test_goals_and_contributions(self):
        r = self.post(reverse("api_goals"), {"name": "Laptop", "target_amount": "1000", "target_date": (today() + datetime.timedelta(days=100)).isoformat()})
        self.assertEqual(r.status_code, 201)
        pk = self.json(r)["goal"]["id"]
        r = self.post(reverse("api_goal_contribute", args=[pk]), {"amount": "250", "date": today().isoformat()})
        goal = self.json(r)["goal"]
        self.assertEqual(goal["saved"], "250.00")
        self.assertEqual(goal["percent"], 25.0)
        self.assertEqual(goal["required_monthly"], "187.50")
        self.assertEqual(self.post(reverse("api_goal_contribute", args=[pk]), {"amount": "-500", "date": today().isoformat()}).status_code, 422)
        self.assertEqual(self.post(reverse("api_goal_contribute", args=[pk]), {"amount": "0", "date": today().isoformat()}).status_code, 422)
        cid = Contribution.objects.get().pk
        self.assertEqual(self.delete(reverse("api_contribution", args=[cid])).status_code, 200)
        self.assertEqual(self.post(reverse("api_goal", args=[pk]), {"name": "MacBook", "target_amount": "2000"}).status_code, 200)
        self.assertEqual(self.delete(reverse("api_goal", args=[pk])).status_code, 200)

    def test_goal_validation(self):
        r = self.post(reverse("api_goals"), {"name": "", "target_amount": "-1"})
        self.assertEqual(r.status_code, 422)
        r = self.post(reverse("api_goals"), {"name": "x", "target_amount": "5", "account": self.account(self.other).pk})
        self.assertEqual(r.status_code, 422)


class RecurringApiTests(AppTestCase):
    def data(self, **kw):
        d = {"name": "Rent", "amount": "20", "kind": "expense", "category": self.cat(name="Rent").pk, "frequency": "monthly",
             "start_date": (today() - datetime.timedelta(days=70)).isoformat()}
        d.update(kw)
        return d

    def test_create_backfills_and_is_idempotent(self):
        r = self.post(reverse("api_recurring"), self.data())
        self.assertEqual(r.status_code, 201)
        count = Transaction.objects.filter(name="Rent").count()
        self.assertGreaterEqual(count, 2)
        self.assertEqual(services.apply_due(self.user), 0)
        self.assertEqual(Transaction.objects.filter(name="Rent").count(), count)

    def test_toggle_edit_delete(self):
        r = self.post(reverse("api_recurring"), self.data(start_date=today().isoformat()))
        pk = self.json(r)["item"]["id"]
        t = self.json(self.post(reverse("api_recurring_toggle", args=[pk])))["item"]
        self.assertFalse(t["active"])
        t = self.json(self.post(reverse("api_recurring_toggle", args=[pk])))["item"]
        self.assertTrue(t["active"])
        self.assertGreater(t["next_due"], today().isoformat())
        r = self.post(reverse("api_recurring_item", args=[pk]), self.data(name="Rent 2", start_date=today().isoformat()))
        self.assertEqual(self.json(r)["item"]["name"], "Rent 2")
        self.assertEqual(self.delete(reverse("api_recurring_item", args=[pk])).status_code, 200)

    def test_validation(self):
        self.assertEqual(self.post(reverse("api_recurring"), self.data(end_date="2000-01-01")).status_code, 422)
        self.assertEqual(self.post(reverse("api_recurring"), self.data(frequency="daily")).status_code, 422)
        self.assertEqual(self.post(reverse("api_recurring"), self.data(category=self.cat(self.other, "Rent").pk)).status_code, 422)


class SummaryAnalyticsApiTests(AppTestCase):
    def test_summary(self):
        self.tx(amount="100", kind="income")
        self.tx(amount="40", kind="expense")
        data = self.json(self.client.get(reverse("api_summary")))
        self.assertEqual(data["balance"], "60.00")
        self.assertEqual(data["savings_rate"], 60.0)
        self.assertFalse(data["overdrawn"])
        self.assertEqual(self.json(self.client.get(reverse("api_summary"), {"month": "garbage"}))["month"], today().strftime("%Y-%m"))

    def test_analytics_payload(self):
        self.tx(amount="40", payee="Shop")
        data = self.json(self.client.get(reverse("api_analytics")))
        for key in ("monthly", "categories", "trend", "stacked", "daily", "weekday", "heatmap", "cumulative", "budget_vs_actual", "payees", "top", "goals"):
            self.assertIn(key, data)
        self.assertEqual(len(data["monthly"]), 12)
        self.assertEqual(data["categories"][0]["total"], "40.00")
        self.assertEqual(data["payees"][0]["name"], "Shop")

    def test_analytics_range_and_filters(self):
        t = self.tx(amount="40")
        services.save_transaction(t, tags=["x"])
        tag = Tag.objects.get()
        r = self.client.get(reverse("api_analytics"), {"start": "2000-01-01", "end": today().isoformat(), "tag": tag.pk, "category": self.cat().pk})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.client.get(reverse("api_analytics"), {"start": "1990-01-01"}).status_code, 422)
        self.assertEqual(self.client.get(reverse("api_analytics"), {"category": self.cat(self.other).pk}).status_code, 404)
        self.assertEqual(self.client.get(reverse("api_analytics"), {"tag": 99999}).status_code, 404)

    def test_notifications_and_onboarding(self):
        n = self.json(self.client.get(reverse("api_notifications")))
        self.assertEqual(n["count"], 0)
        o = self.json(self.client.get(reverse("api_onboarding")))
        self.assertTrue(o["can_load_sample"])
        self.assertFalse(o["dismissed"])
        self.assertTrue(self.json(self.post(reverse("api_onboarding")))["dismissed"])

    def test_sample_data_only_for_empty_account(self):
        r = self.post(reverse("api_sample_data"))
        self.assertEqual(r.status_code, 201)
        self.assertGreater(Transaction.objects.filter(user=self.user).count(), 50)
        self.assertEqual(self.post(reverse("api_sample_data")).status_code, 409)
        self.assertEqual(Transaction.objects.filter(user=self.other).count(), 0)

    def test_search(self):
        t = self.tx(name="Quarterly invoice", payee="Acme Ltd", amount="500")
        services.save_transaction(t, tags=["clientwork"])
        Goal.objects.create(user=self.user, name="Acme fund", target_amount=Decimal("10"))
        types = {g["type"] for g in self.json(self.client.get(reverse("api_search"), {"q": "acme"}))["groups"]}
        self.assertTrue({"Transactions", "Payees", "Goals"} <= types)
        self.assertEqual(self.json(self.client.get(reverse("api_search"), {"q": "a"}))["groups"], [])
        tags = {g["type"] for g in self.json(self.client.get(reverse("api_search"), {"q": "clientw"}))["groups"]}
        self.assertIn("Tags", tags)

    def test_natural_language_search_builds_filter_link(self):
        groups = self.json(self.client.get(reverse("api_search"), {"q": "groceries last month over 500"}))["groups"]
        self.assertEqual(groups[0]["type"], "Filter transactions")
        url = groups[0]["items"][0]["url"]
        self.assertIn("min_amount=500", url)
        self.assertIn("category=", url)
        self.assertIn("date_from=", url)
