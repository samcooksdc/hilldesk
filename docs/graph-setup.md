# Microsoft Graph and Entra ID setup

HillDesk uses two Entra ID (Azure AD) app registrations: one for staff
sign-in and one for the server's access to mail and calendars. Your tenant
administrators create both. In a House tenant that means working with House IT.

## 1. Sign-in app (OIDC)

- Platform: Web. Redirect URI: `https://<your-host>/auth/oidc/callback/`
- ID tokens: enabled. Delegated permissions: `openid`, `profile`, `email`.
- Create a client secret.
- Set `AZURE_AD_TENANT_ID`, `AZURE_AD_CLIENT_ID` and
  `AZURE_AD_CLIENT_SECRET`.

The first time a staffer signs in, a HillDesk account is created for them
with no office or role. An administrator assigns both (see
[office-setup.md](office-setup.md)).

## 2. Graph app (server-to-server)

HillDesk uses the client-credentials flow, so these are **application**
permissions and need admin consent:

| Permission | Why |
| --- | --- |
| `Mail.Read` | Read the shared scheduling mailbox(es) and create change-notification subscriptions |
| `Mail.Send` | Send a reply, only when a staffer clicks send |
| `Calendars.ReadWrite` | Create, update and remove approved events on staff calendars (`ENABLE_CALENDAR_SYNC`) |

Create a client secret, or better, a certificate. Then set
`MICROSOFT_GRAPH_TENANT_ID`, `MICROSOFT_GRAPH_CLIENT_ID` and
`MICROSOFT_GRAPH_CLIENT_SECRET`.

If you don't want calendar sync, set `ENABLE_CALENDAR_SYNC=False` and leave
out `Calendars.ReadWrite`.

## 3. Restrict the app to the mailboxes it needs (required)

Application permissions apply to **every mailbox in the tenant** by default.
Limit them in Exchange Online before going live:

1. Create a mail-enabled security group that contains the shared scheduling
   mailbox(es). If calendar sync is on, add the staff whose calendars
   HillDesk writes to.
2. Restrict the app to that group with Exchange Online RBAC for Applications
   (Microsoft's current recommendation), or with an application access
   policy:

   ```powershell
   New-ApplicationAccessPolicy -AppId <graph-app-client-id> `
     -PolicyScopeGroupId hilldesk-mailboxes@your-office.example.com `
     -AccessRight RestrictAccess `
     -Description "HillDesk: scheduling mailbox and staff calendars only"
   Test-ApplicationAccessPolicy -AppId <graph-app-client-id> -Identity someone-else@your-office.example.com
   ```

   The test against a mailbox outside the group should return **Denied**.

## 4. Tell HillDesk which mailboxes to read

```
SCHEDULING_MAILBOXES=scheduling@your-office.example.com
INTERNAL_EMAIL_DOMAINS=your-office.example.com
```

HillDesk sweeps these mailboxes every `INGEST_SWEEP_MINUTES` (default 5) and
reads nothing else.

## 5. Optional: webhooks

Sweeps are always on. Change notifications only reduce latency:

```
GRAPH_WEBHOOK_ENABLED=True
GRAPH_WEBHOOK_NOTIFICATION_URL=https://<your-host>/api/webhooks/graph/
GRAPH_WEBHOOK_CLIENT_STATE=<random secret>
```

Graph must be able to reach that URL from the internet. Many locked-down
deployments can't allow that, so leave webhooks off and rely on sweeps.

To check connectivity without changing any data:
`python manage.py probe_graph_invites --mailbox scheduling@your-office.example.com`
