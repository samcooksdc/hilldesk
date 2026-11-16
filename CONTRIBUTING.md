# Contributing to HillDesk

Thanks for helping. HillDesk is maintained by a volunteer, so small, focused
pull requests are the easiest to review.

## Never include real data

Do not put real constituent, staff or office email, names or addresses in
issues, pull requests, fixtures or screenshots. Use the fictional demo office
(Rep. James Smith, district FR-1, `example.com` addresses). If you find real
data in the repository, report it privately (see [SECURITY.md](SECURITY.md)).

## Set up

```bash
python -m venv venv && source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt -r requirements-dev.txt
python manage.py bootstrap_demo
python manage.py runserver
```

Or run `docker compose up`.

## Before you open a pull request

```bash
python manage.py test --settings=config.settings.testing
python manage.py makemigrations --check --dry-run
ruff check .
```

CI runs these plus security scans (bandit, pip-audit, gitleaks, CodeQL) and a
production-settings boot check.

Optional: `pip install pre-commit && pre-commit install` runs ruff, gitleaks
and a few file checks on every commit.

## Static files

Edit files under `static/`; Django serves them directly in development.
`staticfiles/` is `collectstatic` output (git-ignored), which WhiteNoise serves
in production. When you change a script, bump its `?v=` query in the template
so browsers drop the cached copy.

## Conventions

- **AI is assistive, never decision-making.** Model output is data for a
  person to approve. Never add a path where the model sends mail, edits the
  calendar or changes records without a human action.
- **Inbound email is untrusted.** Escape it in templates, and use
  `script_safe_json` when embedding data in `<script>`.
- **Production AI stays on Amazon Bedrock.** Don't add other providers to
  production settings.
- **PII fields** use `EncryptedCharField`.
- **Audit** sensitive operations through the `security_audit` logger or the
  existing history models.
- **Type hints** on new code, and **tests** with every feature or bug fix.
- **Demo and seed tools** call `require_dev_environment()`.
- New source files start with `# SPDX-License-Identifier: Apache-2.0`.

AI coding assistants are welcome; `CLAUDE.md` describes the conventions they
should follow. You are responsible for what you submit.

## Sign your commits (DCO)

By contributing you certify the
[Developer Certificate of Origin](https://developercertificate.org/): you
wrote the change or have the right to submit it under the Apache-2.0
license. Sign off each commit with `git commit -s`.

## Licensing

Contributions are licensed under [Apache-2.0](LICENSE).
