from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"Expected integration marker missing in {path}: {old[:100]!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


# Gateway wiring.
replace_once(
    "apps/gateway/mail_agent_gateway/main.py",
    "from .cloud_sync import GoogleGmailSyncService\n",
    "from .cloud_sync import GoogleGmailSyncService, MicrosoftGraphSyncService\n",
)
replace_once(
    "apps/gateway/mail_agent_gateway/main.py",
    "from .oauth_runtime import current_google_access_token\n",
    "from .oauth_runtime import current_google_access_token, current_microsoft_access_token\n",
)
replace_once(
    "apps/gateway/mail_agent_gateway/main.py",
    "gmail_sync_service = GoogleGmailSyncService(mail_store)\n",
    "gmail_sync_service = GoogleGmailSyncService(mail_store)\n"
    "microsoft_sync_service = MicrosoftGraphSyncService(mail_store)\n",
)
replace_once(
    "apps/gateway/mail_agent_gateway/main.py",
    "    google_client_secret=settings.google_client_secret,\n    audit_log=audit_log,\n)",
    "    google_client_secret=settings.google_client_secret,\n"
    "    audit_log=audit_log,\n"
    "    microsoft_client_id=settings.microsoft_client_id,\n"
    "    microsoft_tenant=settings.microsoft_tenant,\n"
    ")",
)
replace_once(
    "apps/gateway/mail_agent_gateway/main.py",
    "        else:\n            result = await sync_service.sync(_runtime_mailbox(mailbox_id), limit=limit)\n",
    "        elif mailbox.get(\"connector\") == \"microsoft_graph\":\n"
    "            if not settings.microsoft_client_id:\n"
    "                raise RuntimeError(\"Microsoft OAuth is not configured in this MAIL-AGENT build\")\n"
    "            access_token = await current_microsoft_access_token(\n"
    "                mailbox,\n"
    "                vault=vault,\n"
    "                client_id=settings.microsoft_client_id,\n"
    "                tenant=settings.microsoft_tenant,\n"
    "            )\n"
    "            result = await microsoft_sync_service.sync(\n"
    "                mailbox_id=mailbox_id,\n"
    "                access_token=access_token,\n"
    "            )\n"
    "        else:\n"
    "            result = await sync_service.sync(_runtime_mailbox(mailbox_id), limit=limit)\n",
)
replace_once(
    "apps/gateway/mail_agent_gateway/main.py",
    "@app.get(\"/v1/oauth/sessions/{state}\")\n",
    "@app.post(\"/v1/oauth/microsoft/start\")\n"
    "async def start_microsoft_oauth(body: OAuthStartRequest) -> dict:\n"
    "    try:\n"
    "        result = oauth_controller.start_microsoft(body.login_hint)\n"
    "    except RuntimeError as exc:\n"
    "        raise HTTPException(status_code=409, detail=str(exc)) from exc\n"
    "    return {\n"
    "        \"provider\": result.provider,\n"
    "        \"state\": result.state,\n"
    "        \"authorization_url\": result.authorization_url,\n"
    "    }\n\n\n"
    "@app.get(\"/v1/oauth/sessions/{state}\")\n",
)
replace_once(
    "apps/gateway/mail_agent_gateway/main.py",
    "@app.get(\"/v1/system/update\")\n",
    "async def _finish_microsoft_oauth(\n"
    "    *,\n"
    "    state: str | None,\n"
    "    code: str | None,\n"
    "    error: str | None,\n"
    "    error_description: str | None,\n"
    ") -> HTMLResponse:\n"
    "    if not state:\n"
    "        raise HTTPException(status_code=400, detail=\"Missing OAuth state\")\n"
    "    if error:\n"
    "        message = error_description or error\n"
    "        oauth_controller.fail(state=state, provider=\"microsoft\", error=message)\n"
    "        return HTMLResponse(_oauth_result_page(False, \"Microsoft-Anmeldung abgebrochen\", message))\n"
    "    if not code:\n"
    "        oauth_controller.fail(\n"
    "            state=state,\n"
    "            provider=\"microsoft\",\n"
    "            error=\"Authorization code is missing\",\n"
    "        )\n"
    "        return HTMLResponse(\n"
    "            _oauth_result_page(\n"
    "                False,\n"
    "                \"Microsoft-Anmeldung fehlgeschlagen\",\n"
    "                \"Kein Autorisierungscode erhalten.\",\n"
    "            )\n"
    "        )\n"
    "    try:\n"
    "        result = await oauth_controller.complete_microsoft(state=state, code=code)\n"
    "        return HTMLResponse(\n"
    "            _oauth_result_page(\n"
    "                True,\n"
    "                \"Microsoft 365 ist verbunden\",\n"
    "                f\"{result.get('email_address') or 'Das Postfach'} wurde sicher mit MAIL-AGENT verbunden.\",\n"
    "            )\n"
    "        )\n"
    "    except KeyError as exc:\n"
    "        raise HTTPException(status_code=400, detail=\"OAuth session not found or expired\") from exc\n"
    "    except Exception as exc:\n"
    "        return HTMLResponse(\n"
    "            _oauth_result_page(False, \"Microsoft-Anmeldung fehlgeschlagen\", str(exc)),\n"
    "            status_code=502,\n"
    "        )\n\n\n"
    "@app.get(\"/v1/oauth/microsoft/callback\", response_class=HTMLResponse, include_in_schema=False)\n"
    "async def microsoft_oauth_callback(\n"
    "    state: str | None = None,\n"
    "    code: str | None = None,\n"
    "    error: str | None = None,\n"
    "    error_description: str | None = None,\n"
    ") -> HTMLResponse:\n"
    "    return await _finish_microsoft_oauth(\n"
    "        state=state, code=code, error=error, error_description=error_description\n"
    "    )\n\n\n"
    "@app.get(\"/v1/system/update\")\n",
)

# UI: make Microsoft a first-class OAuth mailbox connector.
replace_once(
    "apps/web/app.js",
    "let oauthProviders = { google: { configured: false } };",
    "let oauthProviders = { google: { configured: false }, microsoft: { configured: false } };",
)
replace_once(
    "apps/web/app.js",
    "MAIL-AGENT v0.10.0 · Lokales Gateway",
    "MAIL-AGENT v0.11.0 · Lokales Gateway",
)

app_path = Path("apps/web/app.js")
app = app_path.read_text(encoding="utf-8")
start = app.index("  if (step===2) {\n")
end = app.index("  if (step===3) {\n", start)
new_step = '''  if (step===2) {
    const google=oauthProviders.google||{configured:false};
    const microsoft=oauthProviders.microsoft||{configured:false};
    const gmailConnected=mailboxConnected&&mailboxConnector==='gmail_api';
    const microsoftConnected=mailboxConnected&&mailboxConnector==='microsoft_graph';
    const oauthConnected=gmailConnected||microsoftConnected;
    body = `<div class="card-heading"><span class="card-icon">${icon('inbox',22)}</span><div><h2>Postfach verbinden</h2><p>Gmail und Microsoft 365 werden direkt per OAuth verbunden. Kein App-Passwort und keine Serverdaten nötig.</p></div></div><div class="oauth-grid"><button class="oauth-card ${google.configured?'':'unavailable'}" id="google-connect" data-configured="${google.configured?'1':'0'}" ${busy?'disabled':''}><span class="google-mark">G</span><span><b>${gmailConnected?'Gmail verbunden':'Mit Google anmelden'}</b><small>${gmailConnected?esc(form.emailAddress):google.configured?'Google OAuth 2.0 + PKCE':'Google OAuth ist in diesem Build nicht konfiguriert'}</small></span><span class="oauth-arrow">${gmailConnected?icon('check',17):icon('chevron',17)}</span></button><button class="oauth-card ${microsoft.configured?'':'unavailable'}" id="microsoft-connect" data-configured="${microsoft.configured?'1':'0'}" ${busy?'disabled':''}><span class="ms-mark">M</span><span><b>${microsoftConnected?'Microsoft 365 verbunden':'Mit Microsoft anmelden'}</b><small>${microsoftConnected?esc(form.emailAddress):microsoft.configured?'Microsoft OAuth 2.0 + PKCE · Graph':'Microsoft OAuth ist in diesem Build nicht konfiguriert'}</small></span><span class="oauth-arrow">${microsoftConnected?icon('check',17):icon('chevron',17)}</span></button></div>${oauthConnected?`<div class="success-line">${icon('check',16)} ${esc(form.emailAddress)} ist sicher über ${gmailConnected?'Gmail API':'Microsoft Graph'} verbunden.</div>`:''}<div class="separator"><span>oder manuell per IMAP / SMTP</span></div><div class="form-grid two">${field('E-Mail-Adresse','email-address',form.emailAddress,'email','name@example.com')}${field('Benutzername','mailbox-username',form.mailboxUsername,'text','meist E-Mail-Adresse')}${field('IMAP-Server','imap-host',form.imapHost,'text','imap.example.com')}${field('IMAP-Port','imap-port',form.imapPort,'number')}${field('SMTP-Server','smtp-host',form.smtpHost,'text','smtp.example.com')}${field('SMTP-Port','smtp-port',form.smtpPort,'number')}</div>${field('Passwort / App-Passwort','mailbox-password',form.mailboxPassword,'password','••••••••••••')}<div class="security-note">${icon('lock',18)}<span>OAuth-Tokens und manuelle Mail-Secrets werden ausschließlich verschlüsselt im lokalen Vault gespeichert.</span></div><div class="setup-actions"><button class="btn text" data-back="1">Zurück</button><div class="inline-actions"><button class="btn secondary" id="mailbox-test" ${busy?'disabled':''}>IMAP testen</button><button class="btn primary" id="next" ${!mailboxConnected?'disabled':''}>Weiter${icon('chevron',17)}</button></div></div>`;
  }
'''
app = app[:start] + new_step + app[end:]
app_path.write_text(app, encoding="utf-8")

replace_once(
    "apps/web/app.js",
    "  document.getElementById('google-connect')?.addEventListener('click',connectGoogle);\n",
    "  document.getElementById('google-connect')?.addEventListener('click',connectGoogle);\n"
    "  document.getElementById('microsoft-connect')?.addEventListener('click',connectMicrosoft);\n",
)
replace_once(
    "apps/web/app.js",
    "    const result=await waitForOAuth(start.state,popup);\n",
    "    const result=await waitForOAuth(start.state,popup,'Google');\n",
)
replace_once(
    "apps/web/app.js",
    "async function waitForOAuth(state,popup){\n",
    "async function connectMicrosoft(){\n"
    "  saveVisible();\n"
    "  const configured=document.getElementById('microsoft-connect')?.dataset.configured==='1';\n"
    "  if(!configured){showNotice('Microsoft OAuth ist für diesen Build noch nicht freigeschaltet. Der Projekt-Client muss einmalig konfiguriert werden.','error');return;}\n"
    "  const popup=window.open('about:blank','mail-agent-microsoft','popup=yes,width=560,height=760');\n"
    "  if(!popup){showNotice('Der Browser hat das Microsoft-Anmeldefenster blockiert. Pop-ups für MAIL-AGENT erlauben.','error');return;}\n"
    "  busy=true;render();\n"
    "  try{\n"
    "    const start=await post('/v1/oauth/microsoft/start',{login_hint:form.emailAddress||null});\n"
    "    popup.location.replace(start.authorization_url);\n"
    "    const result=await waitForOAuth(start.state,popup,'Microsoft');\n"
    "    mailboxConnected=true;\n"
    "    mailboxId=result.mailbox_id;\n"
    "    mailboxConnector='microsoft_graph';\n"
    "    form.emailAddress=result.email_address||form.emailAddress;\n"
    "    form.mailboxUsername=form.emailAddress;\n"
    "    showNotice(`Microsoft 365 verbunden: ${form.emailAddress}`);\n"
    "  }catch(e){\n"
    "    try{if(!popup.closed)popup.close();}catch(_){}\n"
    "    showNotice(e.message,'error');\n"
    "  }finally{busy=false;render();}\n"
    "}\n\n"
    "async function waitForOAuth(state,popup,providerLabel='OAuth'){\n",
)
replace_once(
    "apps/web/app.js",
    "    if(session.status==='error')throw new Error(session.error||'Google-Anmeldung fehlgeschlagen.');\n",
    "    if(session.status==='error')throw new Error(session.error||`${providerLabel}-Anmeldung fehlgeschlagen.`);\n",
)
replace_once(
    "apps/web/app.js",
    "  throw new Error('Google-Anmeldung hat zu lange gedauert. Bitte erneut versuchen.');\n",
    "  throw new Error(`${providerLabel}-Anmeldung hat zu lange gedauert. Bitte erneut versuchen.`);\n",
)

# Version synchronization.
for path, old, new in [
    ("pyproject.toml", 'version = "0.10.0"', 'version = "0.11.0"'),
    ("apps/gateway/mail_agent_gateway/main.py", 'APP_VERSION = "0.10.0"', 'APP_VERSION = "0.11.0"'),
    ("apps/launcher/mail_agent_launcher/main.py", 'APP_VERSION = "0.10.0"', 'APP_VERSION = "0.11.0"'),
    ("packages/agent_core/mail_agent_core/identity.py", 'app_version: str = "0.10.0"', 'app_version: str = "0.11.0"'),
    ("packaging/windows/MailAgent.iss", '#define MyAppVersion "0.10.0"', '#define MyAppVersion "0.11.0"'),
]:
    replace_once(path, old, new)

print("MAIL-AGENT 0.11.0 Microsoft 365 integration applied.")
