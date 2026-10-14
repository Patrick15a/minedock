'use strict';
const $ = (q) => document.querySelector(q);
const esc = (v) => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const state = {csrf:'', servers:[], host:null, page:'overview', sid:null, tab:'console', cursor:0, query:'', mode:'curseforge', editing:false};
const labels = {overview:'Übersicht', modpacks:'Modpacks', host:'Host & Ressourcen', archive:'Archiv'};
const server = () => state.servers.find(s => s.id === state.sid);
let toastTimer, polling = false;

function toast(message) {
  $('#toast').textContent = message; $('#toast').hidden = false;
  clearTimeout(toastTimer); toastTimer = setTimeout(() => $('#toast').hidden = true, 6500);
}
async function api(url, {method='GET', body, form=false}={}) {
  const headers = {};
  if (method !== 'GET') headers['X-CSRF-Token'] = state.csrf;
  if (body && !form) headers['Content-Type'] = 'application/json';
  const result = await fetch('/api' + url, {method, headers, body:body ? (form ? body : JSON.stringify(body)) : undefined});
  const data = await result.json().catch(() => ({}));
  if (!result.ok) {
    if (result.status === 401 && url !== '/login') showLogin();
    const detail = Array.isArray(data.detail) ? data.detail.map(x => x.msg).join(' · ') : data.detail;
    throw new Error(detail || `Anfrage fehlgeschlagen (${result.status}).`);
  }
  return data;
}
function showLogin() {
  state.csrf = ''; document.title = 'Anmelden · BexoGames MineDock'; $('#shell').hidden = true; $('#login-screen').hidden = false;
  $('#server-dialog').close();
}
async function enter() {
  $('#login-screen').hidden = true; $('#shell').hidden = false;
  await refresh(); render();
}
$('#login-form').addEventListener('submit', async event => {
  event.preventDefault(); const button = event.submitter; button.disabled = true; $('#login-error').textContent = '';
  try {
    const body = Object.fromEntries(new FormData(event.target));
    state.csrf = (await api('/login', {method:'POST', body})).csrf;
    event.target.password.value = ''; await enter();
  } catch (error) { $('#login-error').textContent = error.message; }
  finally { button.disabled = false; }
});
$('#logout').addEventListener('click', async () => {
  try { await api('/logout', {method:'POST'}); showLogin(); } catch (e) { toast(e.message); }
});

function badge(s) {
  const text = s.state === 'running' ? 'Prozess läuft' : s.state === 'busy' ? 'In Bearbeitung' : s.archived ? 'Archiviert' : 'Gestoppt';
  return `<span class="badge ${s.state}"><span class="dot"></span>${text}</span>`;
}
function stat(title, value, suffix, foot, symbol) {
  return `<div class="stat"><div class="stat-top"><span>${title}</span><span>${symbol}</span></div><div class="stat-value">${value} <small>${suffix}</small></div><div class="stat-foot">${foot}</div></div>`;
}
function stats() {
  const active = state.servers.filter(s => !s.archived), running = active.filter(s => s.state === 'running');
  return `<div class="stats">${stat('Deine Server', active.length, 'gesamt', `${running.length} Prozesse gestartet`, '▤')}${stat('RAM reserviert', (state.host.reserved_mb/1024).toFixed(1), `/ ${Math.round(state.host.budget_mb/1024)} GB`, 'Java-Heap + Prozessreserve', '▥')}${stat('RAM verfügbar', (state.host.memory_available_mb/1024).toFixed(1), 'GB', 'Aktuell auf diesem Host', '⌁')}${stat('Speicher frei', state.host.disk_free_gb, 'GB', 'Auf dem Datenlaufwerk', '▱')}</div>`;
}
function connection() {
  return `<span class="connection"><span class="dot connection-dot"></span><span class="connection-label">${state.host?.linux ? 'Panel online' : 'Lokale Vorschau'}</span></span>`;
}
function heading(title, text, action='') {
  return `<div class="page-heading"><div><h1>${title}</h1><p>${text}</p></div><div class="heading-actions">${connection()}${action}</div></div>`;
}
function newButton(label='＋ Server erstellen') { return `<button class="primary" data-new="curseforge">${label}</button>`; }
function cards() {
  const archive = state.page === 'archive';
  const items = state.servers.filter(s => !!s.archived === archive && `${s.name} ${s.pack}`.toLowerCase().includes(state.query.toLowerCase()));
  if (!items.length) return `<div class="empty"><div class="empty-art"><img src="/static/logo.svg" alt=""></div><h3>${state.query ? 'Keine passenden Server' : archive ? 'Dein Archiv ist noch leer' : 'Noch keine Minecraft-Server'}</h3><p>${state.query ? 'Probiere einen anderen Namen oder ein anderes Modpack.' : archive ? 'Archivierte Server behalten ihre Welten und Dateien. Du kannst sie hier weiterhin ansehen und Backups herunterladen.' : 'Importiere dein Lieblingsmodpack von CurseForge oder starte einen eigenen Minecraft-Server. Alles an einem Ort.'}</p>${!archive && !state.query ? newButton('＋ Deinen ersten Server erstellen') : ''}</div>`;
  return `<div class="table-wrap" role="region" aria-label="Serverliste" tabindex="0"><table><thead><tr><th>Server / Modpack</th><th>Status</th><th>RAM</th><th>Java</th><th>Port</th><th><span class="sr-only">Aktionen</span></th></tr></thead><tbody>${items.map(s => `<tr><td class="server-name"><h3>${esc(s.name)}</h3><span class="subline">${esc(s.pack)}${s.version ? ' · ' + esc(s.version) : ''}</span></td><td>${badge(s)}${s.missing.length ? `<span class="subline">${s.missing.length} Dateien fehlen</span>` : !s.installed ? '<span class="subline">Installation ausstehend</span>' : ''}</td><td class="cell-nowrap">${(s.memory_mb/1024).toFixed(1)} GB</td><td>${esc(s.java)}</td><td>${s.port}</td><td class="row-action"><button class="secondary" data-open="${s.id}">Server öffnen ↗</button></td></tr>`).join('')}</tbody></table></div>`;
}
function render() {
  if (!state.host) return;
  document.querySelectorAll('[data-page]').forEach(b => b.classList.toggle('active', b.dataset.page === state.page));
  document.title = `${state.sid ? server()?.name || 'Server' : labels[state.page]} · BexoGames MineDock`;
  $('#nav-count').textContent = state.servers.filter(s => !s.archived).length;
  if (state.sid) return renderDetail();
  if (state.page === 'overview' || state.page === 'archive') {
    $('#main').innerHTML = heading(state.page === 'archive' ? 'Serverarchiv' : 'Serverübersicht', state.page === 'archive' ? 'Deine bisherigen Welten bleiben erhalten.' : 'Deine Welten, Modpacks und Ressourcen im Überblick.', newButton()) +
      (!state.host.linux ? '<div class="notice">Lokale Vorschau auf Windows. Minecraft-Prozesse und Loader-Installer starten erst auf deinem Debian-Server. Die angezeigten Host-Ressourcen gehören zu diesem Rechner.</div>' : '') + stats() +
      `<section class="server-list"><div class="section-heading"><h2>${state.page === 'archive' ? 'Archivierte Server' : 'Deine Server'} <span>Minecraft Java Edition · Server und Modpacks</span></h2><input class="search" id="search" placeholder="Server oder Modpack suchen …" aria-label="Server suchen" value="${esc(state.query)}"></div><div class="cards" id="cards">${cards()}</div></section>` +
      `<div class="hint-row"><div class="hint"><span class="symbol">◇</span><div><h3>Modpacks installieren</h3><p>CurseForge-Dateilink oder ZIP-Export importieren, Ressourcen zuweisen und loslegen.</p><button class="text-button" data-page="modpacks">Zu den Modpacks ↗</button></div></div><div class="hint"><span class="symbol">⌘</span><div><h3>Ressourcen verwalten</h3><p>Direkte Java-Prozesse, lokale Dateien und ein gemeinsames RAM-Budget. Vollständig auf deinem eigenen Host.</p></div></div></div>`;
  } else if (state.page === 'modpacks') {
    $('#main').innerHTML = heading('Modpacks', 'CurseForge-Modpacks importieren und eigene Server installieren.') +
      (!state.host.curseforge_configured ? '<div class="notice">Für CurseForge-Links und Manifest-Downloads fehlt noch der API-Schlüssel auf dem Host. Du kannst die Oberfläche bereits verwenden und eigene Server-JARs hochladen.</div>' : '<div class="notice good">CurseForge-API-Schlüssel ist auf dem Host konfiguriert.</div>') +
      `<div class="grid-three"><article class="option"><span class="symbol">◇</span><h3>Von CurseForge</h3><p>Füge den Link einer konkreten Modpack-Dateiversion ein. Mods und Loader werden aus dem Manifest installiert.</p><button class="primary" data-new="curseforge">Link importieren ↗</button></article><article class="option"><span class="symbol">↥</span><h3>Modpack hochladen</h3><p>Importiere einen CurseForge-ZIP-Export mit manifest.json. Konfigurationen und unterstützte Overrides kommen mit.</p><button class="secondary" data-new="zip">ZIP auswählen ↗</button></article><article class="option"><span class="symbol">▧</span><h3>Eigene Welt starten</h3><p>Installiere einen Vanilla-Server oder lade eine ausführbare Server-JAR hoch. Mods kannst du anschließend einzeln verwalten.</p><button class="secondary" data-new="vanilla">Server erstellen ↗</button></article></div>` +
      `<div class="panel"><h3>Gut zu wissen</h3><p>Forge, NeoForge und Fabric werden anhand des Modpack-Manifests installiert. Wähle eine dazu passende, auf dem Host installierte Java-Version. Client-Mods können über die Mod-Liste deaktiviert werden.</p><p>Einige Autoren erlauben keine automatischen Downloads. Fehlende Dateien erscheinen nach dem Import im Tab „Mods“ mit einem Link zum manuellen Download. Klassische Server-ZIPs mit Startskripten werden nicht automatisch ausgeführt.</p></div>`;
  } else {
    $('#main').innerHTML = heading('Host & Ressourcen', 'Ressourcen und Verbindungen deines Minecraft-Containers.') + stats() +
      `<div class="host-hero"><span class="eyebrow">NATIVES LINUX HOSTING</span><h2>Minecraft-Container</h2><p>MineDock läuft als eigener Dienst. Jeder Minecraft-Server startet als separater Java-Prozess.</p></div><div class="grid-two"><div class="panel"><h3>Host-Konfiguration</h3><div class="kv"><span>Umgebung</span><b>${state.host.linux ? 'Linux' : 'Windows · Vorschau'}</b></div><div class="kv"><span>Minecraft-RAM-Budget</span><b>${state.host.budget_mb/1024} GB</b></div><div class="kv"><span>Gesamter Host-RAM</span><b>${(state.host.memory_total_mb/1024).toFixed(1)} GB</b></div><div class="kv"><span>Konfigurierte Java-Versionen</span><b>${state.host.java_versions.map(esc).join(', ')}</b></div><div class="kv"><span>CurseForge</span><b>${state.host.curseforge_configured ? 'Schlüssel hinterlegt' : 'Schlüssel fehlt'}</b></div></div><div class="panel"><h3>Betrieb & Zugriff</h3><p>Die erste Version verwendet einen Administrator-Zugang. Host-Einstellungen und API-Schlüssel liegen in <code>/etc/minedock/minedock.env</code>.</p><p>Das RAM-Budget reserviert je laufendem Server den Java-Heap plus 768 MB. Es ist eine Startbegrenzung; zusätzliche native Speichernutzung kann darüber hinausgehen.</p><p>Backups entstehen bei gestopptem Server. Vor Wartung am Panel alle Minecraft-Server stoppen.</p><p>MineDock läuft im Minecraft-Container. Euer Apache-Reverse-Proxy übernimmt den HTTPS-Zugriff.</p></div></div>`;
  }
}

function settingsFields(s={}) {
  const ports = state.servers.filter(x => !x.archived).map(x => x.port);
  let nextPort = 25565; while (ports.includes(nextPort)) nextPort++;
  return `<div class="field-grid"><label class="full">Servername<input name="name" required maxlength="60" value="${esc(s.name || '')}" placeholder="z. B. Unsere Survival-Welt"></label><label>Arbeitsspeicher (MB)<input name="memory_mb" type="number" min="1024" max="${Math.min(32768,state.host.budget_mb-768)}" step="256" value="${s.memory_mb || 4096}" required><small>Zusätzlich 768 MB Prozessreserve</small></label><label>Java-Version<select name="java">${state.host.java_versions.map(v => `<option ${v === s.java ? 'selected' : ''} value="${esc(v)}">Java ${esc(v)}</option>`).join('')}</select><small>Muss zum Modpack passen</small></label><label>Server-Port<input name="port" type="number" min="1024" max="65535" required value="${s.port || nextPort}"></label><label>Maximale Spielerzahl<input name="max_players" type="number" min="1" max="500" required value="${s.max_players || 20}"></label><label class="full">Serverbeschreibung<input name="motd" maxlength="120" required value="${esc(s.motd || 'Ein neuer Minecraft-Server')}"></label><label>Schwierigkeit<select name="difficulty">${[['peaceful','Friedlich'],['easy','Einfach'],['normal','Normal'],['hard','Schwer']].map(([v,l]) => `<option value="${v}" ${v === (s.difficulty || 'normal') ? 'selected' : ''}>${l}</option>`).join('')}</select></label><label>Spielmodus<select name="gamemode">${[['survival','Überleben'],['creative','Kreativ'],['adventure','Abenteuer'],['spectator','Zuschauer']].map(([v,l]) => `<option value="${v}" ${v === s.gamemode ? 'selected' : ''}>${l}</option>`).join('')}</select></label></div><label class="check"><input type="checkbox" name="whitelist" ${s.whitelist ? 'checked' : ''}><span>Whitelist aktivieren<small>Spieler über „whitelist add Spielername“ in der Konsole freigeben.</small></span></label><label class="check"><input type="checkbox" name="eula" ${s.eula ? 'checked' : ''}><span>Ich habe die <a href="https://www.minecraft.net/eula" target="_blank" rel="noreferrer">Minecraft-EULA</a> gelesen und stimme ihr zu.<small>Ohne Zustimmung bleibt der Serverstart gesperrt.</small></span></label>`;
}
function formSettings(form) {
  const d = new FormData(form);
  return {name:d.get('name'),port:Number(d.get('port')),memory_mb:Number(d.get('memory_mb')),java:d.get('java'),max_players:Number(d.get('max_players')),motd:d.get('motd'),difficulty:d.get('difficulty'),gamemode:d.get('gamemode'),whitelist:d.has('whitelist'),eula:d.has('eula')};
}
function sourceFields() {
  if (state.mode === 'curseforge') return `<label>CurseForge-Dateilink<input name="source" type="url" required placeholder="https://www.curseforge.com/minecraft/modpacks/…/files/…"><small>Den Link einer bestimmten Version verwenden, nicht die Modpack-Startseite.</small></label>`;
  if (state.mode === 'vanilla') return `<label>Minecraft-Version<input name="version" required placeholder="z. B. 1.21.1"><small>Eine konkrete Java-Edition-Version eintragen.</small></label>`;
  return `<label>${state.mode === 'zip' ? 'CurseForge-Export (.zip)' : 'Ausführbare Server-JAR'}<input name="upload" type="file" accept="${state.mode === 'zip' ? '.zip' : '.jar'}" required><small>${state.mode === 'zip' ? 'Mit manifest.json im ZIP-Hauptverzeichnis. Maximal 512 MB.' : 'Eine direkt startfähige JAR, kein Forge-/NeoForge-Installer. Maximal 512 MB.'}</small></label>`;
}
function openCreate(mode='curseforge', existing=null) {
  state.mode = mode; state.editing = !!existing;
  const dialog = $('#server-dialog'); dialog.dataset.sid = existing?.id || '';
  $('#dialog-title').textContent = existing ? 'Server installieren' : 'Server erstellen';
  $('#create-submit').textContent = existing ? 'Installation starten ↗' : 'Erstellen & installieren ↗';
  $('#server-fields').innerHTML = `<div class="mode-row">${[['curseforge','CurseForge-Link'],['zip','ZIP-Import'],['vanilla','Vanilla'],['custom','Eigene JAR']].map(([m,l]) => `<button type="button" data-mode="${m}" class="${m===mode?'selected':''}">${l}</button>`).join('')}</div><div id="source-fields">${sourceFields()}</div>${!existing ? '<hr class="divider">' + settingsFields() : ''}`;
  $('#form-error').textContent = ''; dialog.showModal();
}
$('#server-fields').addEventListener('click', e => {
  const button = e.target.closest('[data-mode]'); if (!button) return;
  state.mode = button.dataset.mode; $('#source-fields').innerHTML = sourceFields();
  document.querySelectorAll('[data-mode]').forEach(b => b.classList.toggle('selected', b === button));
});
$('#close-dialog').onclick = $('#cancel-dialog').onclick = () => $('#server-dialog').close();
$('#server-form').addEventListener('submit', async event => {
  event.preventDefault(); const button = event.submitter; button.disabled = true; $('#form-error').textContent = '';
  try {
    let sid = $('#server-dialog').dataset.sid;
    if (!sid) {
      sid = (await api('/servers', {method:'POST', body:formSettings(event.target)})).id;
      $('#server-dialog').dataset.sid = sid;
    }
    const d = new FormData(event.target);
    if (state.mode === 'zip' || state.mode === 'custom') {
      const data = new FormData(); data.append('file', d.get('upload'));
      await api(`/servers/${sid}/upload?kind=${state.mode === 'zip' ? 'modpack' : 'server'}`, {method:'POST', body:data, form:true});
    } else await api(`/servers/${sid}/install`, {method:'POST', body:{mode:state.mode,source:d.get('source'),version:d.get('version')}});
    $('#server-dialog').close(); state.sid = sid; state.tab = 'console'; state.cursor = 0;
    await refresh(); render(); toast('Server angelegt. Den Installationsfortschritt findest du in der Konsole.');
  } catch (error) { $('#form-error').textContent = error.message; await refresh().catch(() => {}); }
  finally { button.disabled = false; }
});

function renderDetail() {
  const s = server(); if (!s) { state.sid = null; return render(); }
  $('#main').innerHTML = `<div class="detail-top"><button class="back" data-back aria-label="Zurück">←</button><div><h1>${esc(s.name)}</h1><p>${esc(s.pack)} · Port ${s.port} · Java ${esc(s.java)}</p></div><div class="actions"><span id="detail-badge">${badge(s)}</span><button class="primary" data-action="start">▷ Starten</button><button class="secondary" data-action="restart">↻ Neustart</button><button class="secondary" data-action="stop">□ Stoppen</button></div></div><div id="job-status"></div><div class="tabs">${[['console','Konsole'],['mods','Mods'],['settings','Einstellungen'],['files','Dateien'],['backups','Backups']].map(([v,l]) => `<button data-tab="${v}" class="${v===state.tab?'active':''}">${l}</button>`).join('')}</div><div id="tab-content"></div>`;
  updateDetailStatus(); renderTab();
}
function updateDetailStatus() {
  const s = server(); if (!s || !$('#detail-badge')) return;
  $('#detail-badge').innerHTML = badge(s);
  document.querySelectorAll('[data-action]').forEach(b => {
    b.disabled = s.archived || s.state === 'busy' || (b.dataset.action === 'start' ? s.state === 'running' || !s.installed || s.missing.length || !s.eula : s.state !== 'running');
  });
  $('#job-status').innerHTML = (s.job?.state === 'running' ? `<div class="notice">${esc(s.job.label)} läuft. Du kannst den Fortschritt in der Konsole verfolgen.</div>` : s.job?.state === 'error' ? `<div class="notice error">${esc(s.job.error)}</div>` : '') + (!s.installed && s.state !== 'busy' && !s.archived ? '<div class="notice">Dieser Server ist noch nicht installiert. <button class="text-button" data-install>Installation auswählen ↗</button></div>' : '') + (s.missing.length ? `<div class="notice">${s.missing.length} Dateien fehlen. Bitte im Tab „Mods“ herunterladen und hochladen.</div>` : '') + (s.installed && !s.eula ? '<div class="notice">Vor dem ersten Start bitte die Minecraft-EULA in den Einstellungen bestätigen.</div>' : '');
}
async function renderTab() {
  const s = server(), root = $('#tab-content'); if (!s || !root) return;
  try {
    if (state.tab === 'console') {
      state.cursor = 0;
      root.innerHTML = `<div class="console"><div class="console-head"><span>SERVERKONSOLE</span><small>Letzte 1.200 Zeilen · wird automatisch aktualisiert</small></div><pre id="log-output" aria-label="Serverkonsole">Noch keine Konsolenausgabe.</pre><form id="command-form"><input name="command" autocomplete="off" placeholder="Minecraft-Befehl eingeben, z. B. list" aria-label="Konsolenbefehl" required maxlength="1000"><button class="secondary" type="submit">Senden ↵</button></form></div><p class="console-note">„Prozess läuft“ bestätigt den Java-Prozess. Minecraft ist spielbereit, sobald „Done“ in der Konsole erscheint.</p>`;
      await refreshLogs();
    } else if (state.tab === 'settings') {
      root.innerHTML = `<div class="panel"><h3>Server-Einstellungen</h3><p>Änderungen sind bei gestopptem Server möglich und gelten ab dem nächsten Start.</p><form id="settings-form"><fieldset ${s.state !== 'stopped' || s.archived ? 'disabled' : ''}>${settingsFields(s)}<button class="primary" type="submit">Einstellungen speichern</button></fieldset></form></div>${!s.archived ? '<div class="panel"><h3>Server archivieren</h3><p>Stoppt die Verwaltung dieses Servers und gibt seinen Port frei. Die Dateien bleiben auf dem Host erhalten.</p><button class="danger" data-archive>Ins Archiv verschieben</button></div>' : ''}`;
    } else if (state.tab === 'mods') {
      root.innerHTML = '<div class="panel">Mod-Liste wird geladen …</div>';
      const mods = await api(`/servers/${s.id}/mods`); if (state.tab !== 'mods' || state.sid !== s.id) return;
      root.innerHTML = `<div class="panel"><h3>Deine Mods</h3><p>Zum Hochladen, Aktivieren oder Entfernen den Server stoppen. Mods und Server müssen dieselbe Loader- und Minecraft-Version verwenden.</p>${s.missing.length ? `<div class="notice"><b>Manueller Download erforderlich</b>${s.missing.map(m => `<div class="file-row"><span class="file-name">${esc(m.name)}</span><a href="${esc(m.url)}" target="_blank" rel="noreferrer">CurseForge ↗</a></div>`).join('')}</div>` : ''}<div class="upload-box"><h3>Mod-Dateien hinzufügen</h3><p>JAR-Datei auswählen. Vorhandene Dateien werden nicht überschrieben.</p><input type="file" id="mod-upload" accept=".jar" multiple aria-label="Mod-Dateien hochladen" ${s.state !== 'stopped' || !s.installed || s.archived ? 'disabled' : ''}></div>${mods.length ? mods.map(m => `<div class="file-row"><span class="file-name">${esc(m.name)}<br><small>${m.size_mb} MB · ${m.enabled ? 'Aktiv' : 'Deaktiviert'}</small></span><button class="secondary" data-mod="${esc(m.name)}" data-mod-action="toggle" ${s.state !== 'stopped' || s.archived ? 'disabled' : ''}>${m.enabled ? 'Deaktivieren' : 'Aktivieren'}</button><button class="text-button" data-mod="${esc(m.name)}" data-mod-action="remove" ${s.state !== 'stopped' || s.archived ? 'disabled' : ''}>Entfernen</button></div>`).join('') : '<div class="empty-small">Noch keine Mod-Dateien vorhanden.</div>'}</div>`;
    } else if (state.tab === 'files') {
      const files = await api(`/servers/${s.id}/files`); if (state.tab !== 'files' || state.sid !== s.id) return;
      root.innerHTML = `<div class="panel"><h3>Konfigurationsdateien</h3><p>Textdateien bis 1 MB. Server-Eigenschaften werden über den Tab „Einstellungen“ verwaltet.</p>${files.length ? `<label>Datei auswählen<select id="file-select"><option value="">Bitte auswählen …</option>${files.map(f => `<option value="${esc(f)}">${esc(f)}</option>`).join('')}</select></label><textarea id="file-editor" class="editor" aria-label="Dateiinhalt" spellcheck="false" readonly></textarea><div class="inline-actions"><button class="primary" id="save-file" disabled>Datei speichern</button><small id="file-info"></small></div>` : '<div class="empty-small">Nach der Serverinstallation erscheinen hier die Konfigurationsdateien.</div>'}</div>`;
    } else {
      root.innerHTML = `<div class="panel"><h3>Backups</h3><p>Erstellt ein vollständiges Archiv des Serververzeichnisses. Der Server muss dafür gestoppt sein. Wiederherstellung erfolgt in dieser Version über die Debian-Shell.</p><button class="primary" data-backup ${s.state !== 'stopped' || s.archived ? 'disabled' : ''}>＋ Backup erstellen</button><div id="backup-list"></div></div>`;
      await refreshBackups();
    }
  } catch (e) { toast(e.message); }
}
async function refreshLogs() {
  if (!state.sid || state.tab !== 'console' || !$('#log-output')) return;
  const sid = state.sid, data = await api(`/servers/${sid}/logs?after=${state.cursor}`);
  if (state.sid !== sid || !$('#log-output')) return;
  const log = $('#log-output'), bottom = log.scrollTop + log.clientHeight >= log.scrollHeight - 60;
  if (data.cursor < state.cursor) { state.cursor = 0; log.textContent = ''; return; }
  if (data.lines.length) {
    if (state.cursor === 0) log.textContent = '';
    log.textContent = (log.textContent + data.lines.map(l => l.text).join('\n') + '\n').split('\n').slice(-1201).join('\n');
    if (bottom) log.scrollTop = log.scrollHeight;
  }
  state.cursor = data.cursor;
}
async function refreshBackups() {
  const sid = state.sid, data = await api(`/servers/${sid}/backups`);
  if (!$('#backup-list') || state.sid !== sid) return;
  $('#backup-list').innerHTML = data.length ? data.map(b => `<div class="file-row"><span class="file-name">${esc(b.name)}<br><small>${b.size_mb} MB</small></span><a href="/api/servers/${sid}/backups/${encodeURIComponent(b.name)}">Herunterladen ↓</a></div>`).join('') : '<div class="empty-small">Noch keine Backups erstellt.</div>';
}
async function refresh() {
  const data = await api('/overview'); state.servers = data.servers; state.host = data.host;
  document.querySelectorAll('.connection-label').forEach(el => el.textContent = state.host.linux ? 'Panel online' : 'Lokale Vorschau');
  document.querySelectorAll('.connection-dot').forEach(el => el.classList.remove('offline'));
}
document.addEventListener('click', async event => {
  const b = event.target.closest('button, a.brand'); if (!b || b.disabled) return;
  try {
    if (b.dataset.page || b.matches('.brand') || b.hasAttribute('data-back')) {
      if (b.matches('.brand')) event.preventDefault();
      state.page = b.dataset.page || 'overview'; state.sid = null; state.query = ''; render();
    } else if (b.dataset.new) openCreate(b.dataset.new);
    else if (b.dataset.open) { state.sid = b.dataset.open; state.tab = 'console'; render(); }
    else if (b.dataset.tab) { state.tab = b.dataset.tab; renderDetail(); }
    else if (b.hasAttribute('data-install')) openCreate('curseforge', server());
    else if (b.dataset.action) {
      b.disabled = true; const verb = b.dataset.action; toast(verb === 'start' ? 'Server wird gestartet …' : 'Server wird gestoppt. Das kann bis zu einer Minute dauern …');
      await api(`/servers/${state.sid}/action/${verb}`, {method:'POST'}); await refresh(); updateDetailStatus(); toast('Aktion abgeschlossen. Status in der Konsole prüfen.');
    } else if (b.hasAttribute('data-archive')) {
      if (!confirm('Server archivieren? Seine Dateien bleiben erhalten.')) return;
      await api(`/servers/${state.sid}/action/archive`, {method:'POST'}); await refresh(); state.sid = null; render(); toast('Server archiviert.');
    } else if (b.dataset.mod) {
      if (b.dataset.modAction === 'remove' && !confirm(`„${b.dataset.mod}“ wirklich entfernen?`)) return;
      await api(`/servers/${state.sid}/mods`, {method:'POST',body:{name:b.dataset.mod,action:b.dataset.modAction}}); await renderTab();
    } else if (b.hasAttribute('data-backup')) {
      await api(`/servers/${state.sid}/backup`,{method:'POST'}); await refresh(); renderDetail(); toast('Backup wird erstellt.');
    } else if (b.id === 'save-file') {
      b.disabled = true;
      await api(`/servers/${state.sid}/file`,{method:'PUT',body:{path:$('#file-select').value,content:$('#file-editor').value}}); toast('Datei gespeichert.'); b.disabled = false;
    }
  } catch (e) { toast(e.message); if (b.dataset.action || b.id === 'save-file') b.disabled = false; }
});
document.addEventListener('input', e => {
  if (e.target.id === 'search') { state.query = e.target.value; $('#cards').innerHTML = cards(); }
});
document.addEventListener('change', async e => {
  try {
    if (e.target.id === 'file-select') {
      const path = e.target.value; $('#save-file').disabled = true;
      if (!path) { $('#file-editor').value = ''; $('#file-editor').readOnly = true; return; }
      const sid = state.sid, data = await api(`/servers/${sid}/file?path=${encodeURIComponent(path)}`);
      if (!$('#file-select') || state.sid !== sid || $('#file-select').value !== path) return;
      $('#file-editor').value = data.content;
      const allowed = server().state === 'stopped' && !server().archived && path !== 'server.properties';
      $('#file-editor').readOnly = !allowed; $('#save-file').disabled = !allowed;
      $('#file-info').textContent = allowed ? 'Änderungen gelten ab dem nächsten Serverstart.' : 'Nur Lesen';
    } else if (e.target.id === 'mod-upload') {
      e.target.disabled = true;
      for (const file of e.target.files) {
        const data = new FormData(); data.append('file',file);
        await api(`/servers/${state.sid}/upload?kind=mod`,{method:'POST',body:data,form:true});
      }
      await refresh(); updateDetailStatus(); await renderTab(); toast('Mod-Dateien hochgeladen.');
    }
  } catch (error) { toast(error.message); if (e.target.id === 'mod-upload') e.target.disabled = false; }
});
document.addEventListener('submit', async event => {
  if (!['settings-form','command-form'].includes(event.target.id)) return;
  event.preventDefault(); const b = event.submitter; b.disabled = true;
  try {
    if (event.target.id === 'settings-form') {
      await api(`/servers/${state.sid}`,{method:'PUT',body:formSettings(event.target)}); await refresh(); updateDetailStatus(); toast('Einstellungen gespeichert.');
    } else {
      await api(`/servers/${state.sid}/command`,{method:'POST',body:{command:event.target.command.value}}); event.target.command.value = ''; await refreshLogs();
    }
  } catch (e) { toast(e.message); } finally { b.disabled = false; }
});
setInterval(async () => {
  if (!state.csrf || polling || document.hidden) return;
  polling = true;
  try {
    await refresh();
    if (state.sid) { updateDetailStatus(); await refreshLogs(); if (state.tab === 'backups') await refreshBackups(); }
    else if (!$('#server-dialog').open && !['INPUT','TEXTAREA','SELECT'].includes(document.activeElement.tagName)) render();
  } catch (e) { document.querySelectorAll('.connection-label').forEach(el => el.textContent = 'Verbindung unterbrochen'); document.querySelectorAll('.connection-dot').forEach(el => el.classList.add('offline')); }
  finally { polling = false; }
}, 3500);
(async () => { try { state.csrf = (await api('/session')).csrf; await enter(); } catch { showLogin(); } })();

document.addEventListener('click', event => { const switcher = $('.app-switcher'); if (!switcher.contains(event.target)) switcher.open = false; });
document.addEventListener('keydown', event => { if (event.key === 'Escape') $('.app-switcher').open = false; });
