// Web Worker：加载 Pyodide + core 代码，执行 MapGIS 转换

const PYODIDE_VERSION = '0.26.4';
const PYODIDE_CDN =
  `https://cdn.jsdelivr.net/pyodide/v${PYODIDE_VERSION}/full/`;

const CORE_FILES = [
  'core/__init__.py',
  'core/binary.py',
  'core/constants.py',
  'core/exceptions.py',
  'core/header.py',
  'core/attributes.py',
  'core/display.py',
  'core/crs.py',
  'core/geometry.py',
  'core/reader.py',
  'core/fields.py',
  'core/shp.py',
  'core/transform.py',
  'core/convert.py',
  'core/gpkg_writer.py',
];

const INPUT_DIR  = '/home/pyodide/input';
const OUTPUT_DIR = '/home/pyodide/output';
const CORE_BASE  = '/home/pyodide/mapgis2gpkg';

let pyodideReady = null;

function postEnv(text) {
  self.postMessage({ type: 'env-progress', text });
}

// ---- 递归清空目录并重建 ----
function ensureCleanDir(fs, path) {
  try {
    const entries = fs.readdir(path);
    for (const name of entries) {
      if (name === '.' || name === '..') continue;
      const full = path + '/' + name;
      const st = fs.stat(full);
      if (fs.isDir(st.mode)) {
        ensureCleanDir(fs, full);
        try { fs.rmdir(full); } catch (_) {}
      } else {
        try { fs.unlink(full); } catch (_) {}
      }
    }
  } catch (_) {}
  try { fs.mkdirTree(path); } catch (_) {}
}

async function getPyodide() {
  if (pyodideReady) return pyodideReady;
  pyodideReady = (async () => {
    postEnv('加载 Pyodide…');
    importScripts(`${PYODIDE_CDN}pyodide.js`);
    const pyodide = await loadPyodide({ indexURL: PYODIDE_CDN });

    pyodide.setStdout({ batched: (t) => postEnv(t) });
    pyodide.setStderr({ batched: (t) => postEnv('[err] ' + t) });

    postEnv('加载 micropip…');
    await pyodide.loadPackage('micropip');

    postEnv('安装 geopandas + fiona（首次约 30-60 秒）…');
    await pyodide.runPythonAsync(`
import micropip
await micropip.install(['geopandas', 'fiona'])
    `);

    postEnv('加载解析模块…');
    await loadCorePackage(pyodide);

    const versions = pyodide.runPython(`
import sys, geopandas, pyproj
f"Python {sys.version.split()[0]} · geopandas {geopandas.__version__} · pyproj {pyproj.__version__}"
    `);
    self.postMessage({ type: 'env-ok', versions });
    return pyodide;
  })().catch((err) => {
    self.postMessage({
      type: 'env-error',
      error: String(err),
      traceback: err && err.stack ? err.stack : null,
    });
    throw err;
  });
  return pyodideReady;
}

async function loadCorePackage(pyodide) {
  pyodide.FS.mkdirTree(CORE_BASE + '/core');
  for (const rel of CORE_FILES) {
    const url = 'py/' + rel;
    const resp = await fetch(url);
    if (!resp.ok) throw new Error(`无法加载 ${url}: HTTP ${resp.status}`);
    pyodide.FS.writeFile(CORE_BASE + '/' + rel, await resp.text(),
                         { encoding: 'utf8' });
  }
  await pyodide.runPythonAsync(`
import sys
if '${CORE_BASE}' not in sys.path:
    sys.path.insert(0, '${CORE_BASE}')
import core
  `);
}

// ======================================================================
// Python 转换脚本
//
// 关键：不再通过 file_done_callback 累积结果，改用 convert_folder 返回的
// stats['results']（这是权威数据源）。并把 list 序列化为 JSON 字符串，
// 避免 Pyodide 的 toJs() 处理"list of dict"时类型转换不可靠。
// ======================================================================
const CONVERT_CODE = `
import os, io, zipfile, shutil, traceback, json

result = {'ok': False, 'error': None, 'traceback': None,
          'zip_bytes': None, 'stats': None, 'file_results_json': None}
try:
    from core.convert import convert_folder

    if os.path.exists('${OUTPUT_DIR}'):
        shutil.rmtree('${OUTPUT_DIR}')
    os.makedirs('${OUTPUT_DIR}', exist_ok=True)

    output_format = __FORMAT__
    if output_format == 'gpkg':
        out_param = os.path.join('${OUTPUT_DIR}', 'output.gpkg')
        engine = 'sqlite3'
    else:
        out_param = '${OUTPUT_DIR}'
        engine = 'fiona'

    stats = convert_folder(
        folder='${INPUT_DIR}',
        output_format=output_format,
        output=out_param,
        target_crs=__TARGET_CRS__,
        encoding='gb18030',
        gpkg_engine=engine,
    )

    # ---- 从 stats['results'] 提取每个文件的结果 ----
    file_results = []
    for r in stats.get('results', []):
        try:
            file_results.append({
                'name':     os.path.basename(r.get('source') or ''),
                'layer':    r.get('layer') or '',
                'success':  bool(r.get('success', False)),
                'features': int(r.get('features', 0) or 0),
                'elapsed':  float(r.get('elapsed', 0.0) or 0.0),
                'error':    str(r.get('error') or ''),
            })
        except Exception:
            # 单条出错不影响其它
            pass

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        for root, _, files in os.walk('${OUTPUT_DIR}'):
            for f in files:
                full = os.path.join(root, f)
                arc = os.path.relpath(full, '${OUTPUT_DIR}')
                zf.write(full, arc)

    result['ok'] = True
    result['zip_bytes'] = buf.getvalue()
    result['file_results_json'] = json.dumps(file_results, ensure_ascii=False)
    result['stats'] = {
        'total':   stats['total'],
        'success': stats['success'],
        'failed':  stats['failed'],
        'errors':  [(str(p), str(e)) for p, e in stats['errors']],
    }
except Exception as e:
    result['error'] = f'{type(e).__name__}: {e}'
    result['traceback'] = traceback.format_exc()

result
`;

self.onmessage = async (e) => {
  const msg = e.data;
  try {
    if (msg.type === 'init') {
      await getPyodide();
    } else if (msg.type === 'convert') {
      await handleConvert(msg);
    }
  } catch (err) {
    self.postMessage({
      type: 'error',
      error: String(err.message || err),
      traceback: err.stack || null,
    });
  }
};

async function handleConvert(msg) {
  const pyodide = await getPyodide();
  const { files, format, targetCrs } = msg;

  ensureCleanDir(pyodide.FS, INPUT_DIR);

  for (const f of files) {
    pyodide.FS.writeFile(INPUT_DIR + '/' + f.name,
                         new Uint8Array(f.buffer));
  }

  const crsLiteral = (targetCrs === 'keep')
    ? 'None'
    : JSON.stringify(targetCrs);

  const code = CONVERT_CODE
    .replace('__FORMAT__', JSON.stringify(format))
    .replace('__TARGET_CRS__', crsLiteral);

  let proxy;
  try {
    proxy = await pyodide.runPythonAsync(code);
  } catch (pyErr) {
    self.postMessage({
      type: 'error',
      error: String(pyErr.message || pyErr),
      traceback: pyErr.message || null,
    });
    return;
  }

  let result;
  try {
    result = proxy.toJs({ dict_converter: Object.fromEntries });
  } finally {
    proxy.destroy();
  }

  if (!result.ok) {
    self.postMessage({
      type: 'error',
      error: result.error || '未知 Python 错误',
      traceback: result.traceback || null,
    });
    return;
  }

  // ---- 从 JSON 字符串解析文件结果（避开 toJs 的类型转换问题）----
  let fileResults = [];
  try {
    if (result.file_results_json) {
      fileResults = JSON.parse(result.file_results_json);
    }
  } catch (parseErr) {
    console.error('解析 file_results_json 失败:', parseErr,
                  result.file_results_json);
  }

  const stats = result.stats;
  const zipBytes = result.zip_bytes;
  const ab = zipBytes.buffer.slice(
    zipBytes.byteOffset, zipBytes.byteOffset + zipBytes.byteLength
  );

  self.postMessage({
    type: 'done',
    stats,
    fileResults,
    buffer: ab,
    filename: format === 'gpkg'
      ? 'mapgis2gpkg_output.gpkg.zip'
      : 'mapgis2gpkg_output_shp.zip',
  }, [ab]);
}