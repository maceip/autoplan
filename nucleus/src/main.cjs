'use strict';

/**
 * Nucleus macOS Desktop Application — Electron 45.3.2 (Chromium 156)
 *
 * Unifies:
 *  1. 3-Column AutoPlan Multi-Project Workbench (`webclaw`)
 *  2. Live Interactive PlanAI DAG Visualizations + Split View + SvelteFlow Editor
 *  3. Chromium Blink `window.LanguageModel` Prompt API backed by local Apple Metal
 *     `mlx_lm.server` (`mlx-community/Qwen3-4B-Instruct-2507-4bit`) via Electron's
 *     `session.defaultSession.registerLocalAIHandler(utilityProcess)` and bridged
 *     live into Python's `PlanAI.LLMInterface` Core.
 */

const {
  app,
  BrowserWindow,
  ipcMain,
  session,
  shell,
  utilityProcess,
} = require('electron');
const { spawn } = require('node:child_process');
const fs = require('node:fs');
const http = require('node:http');
const os = require('node:os');
const path = require('node:path');

// Enable Chromium Blink Prompt API (`window.LanguageModel`) before app ready
app.commandLine.appendSwitch('enable-experimental-web-platform-features');
app.commandLine.appendSwitch(
  'enable-features',
  'AIPromptAPI,AIPromptAPIMultimodalInput'
);

const EXPLICIT_BACKEND_URL = (process.env.NUCLEUS_BACKEND_URL || '').replace(
  /\/+$/,
  ''
);
const BACKEND_CANDIDATES = [
  EXPLICIT_BACKEND_URL,
  'http://127.0.0.1:5051',
  'http://100.80.211.36:5051',
].filter(Boolean);
let resolvedBackendUrl = BACKEND_CANDIDATES[0] || 'http://127.0.0.1:5051';
const MLX_PORT = Number(process.env.AUTOPLAN_MLX_PORT || 18089);
const MLX_MODEL =
  process.env.AUTOPLAN_MLX_MODEL || 'mlx-community/Qwen3-4B-Instruct-2507-4bit';
const LOCAL_WEBCLAW_PORT = Number(process.env.NUCLEUS_WEBCLAW_PORT || 5199);

let mainWindow = null;
let aiUtilityProcess = null;
let spawnedMlxProc = null;
let spawnedWebclawProc = null;
let shellHttpServer = null;
let shellBaseUrl = '';
let resolvedWebclawUrl = process.env.NUCLEUS_WEBCLAW_URL || '';

function probeHttpOk(urlStr, timeoutMs = 1500) {
  return new Promise((resolve) => {
    try {
      const u = new URL(urlStr);
      const req = http.request(
        {
          hostname: u.hostname,
          port: u.port || 80,
          path: u.pathname + u.search,
          method: 'GET',
          timeout: timeoutMs,
        },
        (res) => {
          res.resume();
          resolve(Boolean(res.statusCode && res.statusCode < 500));
        }
      );
      req.on('timeout', () => {
        req.destroy();
        resolve(false);
      });
      req.on('error', () => resolve(false));
      req.end();
    } catch {
      resolve(false);
    }
  });
}

async function waitForHttp(urlStr, maxWaitMs = 20000) {
  const deadline = Date.now() + maxWaitMs;
  while (Date.now() < deadline) {
    if (await probeHttpOk(urlStr, 1500)) return true;
    await new Promise((r) => setTimeout(r, 400));
  }
  return false;
}

function findMlxServerBinary() {
  const candidates = [
    process.env.AUTOPLAN_MLX_BIN || '',
    path.join(os.homedir(), '.local', 'bin', 'mlx_lm.server'),
    '/opt/homebrew/bin/mlx_lm.server',
    '/usr/local/bin/mlx_lm.server',
  ].filter(Boolean);
  for (const c of candidates) {
    if (fs.existsSync(c)) return c;
  }
  return '';
}

async function ensureLocalMlxServer() {
  const modelsUrl = `http://127.0.0.1:${MLX_PORT}/v1/models`;
  if (await probeHttpOk(modelsUrl, 1200)) {
    return { running: true, spawned: false };
  }
  const bin = findMlxServerBinary();
  if (!bin) {
    return { running: false, spawned: false, reason: 'mlx_lm.server not found' };
  }
  spawnedMlxProc = spawn(
    bin,
    [
      '--model',
      MLX_MODEL,
      '--host',
      '127.0.0.1',
      '--port',
      String(MLX_PORT),
    ],
    {
      stdio: 'ignore',
      env: { ...process.env },
    }
  );
  spawnedMlxProc.unref();
  const ready = await waitForHttp(modelsUrl, 22000);
  return { running: ready, spawned: true };
}

function resolveRepoRoot() {
  // Works both in dev (`/Users/mac/autoplan/nucleus/src`) and packaged `Nucleus.app`
  const candidates = [
    process.env.AUTOPLAN_ROOT || '',
    path.resolve(__dirname, '..', '..'),
    path.join(os.homedir(), 'autoplan'),
  ].filter(Boolean);
  for (const dir of candidates) {
    if (
      fs.existsSync(
        path.join(dir, 'webclaw', 'apps', 'webclaw', 'package.json')
      )
    ) {
      return dir;
    }
  }
  return '';
}

async function detectBackendUrl() {
  if (EXPLICIT_BACKEND_URL) {
    resolvedBackendUrl = EXPLICIT_BACKEND_URL;
    return resolvedBackendUrl;
  }
  for (const candidate of BACKEND_CANDIDATES) {
    if (await probeHttpOk(`${candidate}/api/projects`, 1200)) {
      resolvedBackendUrl = candidate;
      return resolvedBackendUrl;
    }
  }
  return resolvedBackendUrl;
}

async function ensureLocalWebclawServer() {
  await detectBackendUrl();
  if (resolvedWebclawUrl) {
    return resolvedWebclawUrl;
  }
  const localCandidate = `http://127.0.0.1:${LOCAL_WEBCLAW_PORT}`;
  if (await probeHttpOk(`${localCandidate}/new`, 1200)) {
    resolvedWebclawUrl = localCandidate;
    return resolvedWebclawUrl;
  }

  const repoRoot = resolveRepoRoot();
  if (repoRoot) {
    const webclawAppDir = path.join(repoRoot, 'webclaw', 'apps', 'webclaw');
    const viteBin = path.join(webclawAppDir, 'node_modules', '.bin', 'vite');
    if (fs.existsSync(viteBin)) {
      spawnedWebclawProc = spawn(
        viteBin,
        [
          'preview',
          '--host',
          '127.0.0.1',
          '--port',
          String(LOCAL_WEBCLAW_PORT),
          '--strictPort',
        ],
        {
          cwd: webclawAppDir,
          stdio: 'ignore',
          env: {
            ...process.env,
            AUTOPLAN_BACKEND_URL: resolvedBackendUrl,
          },
        }
      );
      spawnedWebclawProc.unref();
      if (await waitForHttp(`${localCandidate}/new`, 12000)) {
        resolvedWebclawUrl = localCandidate;
        return resolvedWebclawUrl;
      }
    }
  }

  resolvedWebclawUrl = 'https://queue.secure.build';
  return resolvedWebclawUrl;
}

async function startLocalShellServer() {
  const shellHtmlPath = path.join(__dirname, 'shell.html');
  const iconPngPath = path.join(__dirname, '..', 'assets', 'icon.png');

  shellHttpServer = http.createServer((req, res) => {
    const reqUrl = new URL(req.url || '/', 'http://127.0.0.1');
    if (reqUrl.pathname === '/icon.png' && fs.existsSync(iconPngPath)) {
      res.writeHead(200, {
        'content-type': 'image/png',
        'cache-control': 'no-cache',
      });
      fs.createReadStream(iconPngPath).pipe(res);
      return;
    }
    res.writeHead(200, {
      'content-type': 'text/html; charset=utf-8',
      'cache-control': 'no-cache',
    });
    fs.createReadStream(shellHtmlPath).pipe(res);
  });

  await new Promise((resolve) =>
    shellHttpServer.listen(0, '127.0.0.1', resolve)
  );
  const port = shellHttpServer.address().port;
  shellBaseUrl = `http://127.0.0.1:${port}`;
  return shellBaseUrl;
}

function startLocalAIUtility() {
  const utilityScript = path.join(__dirname, 'ai-utility.cjs');
  aiUtilityProcess = utilityProcess.fork(utilityScript, [], {
    serviceName: 'Nucleus Chromium Local AI Utility',
    env: {
      ...process.env,
      AUTOPLAN_MLX_PORT: String(MLX_PORT),
      AUTOPLAN_MLX_MODEL: MLX_MODEL,
    },
  });

  aiUtilityProcess.on('message', (msg) => {
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.webContents.send('nucleus:ai-telemetry', msg);
    }
  });

  session.defaultSession.registerLocalAIHandler(aiUtilityProcess);
}

async function createMainWindow() {
  const iconPng = path.join(__dirname, '..', 'assets', 'icon.png');
  mainWindow = new BrowserWindow({
    width: 1480,
    height: 920,
    minWidth: 1024,
    minHeight: 680,
    title: 'Nucleus',
    backgroundColor: '#002028',
    titleBarStyle: process.platform === 'darwin' ? 'hiddenInset' : 'default',
    trafficLightPosition:
      process.platform === 'darwin' ? { x: 14, y: 12 } : undefined,
    icon: fs.existsSync(iconPng) ? iconPng : undefined,
    show: process.env.NUCLEUS_HEADLESS_TEST !== '1',
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      contextIsolation: true,
      nodeIntegration: false,
      enableBlinkFeatures: 'AIPromptAPI,AIPromptAPIMultimodalInput',
    },
  });

  await mainWindow.loadURL(shellBaseUrl);
}

ipcMain.handle('nucleus:get-runtime-info', () => ({
  appName: 'Nucleus',
  appVersion: app.getVersion(),
  electronVersion: process.versions.electron,
  chromeVersion: process.versions.chrome,
  nodeVersion: process.versions.node,
  v8Version: process.versions.v8,
  arch: process.arch,
  platform: process.platform,
  backendUrl: resolvedBackendUrl,
  webclawUrl: resolvedWebclawUrl,
  mlxPort: MLX_PORT,
  mlxModel: MLX_MODEL,
}));

ipcMain.handle('nucleus:get-services-status', async () => {
  await detectBackendUrl();
  const [backendOk, mlxOk, webclawOk] = await Promise.all([
    probeHttpOk(`${resolvedBackendUrl}/api/projects`),
    probeHttpOk(`http://127.0.0.1:${MLX_PORT}/v1/models`),
    resolvedWebclawUrl ? probeHttpOk(resolvedWebclawUrl) : Promise.resolve(false),
  ]);
  return {
    backendOk,
    mlxOk,
    webclawOk,
    backendUrl: resolvedBackendUrl,
    webclawUrl: resolvedWebclawUrl,
  };
});

ipcMain.handle('nucleus:ensure-local-services', async () => {
  const mlx = await ensureLocalMlxServer();
  const wc = await ensureLocalWebclawServer();
  return { mlx, webclawUrl: wc };
});

ipcMain.handle('nucleus:open-external', async (_event, url) => {
  if (typeof url === 'string' && /^https?:\/\//i.test(url)) {
    await shell.openExternal(url);
    return true;
  }
  return false;
});

app.whenReady().then(async () => {
  startLocalAIUtility();
  await Promise.all([ensureLocalMlxServer(), ensureLocalWebclawServer()]);
  await startLocalShellServer();
  await createMainWindow();

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      void createMainWindow();
    }
  });
});

function cleanupChildren() {
  try {
    session.defaultSession.registerLocalAIHandler(null);
  } catch {}
  if (aiUtilityProcess) {
    try {
      aiUtilityProcess.kill();
    } catch {}
    aiUtilityProcess = null;
  }
  if (spawnedMlxProc) {
    try {
      spawnedMlxProc.kill('SIGTERM');
    } catch {}
    spawnedMlxProc = null;
  }
  if (spawnedWebclawProc) {
    try {
      spawnedWebclawProc.kill('SIGTERM');
    } catch {}
    spawnedWebclawProc = null;
  }
  if (shellHttpServer) {
    try {
      shellHttpServer.close();
    } catch {}
    shellHttpServer = null;
  }
}

app.on('before-quit', cleanupChildren);
app.on('window-all-closed', () => {
  cleanupChildren();
  app.quit();
});
