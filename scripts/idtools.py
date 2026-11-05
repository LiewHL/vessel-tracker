"""Load / Hide / Export for the emailed reports.

The report only contains codes (e.g. MR05). A reader can press **Load** and pick their own Excel
(.xlsx) or .csv list with the headings Code, ST.ID, ST.N and SF.I in row 1. The browser then shows
"MR05 · <ST.ID> · <ST.N>" wherever a code appears and adds an "SF.I" column.

**Export** (always available) saves the report's tables as one Excel file on the reader's computer:
a summary (one row per code) plus the sheets passed in (positions, port calls, countries ...).
After Load, ST.ID / ST.N / SF.I columns are added next to the code. The emails carry no Excel.

Everything happens in the reader's browser: nothing is uploaded, stored or sent, and closing the tab
clears it. No outside library is used (the .xlsx reader/writer is built in), so it also works offline.
"""
import html
import json

CSS = """
  .ldbar { display:flex; flex-wrap:wrap; gap:6px 10px; align-items:center; margin:-6px 0 14px; font-size:13px; }
  .ldbar button { font:inherit; font-size:13px; padding:4px 12px; border:1px solid var(--line, #dde3e8); border-radius:7px;
                   background:#fff; color:var(--accent, #0b4f7a); cursor:pointer; }
  .ldbar button:hover { background:#f0f5f9; }
  .ldbar .ldnote { color:var(--muted, #5b6b78); font-size:12px; }
  .ldbar .ldwarn { color:#a15c00; font-size:12px; }
  .ld-staff { color:var(--muted, #5b6b78); font-size:12px; }
  @media print {
    .ldbar { display:none !important; }
    body.ld-on::after { content:"Confidential \\2013  do not forward"; position:fixed; left:0; right:0; bottom:0;
                         text-align:center; font-size:10px; color:#a00; }
  }
"""

JS = r"""
(function () {
  const ROWS = __ROWS__, SHEETS = __SHEETS__, NAME = __NAME__;
  const $ = id => document.getElementById(id);
  const bar = $('ldbar'), inp = $('ld-file'), note = $('ld-note');
  const bLoad = $('ld-load'), bHide = $('ld-hide'), bExp = $('ld-export');
  const CODES = [...new Set(ROWS.map(r => r.Code))].sort((a, b) => b.length - a.length);
  const esc = s => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const RX = CODES.length ? new RegExp('(^|[^A-Za-z0-9-])(' + CODES.map(esc).join('|') + ')(?![A-Za-z0-9-])', 'g') : null;
  let list = null, on = false, changed = [], done = new WeakSet(), obs = null;

  // ---------- reading .xlsx (zip + XML) and .csv ----------
  async function inflate(u8) {
    const s = new Blob([u8]).stream().pipeThrough(new DecompressionStream('deflate-raw'));
    return await new Response(s).text();
  }
  async function unzip(buf, want) {
    const dv = new DataView(buf), td = new TextDecoder(), out = {};
    let eocd = -1;
    for (let i = buf.byteLength - 22; i >= Math.max(0, buf.byteLength - 65557); i--) if (dv.getUint32(i, true) === 0x06054b50) { eocd = i; break; }
    if (eocd < 0) throw new Error('not an Excel (.xlsx) file');
    let p = dv.getUint32(eocd + 16, true);
    for (let k = dv.getUint16(eocd + 10, true); k > 0; k--) {
      const method = dv.getUint16(p + 10, true), size = dv.getUint32(p + 20, true), nl = dv.getUint16(p + 28, true),
            el = dv.getUint16(p + 30, true), cl = dv.getUint16(p + 32, true), lho = dv.getUint32(p + 42, true);
      const name = td.decode(new Uint8Array(buf, p + 46, nl));
      p += 46 + nl + el + cl;
      if (!want(name)) continue;
      const data = new Uint8Array(buf, lho + 30 + dv.getUint16(lho + 26, true) + dv.getUint16(lho + 28, true), size);
      out[name] = method === 0 ? td.decode(data) : await inflate(data);
    }
    return out;
  }
  const tags = (node, name) => [...node.getElementsByTagNameNS('*', name)];
  const xml = s => new DOMParser().parseFromString(s, 'application/xml');
  async function readXlsx(buf) {
    const f = await unzip(buf, n => n === 'xl/workbook.xml' || n === 'xl/_rels/workbook.xml.rels' || n === 'xl/sharedStrings.xml' || n.startsWith('xl/worksheets/'));
    let path = 'xl/worksheets/sheet1.xml';
    try {
      const sh = tags(xml(f['xl/workbook.xml']), 'sheet')[0];
      const rid = sh.getAttribute('r:id') || [...sh.attributes].find(a => a.localName === 'id').value;
      const rel = tags(xml(f['xl/_rels/workbook.xml.rels']), 'Relationship').find(r => r.getAttribute('Id') === rid);
      const t = rel.getAttribute('Target');
      path = t.startsWith('/') ? t.slice(1) : 'xl/' + t.replace(/^\.\//, '');
    } catch (e) { /* fall back to sheet1 */ }
    if (!f[path]) throw new Error('could not find the first sheet');
    const ss = f['xl/sharedStrings.xml'] ? tags(xml(f['xl/sharedStrings.xml']), 'si').map(si => tags(si, 't').map(t => t.textContent).join('')) : [];
    const colIdx = ref => { let n = 0; for (const ch of ref.replace(/\d+/g, '')) n = n * 26 + ch.charCodeAt(0) - 64; return n - 1; };
    return tags(xml(f[path]), 'row').map(row => {
      const out = [];
      tags(row, 'c').forEach((c, i) => {
        const t = c.getAttribute('t'), ref = c.getAttribute('r'), v = tags(c, 'v')[0];
        let val = '';
        if (t === 's') val = v ? (ss[+v.textContent] || '') : '';
        else if (t === 'inlineStr') val = tags(c, 't').map(x => x.textContent).join('');
        else if (v) { val = v.textContent; const n = Number(val); if ((!t || t === 'n') && Number.isFinite(n) && Number.isInteger(n)) val = String(n); }
        out[ref ? colIdx(ref) : i] = val;
      });
      return Array.from(out, x => (x == null ? '' : String(x)).trim());
    });
  }
  function readCsv(text) {
    text = text.replace(/^\ufeff/, '');
    const first = text.split(/\r?\n/)[0] || '', sep = first.includes(';') && !first.includes(',') ? ';' : ',';
    const rows = []; let row = [], cell = '', q = false;
    for (let i = 0; i < text.length; i++) {
      const c = text[i];
      if (q) { if (c === '"' && text[i + 1] === '"') { cell += '"'; i++; } else if (c === '"') q = false; else cell += c; }
      else if (c === '"') q = true;
      else if (c === sep) { row.push(cell.trim()); cell = ''; }
      else if (c === '\n' || c === '\r') { if (c === '\r' && text[i + 1] === '\n') i++; row.push(cell.trim()); rows.push(row); row = []; cell = ''; }
      else cell += c;
    }
    if (cell || row.length) { row.push(cell.trim()); rows.push(row); }
    return rows;
  }
  function toList(rows) {
    const hi = rows.findIndex(r => r.some(c => /^code$/i.test(c)));
    if (hi < 0) throw new Error('no "Code" heading found in row 1');
    const h = rows[hi].map(c => c.toLowerCase());
    const col = name => h.findIndex(c => c.replace(/[\s.]/g, '') === name);
    const ic = h.findIndex(c => c === 'code'), ii = col('stid'), iname = col('stn'), it = col('sfi');
    if (ii < 0 && iname < 0) throw new Error('no "ST.ID" or "ST.N" heading found');
    const map = {}, dup = [];
    rows.slice(hi + 1).forEach(r => {
      const code = (r[ic] || '').trim();
      if (!code) return;
      if (map[code]) dup.push(code);
      const get = i => i >= 0 ? (r[i] || '').trim() : '';
      map[code] = { id: get(ii), name: get(iname), staff: get(it) };
    });
    return { map, dup, hasId: ii >= 0, hasName: iname >= 0, hasStaff: it >= 0 };
  }

  // ---------- showing IDs on the page ----------
  function skip(n) { const el = n.nodeType === 1 ? n : n.parentElement; return !el || el.closest('#ldbar, script, style, textarea'); }
  function swapText(root) {
    if (!RX) return;
    const w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    const nodes = [];
    for (let n = root.nodeType === 3 ? root : w.nextNode(); n; n = w.nextNode()) nodes.push(n);
    nodes.forEach(n => {
      if (done.has(n) || skip(n)) return;
      RX.lastIndex = 0;
      const t = n.data.replace(RX, (m, pre, code) => { const x = list.map[code]; return pre + code + (x ? [x.id, x.name].filter(Boolean).map(v => ' · ' + v).join('') : ''); });
      if (t !== n.data) { changed.push([n, n.data]); n.data = t; done.add(n); }
    });
  }
  const codeIn = s => { if (!RX) return ''; RX.lastIndex = 0; const m = RX.exec(s || ''); return m ? m[2] : ''; };
  const staffOf = code => (list.map[code] && list.map[code].staff) || '';
  function addStaff() {
    if (!list.hasStaff) return;
    document.querySelectorAll('details.ship').forEach(d => {
      const sum = d.querySelector(':scope > summary'); if (!sum) return;
      const b = sum.querySelector('b');
      const code = d.dataset.id || (d.dataset.view || '').replace(/^s:/, '') || codeIn(b && b.textContent);
      const st = staffOf(code); if (!st) return;
      const sp = document.createElement('span'); sp.className = 'ld-add ld-staff'; sp.textContent = ' · SF.I: ' + st;
      (b && b.nextSibling) ? sum.insertBefore(sp, b.nextSibling.nextSibling || null) : sum.appendChild(sp);
      const kv = d.querySelector('dl.kv');
      if (kv) { const dt = document.createElement('dt'), dd = document.createElement('dd'); dt.className = dd.className = 'ld-add';
        dt.textContent = 'SF.I'; dd.textContent = st; kv.prepend(dt, dd); dt.after(dd); }
    });
    document.querySelectorAll('table').forEach(tb => {
      if (skip(tb)) return;
      const ths = [...tb.querySelectorAll('thead th')], idx = ths.findIndex(th => /^(ID|Code)$/i.test(th.textContent.trim()));
      if (idx < 0) return;
      const th = document.createElement('th'); th.className = 'ld-add'; th.textContent = 'SF.I'; ths[idx].after(th);
      tb.querySelectorAll('tbody tr').forEach(tr => {
        const c = tr.children[idx]; if (!c) return;
        const td = document.createElement('td'); td.className = 'ld-add'; td.textContent = staffOf(codeIn(c.textContent)); c.after(td);
      });
    });
  }
  function show() {
    on = true; document.body.classList.add('ld-on');
    addStaff(); swapText(document.body);
    obs = new MutationObserver(ms => ms.forEach(m => m.addedNodes.forEach(n => { if (on && !skip(n)) swapText(n); })));
    obs.observe(document.body, { childList:true, subtree:true });
    bHide.hidden = false;
  }
  function hide() {
    on = false; if (obs) obs.disconnect();
    changed.forEach(([n, t]) => { n.data = t; }); changed = []; done = new WeakSet();
    document.querySelectorAll('.ld-add').forEach(x => x.remove());
    document.body.classList.remove('ld-on');
  }

  // ---------- Export (.xlsx written here, nothing sent) ----------
  const CRC = (() => { const t = new Uint32Array(256); for (let n = 0; n < 256; n++) { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1; t[n] = c >>> 0; } return t; })();
  const crc32 = u8 => { let c = 0xffffffff; for (let i = 0; i < u8.length; i++) c = CRC[(c ^ u8[i]) & 255] ^ (c >>> 8); return (c ^ 0xffffffff) >>> 0; };
  function zip(files) {
    const te = new TextEncoder(), parts = [], cd = []; let off = 0;
    files.forEach(([name, text]) => {
      const nm = te.encode(name), data = te.encode(text), crc = crc32(data);
      const lh = new DataView(new ArrayBuffer(30));
      lh.setUint32(0, 0x04034b50, true); lh.setUint16(4, 20, true); lh.setUint16(8, 0, true); lh.setUint32(14, crc, true);
      lh.setUint32(18, data.length, true); lh.setUint32(22, data.length, true); lh.setUint16(26, nm.length, true);
      parts.push(new Uint8Array(lh.buffer), nm, data);
      const ch = new DataView(new ArrayBuffer(46));
      ch.setUint32(0, 0x02014b50, true); ch.setUint16(4, 20, true); ch.setUint16(6, 20, true); ch.setUint32(16, crc, true);
      ch.setUint32(20, data.length, true); ch.setUint32(24, data.length, true); ch.setUint16(28, nm.length, true); ch.setUint32(42, off, true);
      cd.push(new Uint8Array(ch.buffer), nm);
      off += 30 + nm.length + data.length;
    });
    const cdSize = cd.reduce((s, a) => s + a.length, 0), end = new DataView(new ArrayBuffer(22));
    end.setUint32(0, 0x06054b50, true); end.setUint16(8, files.length, true); end.setUint16(10, files.length, true);
    end.setUint32(12, cdSize, true); end.setUint32(16, off, true);
    return new Blob([...parts, ...cd, new Uint8Array(end.buffer)], { type:'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' });
  }
  // sheets: [[name, rows]] (row 0 = headings) -> one .xlsx with a sheet each
  function xlsx(sheets) {
    const x = s => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/[\x00-\x08\x0b\x0c\x0e-\x1f]/g, '');
    const col = i => { let s = ''; for (i++; i > 0; i = Math.floor((i - 1) / 26)) s = String.fromCharCode(65 + (i - 1) % 26) + s; return s; };
    const NS = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main', R = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships';
    const REL = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships';
    const names = [];
    const sheetXml = sheets.map(([name, rows]) => {
      let nm = String(name).replace(/[\\\/?*\[\]:]/g, ' ').slice(0, 31) || 'Sheet', k = 2;
      while (names.includes(nm)) nm = nm.slice(0, 28) + ' ' + k++;
      names.push(nm);
      const ncol = Math.max(1, ...rows.map(r => r.length));
      const width = Array.from({ length:ncol }, (_, i) => Math.min(60, Math.max(8, ...rows.slice(0, 400).map(r => String(r[i] ?? '').length + 2))));
      const data = rows.map((r, ri) => `<row r="${ri + 1}">` + r.map((v, ci) => {
        const ref = col(ci) + (ri + 1), st = ri === 0 ? ' s="1"' : '';
        return typeof v === 'number' && isFinite(v) ? `<c r="${ref}"${st}><v>${v}</v></c>` : `<c r="${ref}" t="inlineStr"${st}><is><t xml:space="preserve">${x(v ?? '')}</t></is></c>`;
      }).join('') + '</row>').join('');
      return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet xmlns="${NS}" xmlns:r="${R}"><sheetViews><sheetView workbookViewId="0"${names.length === 1 ? ' tabSelected="1"' : ''}><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews><cols>${width.map((w, i) => `<col min="${i + 1}" max="${i + 1}" width="${w}" customWidth="1"/>`).join('')}</cols><sheetData>${data}</sheetData>${rows.length > 1 ? `<autoFilter ref="A1:${col(ncol - 1)}${rows.length}"/>` : ''}</worksheet>`;
    });
    const n = sheetXml.length;
    return zip([
      ['[Content_Types].xml', '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        + sheetXml.map((_, i) => `<Override PartName="/xl/worksheets/sheet${i + 1}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>`).join('')
        + '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/></Types>'],
      ['_rels/.rels', `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="${REL}/officeDocument" Target="xl/workbook.xml"/></Relationships>`],
      ['xl/workbook.xml', `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="${NS}" xmlns:r="${R}"><sheets>${names.map((nm, i) => `<sheet name="${x(nm)}" sheetId="${i + 1}" r:id="rId${i + 1}"/>`).join('')}</sheets></workbook>`],
      ['xl/_rels/workbook.xml.rels', `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">${names.map((_, i) => `<Relationship Id="rId${i + 1}" Type="${REL}/worksheet" Target="worksheets/sheet${i + 1}.xml"/>`).join('')}<Relationship Id="rId${n + 1}" Type="${REL}/styles" Target="styles.xml"/></Relationships>`],
      ['xl/styles.xml', `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><styleSheet xmlns="${NS}"><fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><name val="Calibri"/></font></fonts><fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills><borders count="1"><border/></borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs><cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/></cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>`],
    ].concat(sheetXml.map((xmlText, i) => [`xl/worksheets/sheet${i + 1}.xml`, xmlText])));
  }
  // Export works with or without Load; after Load, ST.ID / ST.N / SF.I columns follow the code column.
  function withList(head, rows) {
    if (!list) return [head].concat(rows);
    const ci = head.findIndex(h => /^(ID|Code)$/i.test(String(h)));
    if (ci < 0) return [head].concat(rows);
    const ins = (arr, vals) => arr.slice(0, ci + 1).concat(vals, arr.slice(ci + 1));
    return [ins(head, ['ST.ID', 'ST.N', 'SF.I'])].concat(rows.map(r => { const v = list.map[r[ci]] || {}; return ins(r, [v.id || '', v.name || '', v.staff || '']); }));
  }
  function exportXlsx() {
    const keys = Object.keys(ROWS[0] || { Code:'' });
    const sheets = [['Summary', withList(keys, ROWS.map(r => keys.map(k => r[k])))]]
      .concat(SHEETS.map(([name, head, rows]) => [name, withList(head, rows)]));
    const a = document.createElement('a'); a.href = URL.createObjectURL(xlsx(sheets));
    a.download = list ? NAME.replace(/\.xlsx$/, '-list.xlsx') : NAME; document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 4000);
  }

  bLoad.onclick = () => inp.click();
  inp.onchange = async () => {
    const f = inp.files[0]; inp.value = ''; if (!f) return;
    note.className = 'ldnote'; note.textContent = 'Reading ' + f.name + '…';
    try {
      const rows = /\.csv$/i.test(f.name) ? readCsv(await f.text()) : await readXlsx(await f.arrayBuffer());
      const l = toList(rows);
      if (on) hide();
      list = l; show();
      const missing = CODES.filter(c => !l.map[c]);
      const msg = [`Loaded ${f.name}: shown on this page only (nothing is saved or sent).`];
      if (missing.length) msg.push(`Not in your list: ${missing.join(', ')}.`);
      if (l.dup.length) msg.push(`Listed twice (last one used): ${[...new Set(l.dup)].join(', ')}.`);
      note.className = missing.length || l.dup.length ? 'ldwarn' : 'ldnote'; note.textContent = msg.join(' ');
    } catch (e) { note.className = 'ldwarn'; note.textContent = 'Could not read that file: ' + (e.message || e) + '. Use an .xlsx or .csv with headings Code, ST.ID, ST.N, SF.I.'; }
  };
  bHide.onclick = () => { hide(); list = null; bHide.hidden = true; note.className = 'ldnote'; note.textContent = ''; };
  bExp.onclick = () => exportXlsx();
})();
"""


def block(rows, export_name, sheets=()):
    """HTML for the Load / Export bar (place under the report heading) + its script.
    rows: one dict per code, first key "Code" (the Summary sheet). sheets: more [(name, header, rows)]."""
    def js_json(x):
        return json.dumps(x, ensure_ascii=False, default=str).replace("</", "<\\/")
    js = JS.replace("__ROWS__", js_json(rows)) \
           .replace("__SHEETS__", js_json([[n, h, r] for n, h, r in sheets])) \
           .replace("__NAME__", json.dumps(export_name))
    return (f'<div class="ldbar" id="ldbar"><button type="button" id="ld-load" title="Read on this computer only; '
            f'nothing is uploaded or saved">Load</button>'
            f'<button type="button" id="ld-hide" hidden>Hide</button>'
            f'<button type="button" id="ld-export" title="Save the report tables as Excel on this computer">Export</button>'
            f'<input type="file" id="ld-file" accept=".xlsx,.csv" hidden>'
            f'<span class="ldnote" id="ld-note"></span></div>'
            f'<script>{js}</script>')


def export_name(tag):
    return f"{html.unescape(tag)}.xlsx"
