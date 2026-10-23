"""HTML pages. Data-heavy pages fetch their content from app.api."""
import csv
import datetime
import re
import secrets
import unicodedata

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.http import Http404, HttpResponse, JsonResponse, StreamingHttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from . import backup as backup_lib
from . import csvio, insights as insight_lib, reports as report_lib, services
from .filters import PAGE_SIZES, SORT_OPTIONS, TransactionFilter
from .forms import ChangePasswordForm, ImportForm, RegisterForm, SettingsForm, SetupForm
from .icons import CATEGORY_ICONS
from .models import ACCOUNT_TYPES, COLOR_CHOICES, LEDGER_KINDS, Category, MonthLock, Tag, Transaction
from .ratelimit import Throttle, client_ip

USERNAME_RE = re.compile(r"^[\w.@+-]+$")

login_by_user = Throttle("login-user", settings.LOGIN_MAX_ATTEMPTS, settings.LOGIN_LOCKOUT_SECONDS)
login_by_ip = Throttle("login-ip", settings.LOGIN_MAX_ATTEMPTS * 4, settings.LOGIN_LOCKOUT_SECONDS)
register_by_ip = Throttle("register-ip", settings.REGISTER_MAX_PER_HOUR, 3600)


class LoginForm(AuthenticationForm):
    """Accepts the username in any letter case (registration stores it lowercase)."""

    def clean_username(self):
        raw = self.cleaned_data["username"].strip()
        match = User.objects.filter(username__iexact=raw).values_list("username", flat=True).first()
        return match or raw


class LoginView(auth_views.LoginView):
    authentication_form = LoginForm
    template_name = "registration/login.html"
    redirect_authenticated_user = True

    def get_context_data(self, **kwargs):
        return super().get_context_data(allow_registration=settings.ALLOW_REGISTRATION, **kwargs)

    def post(self, request, *args, **kwargs):
        self.throttle_name = (request.POST.get("username") or "").strip().lower()[:150]
        self.throttle_ip = client_ip(request)
        if login_by_user.blocked(self.throttle_name, self.throttle_ip) or login_by_ip.blocked(self.throttle_ip):
            form = self.get_form_class()(request)
            response = self.render_to_response(self.get_context_data(form=form, locked=True))
            response.status_code = 429
            return response
        return super().post(request, *args, **kwargs)

    def form_invalid(self, form):
        login_by_user.hit(self.throttle_name, self.throttle_ip)
        login_by_ip.hit(self.throttle_ip)
        return super().form_invalid(form)

    def form_valid(self, form):
        login_by_user.reset(self.throttle_name, self.throttle_ip)
        return super().form_valid(form)


@require_POST
def logout_view(request):
    logout(request)
    return redirect(settings.LOGOUT_REDIRECT_URL)


@never_cache
def register(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    if not settings.ALLOW_REGISTRATION:
        raise Http404
    ip = client_ip(request)
    if request.method == "POST":
        if register_by_ip.blocked(ip):
            messages.error(request, "Too many sign-ups from this address. Try again later.")
            return render(request, "registration/register.html", {"form": RegisterForm()}, status=429)
        form = RegisterForm(request.POST)
        if form.is_valid():
            user = form.save()
            register_by_ip.hit(ip)
            login(request, user, backend="django.contrib.auth.backends.ModelBackend")
            messages.success(request, "Welcome. Your account is ready.")
            return redirect("dashboard")
    else:
        form = RegisterForm()
    return render(request, "registration/register.html", {"form": form})


username_check = Throttle("username-check", 30, 60)


@require_GET
def username_available(request):
    """Is this username free? Reveals no more than the sign-up form itself (rate limited)."""
    if not settings.ALLOW_REGISTRATION:
        raise Http404
    ip = client_ip(request)
    if username_check.hit(ip) > username_check.limit:
        response = JsonResponse({"ok": False, "message": "Too many checks. Try again in a minute."}, status=429)
        response["Retry-After"] = "60"
        return response
    raw = unicodedata.normalize("NFKC", (request.GET.get("u") or "")).strip().lower()
    valid = bool(raw) and len(raw) <= 150 and USERNAME_RE.match(raw) is not None
    available = valid and not User.objects.filter(username__iexact=raw).exists()
    response = JsonResponse({"ok": True, "valid": valid, "available": available})
    response["Cache-Control"] = "no-store"
    return response


# --- pages -------------------------------------------------------------------

@login_required
def dashboard(request):
    if not services.get_profile(request.user).setup_done:
        return redirect("welcome")
    services.apply_due(request.user)
    return render(request, "app/dashboard.html", {"month": timezone.localdate().strftime("%Y-%m")})


def _results_context(request, flt):
    paginator = Paginator(flt.queryset(), flt.page_size)
    page = paginator.get_page(flt.page)
    income, expense = services.income_expense_for(flt.queryset())
    return {
        "flt": flt, "page": page, "paginator": paginator, "income": income, "expense": expense,
        "net": income - expense,
        "headers": [
            flt.sort_header("date", "Date"), flt.sort_header("name", "Description"),
            flt.sort_header("category", "Category"),
        ],
        "amount_header": flt.sort_header("amount", "Amount", numeric=True),
        "pages": [
            {"gap": True} if n == paginator.ELLIPSIS else
            {"number": n, "href": flt.page_href(n), "current": n == page.number}
            for n in paginator.get_elided_page_range(page.number, on_each_side=1, on_ends=1)
        ],
        "prev_href": flt.page_href(page.previous_page_number()) if page.has_previous() else "",
        "next_href": flt.page_href(page.next_page_number()) if page.has_next() else "",
    }


@login_required
def transactions(request):
    services.apply_due(request.user)
    flt = TransactionFilter(request.user, request.GET)
    context = _results_context(request, flt)
    if request.GET.get("fragment") == "1":
        return render(request, "app/_transactions_results.html", context)
    context.update(
        page_sizes=PAGE_SIZES, categories=request.user.categories.all(), tag_list=Tag.objects.filter(user=request.user),
        accounts=request.user.accounts.all(), sort_options=SORT_OPTIONS)
    return render(request, "app/transactions.html", context)


@login_required
def categories(request):
    return render(request, "app/categories.html", {"colors": COLOR_CHOICES, "icons": CATEGORY_ICONS})


@login_required
def budgets(request):
    return render(request, "app/budgets.html", {"month": services.parse_month(request.GET.get("month")).strftime("%Y-%m")})


@login_required
def goals(request):
    return render(request, "app/goals.html", {"today": timezone.localdate()})


@login_required
def accounts(request):
    return render(request, "app/accounts.html", {"account_types": ACCOUNT_TYPES, "today": timezone.localdate()})


@login_required
def recurring(request):
    return render(request, "app/recurring.html", {"today": timezone.localdate()})


@login_required
def analytics(request):
    today = timezone.localdate()
    return render(request, "app/analytics.html", {
        "start": services.month_start(today), "end": today,
        "categories": request.user.categories.all(), "tag_list": Tag.objects.filter(user=request.user)})


def _report_range(request):
    today = timezone.localdate()

    def day(name):
        try:
            return datetime.date.fromisoformat(request.GET.get(name, ""))
        except ValueError:
            return None

    return report_lib.resolve_period(request.GET.get("preset", "this_month"), day("start"), day("end"), today)


@login_required
def reports(request):
    preset, start, end = _report_range(request)
    data = report_lib.build(request.user, start, end)
    return render(request, "app/reports.html", {
        "data": data, "preset": preset, "presets": report_lib.PRESETS, "start": start, "end": end,
        "report_list": report_lib.REPORTS, "query": f"start={start.isoformat()}&end={end.isoformat()}&preset={preset}",
        "generated": timezone.localtime()})


@login_required
def report_export(request):
    name = request.GET.get("report", "")
    if name not in dict(report_lib.REPORTS):
        raise Http404
    _, start, end = _report_range(request)
    header, rows = report_lib.csv_rows(name, report_lib.build(request.user, start, end))
    writer = csv.writer(csvio.Echo())

    def lines():
        yield "\ufeff"
        yield writer.writerow(header)
        for row in rows:
            yield writer.writerow(row)

    response = StreamingHttpResponse(lines(), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="report-{name}-{start.isoformat()}-{end.isoformat()}.csv"'
    response["Cache-Control"] = "no-store"
    return response


@login_required
@require_http_methods(["GET", "POST"])
def settings_page(request):
    if request.method == "POST":
        form = SettingsForm(request.POST, user=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, "Settings saved.")
            return redirect("settings")
    else:
        form = SettingsForm(user=request.user)
    return render(request, "app/settings.html", {
        "form": form, "password_form": ChangePasswordForm(request.user), "locks": MonthLock.objects.filter(user=request.user),
        "current_month": timezone.localdate().strftime("%Y-%m")})


@login_required
@require_POST
def change_password(request):
    form = ChangePasswordForm(request.user, request.POST)
    if form.is_valid():
        user = form.save()
        update_session_auth_hash(request, user)
        messages.success(request, "Password changed.")
        return redirect("settings")
    return render(request, "app/settings.html", {
        "form": SettingsForm(user=request.user), "password_form": form, "locks": MonthLock.objects.filter(user=request.user),
        "current_month": timezone.localdate().strftime("%Y-%m")})


# --- CSV ---------------------------------------------------------------------

@login_required
@require_GET
def export_csv(request):
    flt = TransactionFilter(request.user, request.GET)
    qs = flt.queryset()
    bom = request.GET.get("bom", "1") != "0"
    response = StreamingHttpResponse(csvio.export_lines(qs, bom=bom), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="transactions-{timezone.localdate().isoformat()}.csv"'
    response["Cache-Control"] = "no-store"
    return response


@login_required
@require_http_methods(["GET", "POST"])
def import_page(request):
    form = ImportForm()
    if request.method == "POST":
        form = ImportForm(request.POST, request.FILES)
        if form.is_valid():
            try:
                rows = csvio.parse(form.cleaned_data["file"].read(), request.user)
            except csvio.CsvImportError as exc:
                form.add_error("file", str(exc))
            else:
                request.session["import_preview"] = {"token": secrets.token_urlsafe(16), "rows": csvio.serialise(rows)}
                return redirect("import")
    preview = request.session.get("import_preview")
    context = {"form": form}
    if preview:
        rows = csvio.deserialise(preview["rows"])
        valid = [r for r in rows if not r["errors"]]
        context.update(
            token=preview["token"], rows=rows,
            n_valid=len([r for r in valid if not r["duplicate"]]),
            n_duplicate=len([r for r in valid if r["duplicate"]]),
            n_error=len(rows) - len(valid),
            new_categories=sorted({r["category"] for r in valid if r["new_category"]}, key=str.lower),
            n_rules=len([r for r in valid if r.get("rule_matched")]),
        )
    return render(request, "app/import.html", context)


@login_required
@require_POST
def import_cancel(request):
    request.session.pop("import_preview", None)
    return redirect("import")


@login_required
@require_POST
def import_confirm(request):
    preview = request.session.get("import_preview")
    if not preview or not secrets.compare_digest(preview["token"], request.POST.get("token", "")):
        messages.error(request, "That import has expired. Upload the file again.")
        return redirect("import")
    skip_duplicates = request.POST.get("skip_duplicates") == "on"
    rows = [r for r in csvio.deserialise(preview["rows"]) if not r["errors"] and not (skip_duplicates and r["duplicate"])]
    if not rows:
        messages.error(request, "There are no valid rows to import.")
        return redirect("import")
    user = request.user
    try:
        with services.locked(user):
            cats = {c.name.lower(): c for c in user.categories.all()}
            accounts = {a.name.lower(): a for a in user.accounts.all()}
            fallback = services.default_account(user)
            made = []
            for r in rows:
                cat = cats.get(r["category"].lower())
                if cat is None:
                    cat = Category.objects.create(user=user, name=r["category"], kind="both")
                    cats[r["category"].lower()] = cat
                account = accounts.get(r["account"].lower()) if r["account"] else fallback
                made.append((Transaction(
                    user=user, name=r["name"], amount=r["amount"], kind=r["kind"], date=r["date"], category=cat,
                    account=account, payee=r["payee"], note=r["note"]), r["tags"]))
            services.ensure_unlocked(user, *{tx.date for tx, _ in made})
            services.ensure_effects(user, [(tx.account, tx.effect) for tx, _ in made])
            for tx, tag_names in made:
                tx.save()
                if tag_names:
                    services.set_tags(tx, tag_names)
                services.record(user, tx.pk, "imported", f"Imported {tx.name} ({tx.amount:.2f})", None, services.snapshot(tx))
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
        return redirect("import")
    created = made
    request.session.pop("import_preview", None)
    messages.success(request, f"Imported {len(created)} transaction(s).")
    return redirect("transactions")


# --- first-run setup, digest, trash, people, backup ---------------------------

@login_required
@require_http_methods(["GET", "POST"])
def welcome(request):
    if request.method == "POST":
        if "skip" in request.POST:
            profile = services.get_profile(request.user)
            profile.setup_done = True
            profile.save(update_fields=["setup_done"])
            services.forget_profile(request.user)
            return redirect("dashboard")
        form = SetupForm(request.POST, user=request.user)
        if form.is_valid():
            form.apply()
            messages.success(request, "You are all set. Add your first transaction when you are ready.")
            return redirect("dashboard")
    else:
        form = SetupForm(user=request.user)
    return render(request, "app/welcome.html", {"form": form})


@login_required
def digest(request):
    return render(request, "app/digest.html", {"d": insight_lib.weekly_digest(request.user)})


@login_required
def trash(request):
    return render(request, "app/trash.html", {"days": services.TRASH_DAYS})


@login_required
def people(request):
    return render(request, "app/people.html", {"kinds": LEDGER_KINDS, "today": timezone.localdate()})


@login_required
@require_GET
def backup_export(request):
    response = HttpResponse(backup_lib.dumps(request.user), content_type="application/json; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="finance-manager-backup-{timezone.localdate().isoformat()}.json"'
    response["Cache-Control"] = "no-store"
    return response


@login_required
@require_http_methods(["GET", "POST"])
def backup_page(request):
    context = {"problems": [], "summary": None}
    if request.method == "POST":
        upload = request.FILES.get("file")
        if upload is None:
            context["problems"] = ["Choose a backup file."]
        else:
            try:
                parsed = backup_lib.parse(upload.read(backup_lib.MAX_BYTES + 1))
            except backup_lib.BackupError as exc:
                context["problems"] = exc.problems
            else:
                context["summary"] = backup_lib.summary(parsed)
                if "restore" in request.POST:
                    if request.POST.get("confirm") != "on":
                        context["problems"] = ["Tick the box to confirm that this replaces your current data."]
                    else:
                        backup_lib.restore(request.user, parsed)
                        messages.success(request, "Backup restored.")
                        return redirect("dashboard")
    return render(request, "app/backup.html", context)


@login_required
@require_POST
def lock_month(request):
    month = services.parse_month(request.POST.get("month"), default=None) if request.POST.get("month") else None
    if month is None or request.POST.get("month") != month.strftime("%Y-%m"):
        messages.error(request, "Choose a month to close.")
    elif request.POST.get("action") == "reopen":
        MonthLock.objects.filter(user=request.user, month=month).delete()
        messages.success(request, f"{month:%B %Y} is open again.")
    elif month > services.month_start(timezone.localdate()):
        messages.error(request, "You can only close the current month or earlier months.")
    else:
        MonthLock.objects.get_or_create(user=request.user, month=month)
        messages.success(request, f"{month:%B %Y} is closed. Its transactions are protected from changes.")
    return redirect("settings")


def _confirmed_password(request):
    return request.user.check_password(request.POST.get("password", ""))


@login_required
@require_POST
def erase_data(request):
    if request.POST.get("confirm") != "ERASE" or not _confirmed_password(request):
        messages.error(request, "Nothing was erased. Type ERASE and enter your password to confirm.")
        return redirect("settings")
    with services.locked(request.user):
        backup_lib.erase(request.user)
        services.set_up_new_user(request.user)
    messages.success(request, "All of your data was erased. Your account is still here.")
    return redirect("settings")


@login_required
@require_POST
def delete_account(request):
    if request.POST.get("confirm") != request.user.username or not _confirmed_password(request):
        messages.error(request, "Your account was not deleted. Type your username and enter your password to confirm.")
        return redirect("settings")
    user = request.user
    logout(request)
    user.delete()
    messages.success(request, "Your account and all of its data were deleted.")
    return redirect("login")
