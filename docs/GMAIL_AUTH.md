# Gmail OAuth

MAIL-AGENT connects Gmail accounts through Google's OAuth 2.0 installed-app flow. End users do not
enter IMAP hosts, SMTP ports, Google passwords, or app passwords.

## End-user flow

1. Click **Mit Google anmelden** in onboarding.
2. MAIL-AGENT opens Google's authorization page in the system browser.
3. The user selects a Google account and grants Gmail access.
4. Google redirects to MAIL-AGENT's loopback listener on `127.0.0.1`.
5. MAIL-AGENT exchanges the authorization code using PKCE, reads the Gmail profile, encrypts the
   refresh/access token set in the local credential vault, and creates the mailbox automatically.
6. Future syncs refresh access tokens without prompting the user again.

The requested scope is `https://www.googleapis.com/auth/gmail.modify`. It supports reading,
composing, sending, and modifying mail while avoiding the broader `https://mail.google.com/` scope
that also permits permanent deletion without Trash.

## One-time release-owner setup

Google requires every OAuth application to have a Google-issued OAuth client ID. This is an
application identity, not a per-user API key.

For release builds:

1. Create/select the MAIL-AGENT project in Google Cloud.
2. Enable the Gmail API.
3. Configure the OAuth consent screen.
4. Create an OAuth client with application type **Desktop app**.
5. Add the client ID to the GitHub repository variable `GOOGLE_OAUTH_CLIENT_ID` (a repository secret
   with the same name is also accepted).
6. Rebuild the installer.

The build pipeline embeds only the desktop client ID. Runtime environment variable
`MAIL_AGENT_GOOGLE_CLIENT_ID` overrides it for development builds.

For public distribution, Google's verification requirements for restricted Gmail scopes must be
completed before treating the OAuth application as production-ready. Test users can be used while
the consent screen remains in testing mode.

## Security properties

- Authorization Code flow with PKCE (`S256`).
- Random per-login `state` value for CSRF protection.
- System browser, not an embedded credential webview.
- Loopback redirect on `127.0.0.1` for the desktop application.
- Gmail password is never requested by MAIL-AGENT.
- OAuth tokens are stored only in the encrypted local credential vault.
- Refresh tokens are required so background synchronization can continue without repeated login.
- The remote agent registry never receives Gmail tokens or message contents.
