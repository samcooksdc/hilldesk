# Security Policy

HillDesk processes congressional correspondence, so security reports are
taken seriously.

## Reporting a vulnerability

**Do not open a public issue.** Report privately through GitHub:
**Security → Report a vulnerability** on this repository (private
vulnerability reporting). If you can't use that, email
**samuel@hilldesk.app** with "HillDesk security" in the subject.

Please include the affected version or commit, steps to reproduce, and the
impact you expect. Never include real constituent, staff or office data;
reproduce with the fictional demo office instead.

What to expect:

- An acknowledgment within **7 days**
- An assessment and a planned fix window within **30 days**
- Credit in the release notes if you'd like it, once a fix ships

This is a volunteer project, so these are good-faith targets, not a
contractual commitment.

## Supported versions

Only the latest release on `main` receives security fixes.

## Scope

In scope: the code in this repository, including the email pipeline,
authentication, authorization, the handling of AI output, and the settings
and deployment defaults.

Out of scope: a particular office's deployment, infrastructure or Microsoft
365 tenant. If you find a problem in a live House deployment, report it to
that office and its IT security contacts, not here. Do not test
against systems you are not authorized to test.

## Design notes for researchers

See [docs/security-model.md](docs/security-model.md) for the threat model,
including how inbound email (untrusted input) and AI output are handled.
