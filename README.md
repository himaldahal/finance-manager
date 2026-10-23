# Finance Manager

A personal finance tracker built with Django. It keeps your accounts, transactions, budgets, savings goals, bills and
debts in one place, answers "how am I doing this month?" in plain language, and runs on a single SQLite file with no
external services. Nothing is loaded from a third party at runtime: fonts, icons, charts and scripts are all served by the
app itself.

Plain, light and quick: a spreadsheet-clean interface, no tracking, no network calls from the browser except to your own server.

## Screenshots

| | |
|---|---|
| ![Dashboard](docs/screenshots/dashboard.png) **Dashboard** with plain-language insights, upcoming bills, goals, subscriptions | ![Transactions](docs/screenshots/transactions.png) **Transactions** with filters, sorting, saved views and bulk actions |
| ![Add transaction](docs/screenshots/add-transaction.png) **Add a transaction** with smart defaults, rule hints and "more options" | ![Budgets](docs/screenshots/budgets.png) **Budgets** with progress, rollover, safe-to-spend, projections and history |
| ![Analytics](docs/screenshots/analytics.png) **Analytics**: hand-written SVG charts, filters synced to the URL | ![Reports](docs/screenshots/reports.png) **Reports**: income statement, trends, net worth, cash flow, CSV and print |
| ![Accounts](docs/screenshots/accounts.png) **Accounts** and transfers | ![Goals](docs/screenshots/goals.png) **Savings goals** with progress rings |
| ![Categories](docs/screenshots/categories.png) **Categories**, sub-categories, rules and tags | ![Category dialog](docs/screenshots/category-dialog.png) Colour and icon picker |
| ![Recurring](docs/screenshots/recurring.png) **Bills** and recurring transactions | ![People](docs/screenshots/people.png) **Debts and sharing** |
| ![Weekly digest](docs/screenshots/digest.png) **Weekly digest** | ![Trash](docs/screenshots/trash.png) **Trash** (30 days) and change history |
| ![Import](docs/screenshots/import-preview.png) **CSV import** preview with per-row errors and duplicate detection | ![Backup](docs/screenshots/backup.png) **Backup** and restore (JSON) |
| ![Settings](docs/screenshots/settings.png) **Settings**: currency, number format, closed months, data erase | ![Search](docs/screenshots/search.png) **Quick search** (`/`) understands "dining last month over 500" |
| ![Welcome](docs/screenshots/welcome.png) **First-run setup** | ![Reconcile](docs/screenshots/transactions-tools.png) **Reconcile** against a bank statement |
| ![Register](docs/screenshots/register-invalid.png) **Sign-up** with live, specific checks (problems shown) | ![Register valid](docs/screenshots/register-valid.png) Sign-up when everything looks good |
| ![Login](docs/screenshots/login.png) **Sign in** | ![Register](docs/screenshots/register.png) **Create account**, show/hide password and strength meter |

### Sidebar and mobile

| Expanded | Collapsed rail | Mobile drawer |
|---|---|---|
| ![Expanded sidebar](docs/screenshots/sidebar-expanded.png) | ![Collapsed sidebar](docs/screenshots/sidebar-collapsed.png) | ![Mobile drawer](docs/screenshots/mobile-drawer.png) |

| Mobile dashboard | Mobile transactions | Mobile analytics | Mobile budgets |
|---|---|---|---|
| ![Mobile dashboard](docs/screenshots/mobile-dashboard.png) | ![Mobile transactions](docs/screenshots/mobile-transactions.png) | ![Mobile analytics](docs/screenshots/mobile-analytics.png) | ![Mobile budgets](docs/screenshots/mobile-budgets.png) |

## Features

**Everyday use**
- First-run setup: currency, accounts, starter categories, an optional monthly budget, optional sample data.
- Add a transaction from anywhere (`n`, the Add button, or the floating button on phones). Smart defaults: today, last used
  account and category, the type follows an income-only or expense-only category. Type "coffee 150 food" in the quick-add
  bar to get a preview chip before saving.
- Accounts (bank, cash, wallet, credit) with their own balances and transfers that never count as income or expenses.
- Categories with colour, icon, a kind (income, expense or both) and one level of sub-categories; tags and payees with
  autocomplete; auto-categorise rules (also applied on CSV import).
- Split one purchase over several categories, duplicate a transaction, change a category inline, bulk delete or recategorise,
  undo toasts and a 30-day trash. Every change is logged and viewable per transaction.
- Recurring bills (weekly or monthly) created automatically, with pause and resume; a `apply_recurring` command for cron.
- Month close: lock a finished month so it cannot be edited by accident (reopen any time).
- Reconcile an account against a bank statement balance.

**Insight**
- Dashboard sentences such as "You have spent 62% of your Groceries budget with 11 days left", end-of-month forecast,
  this month against last month, unusual spending, top movers, subscription detector, upcoming bills, goal progress.
- Budgets per month for the whole month and per category: rollover, alert thresholds, copy last month, projected month-end
  spend, safe-to-spend per day, week-by-week breakdown, history, budget against actual.
- Savings goals with target dates, required monthly amount and contribution history.
- Analytics: monthly income and expenses, net cash flow, stacked category spending, donut and ranked bars, category
  sparklines, daily heatmap, weekday pattern, cumulative spend against budget, balance over time, top payees. Every chart has
  tooltips on hover and keyboard focus and a data-table view.
- Reports: income statement with comparison to the previous period, category breakdown, trend and savings rate, net worth,
  top payees, tags, cash flow by account. Each exports to CSV and prints cleanly ("Save as PDF" from the browser).
- Weekly digest page.

**Money tools**
- Debts and sharing: lend, borrow or split a bill with a friend and settle up later (no account needed for them).
- CSV export (respects filters, formula-safe) and CSV import with a preview, per-row errors and duplicate detection.
- One-click JSON backup and a validated, versioned restore. Erase your data or delete your account from Settings.
- An optional second currency shown on the dashboard with a rate you enter yourself.

**Interface**
- Light, plain design with a foldable sidebar (icon rail, remembered), off-canvas drawer on small screens, bottom navigation
  on phones, skip link, landmarks, visible focus, `prefers-reduced-motion` respected.
- Quick search (`/`) across transactions, payees, categories, tags, accounts and goals, including phrases like
  "food last month over 500". Saved filter views.
- Keyboard shortcuts: `n` new transaction, `/` search, `[` toggle sidebar, `?` help.
- Show/hide on every password field, caps lock warning, strength meter and live, specific sign-up checks.
- No inline scripts or styles, strict Content Security Policy, no third party requests.

## Requirements

Python 3.9 or newer and Django 4.2 to 5.2 (Django 5 needs Python 3.10 or newer). There are no other dependencies.

## Quick start

```bash
git clone https://github.com/himaldahal/finance-manager.git
cd finance-manager
scripts/bootstrap.sh --demo --run      # creates .venv, installs, writes .env, migrates, seeds a demo user, starts the server
```

Open http://127.0.0.1:8000/ and sign in with `demo` / `demo-password-123`, or create your own account.
Leave out `--demo` for an empty database. Manual steps:

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # then set SECRET_KEY (and DEBUG=1 for local use)
python manage.py migrate
python manage.py createsuperuser   # optional, for /admin/
python manage.py runserver
```

On Windows activate with `.venv\Scripts\activate`.

## Configuration

Settings come from environment variables, optionally from a `.env` file in the project root (a tiny built-in loader; real
environment variables win). See `.env.example`.

| Variable | Default | Purpose |
|---|---|---|
| `SECRET_KEY` | none | Required unless `DEBUG=1`. Use a long random value. |
| `DEBUG` | `0` | Development mode. Never enable in production. |
| `ALLOWED_HOSTS` | `localhost,127.0.0.1` in debug, empty otherwise | Comma separated host names. |
| `CSRF_TRUSTED_ORIGINS` | empty | Origins with scheme for HTTPS behind a proxy. |
| `DATABASE_PATH` | `db.sqlite3` | Location of the SQLite file. |
| `TIME_ZONE` | `Asia/Kathmandu` | Used for "today" and month boundaries. |
| `ALLOW_NEGATIVE_BALANCE` | `1` | Default overdraft policy (each user can override it). |
| `ALLOW_REGISTRATION` | `1` | Set to `0` to close sign-ups. |
| `DEFAULT_CURRENCY_CODE`, `DEFAULT_CURRENCY_SYMBOL` | `NPR`, `Rs` | Defaults for new users. |
| `LOGIN_MAX_ATTEMPTS`, `LOGIN_LOCKOUT_SECONDS` | `5`, `900` | Login brute force protection. |
| `REGISTER_MAX_PER_HOUR` | `10` | Sign-ups per address per hour. |
| `SECURE_SSL_REDIRECT` | on when `DEBUG=0` | Redirect HTTP to HTTPS. |
| `SECURE_HSTS_SECONDS` | `31536000` when `DEBUG=0` | HSTS lifetime. |
| `TRUST_X_FORWARDED_PROTO` | `0` | Enable only behind a proxy that always sets the header. |

## Security notes

- The secret key is never in the source. `SECRET_KEY` is required unless `DEBUG=1`.
- With `DEBUG=0`: secure and HttpOnly cookies, SameSite, HSTS, HTTPS redirect, nosniff, `X-Frame-Options: DENY`,
  same-origin referrer policy. `python manage.py check --deploy` is clean with a production environment.
- Every query is scoped to the signed-in user and other users' objects answer 404. All mutating endpoints require POST or
  DELETE with CSRF protection; logout is POST only.
- User data is stored raw and escaped by the templates. The browser code builds the page with DOM APIs, never HTML strings.
- A strict Content Security Policy (`default-src 'self'`, no inline script or style). The admin site gets the same policy
  plus inline styles, which it still needs.
- Login lockout and sign-up throttling use the cache. The default cache is per process; use a shared cache backend when
  running several workers.
- CSV exports prefix cells starting with `=`, `+`, `-` or `@` so spreadsheets do not run them as formulas.
- Static files are not served by Django when `DEBUG=0`: run `python manage.py collectstatic` and serve `staticfiles/`
  with your web server.

## Troubleshooting

**`OperationalError: no such table: app_balance` (or any "no such table") at `/register/`**
The database has not been migrated, which is what you get on a fresh clone. Run:

```bash
python manage.py migrate
```

and start the server again. The app now detects this and shows a plain "Database not set up" page (HTTP 503) with the same
instruction instead of a stack trace, and `python manage.py check` prints a warning (`app.W001`). Registration creates the
user, categories and a first account in one transaction, so a user can never be left without defaults.

**`SECRET_KEY is not set`** Copy `.env.example` to `.env` and set `SECRET_KEY`, or run `scripts/bootstrap.sh`.

**The folder is called `finance-manger`.** Older checkouts stored the app inside a misspelled `finance-manger` directory.
The project root is the folder that contains `manage.py`; run every command from there.

**Python 3.9 and Django 4.1** An old Django 4.1 install will not work. Run `pip install -r requirements.txt` to get
Django 4.2 or newer.

**Pages look unstyled with `DEBUG=0`** Run `python manage.py collectstatic` and serve the `staticfiles/` folder.

## Project structure

```
manage.py
expensemanager/      settings, env loader, security middleware, URLs
app/
  models.py          accounts, categories, transactions, budgets, goals, recurring, people, backups ...
  services.py        balances, overdraft policy, locks, change log, recurring
  budgeting.py       budget maths, goals, alerts      insights.py   plain-language insights
  reports.py         period reports                    backup.py     JSON backup and restore
  api.py             JSON endpoints                    views.py      HTML pages
  csvio.py nlq.py filters.py forms.py ratelimit.py
  templates/ static/app/{css,js,icons}
  management/commands/   apply_recurring, seed_demo
  tests/
scripts/             bootstrap.sh, check_hygiene.sh, capture_screenshots.py, build_icons.py
docs/screenshots/
```

## Tests

```bash
python manage.py test
```

The suite covers models, services, forms, the API, pages, budgets and goals, recurring items, import and export, reports,
insights, backup and restore, security (IDOR on every object endpoint, CSRF, method restrictions, XSS, CSV injection, rate
limiting), registration edge cases, migrating a database created with the original schema, the unmigrated-database page,
deployment settings and a CSS and JavaScript size budget. CI runs it on Python 3.9 to 3.13 with Django 4.2 and 5.2
(`.github/workflows/ci.yml`). `scripts/check_hygiene.sh` checks text files for forbidden characters and words.

Every page loads well under 115 KB of CSS and JavaScript uncompressed (about 30 KB gzipped).

## Regenerating the screenshots

```bash
python scripts/capture_screenshots.py            # needs Chromium or Chrome
python scripts/capture_screenshots.py --only dashboard,budgets
```

The script starts the app on a free port with a temporary database and demo data, signs in by setting a session cookie
through the DevTools protocol (the app has no login backdoor), and writes PNG files to `docs/screenshots/`.

## Not included

Receipt photo attachments, reverting a transaction to an earlier version (the history is viewable, not restorable), and
live exchange rates (rates are entered by hand on purpose).

## Credits and license

Icons are from [Lucide](https://lucide.dev) (ISC licence, copy in `app/static/app/icons/LICENSE`), vendored as a
self-hosted sprite built by `scripts/build_icons.py`.

Released under the MIT License. See [LICENSE](LICENSE). Copyright (c) Himal Dahal.
