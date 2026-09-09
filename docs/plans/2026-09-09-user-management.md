# User management and session authentication

## Summary

Add the first application identity model and private session-authenticated Web GUI. A custom Django
user uses a case-insensitive unique email address as its only login identifier. The application
provides an email/password login page and POST logout, protects all user-facing pages by default,
and exposes Django admin for explicitly authorized staff. Accounts remain operator-created through
`manage.py createsuperuser` and Django admin; there is no public account lifecycle.

The existing liveness and readiness endpoints remain unauthenticated and keep their current JSON
contract. This feature adds no authentication API, JavaScript framework, or third-party dependency.

## Goals

- Establish a custom Django user model before financial models or user data exist.
- Authenticate users with email and password through Django's server-rendered session facilities.
- Enforce case-insensitive email identity in application lookup and at the database boundary.
- Make every user-facing application page private by default while keeping operational health
  probes public.
- Provide Django admin user creation and management using Django's standard staff, superuser,
  group, and permission behavior.
- Deliver accessible login and logout behavior that works without JavaScript.
- Cover persistence, authorization, login failure, navigation, and operational endpoint regressions.

## Non-goals

- Public registration, invitations, email verification, or self-service profile management.
- Self-service password reset, account recovery, or outbound email.
- JSON authentication endpoints, tokens, API sessions, or OpenAPI authentication definitions.
- Login-attempt rate limiting, lockout policy, CAPTCHA, or a new security dependency.
- Automatic provisioning of the first account during deployment.
- Financial-data ownership, per-user financial authorization, or any financial feature.
- Changes to the health response shapes, status codes, ingress exposure, or readiness semantics.

## User-visible behavior

- Visiting `/` without an authenticated session redirects to `/login/?next=/`.
- `/login/` shows only visible email and password controls, a submit button, and no registration or
  recovery links. The email control uses an email-appropriate input type and autocomplete hint; the
  password control uses the current-password autocomplete hint.
- Successful login redirects to the validated local `next` target when one was supplied, otherwise
  to the existing home page at `/`. Django's built-in redirect validation must prevent external
  redirect targets.
- Unknown email, incorrect password, and inactive-user authentication all display the same generic
  form-level credentials error. A rejected login does not disclose whether an account exists or is
  inactive. Ordinary field validation remains associated with its input.
- Email matching ignores case. For example, `Alex@Example.com` and `alex@example.com` identify the
  same account, and the second case variant cannot be created.
- An authenticated active user can access the home page. The application shell identifies the
  current user and provides a CSRF-protected POST logout control that works without JavaScript.
- Successful logout clears the session and redirects to `/login/`. A GET request must not perform
  logout.
- `/admin/` uses Django admin. Active staff users can enter according to their Django permissions;
  active non-staff users can use the money manager but cannot enter admin. Superusers retain normal
  Django behavior.
- Operators create the initial superuser with `python manage.py createsuperuser` in the server
  environment. That user can create further users in admin. No public URL creates an account.
- `GET /health/live` and `GET /health/ready` remain accessible without a session and retain their
  existing responses. Production ingress continues to keep readiness internal as already designed.

## Decisions and assumptions

- Implement `penni_more.users.User` from `AbstractUser`, set `username = None`, make `email` the
  `USERNAME_FIELD`, and leave `REQUIRED_FIELDS` empty. Inherited optional `first_name` and
  `last_name` fields may remain for admin use but do not appear on the login form.
- Add a dedicated user manager. It must require a non-empty email, normalize the entire address to
  one canonical lowercase form on user and superuser creation, perform natural-key lookup without
  case sensitivity, and preserve Django's required superuser flag checks.
- Normalize email on model validation and persistence as well as through the manager. Add a named
  database `UniqueConstraint` over `Lower("email")`; do not rely only on form validation or a
  case-sensitive unique column. Admin forms must turn a duplicate case variant into a useful form
  error rather than an unhandled integrity error.
- Continue using Django's password hashers, authentication backend, session storage, CSRF
  protection, safe-next handling, and permissions. Do not implement custom password comparison or
  session cookies. Enable Django's standard built-in password validators for operator-created
  passwords without adding a dependency.
- Use Django's default-deny `LoginRequiredMiddleware` after authentication middleware. Explicitly
  mark only the login and both health views as not requiring application login. Django admin keeps
  its own login and staff authorization flow.
- Use a small `AuthenticationForm` subclass only for the email-specific field presentation and
  generic authentication error policy. Keep Django's authentication and redirect logic in
  `LoginView` and `LogoutView`.
- Use the route names `login`, `logout`, `home`, and `admin:index`. Configure `LOGIN_URL`,
  `LOGIN_REDIRECT_URL`, and `LOGOUT_REDIRECT_URL` with named routes rather than duplicated literal
  paths where Django settings permit it.
- Logout is POST-only. The base template renders a normal HTML form with a CSRF token; JavaScript is
  neither required nor added.
- The repository currently has no custom application migrations and does not enable Django auth,
  admin, sessions, or messages. The custom user model must be installed before any built-in auth or
  admin migration is first used in a Penni More database.
- Existing deployment migration and pre-migration backup behavior is sufficient. Creating an
  operator account remains a deliberate manual action after migrations, and no credentials belong
  in source, fixtures, images, examples, or logs.

## Scope and ownership

### Backend coder

The `backend_coder` exclusively owns all implementation under `src/backend`:

- Add `src/backend/penni_more/users/__init__.py`, `apps.py`, `models.py`, `managers.py`, `admin.py`,
  `forms.py`, `migrations/__init__.py`, and `migrations/0001_initial.py` for the custom user
  application, model, manager, admin registration, authentication form, and initial migration.
- Update `src/backend/penni_more/settings/base.py` to enable the built-in admin, auth, sessions, and
  messages applications; the required middleware and template context processors; the custom user
  setting; and login/logout redirects.
- Update `src/backend/penni_more/urls.py` and `src/backend/penni_more/views.py` with admin,
  login/logout, default authentication enforcement, and explicit health exemptions.
- Add `src/backend/tests/test_users.py` and `src/backend/tests/test_auth.py`; update
  `test_home.py`, `test_health.py`, `test_settings.py`, and `test_contract.py` only as needed for the
  user model, manager, migration constraint, admin, login/logout, default page protection, and
  public health behavior. If admin coverage warrants a separate `test_admin.py`, it remains owned
  by the backend coder.
- Do not edit templates or Web tests under `src/web`, deployment automation, or OpenAPI artifacts.

The initial migration must create the custom user table and its case-insensitive uniqueness
constraint. It may depend on the latest built-in auth migration needed for inherited permissions.
It must be generated and checked through Django rather than handwritten unless a reviewed Django
limitation requires a narrow documented adjustment.

### Web GUI coder

The `web_gui_coder` exclusively owns presentation under `src/web`:

- Add `src/web/templates/registration/login.html` using the existing server-rendered shell and
  Tailwind/DaisyUI design system.
- Update `src/web/templates/base.html` to show appropriate authenticated navigation and the
  CSRF-protected POST logout form without exposing that control on the login page.
- Adjust `src/web/templates/home.html` only where authenticated context or copy requires it.
- Update `src/web/tests/unit/shell.test.js` and `src/web/tests/browser/home.spec.js`, and add
  `src/web/tests/unit/login.test.js` or `src/web/tests/browser/login.spec.js` where separation makes
  the login coverage clearer. These paths cover login semantics, responsive layout, keyboard
  navigation, generic error presentation hooks, and accessibility.
- Do not add client-side authentication, browser storage, custom JavaScript, or a dependency.

The browser suite can verify the unauthenticated redirect and login experience without test-only
account provisioning. Backend request tests own the authenticated login, logout, admin, and home
flows; Web unit tests own the template structure for authenticated navigation.

### Contract and deployment

- `src/contract/openapi.yaml` has no planned change. It remains the source of truth only for the
  existing health endpoints, whose `security: []` declarations remain correct. No
  `contract_coder` assignment is required.
- The architect reviews the final diff for cross-scope consistency and confirms that neither an
  auth path nor auth security scheme was added to OpenAPI and that health remains public through
  Django authentication middleware.
- No implementation change under `deploy/**`, `penni-more.sh`, dependency manifests, or lockfiles
  is planned. The `deployment_agent` owns final repository validation and all local Git mutations.

Backend and Web implementation can run concurrently after both agents accept the route names,
template path, form fields, and context behavior fixed by this plan. Web browser verification
depends on the backend routes being integrated; backend template-rendering tests depend on the Web
login template being present.

## Contract impact

There is no OpenAPI contract change. Login, logout, admin, and the home page are server-rendered
HTML routes, not JSON API operations. The existing contract continues to declare both health GET
operations unauthenticated.

The internal HTML integration surface is:

- `GET|POST /login/`, route name `login`, rendered by Django `LoginView` with the custom email
  authentication form and `registration/login.html`;
- `POST /logout/`, route name `logout`, redirected by Django `LogoutView` to `login`;
- `/admin/`, Django admin namespace, with standard staff authorization;
- `GET /`, route name `home`, authenticated by the default middleware policy;
- `GET /health/live` and `GET /health/ready`, explicitly exempt from login enforcement.

The login template receives Django form errors and a safe `next` value through standard auth-view
context. Its submitted controls are the authentication form's email identifier and password plus
CSRF metadata; no additional profile or registration fields are accepted by this view.

## Implementation sequence

1. The backend coder creates `penni_more.users` and the custom model before enabling or migrating
   built-in auth consumers. Implement canonical lowercase normalization, case-insensitive natural
   lookup, required email validation, manager flag invariants, and the database constraint.
2. The backend coder registers the model with a tailored `UserAdmin`. The add form must require
   email and matching passwords; change and list views must expose useful email, active/staff, name,
   group, permission, and audit fields without referencing a removed username.
3. The backend coder generates the initial user migration and enables the built-in Django
   applications, middleware, context processors, and `AUTH_USER_MODEL`. Preserve the standard
   security, CSRF, and clickjacking middleware already configured.
4. The backend coder adds the email authentication form, named login/logout/admin routes, redirect
   settings, default authenticated-page middleware, and explicit login/health exemptions. Ensure
   all credential failures share one generic error and logout changes state only on POST.
5. In parallel with steps 1-4, the Web GUI coder builds the login template and conditional
   authenticated shell using the fixed interfaces in this plan. Use visible labels, semantic
   landmarks, field-linked errors, a form-level error summary that does not enumerate accounts,
   keyboard-visible focus, responsive layout, and no JavaScript dependency.
6. The backend coder adds focused request and persistence tests. The Web GUI coder updates static
   template tests and changes the existing browser tests from assuming public home access to
   verifying the redirect and login page. Each coder runs `.codex/lint.sh` and the checks for their
   owned scope before review.
7. The `backend_reviewer` reviews all backend and migration work. The `web_gui_reviewer` reviews
   the login and shell behavior, including keyboard-only and no-JavaScript operation. Every
   actionable finding returns to its owning coder, and review repeats until neither reviewer has a
   blocking finding.
8. The architect performs the cross-scope and no-contract-change review after both coding scopes
   converge. Any accidental contract edit goes back to its owner; a newly discovered need for an
   auth API is a plan change and must not be introduced silently.
9. The `deployment_agent` runs final checks, verifies the migration from an empty database and the
   upgrade path through the normal deployment migration command, and creates the justified local
   commit or commits. Afterward, the feature cycle records results in the required report under
   `docs/reports` and the deployment agent commits that report if it is separate.

## Review and verification

### Backend behavior

Backend tests must demonstrate:

- `create_user` requires email, stores the full email in canonical lowercase, hashes the password,
  and creates an active non-staff, non-superuser by default;
- `create_superuser` requires and preserves both staff and superuser status, while rejecting
  contradictory flags;
- authentication succeeds for any case variant of the stored email and fails generically for an
  unknown email, wrong password, and inactive user;
- model/admin validation rejects a duplicate case variant cleanly, while the database constraint
  independently rejects a bypass attempt, including a transaction-safe concurrency-oriented
  persistence test where practical;
- the custom model has no username field, retains optional name fields, groups, user permissions,
  staff, active, superuser, timestamps, and password management;
- unauthenticated `/` redirects to the named login route with `next=/`; an authenticated active
  user receives the home page; external `next` targets are not followed after login;
- login uses CSRF-protected POST session authentication, exposes only email/password user inputs,
  and defaults to home after success;
- logout rejects GET as a state-changing action, POST logout clears authentication, and its response
  redirects to login;
- an active non-staff user is denied admin while an active staff user with appropriate permissions
  and a superuser follow normal Django admin rules;
- both health endpoints stay callable without authentication and keep the contract-tested statuses,
  methods, and response bodies.

Run and observe at minimum:

```text
.codex/lint.sh
./penni-more.sh check backend
```

### Web GUI behavior

Web tests and reviewer observation must demonstrate:

- the login page has one visibly labeled email field, one visibly labeled password field, one
  submit control, CSRF metadata, sensible autocomplete, and no registration/recovery affordance;
- field and form errors are programmatically associated and usable by screen readers without
  revealing account status;
- the authenticated shell exposes identity and a semantic POST logout form, while the anonymous
  login page does not show authenticated navigation;
- the login layout has no horizontal overflow at existing mobile and desktop viewports, retains a
  useful page title, heading, landmark, skip link, focus order, and visible focus;
- the unauthenticated root redirect lands on the login page with the local return target;
- automated accessibility analysis reports no violations in the tested login state;
- core login and logout markup remains usable when JavaScript is unavailable.

Run and observe at minimum:

```text
.codex/lint.sh
./penni-more.sh check web
./penni-more.sh check integration
```

### Final validation

The deployment agent runs the complete repository check from a state with the required declared
dependencies already installed:

```text
./penni-more.sh check all
```

It must also observe `python manage.py migrate` against a clean test/local database before creating
the initial superuser and confirm `python manage.py makemigrations --check --dry-run` reports no
missing model changes. Operational verification must not use real credentials in command output or
tracked fixtures.

No reviewer may claim a check passed without observing its exit status. A failure is returned to
the owning coder, fixed, and rerun before final validation.

## Risks

- Django cannot safely switch `AUTH_USER_MODEL` after application tables depend on the default
  user. This repository has no installed auth app or dependent financial models today, so the
  custom model and its initial migration must land together before later features.
- Application-only normalization can race or be bypassed. The functional database constraint is
  mandatory; manager and model normalization provide predictable storage and user-facing errors.
- Functional unique constraints can surface as `IntegrityError` under concurrent creation after
  form validation. Admin should validate normally, while the database remains the final authority;
  tests must not weaken the constraint to improve messaging.
- Default authentication middleware can accidentally protect health probes or loop on login. The
  explicit public-view markers and regression tests are required before deployment.
- Rendering logout as a link or allowing GET would enable cross-site logout. Keep a CSRF-protected
  POST form and test method rejection.
- Detailed inactive or duplicate messages can disclose account state. Login errors remain generic;
  duplicate details are shown only inside authenticated admin account management.
- Browser end-to-end login would require provisioning credentials. Do not add a public/test-only
  account creation route or commit credentials merely to simplify Playwright; cover authenticated
  behavior in isolated Django tests.
- Existing databases gain built-in auth, admin, content type, and session tables plus the custom
  user table. Normal deployment backup-before-migration behavior mitigates rollout risk; rollback
  after real users are created can discard their records and therefore requires operator judgment.

## Deferred work

The following are explicitly outside this cycle and do not require task files unless a later defect
or concrete requirement makes them actionable:

- rate limiting and account lockout;
- public registration, invitations, email verification, and self-service recovery;
- API or token authentication;
- profile editing and user-owned financial records;
- audit reporting beyond Django's existing admin log.

## Completion criteria

- The custom user model is active in settings, has no username, authenticates by case-insensitive
  unique email, and is created by a reviewed initial migration with database-enforced uniqueness.
- `createsuperuser` and Django admin can create and manage users without a username; standard
  active, staff, superuser, group, and permission behavior is preserved.
- The server-rendered login page accepts only email and password, uses generic credentials errors,
  safely handles local return targets, and requires no JavaScript.
- All user-facing application pages are private by default; authenticated users reach the existing
  home page; CSRF-protected POST logout returns to login.
- Non-staff users cannot enter admin, and no registration or recovery route exists.
- Both health endpoints remain unauthenticated and contract-compatible; OpenAPI contains no auth
  endpoint or unnecessary security-scheme change.
- Backend, Web GUI, architect, and final deployment reviews have no unresolved blocking findings.
- `.codex/lint.sh`, scoped checks, migration checks, and `./penni-more.sh check all` pass with
  observed results.
- The implementation and required report are committed locally only by the deployment agent, with
  no credentials or unrelated changes included.
