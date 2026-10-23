import json
from decimal import Decimal

from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from app import backup, demo, services
from app.models import Budget, Category, LedgerEntry, MonthLock, Person, Transaction

from .base import AppTestCase, today


class BackupTests(AppTestCase):
    def populated(self):
        demo.seed_user(self.user)
        MonthLock.objects.create(user=self.user, month=services.add_months(today().replace(day=1), -5))

    def snapshot(self, user):
        data = backup.export_data(user)
        data.pop("exported_at")
        return data

    def test_export_restore_round_trip_is_lossless(self):
        self.populated()
        before = self.snapshot(self.user)
        raw = backup.dumps(self.user).encode()
        # wipe and restore into the same account
        parsed = backup.parse(raw)
        backup.restore(self.user, parsed)
        after = self.snapshot(self.user)
        for key in before:
            if key in ("transactions",):
                self.assertEqual(len(before[key]), len(after[key]))
                continue
            self.assertEqual(before[key], after[key], key)
        self.assertEqual(sorted((t["date"], t["name"], t["amount"]) for t in before["transactions"]),
                         sorted((t["date"], t["name"], t["amount"]) for t in after["transactions"]))

    def test_restore_into_another_account_keeps_balance(self):
        self.populated()
        balance = services.balance_for(self.user)
        backup.restore(self.other, backup.parse(backup.dumps(self.user).encode()))
        self.assertEqual(services.balance_for(self.other), balance)
        self.assertEqual(Transaction.objects.filter(user=self.user).count(), Transaction.objects.filter(user=self.other).count())

    def test_restore_replaces_existing_data_and_isolated(self):
        self.tx(name="old")
        self.tx(user=self.other, name="not mine")
        data = backup.dumps(self.other).encode()
        backup.restore(self.user, backup.parse(data))
        self.assertFalse(Transaction.objects.filter(user=self.user, name="old").exists())
        self.assertTrue(Transaction.objects.filter(user=self.other, name="not mine").exists())

    def test_split_groups_survive(self):
        base = Transaction(user=self.user, name="Market", date=today(), kind="expense", account=self.account())
        services.create_split(self.user, base, [(self.cat(), Decimal("3")), (self.cat(name="Health"), Decimal("2"))])
        backup.restore(self.user, backup.parse(backup.dumps(self.user).encode()))
        groups = set(Transaction.objects.filter(user=self.user).values_list("split_group", flat=True))
        self.assertEqual(len(groups), 1)
        self.assertNotIn(None, groups)

    def mutate(self, fn):
        data = backup.export_data(self.user)
        fn(data)
        return json.dumps(data, default=str).encode()

    def test_validation_rejects_bad_files(self):
        self.tx()
        cases = {
            "not json": b"{oops",
            "wrong format": json.dumps({"format": "x", "version": 1}).encode(),
            "wrong version": json.dumps({"format": backup.FORMAT, "version": 99}).encode(),
            "list": b"[]",
        }
        for label, raw in cases.items():
            with self.assertRaises(backup.BackupError, msg=label):
                backup.parse(raw)

        def amount(d): d["transactions"][0]["amount"] = "-5"
        def date(d): d["transactions"][0]["date"] = "junk"
        def cat(d): d["transactions"][0]["category"] = "Ghost"
        def acct(d): d["transactions"][0]["account"] = "Ghost"
        def kind(d): d["transactions"][0]["kind"] = "gift"
        def dup(d): d["categories"].append(dict(d["categories"][0]))
        def parent(d): d["categories"][0]["parent"] = "Nope"
        def tags(d): d["transactions"][0]["tags"] = "string"
        def big(d): d["transactions"][0]["amount"] = "99999999999999.00"
        def notlist(d): d["accounts"] = {"a": 1}
        def month(d): d["budgets"] = [{"category": None, "month": "2025-99", "amount": "5"}]
        for fn in (amount, date, cat, acct, kind, dup, parent, tags, big, notlist, month):
            with self.assertRaises(backup.BackupError, msg=fn.__name__):
                backup.parse(self.mutate(fn))

    def test_size_limit(self):
        with self.assertRaises(backup.BackupError):
            backup.parse(b" " * (backup.MAX_BYTES + 1))

    def test_problems_are_collected_not_just_first(self):
        self.tx()
        self.tx()

        def fn(d):
            for t in d["transactions"]:
                t["amount"] = "x"

        with self.assertRaises(backup.BackupError) as ctx:
            backup.parse(self.mutate(fn))
        self.assertGreaterEqual(len(ctx.exception.problems), 2)

    def test_failed_restore_changes_nothing(self):
        self.tx(name="keep me")
        parsed = backup.parse(backup.dumps(self.other).encode())
        parsed["transactions"] = [{"name": "x", "amount": Decimal("1"), "date": today(), "kind": "expense", "category": "Missing",
                                   "account": None, "payee": "", "note": "", "tags": [], "split_group": None, "reconciled": False}]
        with self.assertRaises(KeyError):
            backup.restore(self.user, parsed)
        self.assertTrue(Transaction.objects.filter(name="keep me").exists())

    def test_download_and_upload_views(self):
        self.tx(name="Tea")
        r = self.client.get(reverse("backup_export"))
        self.assertIn("application/json", r["Content-Type"])
        self.assertIn("attachment", r["Content-Disposition"])
        self.assertEqual(json.loads(r.content)["version"], 1)
        file = SimpleUploadedFile("b.json", r.content)
        r = self.client.post(reverse("backup"), {"file": file, "check": "1"})
        self.assertContains(r, "The file is valid")
        self.assertEqual(Transaction.objects.count(), 1)
        file = SimpleUploadedFile("b.json", self.client.get(reverse("backup_export")).content)
        r = self.client.post(reverse("backup"), {"file": file, "restore": "1"})
        self.assertContains(r, "Tick the box")
        file = SimpleUploadedFile("b.json", self.client.get(reverse("backup_export")).content)
        r = self.client.post(reverse("backup"), {"file": file, "restore": "1", "confirm": "on"})
        self.assertRedirects(r, reverse("dashboard"))

    def test_upload_errors(self):
        r = self.client.post(reverse("backup"), {"file": SimpleUploadedFile("b.json", b"nope"), "check": "1"})
        self.assertContains(r, "not a valid JSON")
        r = self.client.post(reverse("backup"), {"check": "1"})
        self.assertContains(r, "Choose a backup file")

    def test_users_cannot_download_each_others_backup(self):
        self.tx(user=self.other, name="OTHER-ONLY")
        self.assertNotIn(b"OTHER-ONLY", self.client.get(reverse("backup_export")).content)


class PeopleTests(AppTestCase):
    def entry(self, person, **data):
        base = {"kind": "lent", "amount": "100", "date": today().isoformat()}
        base.update(data)
        return self.post(reverse("api_person_entry", args=[person]), base)

    def person(self, name="Sita"):
        return self.json(self.post(reverse("api_people"), {"name": name}))["person"]["id"]

    def test_lend_borrow_and_repay(self):
        pid = self.person()
        self.assertEqual(self.json(self.entry(pid))["person"]["net"], "100.00")
        r = self.json(self.entry(pid, kind="paid_me", amount="40"))["person"]
        self.assertEqual((r["net"], r["direction"]), ("60.00", "owes_you"))
        r = self.json(self.entry(pid, kind="paid_me", amount="60"))["person"]
        self.assertEqual(r["direction"], "settled")
        r = self.json(self.entry(pid, kind="borrowed", amount="25"))["person"]
        self.assertEqual((r["net"], r["direction"]), ("-25.00", "you_owe"))

    def test_shared_bill_split(self):
        pid = self.person()
        # I paid a 90 bill, my share defaults to half -> they owe me 45
        self.assertEqual(self.json(self.entry(pid, kind="split_me", amount="", total="90"))["person"]["net"], "45.00")
        # they paid a 60 bill and my share is 20 -> I owe them 20
        r = self.json(self.entry(pid, kind="split_them", total="60", my_share="20"))["person"]
        self.assertEqual(r["net"], "25.00")

    def test_totals_and_listing(self):
        a, b = self.person("A"), self.person("B")
        self.entry(a, amount="100")
        self.entry(b, kind="borrowed", amount="30")
        data = self.json(self.client.get(reverse("api_people")))
        self.assertEqual((data["owed_to_you"], data["you_owe"]), ("100.00", "30.00"))
        self.assertEqual(len(data["people"][0]["entries"]) + len(data["people"][1]["entries"]), 2)

    def test_due_dates(self):
        pid = self.person()
        r = self.entry(pid, due_date=(today() + datetime_days(10)).isoformat())
        self.assertEqual(self.json(r)["person"]["next_due"], (today() + datetime_days(10)).isoformat())

    def test_validation(self):
        pid = self.person()
        for bad in ({"amount": "0"}, {"amount": "-5"}, {"amount": "abc"}, {"kind": "gift"}, {"amount": ""},
                    {"kind": "split_me", "total": "10", "my_share": "10", "amount": ""},
                    {"kind": "split_them", "total": "10", "my_share": "0", "amount": ""}):
            self.assertEqual(self.entry(pid, **bad).status_code, 422, bad)
        self.assertEqual(self.post(reverse("api_people"), {"name": "sita"}).status_code, 422)
        self.assertEqual(self.post(reverse("api_people"), {"name": ""}).status_code, 422)

    def test_rename_delete_and_entry_delete(self):
        pid = self.person()
        eid = self.json(self.entry(pid))["person"]["entries"][0]["id"]
        self.assertEqual(self.json(self.post(reverse("api_person", args=[pid]), {"name": "Sita D"}))["person"]["name"], "Sita D")
        self.assertEqual(self.delete(reverse("api_entry", args=[eid])).status_code, 200)
        self.assertEqual(self.delete(reverse("api_person", args=[pid])).status_code, 200)
        self.assertFalse(Person.objects.exists())

    def test_people_do_not_affect_balance(self):
        pid = self.person()
        self.entry(pid, amount="500")
        self.assertEqual(services.balance_for(self.user), Decimal("0.00"))

    def test_page_renders(self):
        self.assertContains(self.client.get(reverse("people")), "Debts and sharing")


def datetime_days(n):
    import datetime
    return datetime.timedelta(days=n)
