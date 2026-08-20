/* MAIL-AGENT 0.16 · explicit estimated-savings metric. No DOM observer. */
(() => {
  let latest=null;
  let loadedAt=0;
  const fmt=value=>Number.isFinite(Number(value))?Number(value).toLocaleString('de-DE'):'—';

  async function load(force=false){
    if(!installed)return;
    if(!force&&latest&&Date.now()-loadedAt<15000)return;
    try{latest=await get('/v1/usage?days=7');loadedAt=Date.now();}catch(_){latest=null;}
  }

  function mount(){
    if(!installed||activeView!=='system'||!latest)return;
    const grid=document.querySelector('#ai16-mounted .ai16-grid');
    if(!grid)return;
    let metric=document.getElementById('ai16-estimated-token-savings');
    if(!metric){metric=document.createElement('div');metric.id='ai16-estimated-token-savings';metric.className='ai16-metric';grid.appendChild(metric);}
    const value=latest.local?.estimated_tokens_avoided;
    metric.innerHTML=`<small>7 Tage · Tokens vermieden</small><strong>${fmt(value)}</strong><span>geschätzt · nur sicher übersprungene Codex-Prompts</span>`;
  }

  const originalRender=render;
  render=function efficiencyMetricsRender(){const value=originalRender();queueMicrotask(async()=>{if(activeView==='system'){await load(false);mount();}});return value;};
  document.addEventListener('click',event=>{if(event.target.closest('[data-view="system"]'))setTimeout(async()=>{await load(true);mount();},0);});
  setTimeout(async()=>{await load(true);mount();},850);
})();
