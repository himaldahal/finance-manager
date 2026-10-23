import datetime
import io
from decimal import Decimal

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import override_settings
from django.urls import reverse

from app import csvio, services
from app.models import Account, Category, CategoryRule, RecurringTransaction, Tag, Transaction

from .base import AppTestCase, today


class RecurringTests(AppTestCase):
    def item(self, **kw):
        d = dict(user=self.user, name="Rent", amount=Decimal("10"), kind="expense", category=self.cat(name="Rent"),
                 frequency="monthly", start_date=datetime.date(2025, 1, 31), next_due=datetime.date(2025, 1, 31), account=self.account())
        d.update(kw)
        return RecurringTransaction.objects.create(**d)

    def test_monthly_clamps_to_month_end_without_drift(self):
        item = self.item()
        services.apply_recurring_item(item, today=datetime.date(2025, 5, 1))
        dates = list(Transaction.objects.filter(recurring=item).order_by("date").values_list("date", flat=True))
        self.assertEqual(dates, [datetime.date(2025, 1, 31), datetime.date(2025, 2, 28), datetime.date(2025, 3, 31), datetime.date(2025, 4, 30)])
        item.refresh_from_db()
        self.assertEqual(item.next_due, datetime.date(2025, 5, 31))

    def test_weekly(self):
        item = self.item(frequency="weekly", start_date=datetime.date(2025, 1, 1), next_due=datetime.date(2025, 1, 1))
        self.assertEqual(services.apply_recurring_item(item, today=datetime.date(2025, 1, 22)), 4)

    def test_idempotent_and_command(self):
        item = self.item(start_date=today() - datetime.timedelta(days=65), next_due=today() - datetime.timedelta(days=65))
        out = io.StringIO()
        call_command("apply_recurring", stdout=out)
        count = Transaction.objects.filter(recurring=item).count()
        self.assertGreaterEqual(count, 2)
        self.assertIn("Created", out.getvalue())
        call_command("apply_recurring", stdout=io.StringIO())
        self.assertEqual(Transaction.objects.filter(recurring=item).count(), count)

    def test_paused_items_skipped_and_end_date_deactivates(self):
        paused = self.item(name="P", active=False, next_due=today())
        self.assertEqual(services.apply_recurring_item(paused, today=today()), 0)
        ending = self.item(name="E", start_date=datetime.date(2025, 1, 1), next_due=datetime.date(2025, 1, 1), end_date=datetime.date(2025, 2, 15))
        services.apply_recurring_item(ending, today=datetime.date(2025, 6, 1))
        ending.refresh_from_db()
        self.assertFalse(ending.active)
        self.assertEqual(Transaction.objects.filter(recurring=ending).count(), 2)

    def test_deleted_occurrence_is_not_recreated(self):
        item = self.item(start_date=today() - datetime.timedelta(days=40), next_due=today() - datetime.timedelta(days=40))
        services.apply_recurring_item(item)
        t = Transaction.objects.filter(recurring=item).first()
        services.delete_transactions(self.user, Transaction.objects.filter(pk=t.pk))
        item.next_due = t.date
        item.save()
        services.apply_recurring_item(item)
        self.assertEqual(Transaction.all_objects.filter(recurring=item, recurring_date=t.date).count(), 1)
        self.assertFalse(Transaction.objects.filter(pk=t.pk).exists())

    @override_settings(ALLOW_NEGATIVE_BALANCE=False)
    def test_overdraft_recorded_not_silently_dropped(self):
        item = self.item(next_due=today(), start_date=today())
        services.apply_due(self.user)
        item.refresh_from_db()
        self.assertEqual(item.next_due, today())  # will retry later
        self.assertIn("below zero", item.last_error)
        self.assertEqual(Transaction.objects.count(), 0)

    def test_first_due_on_or_after(self):
        item = self.item()
        self.assertEqual(services.first_due_on_or_after(item, datetime.date(2025, 3, 1)), datetime.date(2025, 3, 31))
        weekly = self.item(frequency="weekly", start_date=datetime.date(2025, 1, 1))
        self.assertEqual(services.first_due_on_or_after(weekly, datetime.date(2025, 1, 9)), datetime.date(2025, 1, 15))

    def test_edit_schedule_recomputes_next_due(self):
        r = self.post(reverse("api_recurring"), {"name": "X", "amount": "1", "kind": "expense", "category": self.cat().pk,
                                                 "frequency": "monthly", "start_date": today().isoformat()})
        pk = self.json(r)["item"]["id"]
        r = self.post(reverse("api_recurring_item", args=[pk]), {"name": "X", "amount": "1", "kind": "expense", "category": self.cat().pk,
                                                                 "frequency": "weekly", "start_date": today().isoformat()})
        self.assertEqual(self.json(r)["item"]["frequency"], "weekly")
        self.assertEqual(self.json(r)["item"]["next_due"], (today() + datetime.timedelta(days=7)).isoformat())

    def test_purge_runs_with_command(self):
        t = self.tx()
        Transaction.all_objects.filter(pk=t.pk).update(deleted_at=datetime.datetime(2020, 1, 1, tzinfo=datetime.timezone.utc))
        out = io.StringIO()
        call_command("apply_recurring", stdout=out)
        self.assertFalse(Transaction.all_objects.filter(pk=t.pk).exists())


class ExportTests(AppTestCase):
    def read(self, **params):
        r = self.client.get(reverse("export"), params)
        self.assertIn("text/csv", r["Content-Type"])
        self.assertIn("attachment", r["Content-Disposition"])
        return b"".join(r.streaming_content).decode("utf-8")

    def test_bom_and_header_and_filters(self):
        self.tx(amount="5", name="Keep", payee="Shop")
        self.tx(amount="7", name="Skip")
        text = self.read(q="Keep")
        self.assertTrue(text.startswith("﻿"))
        lines = text.strip().splitlines()
        self.assertEqual(lines[0].lstrip("﻿"), ",".join(csvio.HEADER))
        self.assertEqual(len(lines), 2)
        self.assertIn("Keep", lines[1])
        self.assertFalse(self.read(bom="0").startswith("﻿"))

    def test_export_respects_all_filters(self):
        self.tx(amount="5", kind="income", name="Pay")
        self.tx(amount="500", name="Big")
        self.assertEqual(len(self.read(type="income").strip().splitlines()), 2)
        self.assertEqual(len(self.read(min_amount="100").strip().splitlines()), 2)

    def test_export_includes_tags_and_account(self):
        t = self.tx()
        services.save_transaction(t, tags=["a", "b"])
        self.assertIn("a; b", self.read())
        self.assertIn("Main account", self.read())


class ImportTests(AppTestCase):
    HEADER = "date,type,name,category,amount,payee,account,tags,note\n"

    def upload(self, text, name="data.csv"):
        return self.client.post(reverse("import"), {"file": SimpleUploadedFile(name, text.encode("utf-8"))})

    def row(self, **kw):
        d = {"date": today().isoformat(), "type": "expense", "name": "Tea", "category": "Groceries", "amount": "5.00", "payee": "", "account": "", "tags": "", "note": ""}
        d.update(kw)
        return ",".join(f'"{d[k]}"' for k in ("date", "type", "name", "category", "amount", "payee", "account", "tags", "note")) + "\n"

    def confirm(self, **extra):
        token = self.client.session["import_preview"]["token"]
        return self.client.post(reverse("import_confirm"), {"token": token, **extra})

    def test_preview_then_import(self):
        r = self.upload(self.HEADER + self.row() + self.row(name="Coffee", amount="3.50", tags="x;y", payee="Cafe"))
        self.assertRedirects(r, reverse("import"))
        page = self.client.get(reverse("import"))
        self.assertEqual(page.context["n_valid"], 2)
        self.assertEqual(Transaction.objects.count(), 0)  # nothing saved by the preview
        self.assertRedirects(self.confirm(skip_duplicates="on"), reverse("transactions"))
        self.assertEqual(Transaction.objects.count(), 2)
        t = Transaction.objects.get(name="Coffee")
        self.assertEqual((t.payee, sorted(x.name for x in t.tags.all())), ("Cafe", ["x", "y"]))
        self.assertNotIn("import_preview", self.client.session)

    def test_row_errors_reported_and_not_imported(self):
        self.upload(self.HEADER + self.row(amount="-5") + self.row(date="31/12/2025") + self.row(type="transfer") + self.row(amount="1.234")
                    + self.row(name="") + self.row(amount="1e9") + self.row(account="Nope") + self.row())
        page = self.client.get(reverse("import"))
        self.assertEqual((page.context["n_valid"], page.context["n_error"]), (1, 7))
        self.confirm()
        self.assertEqual(Transaction.objects.count(), 1)

    def test_duplicates_detected_in_db_and_file(self):
        self.tx(amount="5.00", name="Tea")
        self.upload(self.HEADER + self.row() + self.row(name="New") + self.row(name="New"))
        page = self.client.get(reverse("import"))
        self.assertEqual((page.context["n_valid"], page.context["n_duplicate"]), (1, 2))
        self.confirm(skip_duplicates="on")
        self.assertEqual(Transaction.objects.count(), 2)

    def test_duplicates_can_be_imported_on_request(self):
        self.tx(amount="5.00", name="Tea")
        self.upload(self.HEADER + self.row())
        self.confirm()
        self.assertEqual(Transaction.objects.count(), 2)

    def test_new_categories_created_and_rules_applied(self):
        CategoryRule.objects.create(user=self.user, pattern="bhat", category=self.cat(name="Groceries"))
        self.upload(self.HEADER + self.row(category="Fitness", name="Gym") + self.row(category="", name="Bhat Bhateni"))
        page = self.client.get(reverse("import"))
        self.assertEqual(page.context["new_categories"], ["Fitness"])
        self.assertEqual(page.context["n_rules"], 1)
        self.confirm()
        self.assertTrue(Category.objects.filter(user=self.user, name="Fitness").exists())
        self.assertEqual(Transaction.objects.get(name="Bhat Bhateni").category.name, "Groceries")

    def test_category_missing_without_rule_is_an_error(self):
        self.upload(self.HEADER + self.row(category=""))
        self.assertEqual(self.client.get(reverse("import")).context["n_error"], 1)

    def test_category_kind_mismatch(self):
        self.upload(self.HEADER + self.row(category="Salary"))
        self.assertEqual(self.client.get(reverse("import")).context["n_error"], 1)

    def test_file_problems(self):
        for text, fragment in (("", "empty"), ("a,b\n1,2\n", "Missing column"), (self.HEADER, "no data rows")):
            r = self.upload(text)
            self.assertEqual(r.status_code, 200)
            self.assertContains(r, fragment)
        r = self.client.post(reverse("import"), {"file": SimpleUploadedFile("a.txt", b"x")})
        self.assertContains(r, "Upload a .csv")
        r = self.upload("x" * (600 * 1024))
        self.assertContains(r, "too large")

    def test_row_limit(self):
        text = self.HEADER + "".join(self.row(name=f"n{i}") for i in range(csvio.MAX_ROWS + 1))
        self.assertContains(self.upload(text), "Too many rows")

    def test_round_trip_of_our_own_export(self):
        t = self.tx(amount="12.50", name="=cmd", payee="+p", note="-n")
        services.save_transaction(t, tags=["t1"])
        text = b"".join(self.client.get(reverse("export")).streaming_content).decode("utf-8")
        Transaction.all_objects.all().delete()
        self.upload(text)
        self.confirm()
        back = Transaction.objects.get()
        self.assertEqual((back.name, back.payee, back.note, back.amount), ("=cmd", "+p", "-n", Decimal("12.50")))

    def test_encodings_and_delimiters(self):
        text = (self.HEADER + self.row(note="café")).replace(",", ";")
        self.client.post(reverse("import"), {"file": SimpleUploadedFile("a.csv", ("﻿" + text).encode("utf-8"))})
        self.assertEqual(self.client.get(reverse("import")).context["n_valid"], 1)
        r = self.client.post(reverse("import"), {"file": SimpleUploadedFile("b.csv", b"\xff\xfe\x00bad")})
        self.assertEqual(r.status_code, 200)

    @override_settings(ALLOW_NEGATIVE_BALANCE=False)
    def test_import_respects_overdraft_policy(self):
        self.upload(self.HEADER + self.row(amount="50"))
        r = self.confirm()
        self.assertRedirects(r, reverse("import"))
        self.assertEqual(Transaction.objects.count(), 0)

    def test_confirm_needs_valid_token_and_is_scoped(self):
        self.upload(self.HEADER + self.row())
        r = self.client.post(reverse("import_confirm"), {"token": "wrong"})
        self.assertRedirects(r, reverse("import"))
        self.assertEqual(Transaction.objects.count(), 0)
        other = self.csrf_client(self.other)
        self.assertEqual(other.post(reverse("import_confirm"), {"token": "x"}).status_code, 403)
        self.client.post(reverse("import_cancel"))
        self.assertNotIn("import_preview", self.client.session)

    def test_closed_month_blocks_import(self):
        from app.models import MonthLock
        MonthLock.objects.create(user=self.user, month=today().replace(day=1))
        self.upload(self.HEADER + self.row())
        self.confirm()
        self.assertEqual(Transaction.objects.count(), 0)
