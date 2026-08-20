(() => {
  const VERSION = '0.13.9';
  const providers = [
    {id:'gmail', name:'Gmail / Google Workspace', mark:'G', mode:'oauth', oauth:'google', domains:['gmail.com','googlemail.com'], hint:'Sicher per Google OAuth verbinden. Kein Mail-Passwort und keine Serverdaten nötig.'},
    {id:'microsoft', name:'Outlook / Microsoft 365', mark:'M', mode:'oauth', oauth:'microsoft', domains:['outlook.com','outlook.de','hotmail.com','hotmail.de','live.com','live.de','msn.com'], hint:'Sicher per Microsoft OAuth und Graph verbinden. Wird nur angeboten, wenn der MAIL-AGENT Microsoft-Client im Build aktiviert ist.'},
    {id:'gmx', name:'GMX', mark:'GMX', domains:['gmx.de','gmx.net','gmx.at','gmx.ch'], imapHost:'imap.gmx.net', imapPort:993, smtpHost:'mail.gmx.net', smtpPort:465, hint:'Bei GMX muss POP3/IMAP im Web-Postfach aktiviert sein.'},
    {id:'webde', name:'WEB.DE', mark:'WEB', domains:['web.de'], imapHost:'imap.web.de', imapPort:993, smtpHost:'smtp.web.de', smtpPort:465, hint:'Bei WEB.DE muss POP3/IMAP im Web-Postfach aktiviert sein.'},
    {id:'yahoo', name:'Yahoo Mail', mark:'Y!', domains:['yahoo.com','yahoo.de','ymail.com','rocketmail.com'], imapHost:'imap.mail.yahoo.com', imapPort:993, smtpHost:'smtp.mail.yahoo.com', smtpPort:465, passwordLabel:'App-Passwort', hint:'Yahoo verlangt für externe Mailprogramme normalerweise ein App-Passwort.'},
    {id:'icloud', name:'Apple iCloud Mail', mark:'', domains:['icloud.com','me.com','mac.com'], imapHost:'imap.mail.me.com', imapPort:993, smtpHost:'smtp.mail.me.com', smtpPort:587, passwordLabel:'App-spezifisches Passwort', hint:'iCloud benötigt ein app-spezifisches Passwort. Port 587 wird automatisch mit STARTTLS verwendet.'},
    {id:'ionos', name:'IONOS', mark:'I', domains:[], imapHost:'imap.ionos.de', imapPort:993, smtpHost:'smtp.ionos.de', smtpPort:465, hint:'Für IONOS Mail Basic und Mail Business. Benutzername ist normalerweise die vollständige E-Mail-Adresse.'},
    {id:'strato', name:'STRATO', mark:'S', domains:[], imapHost:'imap.strato.de', imapPort:993, smtpHost:'smtp.strato.de', smtpPort:465, hint:'Für STRATO Hosting- und Mail-Postfächer mit verschlüsseltem IMAP/SMTP.'},
    {id:'telekom', name:'Telekom Mail', mark:'T', domains:['t-online.de','magenta.de'], imapHost:'secureimap.t-online.de', imapPort:993, smtpHost:'securesmtp.t-online.de', smtpPort:465, passwordLabel:'Passwort für E-Mail-Programme', hint:'Telekom verwendet für externe Programme ein separates „Passwort für E-Mail-Programme“.'},
    {id:'mailbox', name:'mailbox.org', mark:'mb', domains:['mailbox.org'], imapHost:'imap.mailbox.org', imapPort:993, smtpHost:'smtp.mailbox.org', smtpPort:465, hint:'Direkte verschlüsselte IMAP-/SMTP-Verbindung zu mailbox.org.'},
    {id:'fastmail', name:'Fastmail', mark:'F', domains:['fastmail.com','fastmail.fm'], imapHost:'imap.fastmail.com', imapPort:993, smtpHost:'smtp.fastmail.com', smtpPort:465, passwordLabel:'App-Passwort', hint:'Fastmail verlangt für IMAP/SMTP ein eigenes App-Passwort; das normale Kontopasswort funktioniert nicht.'},
    {id:'custom', name:'Anderer Anbieter', mark:'…', domains:[], custom:true, hint:'MAIL-AGENT unterstützt jeden Anbieter mit IMAP und SMTP. Serverdaten können unter „Erweitert“ eingetragen werden.'},
  ];

  let selectedProvider = null;
  let explicitChoice = false;
  let advancedOpen = false;

  const byId = id => providers.find(item => item.id === id);
  const labelFor = id => document.getElementById(id)?.closest('label');
  const input = id => document.getElementById(id);

  function domainOf(address) {
    const value = String(address || '').trim().toLowerCase();
    const at = value.lastIndexOf('@');
    return at > -1 ? value.slice(at + 1) : '';
  }

  function detectProvider(address) {
    const domain = domainOf(address);
    if (!domain) return null;
    return providers.find(item => item.domains?.includes(domain)) || null;
  }

  function setValue(id, value) {
    const el = input(id);
    if (!el) return;
    el.value = String(value ?? '');
    el.dispatchEvent(new Event('input', {bubbles:true}));
  }

  function nativeOAuth(provider) {
    return document.getElementById(provider.oauth === 'google' ? 'google-connect' : 'microsoft-connect');
  }

  function oauthAvailable(provider) {
    const native = nativeOAuth(provider);
    return !!native && native.dataset.configured === '1';
  }

  function oauthConnected(provider) {
    const native = nativeOAuth(provider);
    return !!native && /verbunden/i.test(native.textContent || '');
  }

  function updateFormVisibility(provider) {
    const password = labelFor('mailbox-password');
    const username = labelFor('mailbox-username');
    const advanced = ['imap-host','imap-port','smtp-host','smtp-port'].map(labelFor).filter(Boolean);
    const test = document.getElementById('mailbox-test');

    if (!provider) {
      if (password) password.hidden = true;
      if (username) username.hidden = true;
      advanced.forEach(el => { el.hidden = true; });
      if (test) test.hidden = true;
      return;
    }

    if (provider.mode === 'oauth') {
      if (password) password.hidden = true;
      if (username) username.hidden = true;
      advanced.forEach(el => { el.hidden = true; });
      if (test) test.hidden = true;
      return;
    }

    if (password) password.hidden = false;
    if (username) username.hidden = !(provider.custom || advancedOpen);
    advanced.forEach(el => { el.hidden = !(provider.custom || advancedOpen); });
    if (test) {
      test.hidden = false;
      test.textContent = 'Postfach verbinden';
    }
  }

  function applyPreset(provider, {preserveUsername=false} = {}) {
    if (!provider || provider.mode === 'oauth') return;
    const email = input('email-address')?.value.trim() || '';
    if (!preserveUsername || !input('mailbox-username')?.value.trim()) setValue('mailbox-username', email);
    if (!provider.custom) {
      setValue('imap-host', provider.imapHost);
      setValue('imap-port', provider.imapPort);
      setValue('smtp-host', provider.smtpHost);
      setValue('smtp-port', provider.smtpPort);
    }
    const passwordLabel = labelFor('mailbox-password')?.querySelector(':scope > span');
    if (passwordLabel) passwordLabel.textContent = provider.passwordLabel || 'Passwort / App-Passwort';
    updateFormVisibility(provider);
  }

  function renderGuidance(root, provider) {
    const target = root.querySelector('#provider-guidance');
    if (!target) return;
    if (!provider) {
      target.innerHTML = '<div class="provider-guidance neutral"><b>Einfach starten</b><span>E-Mail-Adresse eingeben – bei bekannten Domains erkennt MAIL-AGENT den Anbieter automatisch. Alternativ oben direkt auswählen.</span></div>';
      return;
    }

    if (provider.mode === 'oauth') {
      const available = oauthAvailable(provider);
      const connected = oauthConnected(provider);
      const label = connected ? `${provider.name} verbunden` : provider.oauth === 'google' ? 'Mit Google verbinden' : 'Mit Microsoft verbinden';
      target.innerHTML = `<div class="provider-guidance ${available ? 'ok' : 'warn'}"><div><b>${provider.name}</b><span>${provider.hint}</span></div><button class="btn ${connected ? 'secondary' : 'primary'}" id="provider-oauth-action" ${(!available || connected) ? 'disabled' : ''}>${label}</button></div>`;
      target.querySelector('#provider-oauth-action')?.addEventListener('click', () => nativeOAuth(provider)?.click());
      return;
    }

    const connectionLabel = provider.custom ? 'Manuelle Serverdaten' : `${provider.imapHost}:${provider.imapPort} · ${provider.smtpHost}:${provider.smtpPort}`;
    target.innerHTML = `<div class="provider-guidance ok"><div><b>${provider.name} ist vorbereitet</b><span>${provider.hint}</span><small>${connectionLabel}</small></div></div>`;
  }

  function refresh(root) {
    const provider = byId(selectedProvider);
    root.querySelectorAll('[data-mail-provider]').forEach(card => {
      const item = byId(card.dataset.mailProvider);
      card.classList.toggle('selected', item?.id === selectedProvider);
      const disabled = item?.mode === 'oauth' && !oauthAvailable(item);
      card.classList.toggle('unavailable', !!disabled);
      card.setAttribute('aria-pressed', item?.id === selectedProvider ? 'true' : 'false');
      card.querySelector('.provider-card-state').textContent = disabled ? 'Noch nicht aktiviert' : (item?.id === selectedProvider ? 'Ausgewählt' : '');
    });
    const state = root.querySelector('#provider-detect-state');
    if (state) {
      const detected = detectProvider(input('email-address')?.value);
      state.textContent = detected ? `Automatisch erkannt: ${detected.name}` : (provider ? `Ausgewählt: ${provider.name}` : 'Noch kein Anbieter gewählt');
    }
    const advanced = root.querySelector('#provider-advanced-toggle');
    if (advanced) {
      advanced.hidden = !provider || provider.mode === 'oauth';
      advanced.textContent = advancedOpen || provider?.custom ? 'Erweiterte Serverdaten ausblenden' : 'Erweiterte Serverdaten anzeigen';
    }
    updateFormVisibility(provider);
    renderGuidance(root, provider);
  }

  function choose(root, id, explicit=true) {
    const provider = byId(id);
    if (!provider) return;
    selectedProvider = id;
    if (explicit) explicitChoice = true;
    if (!provider.mode) applyPreset(provider);
    refresh(root);
  }

  function providerCards() {
    return providers.map(provider => `<button type="button" class="provider-card" data-mail-provider="${provider.id}" aria-pressed="false"><span class="provider-mark">${provider.mark}</span><span class="provider-card-copy"><b>${provider.name}</b><small>${provider.mode === 'oauth' ? 'OAuth · kein Mail-Passwort' : provider.custom ? 'IMAP / SMTP manuell' : 'Automatisch vorkonfiguriert'}</small></span><span class="provider-card-state"></span></button>`).join('');
  }

  function enhanceSetup() {
    const email = input('email-address');
    const test = document.getElementById('mailbox-test');
    if (!email || !test) return;
    if (document.getElementById('mail-provider-assistant')) return;

    const nativeGrid = document.querySelector('.oauth-grid');
    if (nativeGrid) nativeGrid.classList.add('provider-native-oauth');
    const separator = document.querySelector('.separator');
    if (separator) separator.classList.add('provider-native-separator');

    const firstGrid = email.closest('.form-grid');
    if (!firstGrid) return;
    const root = document.createElement('section');
    root.id = 'mail-provider-assistant';
    root.className = 'mail-provider-assistant';
    root.innerHTML = `<div class="provider-head"><div><span class="kicker">AUTOMATISCHE EINRICHTUNG</span><h3>Mailanbieter auswählen</h3><p>Server, Ports und sichere Verbindung werden automatisch gesetzt.</p></div><span id="provider-detect-state" class="provider-detect-state"></span></div><div class="provider-grid">${providerCards()}</div><div id="provider-guidance"></div><button type="button" class="provider-advanced-toggle" id="provider-advanced-toggle">Erweiterte Serverdaten anzeigen</button>`;
    firstGrid.parentNode.insertBefore(root, firstGrid);

    const footer = document.querySelector('.setup-foot');
    if (footer) footer.textContent = `MAIL-AGENT v${VERSION} · Lokales Gateway`;

    root.querySelectorAll('[data-mail-provider]').forEach(card => card.addEventListener('click', () => choose(root, card.dataset.mailProvider, true)));
    root.querySelector('#provider-advanced-toggle')?.addEventListener('click', () => {
      advancedOpen = !advancedOpen;
      refresh(root);
    });

    email.addEventListener('input', () => {
      const detected = detectProvider(email.value);
      if (detected && !explicitChoice) {
        selectedProvider = detected.id;
        if (!detected.mode) applyPreset(detected);
      } else if (selectedProvider && !byId(selectedProvider)?.mode) {
        const provider = byId(selectedProvider);
        if (provider && !provider.custom) setValue('mailbox-username', email.value.trim());
      }
      refresh(root);
    });

    if (!selectedProvider) {
      const detected = detectProvider(email.value);
      if (detected) selectedProvider = detected.id;
    }
    const current = byId(selectedProvider);
    if (current && !current.mode) applyPreset(current, {preserveUsername:true});
    refresh(root);
  }

  function boot() {
    enhanceSetup();
    const app = document.getElementById('app');
    if (!app) return;
    new MutationObserver(() => enhanceSetup()).observe(app, {childList:true});
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot, {once:true});
  else boot();
})();
