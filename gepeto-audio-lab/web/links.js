'use strict';
// Links salvos: lista no estilo "servidores do Minecraft" (ícone, nome, endereço e botão de acessar).
(() => {
  const css = `
    .links-section{margin-bottom:34px;padding:24px;background:linear-gradient(115deg,#181b21,#14171c);border:1px solid var(--line);border-radius:13px}
    .links-list{display:grid;gap:8px;margin-top:16px}
    .link-row{display:grid;grid-template-columns:52px 1fr auto auto;gap:14px;align-items:center;padding:12px 14px;border:1px solid var(--line);border-radius:10px;background:#1c2027}
    .link-icon{width:52px;height:52px;border-radius:10px;background:#242a33;display:grid;place-content:center;overflow:hidden;font-size:22px;font-weight:700;color:#202818}
    .link-icon img{width:100%;height:100%;object-fit:contain;padding:6px;background:#fff}
    .link-text{min-width:0}.link-text strong{display:block;font-size:13px;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
    .link-text small{display:block;font-size:11px;color:var(--muted);margin-top:4px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
    .link-row .secondary{padding:9px 14px;gap:8px}.link-row .danger{color:#ff9f9f;padding:9px 11px}
    .link-add{display:flex;gap:12px;margin-top:16px}
    .link-add .yt-input{min-width:0}
    .link-more{margin-top:12px;width:100%;border-style:dashed}
    .link-status{font-size:11px;margin-top:10px;min-height:14px}.link-status.error{color:#ff8181}.link-status.success{color:var(--lime)}
    @media(max-width:760px){.link-row{grid-template-columns:44px 1fr auto}.link-icon{width:44px;height:44px}.link-row .secondary:not(.danger){grid-column:2/-1;grid-row:2}.link-add{flex-direction:column}}
  `;
  const style = document.createElement('style');
  style.textContent = css;
  document.head.append(style);

  const palette = ['#d7f990', '#b99bef', '#81cce0', '#f5bc82', '#ee91ac', '#9dafff', '#9bd5bd'];
  const section = document.createElement('section');
  section.className = 'links-section';
  section.id = 'links';
  section.setAttribute('aria-labelledby', 'links-title');
  section.innerHTML = `
    <div class="section-heading">
      <h2 id="links-title"><span class="step">🔗</span> Links salvos</h2>
      <span class="muted small">Cole um link e ele fica salvo aqui, em todos os aparelhos</span>
    </div>
    <div id="links-list" class="links-list"></div>
    <div id="link-add" class="link-add" hidden>
      <input type="text" id="link-url" class="yt-input" placeholder="Cole o link do site aqui (ex: https://exemplo.com)" aria-label="Link do site" autocomplete="off" autocapitalize="off" spellcheck="false">
      <button id="link-save" class="primary">Salvar</button>
    </div>
    <button id="link-more" class="secondary link-more" hidden>＋ Adicionar outro</button>
    <div id="link-status" class="link-status" role="status"></div>`;
  const anchor = document.getElementById('share') || document.getElementById('setup');
  anchor.parentNode.insertBefore(section, anchor.nextSibling);

  const $ = id => document.getElementById(id);
  let links = [];

  async function api(url, options = {}) {
    const response = await fetch(url, { ...options, headers: { 'X-Gepeto-Local': '1', 'Content-Type': 'application/json', ...options.headers } });
    const data = await response.json();
    if (!response.ok) throw Error(typeof data.detail === 'string' ? data.detail : 'Não foi possível concluir a solicitação.');
    return data;
  }
  function status(text, kind = '') { const box = $('link-status'); box.className = 'link-status ' + kind; box.textContent = text; }

  function render() {
    const list = $('links-list');
    list.replaceChildren();
    for (const link of links) {
      const row = document.createElement('div');
      row.className = 'link-row';
      const icon = document.createElement('div');
      icon.className = 'link-icon';
      if (link.icon) {
        const img = document.createElement('img');
        img.alt = '';
        img.loading = 'lazy';
        img.src = link.icon;
        img.onerror = () => { img.remove(); letter(icon, link); };
        icon.append(img);
      } else letter(icon, link);
      const text = document.createElement('div');
      text.className = 'link-text';
      const name = document.createElement('strong');
      name.textContent = link.name;
      name.title = link.name;
      const address = document.createElement('small');
      address.textContent = link.host;
      address.title = link.url;
      text.append(name, address);
      const open = document.createElement('a');
      open.className = 'secondary';
      open.href = link.url;
      open.target = '_blank';
      open.rel = 'noopener noreferrer';
      open.textContent = 'Acessar site ↗';
      const remove = document.createElement('button');
      remove.className = 'secondary danger';
      remove.textContent = '✕';
      remove.title = 'Remover';
      remove.setAttribute('aria-label', `Remover ${link.name}`);
      remove.onclick = async () => {
        if (!confirm(`Remover "${link.name}" dos links salvos?`)) return;
        try { await api(`/api/links/${link.id}`, { method: 'DELETE' }); await load(); } catch (error) { status(error.message, 'error'); }
      };
      row.append(icon, text, open, remove);
      list.append(row);
    }
    // sem links: o campo já aparece aberto; com links: só o botão "Adicionar outro"
    if (!links.length) { $('link-add').hidden = false; $('link-more').hidden = true; }
    else if ($('link-add').hidden) $('link-more').hidden = false;
  }
  function letter(icon, link) {
    icon.textContent = (link.name.match(/[\p{L}\p{N}]/u) || ['?'])[0].toUpperCase();
    icon.style.background = palette[[...link.host].reduce((sum, ch) => sum + ch.charCodeAt(0), 0) % palette.length];
  }

  async function load() {
    try {
      const fresh = await api('/api/links');
      const signature = list => list.map(link => link.id + link.icon).join('|');
      if (signature(fresh) !== signature(links) || !$('links-list').children.length) { links = fresh; render(); }
    } catch { /* servidor fora do ar: a página principal já avisa */ }
  }

  async function save() {
    const url = $('link-url').value.trim();
    if (!url) { status('Cole o link do site primeiro.', 'error'); return; }
    $('link-save').disabled = true;
    status('Buscando o nome e o ícone do site…');
    try {
      const link = await api('/api/links', { method: 'POST', body: JSON.stringify({ url }) });
      $('link-url').value = '';
      status(`"${link.name}" salvo.`, 'success');
      $('link-add').hidden = true;
      $('link-more').hidden = false;
      links = [link, ...links.filter(item => item.id !== link.id)];
      render();
    } catch (error) { status(error.message, 'error'); }
    finally { $('link-save').disabled = false; }
  }

  $('link-save').onclick = save;
  $('link-url').addEventListener('keydown', event => { if (event.key === 'Enter') save(); });
  $('link-more').onclick = () => { $('link-add').hidden = false; $('link-more').hidden = true; status(''); $('link-url').focus(); };
  load();
  setInterval(load, 5000);
})();
