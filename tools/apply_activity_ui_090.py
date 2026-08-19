from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, content: str) -> None:
    (ROOT / path).write_text(content, encoding="utf-8")


def replace_once(path: str, old: str, new: str) -> None:
    text = read(path)
    if old not in text:
        raise SystemExit(f"Anchor not found in {path}: {old[:140]!r}")
    write(path, text.replace(old, new, 1))


def replace_all(path: str, old: str, new: str) -> None:
    text = read(path)
    if old not in text:
        raise SystemExit(f"Anchor not found in {path}: {old!r}")
    write(path, text.replace(old, new))


# Gateway: sync observability, trace API/payload and product version.
replace_once(
    "apps/gateway/mail_agent_gateway/main.py",
    '        audit_log.append("mailbox_synced", details=result)\n',
    '        audit_log.append("mailbox_synced", details=result)\n'
    '        synced_count = next(\n'
    '            (int(result.get(key) or 0) for key in ("imported", "inserted", "new_messages", "fetched") if result.get(key) is not None),\n'
    '            None,\n'
    '        )\n'
    '        agent_runtime.activity.record_sync(\n'
    '            mailbox_id=mailbox_id,\n'
    '            status="completed",\n'
    '            detail="Postfach erfolgreich synchronisiert.",\n'
    '            connector=str(mailbox.get("connector") or "imap"),\n'
    '            messages_synced=synced_count,\n'
    '        )\n',
)
replace_once(
    "apps/gateway/mail_agent_gateway/main.py",
    '    except Exception as exc:\n        mail_store.record_sync(\n',
    '    except Exception as exc:\n'
    '        agent_runtime.activity.record_sync(\n'
    '            mailbox_id=mailbox_id,\n'
    '            status="failed",\n'
    '            detail=f"Synchronisierung fehlgeschlagen: {exc}",\n'
    '            connector=str(mailbox.get("connector") or "imap"),\n'
    '        )\n'
    '        mail_store.record_sync(\n',
)
replace_once(
    "apps/gateway/mail_agent_gateway/main.py",
    'APP_VERSION = "0.8.0"',
    'APP_VERSION = "0.9.0"',
)
replace_once(
    "apps/gateway/mail_agent_gateway/main.py",
    '        "recent_activity": agent_runtime.brain.recent_activity(30),\n',
    '        "recent_activity": agent_runtime.brain.recent_activity(30),\n'
    '        "activity": agent_runtime.activity.recent_traces(25),\n'
    '        "activity_summary": agent_runtime.activity.summary(),\n',
)
replace_once(
    "apps/gateway/mail_agent_gateway/main.py",
    '@app.put("/v1/agent/brain")\n',
    '@app.get("/v1/agent/activity")\n'
    'async def get_agent_activity(limit: int = 50, mailbox_id: str | None = None) -> dict:\n'
    '    _configuration_or_409()\n'
    '    return {\n'
    '        "traces": agent_runtime.activity.recent_traces(limit, mailbox_id=mailbox_id),\n'
    '        "summary": agent_runtime.activity.summary(mailbox_id=mailbox_id),\n'
    '    }\n\n\n'
    '@app.put("/v1/agent/brain")\n',
)

# UI version and navigation.
replace_all("apps/web/app.js", "0.8.0", "0.9.0")
replace_once(
    "apps/web/app.js",
    "${navItem('overview','Übersicht','home')}${navItem('inbox','Inbox','inbox',dashboard.messages.length||'')}",
    "${navItem('overview','Übersicht','home')}${navItem('activity','Aktivität','spark',brainStatus?.pending_total||'')}${navItem('inbox','Inbox','inbox',dashboard.messages.length||'')}",
)
replace_once(
    "apps/web/app.js",
    "function viewTitle(){return ({overview:'Übersicht',inbox:'Inbox',approvals:'Freigaben',drafts:'Entwürfe',settings:'Einstellungen'})[activeView]||'Übersicht';}",
    "function viewTitle(){return ({overview:'Übersicht',activity:'Agent Activity',inbox:'Inbox',approvals:'Freigaben',drafts:'Entwürfe',settings:'Einstellungen'})[activeView]||'Übersicht';}",
)
replace_once(
    "apps/web/app.js",
    "  if(activeView==='inbox') content=",
    "  if(activeView==='activity') content=renderActivityCenter();\n  if(activeView==='inbox') content=",
)

TRACE_UI = r'''
const activityStageLabels={queued:'Eingeplant',sync:'Synchronisierung',context:'Thread-Kontext',brain:'Brain-Kontext',llm:'LLM-Analyse',proposal:'Vorschlag',rule:'Regel',policy:'Policy Engine',artifact:'Aktion / Artefakt',finished:'Ergebnis'};
function activityOutcomeLabel(outcome=''){
  return ({draft_created:'Entwurf erstellt',approval_required:'Freigabe nötig',executed:'Ausgeführt',no_action:'Keine Aktion',blocked:'Blockiert',below_confidence:'Konfidenz zu niedrig',ignored:'Ignoriert',error:'Fehler',sync_completed:'Synchronisiert'})[outcome]||outcome||'Läuft';
}
function agentTraceCard(trace){
  const statusClass=trace.status==='failed'||trace.outcome==='error'?'bad':trace.status==='running'?'running':'ok';
  const title=trace.subject||'Postfach-Synchronisierung';
  const meta=[trace.sender,trace.provider&&trace.model?`${trace.provider} / ${trace.model}`:trace.provider].filter(Boolean).join(' · ');
  const steps=(trace.steps||[]).map(step=>{
    const duration=step.duration_ms!==null&&step.duration_ms!==undefined?` · ${Math.round(step.duration_ms)} ms`:'';
    const state=step.status==='failed'||step.status==='blocked'?'bad':step.status==='running'?'running':'ok';
    return `<div class="activity-step ${state}"><span class="activity-dot"></span><div><b>${esc(activityStageLabels[step.stage]||step.stage||'Schritt')}</b><small>${esc(step.detail||'')}${esc(duration)}</small></div></div>`;
  }).join('');
  return `<article class="activity-trace"><div class="activity-trace-head"><div><span class="activity-time">${esc(trace.started_at?new Date(trace.started_at).toLocaleString():'')}</span><h4>${esc(title)}</h4><p>${esc(meta)}</p></div><span class="activity-outcome ${statusClass}">${esc(activityOutcomeLabel(trace.outcome))}</span></div>${steps}<div class="activity-why"><b>Warum?</b><span>${esc(trace.reason||'Der Lauf ist noch nicht abgeschlossen.')}</span></div></article>`;
}
function renderActivityCenter(){
  const brain=brainStatus||{};
  const summary=brain.activity_summary||{};
  const traces=brain.activity||[];
  const pending=Number(brain.pending_total||0);
  const avg=summary.avg_llm_ms===null||summary.avg_llm_ms===undefined?'—':`${Math.round(summary.avg_llm_ms)} ms`;
  const failures=Number(summary.failed||0);
  const running=Number(summary.running||0);
  return `<div class="activity-center">
    <section class="activity-hero panel"><div><span class="hero-kicker">LOCAL AGENT OBSERVABILITY</span><h2>Was der Agent tut – und warum.</h2><p>Jeder Schritt bleibt lokal nachvollziehbar. Mailtexte, Prompts, SOUL/MEMORY-Inhalte und Zugangsdaten werden nicht in Activity-Traces gespeichert.</p><div class="hero-actions"><button class="btn primary" id="activity-run-agent">Agent jetzt arbeiten lassen</button><button class="btn secondary" id="activity-refresh">Aktualisieren</button></div></div><div class="hero-orb">${icon('spark',34)}</div></section>
    <div class="stats-grid">${metric('Backlog',pending,'Mails warten auf Analyse','inbox')}${metric('Traces',summary.trace_count||0,'zuletzt protokollierte Mail-Läufe','spark')}${metric('LLM Ø',avg,'gemessene Analysezeit','sync')}${metric('Fehler',failures,running?`${running} Lauf/Läufe aktiv`:'keine laufenden Traces','shield')}</div>
    <section class="panel full"><div class="panel-head"><div><span>ENTSCHEIDUNGS-TIMELINE</span><h3>Letzte Agentenläufe</h3></div><span class="badge ${pending?'':'soft'}">${esc(pending)} WARTEN</span></div>${traces.length?traces.map(agentTraceCard).join(''):emptyState('spark','Noch keine Traces','Synchronisiere dein Postfach oder starte den Agenten. Jeder neue Lauf erscheint dann hier.')}</section>
  </div>`;
}
'''
replace_once(
    "apps/web/app.js",
    "function brainLearningCard(item)",
    TRACE_UI + "\nfunction brainLearningCard(item)",
)
replace_once(
    "apps/web/app.js",
    "if(activeView==='settings')await Promise.all([runtimeSettings?Promise.resolve():loadRuntimeSettings(true),loadBrainStatus(true)]);",
    "if(['settings','activity'].includes(activeView))await Promise.all([runtimeSettings?Promise.resolve():loadRuntimeSettings(true),loadBrainStatus(true)]);",
)
replace_once(
    "apps/web/app.js",
    "  document.getElementById('brain-refresh-activity')?.addEventListener('click',async()=>{await loadBrainStatus(false);render();});\n",
    "  document.getElementById('brain-refresh-activity')?.addEventListener('click',async()=>{await loadBrainStatus(false);render();});\n"
    "  document.getElementById('activity-run-agent')?.addEventListener('click',runAgentNow);\n"
    "  document.getElementById('activity-refresh')?.addEventListener('click',async()=>{await loadBrainStatus(false);render();});\n",
)

CSS = r'''

/* MAIL-AGENT 0.9 Activity Center */
.activity-center{display:grid;gap:18px}
.activity-hero{display:flex;justify-content:space-between;align-items:center;gap:24px;padding:28px}
.activity-hero h2{margin:6px 0 8px;font-size:28px}
.activity-hero p{max-width:760px;color:var(--muted);line-height:1.55}
.activity-trace{border:1px solid rgba(137,166,214,.16);background:rgba(7,12,21,.48);border-radius:18px;padding:18px;margin-top:12px}
.activity-trace-head{display:flex;align-items:flex-start;justify-content:space-between;gap:16px;margin-bottom:14px}
.activity-trace-head h4{font-size:16px;margin:4px 0}
.activity-trace-head p,.activity-time{color:var(--muted);font-size:12px;margin:0}
.activity-outcome{font-size:11px;font-weight:800;letter-spacing:.04em;text-transform:uppercase;padding:7px 10px;border-radius:999px;background:rgba(74,222,128,.1);color:#86efac;white-space:nowrap}
.activity-outcome.bad{background:rgba(251,113,133,.12);color:#fda4af}
.activity-outcome.running{background:rgba(96,165,250,.12);color:#93c5fd}
.activity-step{position:relative;display:grid;grid-template-columns:18px 1fr;gap:10px;padding:8px 0 8px 4px}
.activity-step:not(:last-of-type)::after{content:"";position:absolute;left:8px;top:24px;bottom:-8px;width:1px;background:rgba(137,166,214,.2)}
.activity-dot{width:9px;height:9px;border-radius:50%;margin-top:5px;background:#4ade80;box-shadow:0 0 12px rgba(74,222,128,.35)}
.activity-step.bad .activity-dot{background:#fb7185;box-shadow:0 0 12px rgba(251,113,133,.35)}
.activity-step.running .activity-dot{background:#60a5fa;box-shadow:0 0 12px rgba(96,165,250,.35)}
.activity-step b{display:block;font-size:13px}
.activity-step small{display:block;color:var(--muted);line-height:1.45;margin-top:2px}
.activity-why{display:flex;gap:10px;align-items:flex-start;margin-top:12px;padding:11px 12px;border-radius:12px;background:rgba(96,165,250,.07);border:1px solid rgba(96,165,250,.12)}
.activity-why b{font-size:12px;color:#93c5fd}
.activity-why span{font-size:12px;color:var(--muted);line-height:1.45}
@media(max-width:760px){.activity-hero{align-items:flex-start}.activity-trace-head{flex-direction:column}.activity-outcome{align-self:flex-start}}
'''
css_path = "apps/web/agent-settings.css"
css = read(css_path)
if "/* MAIL-AGENT 0.9 Activity Center */" not in css:
    write(css_path, css.rstrip() + CSS + "\n")

# Version synchronization.
replace_once("pyproject.toml", 'version = "0.8.0"', 'version = "0.9.0"')
replace_once(
    "apps/launcher/mail_agent_launcher/main.py",
    'APP_VERSION = "0.8.0"',
    'APP_VERSION = "0.9.0"',
)
replace_once(
    "packages/agent_core/mail_agent_core/identity.py",
    'app_version: str = "0.8.0"',
    'app_version: str = "0.9.0"',
)
replace_once(
    "packaging/windows/MailAgent.iss",
    '#define MyAppVersion "0.8.0"',
    '#define MyAppVersion "0.9.0"',
)

# Source-level regression contract for the gateway/UI wiring.
write(
    "tests/test_activity_center_contract.py",
    '''from pathlib import Path\n\n\ndef test_activity_center_gateway_and_ui_are_wired():\n    gateway = Path("apps/gateway/mail_agent_gateway/main.py").read_text(encoding="utf-8")\n    ui = Path("apps/web/app.js").read_text(encoding="utf-8")\n    assert '@app.get("/v1/agent/activity")' in gateway\n    assert 'agent_runtime.activity.recent_traces(25)' in gateway\n    assert "activity:'Agent Activity'" in ui\n    assert 'renderActivityCenter()' in ui\n    assert 'Was der Agent tut – und warum.' in ui\n\n\ndef test_activity_center_version_is_synchronized():\n    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")\n    gateway = Path("apps/gateway/mail_agent_gateway/main.py").read_text(encoding="utf-8")\n    launcher = Path("apps/launcher/mail_agent_launcher/main.py").read_text(encoding="utf-8")\n    installer = Path("packaging/windows/MailAgent.iss").read_text(encoding="utf-8")\n    assert 'version = "0.9.0"' in pyproject\n    assert 'APP_VERSION = "0.9.0"' in gateway\n    assert 'APP_VERSION = "0.9.0"' in launcher\n    assert '#define MyAppVersion "0.9.0"' in installer\n''',
)

print("MAIL-AGENT 0.9.0 Activity Center UI integration applied.")
