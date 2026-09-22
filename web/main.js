// ============================================================
// 元素引用
// ============================================================
const $ = (id) => document.getElementById(id);
const envDot    = $('env-dot');
const envText   = $('env-text');
const dropEl    = $('drop');
const fileInput = $('file-input');
const dirInput  = $('dir-input');
const fileCard  = $('file-card');
const fileList  = $('file-list');
const fileCount = $('file-count');
const clearBtn  = $('clear-files');
const formatEl  = $('format');
const crsEl     = $('crs');
const convertBtn = $('convert');
const convertLabel = $('convert-label');
const convertBar = $('convert-bar');
const statusEl  = $('status');
const resultCard = $('result-card');
const resultBody = $('result-body');
const resultSummary = $('result-summary');

// ============================================================
// 状态
// ============================================================
let envReady = false;
let format = 'gpkg';                 // 默认 GPKG
let files = [];                      // [{file, name, size, relPath}]

// ============================================================
// Worker
// ============================================================
const WORKER_VERSION = 1;
const worker = new Worker(`worker.js?v=${WORKER_VERSION}`);

worker.onmessage = (e) => {
  const m = e.data;
  switch (m.type) {
    case 'env-progress':
      envText.textContent = m.text;
      break;
    case 'env-ok':
      envReady = true;
      envDot.classList.add('ok');
      envText.textContent = m.versions;
      updateConvertBtn();
      break;
    case 'env-error':
      envDot.classList.add('err');
      envText.textContent = '环境初始化失败';
      console.error(m.error, m.traceback);
      break;
    case 'progress':
      setProgress(m.done, m.total);
      break;
    case 'done':
      setProgress(1, 1);
      convertLabel.textContent = '开始转换';
      convertBtn.disabled = false;
      statusEl.textContent =
        `完成 · 成功 ${m.stats.success} / 失败 ${m.stats.failed} / 共 ${m.stats.total}`;
      // 调试：确认 fileResults 内容
      console.log('done 收到 fileResults:', m.fileResults);
      if (Array.isArray(m.fileResults)) {
        for (const r of m.fileResults) appendResult(r);
      } else {
        console.warn('fileResults 不是数组:', typeof m.fileResults, m.fileResults);
      }
      resultSummary.textContent = `${resultBody.children.length} 个文件`;
      downloadBlob(m.buffer, m.filename);
      break;
    case 'error':
      convertLabel.textContent = '开始转换';
      convertBtn.disabled = false;
      statusEl.textContent = '出错：' + m.error;
      console.error(m.error, m.traceback);
      break;
  }
};

// 页面加载即初始化
worker.postMessage({ type: 'init' });

// ============================================================
// 进度
// ============================================================
function setProgress(done, total) {
  const pct = total ? Math.round(done / total * 100) : 0;
  convertBar.style.width = pct + '%';
  if (total > 0 && done < total) {
    convertLabel.textContent = `转换中 ${done}/${total}`;
  }
}

// ============================================================
// 文件管理
// ============================================================
fileInput.addEventListener('change', (e) => {
  addFiles(Array.from(e.target.files).map((f) => ({ file: f, relPath: f.name })));
  fileInput.value = '';
});

dirInput.addEventListener('change', (e) => {
  addFiles(Array.from(e.target.files).map((f) => ({
    file: f, relPath: f.webkitRelativePath || f.name,
  })));
  dirInput.value = '';
});

clearBtn.addEventListener('click', () => {
  files = [];
  renderFiles();
});

function addFiles(items) {
  const exts = ['.wt', '.wl', '.wp'];
  for (const it of items) {
    const f = it.file;
    const ext = '.' + f.name.toLowerCase().split('.').pop();
    if (!exts.includes(ext)) continue;
    if (files.some((p) => p.name === f.name && p.size === f.size)) continue;
    files.push({ file: f, name: f.name, size: f.size, relPath: it.relPath || f.name });
  }
  renderFiles();
  updateConvertBtn();
}

function renderFiles() {
  if (files.length === 0) {
    fileCard.classList.add('hidden');
    return;
  }
  fileCard.classList.remove('hidden');
  fileCount.textContent = `${files.length} 个`;
  fileList.innerHTML = files.map((p, i) => `
    <li>
      <span class="fname" title="${escapeHtml(p.relPath)}">${escapeHtml(p.name)}</span>
      <span class="fsize">${formatSize(p.size)}</span>
      <button class="fdel" data-i="${i}">×</button>
    </li>
  `).join('');
  fileList.querySelectorAll('.fdel').forEach((b) => {
    b.addEventListener('click', () => {
      files.splice(parseInt(b.dataset.i), 1);
      renderFiles();
      updateConvertBtn();
    });
  });
}

function updateConvertBtn() {
  convertBtn.disabled = !envReady || files.length === 0;
}

function formatSize(n) {
  if (n < 1024) return n + ' B';
  if (n < 1024 * 1024) return (n / 1024).toFixed(1) + ' KB';
  return (n / 1024 / 1024).toFixed(1) + ' MB';
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[c]));
}

// ============================================================
// 拖拽
// ============================================================
['dragenter', 'dragover'].forEach((ev) => {
  dropEl.addEventListener(ev, (e) => {
    e.preventDefault();
    dropEl.classList.add('dragover');
  });
});
['dragleave', 'drop'].forEach((ev) => {
  dropEl.addEventListener(ev, () => dropEl.classList.remove('dragover'));
});

dropEl.addEventListener('drop', async (e) => {
  e.preventDefault();
  const items = e.dataTransfer.items;
  const collected = [];
  if (items && items.length && items[0].webkitGetAsEntry) {
    const entries = [];
    for (const item of items) {
      const en = item.webkitGetAsEntry();
      if (en) entries.push(en);
    }
    for (const en of entries) {
      const sub = await walkEntry(en);
      collected.push(...sub);
    }
  } else {
    collected.push(...Array.from(e.dataTransfer.files).map((f) => ({
      file: f, relPath: f.name,
    })));
  }
  addFiles(collected);
});

async function walkEntry(entry, path = '') {
  if (entry.isFile) {
    const ext = '.' + entry.name.toLowerCase().split('.').pop();
    if (!['.wt', '.wl', '.wp'].includes(ext)) return [];
    const file = await new Promise((res, rej) => entry.file(res, rej));
    return [{ file, relPath: path + entry.name }];
  }
  if (entry.isDirectory) {
    const reader = entry.createReader();
    const all = [];
    while (true) {
      const batch = await new Promise((res, rej) => {
        try { reader.readEntries(res, rej); } catch (e) { rej(e); }
      });
      if (!batch || batch.length === 0) break;
      all.push(...batch);
    }
    const sub = await Promise.all(
      all.map((en) => walkEntry(en, path + entry.name + '/'))
    );
    return sub.flat();
  }
  return [];
}

// ============================================================
// 设置
// ============================================================
formatEl.addEventListener('click', (e) => {
  const btn = e.target.closest('button');
  if (!btn) return;
  formatEl.querySelectorAll('button').forEach((b) => b.classList.remove('active'));
  btn.classList.add('active');
  format = btn.dataset.v;
});

// ============================================================
// 转换
// ============================================================
convertBtn.addEventListener('click', async () => {
  if (!envReady || files.length === 0) return;

  convertBtn.disabled = true;
  convertLabel.textContent = '准备中…';
  convertBar.style.width = '0%';
  resultBody.innerHTML = '';
  resultCard.classList.remove('hidden');
  resultSummary.textContent = '';
  statusEl.textContent = '读取文件…';

  const payloads = [];
  for (const p of files) {
    const buf = await p.file.arrayBuffer();
    payloads.push({ name: p.name, buffer: buf });
  }

  statusEl.textContent = '开始转换…';
  worker.postMessage({
    type: 'convert',
    format,
    targetCrs: crsEl.value,
    files: payloads,
  }, payloads.map((p) => p.buffer));
});

function appendResult(r) {
  try {
    const ok = !!r.success;
    const elapsed = (typeof r.elapsed === 'number') ? r.elapsed : 0;
    const features = (typeof r.features === 'number') ? r.features : 0;
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td>${escapeHtml(r.name || '')}</td>
      <td>${escapeHtml(r.layer || '-')}</td>
      <td class="${ok ? 'ok' : 'fail'}">${ok ? '成功' : '失败'}</td>
      <td class="num">${ok ? features : '-'}</td>
      <td class="num">${elapsed.toFixed(2)}s</td>
    `;
    resultBody.appendChild(tr);
  } catch (err) {
    console.error('appendResult 失败:', err, r);
  }
}

// ============================================================
// 下载
// ============================================================
function downloadBlob(buffer, filename) {
  const blob = new Blob([buffer], { type: 'application/zip' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

window.addEventListener('beforeunload', () => worker.terminate());