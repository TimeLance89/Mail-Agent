/* MAIL-AGENT Owner Intelligence & Efficiency. No DOM MutationObserver by design. */
(() => {
  const state = { status:null, usage:null, loading:false, lastUsageAt:0 };
  const roles = [
    ['classification','Klassifikation'],
    ['normal','Normale Analyse'],
    ['complex','Komplexe Threads'],
    ['draft','Antwortentwürfe'],
    ['owner_profile','Owner-Profil'],
  ];
  const esc16 = value => String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
  const fmt = value => Number.isFinite(Number(value)) ? Number(value).toLocaleString('de-DE') : '—';
  const pct = value => Number.isFinite(Number(value)) ? `${Number(value).toLocaleString('de-DE',{maximumFractionDigits:1})} %` : 'unbekannt';
  const endpoint = (routing, role) => routing?.[role] || null;

  async function loadStatus(force=false) {
    if (state.loading || (!force && state.status)) return;
    state.loading=true;
    try { state.status=await get('/v1/adaptive/status'); } catch (_) { state.status=null; }
    finally { state.loading=false; }
  }
  async function loadUsage(force=false) {
    if (!force && state.usage && Date.now()-state.lastUsageAt<15000) return;
    try { state.usage=await get('/v1/usage?days=7'); state.lastUsageAt=Date.now(); } catch (_) { state.usage=null; }
  }

  function sourceBadge(source) {
    if (source==='provider_reported') return '<span class="ai16-badge good">Provider gemeldet</span>';
    if (source==='estimated') return '<span class="ai16-badge warn">geschätzt</span>';
    if (source==='mixed') return '<span class="ai16-badge warn">gemischt</span>';
    return '<span class="ai16-badge">unbekannt</span>';
  }

  function ownerProfileHtml(profile) {
    const preview=profile?.preview||[];
    const active=profile?.active||[];
    const status=profile?.status||'not_asked';
    let content='';
    if (!profile?.consent) {
      content=`<div class="ai16-note">Historische E-Mails werden nur nach deiner ausdrücklichen Zustimmung analysiert. Rohinhalte werden nicht im Owner-Profil gespeichert; gelernte Punkte landen nicht automatisch in MEMORY.md und können Policy, Approval, Security oder Agent-ID niemals ändern.</div><div class="ai16-actions" style="margin-top:14px"><button class="ai16-btn primary" id="ai16-consent-yes">Analyse erlauben</button><button class="ai16-btn" id="ai16-consent-no">Nicht verwenden</button></div>`;
    } else if (status==='preview_ready') {
      content=`<div class="ai16-note">Vorschau aus ${fmt(profile.sample_count)} eigenen gesendeten Nachrichten. Jeder Punkt bleibt bis zur Bestätigung inaktiv.</div><div id="ai16-candidates">${preview.length?preview.map((item,i)=>`<label class="ai16-choice"><input type="checkbox" data-owner-enable="${i}" ${item.enabled!==false?'checked':''}><span><input type="text" data-owner-value="${i}" value="${esc16(item.value)}"><small>${esc16(item.rationale||'Abstrahiertes, wiederkehrendes Muster')} · Konfidenz ${pct((item.confidence||0)*100)} · ${fmt(item.evidence_count)} Belege</small><div class="ai16-source">${(item.source_refs||[]).map(esc16).join(' · ')}</div></span></label>`).join(''):'<div class="ai16-empty">Keine ausreichend stabilen Merkmale gefunden.</div>'}</div><div class="ai16-actions" style="margin-top:14px"><button class="ai16-btn primary" id="ai16-profile-activate" ${preview.length?'':'disabled'}>Auswahl aktivieren</button><button class="ai16-btn" id="ai16-profile-relearn">Neu analysieren</button><button class="ai16-btn danger" id="ai16-profile-delete">Profil verwerfen</button></div>`;
    } else if (status==='active') {
      content=`<div class="ai16-note">Aktiviertes, vom Besitzer bestätigtes Profil · Version ${fmt(profile.profile_version)}. Es ist ausschließlich beratender Kontext.</div>${active.map(item=>`<div class="ai16-row"><b>${esc16(item.key)}</b><code>${esc16(item.value)}</code><span class="ai16-badge good">bestätigt</span></div>`).join('')||'<div class="ai16-empty">Keine aktiven Punkte.</div>'}<div class="ai16-actions" style="margin-top:14px"><button class="ai16-btn" id="ai16-profile-relearn">Neu lernen</button><button class="ai16-btn danger" id="ai16-profile-delete">Profil löschen</button></div>`;
    } else {
      content=`<div class="ai16-note">Zustimmung ist aktiv. MAIL-AGENT analysiert erst dann historische eigene Nachrichten, wenn du die Vorschau ausdrücklich startest.</div><div class="ai16-actions" style="margin-top:14px"><button class="ai16-btn primary" id="ai16-profile-preview">Vorschau erstellen</button><button class="ai16-btn danger" id="ai16-profile-delete">Zustimmung & Profil zurücksetzen</button></div>`;
    }
    return `<section class="ai16-surface"><div class="ai16-head"><div><h3>Lerne mich kennen</h3><p>Optionales Owner-Profil aus einer begrenzten Auswahl eigener gesendeter E-Mails. Preview und Bestätigung sind zwingend.</p></div><span class="ai16-badge ${status==='active'?'good':''}">${esc16(status)}</span></div><div class="ai16-body">${content}</div></section>`;
  }

  function routingHtml(status) {
    const routing=status?.model_routing||{mode:'automatic'};
    return `<section class="ai16-surface"><div class="ai16-head"><div><h3>Modellstrategie</h3><p>Automatisch reduziert teure Aufrufe zuerst deterministisch, dann lokal und nutzt das konfigurierte Hauptmodell nur wenn nötig. Expertenmodus überschreibt einzelne Rollen. Nicht verifizierbare Expert-Modelle fallen sicher auf das Hauptmodell zurück.</p></div><span class="ai16-badge">${esc16(status?.configured_provider||'—')} · ${esc16(status?.configured_model||'default')}</span></div><div class="ai16-body"><div class="ai16-actions" style="margin-bottom:15px"><button class="ai16-btn ${routing.mode==='automatic'?'primary':''}" data-ai16-mode="automatic">Automatisch · empfohlen</button><button class="ai16-btn ${routing.mode==='expert'?'primary':''}" data-ai16-mode="expert">Expertenmodus</button></div><div class="ai16-routes">${roles.map(([key,label])=>{const ep=endpoint(routing,key);return `<div class="ai16-route"><label>${label}</label><select data-route-provider="${key}" ${routing.mode!=='expert'?'disabled':''}><option value="">Fallback</option><option value="ollama" ${ep?.provider==='ollama'?'selected':''}>Ollama</option><option value="codex" ${ep?.provider==='codex'?'selected':''}>Codex</option></select><input data-route-model="${key}" value="${esc16(ep?.model||'')}" placeholder="Fallback / Modellname" ${routing.mode!=='expert'?'disabled':''}></div>`}).join('')}</div><div class="ai16-actions" style="margin-top:15px"><button class="ai16-btn primary" id="ai16-routing-save">Strategie speichern</button></div></div></section>`;
  }

  function usageHtml(data) {
    if (!data) return `<section class="ai16-surface"><div class="ai16-body"><div class="ai16-empty">Usage-Daten werden geladen …</div></div></section>`;
    const local=data.local||{}, today=data.today||{}, codex=data.codex||{}, account=codex.account_usage||{};
    const primary=codex.rate_limits?.primary, secondary=codex.rate_limits?.secondary;
    const lowest=[primary?.remaining_percent,secondary?.remaining_percent].filter(v=>Number.isFinite(Number(v))).sort((a,b)=>a-b)[0];
    const quotaClass=Number.isFinite(Number(lowest)) && Number(lowest)<=10?'danger':Number.isFinite(Number(lowest))&&Number(lowest)<=20?'warn':'good';
    const routes=Object.entries(local.routes||{}).sort((a,b)=>b[1]-a[1]);
    const tasks=Object.entries(local.tasks||{}).sort((a,b)=>b[1]-a[1]);
    const providerTotal=account.totalTokens??account.total_tokens??account.totalTokenCount??account.usage?.totalTokens??null;
    const tokenSource=local.prompt_tokens==null?'unknown':(local.token_coverage||'unknown');
    const windowRow=(name,w)=>w?`<div class="ai16-row"><b>${name}</b><code>${pct(w.used_percent)} genutzt · ${pct(w.remaining_percent)} verbleibend${w.window_duration_minutes?` · ${fmt(w.window_duration_minutes)} min Fenster`:''}${w.resets_at?` · Reset ${new Date(Number(w.resets_at)*1000).toLocaleString('de-DE')}`:''}</code>${sourceBadge(w.source)}</div>`:`<div class="ai16-row"><b>${name}</b><code>Vom installierten Codex-Client nicht gemeldet</code><span class="ai16-badge">unbekannt</span></div>`;
    const accountRow=providerTotal==null?`<div class="ai16-row"><b>Codex Tokens gesamt</b><code>Vom installierten Codex-Client nicht gemeldet</code><span class="ai16-badge">unbekannt</span></div>`:`<div class="ai16-row"><b>Codex Tokens gesamt</b><code>${fmt(providerTotal)}</code>${sourceBadge('provider_reported')}</div>`;
    return `<div class="ai16-stack"><section class="ai16-surface"><div class="ai16-head"><div><h3>LLM-Verbrauch & Effizienz</h3><p>Provider-Werte, lokale Messung und Schätzungen werden strikt getrennt. MAIL-AGENT erzeugt keine Fantasie-Quota.</p></div><span class="ai16-badge ${quotaClass}">${Number.isFinite(Number(lowest))?`${pct(lowest)} kleinstes Restfenster`:'Quota unbekannt'}</span></div><div class="ai16-grid"><div class="ai16-metric"><small>Heute · LLM-Aufrufe</small><strong>${fmt(today.today_llm_calls??today.llm_calls)}</strong><span>${fmt(today.today_events)} Entscheidungen</span></div><div class="ai16-metric"><small>7 Tage · LLM-Aufrufe</small><strong>${fmt(local.llm_calls)}</strong><span>${fmt(local.decision_events)} Entscheidungen</span></div><div class="ai16-metric"><small>Codex vermieden</small><strong>${pct(local.codex_avoidance_percent)}</strong><span>${fmt(local.codex_calls_avoided)} Entscheidungen</span></div><div class="ai16-metric"><small>Ø Analysezeit</small><strong>${local.avg_duration_ms==null?'—':`${fmt(local.avg_duration_ms)} ms`}</strong><span>lokal gemessen</span></div></div><div class="ai16-body">${windowRow('Codex Primärfenster',primary)}${windowRow('Codex Sekundärfenster',secondary)}<div class="ai16-row"><b>Codex Usage RPC</b><code>${esc16(codex.detail||'Keine Details')}</code>${sourceBadge(codex.source)}</div>${accountRow}<div class="ai16-row"><b>Tokens lokal</b><code>${local.prompt_tokens==null?'nicht verfügbar':`${fmt(local.prompt_tokens)} Prompt · ${fmt(local.completion_tokens)} Completion`}</code>${sourceBadge(tokenSource)}</div></div></section><section class="ai16-surface"><div class="ai16-head"><div><h3>Wo Aufrufe entstehen</h3><p>Nur Metadaten und Counts; keine Mailtexte, Betreffzeilen oder Absender im Usage-Log.</p></div><button class="ai16-btn" id="ai16-usage-refresh">Aktualisieren</button></div><div class="ai16-body"><table class="ai16-table"><thead><tr><th>Route</th><th>Entscheidungen</th></tr></thead><tbody>${routes.map(([k,v])=>`<tr><td>${esc16(k)}</td><td>${fmt(v)}</td></tr>`).join('')||'<tr><td colspan="2">Noch keine Daten</td></tr>'}</tbody></table><table class="ai16-table" style="margin-top:16px"><thead><tr><th>Aufgabenklasse</th><th>LLM-Aufrufe</th></tr></thead><tbody>${tasks.map(([k,v])=>`<tr><td>${esc16(k)}</td><td>${fmt(v)}</td></tr>`).join('')||'<tr><td colspan="2">Noch keine Daten</td></tr>'}</tbody></table></div></section></div>`;
  }

  function onboardingBanner(profile) {
    if (!profile || profile.asked) return '';
    return `<div class="ai16-banner" id="ai16-owner-banner"><div><strong>Möchtest du, dass MAIL-AGENT deinen Stil kennenlernt?</strong><p>Optional: begrenzte Analyse eigener gesendeter E-Mails → Vorschau → du bestätigst oder änderst jeden Lernpunkt.</p></div><div class="ai16-actions"><button class="ai16-btn primary" id="ai16-banner-yes">Ja, Vorschau vorbereiten</button><button class="ai16-btn" id="ai16-banner-no">Nein</button></div></div>`;
  }

  function mount() {
    if (!installed || !state.status) return;
    const host=document.querySelector('.wb-content');
    if (!host) return;
    document.getElementById('ai16-mounted')?.remove();
    const node=document.createElement('div'); node.id='ai16-mounted';
    if (activeView==='settings') {
      node.className='ai16-stack'; node.innerHTML=ownerProfileHtml(state.status.owner_profile)+routingHtml(state.status); host.appendChild(node);
    } else if (activeView==='system') {
      node.innerHTML=usageHtml(state.usage); host.appendChild(node);
    } else if (activeView==='overview') {
      const banner=onboardingBanner(state.status.owner_profile);
      if (banner) { node.innerHTML=banner; host.prepend(node); } else return;
    } else return;
    bind(node);
  }

  function currentReview() {
    const preview=state.status?.owner_profile?.preview||[];
    return preview.map((item,i)=>({
      ...item,
      enabled:document.querySelector(`[data-owner-enable="${i}"]`)?.checked!==false,
      value:document.querySelector(`[data-owner-value="${i}"]`)?.value?.trim()||item.value,
    }));
  }
  function routingPayload(mode) {
    const routing={mode};
    roles.forEach(([role])=>{
      if (mode==='expert') {
        const provider=document.querySelector(`[data-route-provider="${role}"]`)?.value||'';
        const model=document.querySelector(`[data-route-model="${role}"]`)?.value?.trim()||'';
        routing[role]=(provider&&model)?{provider,model}:null;
      } else {
        routing[role]=endpoint(state.status?.model_routing,role);
      }
    });
    return routing;
  }

  function bind(root) {
    root.querySelector('#ai16-consent-yes')?.addEventListener('click',async()=>{await post('/v1/owner-profile/consent',{enabled:true,actor:'local-user'});await reload(true);showNotice('Owner-Profil-Lernen ist freigegeben. Es wurde noch nichts gelernt.');});
    root.querySelector('#ai16-consent-no')?.addEventListener('click',async()=>{await post('/v1/owner-profile/consent',{enabled:false,actor:'local-user'});await reload(true);});
    root.querySelector('#ai16-banner-yes')?.addEventListener('click',async()=>{await post('/v1/owner-profile/consent',{enabled:true,actor:'local-user'});activeView='settings';await reload(true);render();});
    root.querySelector('#ai16-banner-no')?.addEventListener('click',async()=>{await post('/v1/owner-profile/consent',{enabled:false,actor:'local-user'});await reload(true);});
    const preview=async()=>{root.classList.add('ai16-loading');try{await post('/v1/owner-profile/preview',{limit:30,actor:'local-user'});await reload(true);showNotice('Owner-Profil-Vorschau erstellt. Noch nichts ist aktiv.');}catch(error){showNotice(error.message,'error');}finally{root.classList.remove('ai16-loading');}};
    root.querySelector('#ai16-profile-preview')?.addEventListener('click',preview);
    root.querySelector('#ai16-profile-relearn')?.addEventListener('click',preview);
    root.querySelector('#ai16-profile-activate')?.addEventListener('click',async()=>{try{await post('/v1/owner-profile/activate',{candidates:currentReview()});await reload(true);showNotice('Bestätigtes Owner-Profil aktiviert.');}catch(error){showNotice(error.message,'error');}});
    root.querySelector('#ai16-profile-delete')?.addEventListener('click',async()=>{try{await request('/v1/owner-profile?actor=local-user',{method:'DELETE'});await reload(true);showNotice('Owner-Profil vollständig gelöscht.');}catch(error){showNotice(error.message,'error');}});
    root.querySelectorAll('[data-ai16-mode]').forEach(button=>button.addEventListener('click',()=>{const routing=state.status.model_routing||{};state.status.model_routing={...routing,mode:button.dataset.ai16Mode};mount();}));
    root.querySelector('#ai16-routing-save')?.addEventListener('click',async()=>{try{const mode=state.status?.model_routing?.mode||'automatic';await put('/v1/settings/model-routing',{routing:routingPayload(mode),actor:'local-user'});await reload(true);showNotice('Modellstrategie gespeichert.');}catch(error){showNotice(error.message,'error');}});
    root.querySelector('#ai16-usage-refresh')?.addEventListener('click',async()=>{await loadUsage(true);mount();});
  }

  async function reload(force=false) {
    await loadStatus(force);
    if (activeView==='system') await loadUsage(force);
    mount();
  }

  const originalRender=render;
  render=function adaptiveRender(){const value=originalRender();queueMicrotask(async()=>{await loadStatus(false);if(activeView==='system')await loadUsage(false);mount();});return value;};
  document.addEventListener('click',event=>{if(event.target.closest('[data-view="system"]'))setTimeout(()=>loadUsage(true).then(mount),0);});
  setTimeout(()=>reload(true),700);
})();
