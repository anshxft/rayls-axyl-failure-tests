// Records the live test as frames/NN_name/ and key stills in shots/. Everything on screen is real: live RPC heights, real kill -9, real payments.
// Usage: set PWC=<path to playwright-core> && node record_axyl.js [firstScene]
const { chromium } = require(process.env.PWC);
const { execFile, spawn } = require('child_process');
const fs = require('fs'), path = require('path');

const W = 1600, H = 900, SCALE = 1.2, LAB = path.join(__dirname, '..');
const PORTS = [8545, 8544, 8543, 8542];
const sleep = ms => new Promise(r => setTimeout(r, ms));
let loads = 0;  // a new query string forces a real reload; a hash change alone would not re-run the page
const fileUrl = hash => 'file:///' + path.join(__dirname, 'live.html').split(path.sep).join('/') + `?${++loads}#` + hash;
const ONLY = process.env.ONLY ? new Set(process.env.ONLY.split(',').map(Number)) : null;  // re-record just these scenes, against the running network
let key = JSON.parse(fs.readFileSync(path.join(LAB, 'lab/testkey.json'))).data; key = Array.isArray(key) ? key[0] : key; key = (key.accounts || [key])[0];

const exec = (f, a, o = {}) => new Promise((ok, no) => execFile(f, a, { maxBuffer: 1 << 24, cwd: LAB, ...o }, (e, so, se) => e ? no(new Error(se || e.message)) : ok(so.replace(/\0/g, ''))));
let WSLDIR;
const wsl = (...a) => exec('wsl.exe', ['-d', 'Ubuntu', '--', ...a]);
const ctl = (...a) => wsl('bash', WSLDIR + '/lab_ctl.sh', ...a.map(String));

async function height(p) {
  try {
    const r = await fetch(`http://127.0.0.1:${p}`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: '{"jsonrpc":"2.0","id":1,"method":"eth_blockNumber","params":[]}', signal: AbortSignal.timeout(350) });
    return parseInt((await r.json()).result, 16);
  } catch { return null; }
}
async function caughtUp(limit = 180000) {
  for (const t0 = Date.now(); Date.now() - t0 < limit; await sleep(1000)) {
    const hs = await Promise.all(PORTS.map(height));
    if (hs.every(h => h != null) && Math.max(...hs) - Math.min(...hs) <= 3) return hs;
  }
  throw new Error('validators did not catch up');
}

const HELPERS = () => {
  addEventListener('DOMContentLoaded', () => { const s = document.createElement('style'); s.textContent = 'ins.adsbyslise,iframe[src*="slise"]{display:none!important}'; document.head.appendChild(s); });
  window.__R = {
    find(text) { const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT); let n; while ((n = w.nextNode())) if (n.nodeValue.includes(text) && n.parentElement.getClientRects().length > 0) return n.parentElement; },
    async point(text) {
      document.querySelectorAll('.__hl').forEach(e => e.remove());
      const el = this.find(text); if (!el) return false;
      el.scrollIntoView({ block: 'center', behavior: 'smooth' });
      for (let i = 0, prev = ''; i < 25; i++) { await new Promise(r => setTimeout(r, 120)); const r0 = el.getBoundingClientRect(), cur = Math.round(r0.top) + ''; if (cur === prev) break; prev = cur; }
      const r = el.getBoundingClientRect(), b = document.createElement('div'); b.className = '__hl';
      b.style.cssText = `position:fixed;left:${r.left - 5}px;top:${r.top - 3}px;width:${r.width + 10}px;height:${r.height + 6}px;background:#16a34a1f;border-bottom:4px solid #16a34a;z-index:2147483646;pointer-events:none`;
      document.documentElement.appendChild(b); return true;
    },
  };
};

(async () => {
  WSLDIR = (await exec('wsl.exe', ['-d', 'Ubuntu', '--cd', LAB, '--', 'pwd'])).trim();
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const ctx = await browser.newContext({ viewport: { width: W, height: H }, deviceScaleFactor: SCALE });
  await ctx.addInitScript(HELPERS);
  const page = await ctx.newPage();
  const cdp = await ctx.newCDPSession(page);
  fs.mkdirSync(path.join(__dirname, 'shots'), { recursive: true });
  let n = 0;
  const shot = name => page.screenshot({ path: path.join(__dirname, 'shots', name + '.png') });

  async function scene(name, fn) {
    if (ONLY && !ONLY.has(n + 1)) { n++; return; }
    const dir =path.join(__dirname, 'frames', String(++n).padStart(2, '0') + '_' + name);
    fs.rmSync(dir, { recursive: true, force: true }); fs.mkdirSync(dir, { recursive: true });
    const frames = [], cuts = []; let open = null;
    const onFrame = f => {
      const file = path.join(dir, String(frames.length).padStart(5, '0') + '.jpg');
      fs.writeFileSync(file, Buffer.from(f.data, 'base64')); frames.push({ file, t: f.metadata.timestamp });
      cdp.send('Page.screencastFrameAck', { sessionId: f.sessionId }).catch(() => {});
    };
    cdp.on('Page.screencastFrame', onFrame);
    await cdp.send('Page.startScreencast', { format: 'jpeg', quality: 88, maxWidth: W * SCALE, maxHeight: H * SCALE });
    const t0 = Date.now() / 1000;
    const cut = (on, keep = 0.8) => { if (on) open = [Date.now() / 1000, keep]; else { cuts.push([open[0], Date.now() / 1000, open[1]]); open = null; } };
    await sleep(400); await fn(cut); await sleep(300);
    await cdp.send('Page.stopScreencast'); cdp.off('Page.screencastFrame', onFrame);
    const t1 = Date.now() / 1000, lines = [];
    frames.forEach((f, i) => {  // each frame lasts until the next; cut windows are squeezed to `keep` seconds
      const end = i + 1 < frames.length ? frames[i + 1].t : t1;
      let d = end - Math.max(f.t, t0);
      for (const [a, b, keep] of cuts) { const o = Math.max(0, Math.min(end, b) - Math.max(f.t, a)); if (b - a > keep) d -= o * (1 - keep / (b - a)); }
      lines.push(`file '${f.file.split(path.sep).join('/')}'`, `duration ${Math.max(d, 0.001).toFixed(3)}`);
    });
    if (frames.length) lines.push(`file '${frames.at(-1).file.split(path.sep).join('/')}'`);
    fs.writeFileSync(path.join(dir, 'list.txt'), lines.join('\n'));
    console.log(`scene ${n} ${name}: ${frames.length} frames`);
  }

  const T = (m, ...a) => page.evaluate(([m, a]) => window.T[m](...a), [m, a]);
  const point = (t, hold = 3000) => page.evaluate(t => window.__R.point(t), t).then(ok => { if (!ok) console.log('  not found:', t); return sleep(hold); });

  // Live tiles, polled from here because a file:// page cannot call the RPC ports.
  let poll; const seen = PORTS.map(() => ({ h: null, t: Date.now() }));
  const tiles = on => {
    clearInterval(poll); if (!on) return;
    let busy = false;
    poll = setInterval(async () => {
      if (busy) return; busy = true;
      const hs = await Promise.all(PORTS.map(height)), now = Date.now();
      for (let i = 0; i < 4; i++) {
        if (hs[i] != null && hs[i] !== seen[i].h) seen[i] = { h: hs[i], t: now };
        const ago = Math.floor((now - seen[i].t) / 1000);
        await T('tile', i, hs[i], hs[i] == null ? 'down' : ago >= 3 ? 'stall' : 'live', ago).catch(() => {});
      }
      busy = false;
    }, 400);
  };

  // Runs a real command and streams its stdout into the terminal panel.
  const stream = (file, args) => new Promise((ok, no) => {
    const p = spawn(file, args, { cwd: LAB, env: { ...process.env, PYTHONUNBUFFERED: '1', PYTHONUTF8: '1' } });
    let err = '', all = '';
    p.stdout.on('data', d => { all += d; T('print', d.toString().replace(/\0/g, '')).catch(() => {}); });
    p.stderr.on('data', d => { err += d; });
    p.on('close', c => c ? no(new Error(err)) : ok(all));
  });
  const py = async (shown, ...args) => { await T('type', shown); return stream('python', args); };
  const lab = async (shown, ...args) => { await T('type', shown); await T('print', await ctl(...args)); };
  const openLab = async () => { await page.goto(fileUrl('lab')); tiles(true); await sleep(1500); };

  // Fresh genesis so the video starts from a clean network.
  if (!ONLY) { console.log('resetting local network'); await ctl('reset', key.address); await sleep(60000); await caughtUp(); console.log('network up'); }

  await page.goto(fileUrl('title'));
  await scene('title', async () => { await sleep(5000); });

  await page.goto('https://www.rayls.com/blog/axyl-consensus-protocol-code-is-open', { waitUntil: 'domcontentloaded', timeout: 90000 }); await sleep(3000);
  await page.click('text=Reject', { timeout: 5000 }).catch(() => {});  // decline the optional cookies
  await scene('blog',async () => { await point('sub-second finality', 4500); await shot('blog_claim'); });

  await page.goto('https://docs.rayls.com/docs/meet-axyl-the-consensus-behind-rayls', { waitUntil: 'domcontentloaded', timeout: 90000 }); await sleep(3000);
  await scene('docs', async () => {
    await point('the Rayls Foundation operates them', 3500); await shot('docs_foundation');
    await point('treating the absence of a receipt as a drop', 4500); await shot('docs_drop');
  });

  await openLab();
  await scene('setup', async () => {
    await T('type', 'git log -1 --format="%h %ad" --date=short   # the exact Axyl commit I built');
    await T('print', await wsl('git', '-C', '~/axyl-lab/axyl', 'log', '-1', '--format=%h %ad', '--date=short').catch(() => exec('python', ['-c', 'print(open("../repo/AXYL_COMMIT.txt").read()[:7])'])));
    await sleep(3500); await shot('four_live');
  });

  await scene('baseline', async () => {
    await py('python demo.py pay 0   # one payment, nothing broken', 'demo.py', 'pay', '0');
    await T('hl', 'SETTLED'); await sleep(1500);
  });

  await scene('one_down', async cut => {
    await T('clear');
    await lab('bash lab_ctl.sh kill 3   # kill -9, a crash with no clean shutdown', 'kill', 3);
    await sleep(4000); await shot('one_down');
    await py('python demo.py pay 0', 'demo.py', 'pay', '0');
    await T('hl', 'SETTLED'); await sleep(1500); await shot('one_down_paid');
    await lab('bash lab_ctl.sh start 3', 'start', 3);
    cut(true, 2); await caughtUp(); cut(false);
    await sleep(1000);
  });

  await scene('two_down', async cut => {
    await T('clear');
    await T('clock', true, true);
    await lab('bash lab_ctl.sh kill 2; bash lab_ctl.sh kill 3   # two of four gone, quorum lost', 'kill', 2);
    await ctl('kill', 3);
    await T('print', 'killed validator index 3');
    await sleep(6000);
    const paying = py('python demo.py pay 0', 'demo.py', 'pay', '0');
    await sleep(5000); await shot('two_down_accepted_no_receipt');
    cut(true, 5); await sleep(30000); await shot('two_down_stalled');
    await T('type', 'bash lab_ctl.sh start 2; bash lab_ctl.sh start 3   # bring them back');
    await T('print', await ctl('start', 2)); await T('print', await ctl('start', 3));
    await paying; cut(false);
    await T('hl', 'SETTLED'); await T('clock', false); await sleep(2000); await shot('two_down_settled');
    cut(true, 1); await caughtUp(); cut(false);
  });

  await scene('agree', async cut => {
    await T('clear');
    await T('type', 'python demo.py agree   # same chain on all 4, across the outage?');
    cut(true); const out = stream('python', ['demo.py', 'agree']); await out; cut(false);
    await T('hl', 'hash mismatches'); await sleep(3500); await shot('agree');
  });

  await scene('conflict', async cut => {
    await T('clear');
    await T('type', 'python demo.py conflict   # one nonce, two payments, two validators');
    cut(true, 1.5); await stream('python', ['demo.py', 'conflict', '0']); cut(false);
    await T('hl', 'receipt on 0 of 4'); await sleep(4500); await shot('conflict');
  });

  tiles(false);
  await page.goto(fileUrl('term'));
  await scene('testnet', async cut => {
    await T('print', 'Public Rayls Testnet, chain 7295799');
    for (let i = 0; i < 3; i++) {
      await T('type', 'python demo.py pay testnet');
      await stream('python', ['demo.py', 'pay', 'testnet']);
    }
    await T('hl', 'SETTLED'); await sleep(2500); await shot('testnet');
  });

  await page.goto(fileUrl('img=fig_hist.png'));
  await scene('hist', async () => { await sleep(6000); });

  await page.goto(fileUrl('img=fig_stall.png'));
  await scene('stall_chart', async () => { await sleep(6000); });

  await page.goto(fileUrl('img=fig_table.png'));
  await scene('table', async () => { await sleep(5000); });

  await page.goto(fileUrl('term'));
  await scene('checker', async () => {
    await T('type', 'python check_results.py   # recomputes every number from the raw data');
    const all = await exec('python', ['check_results.py']);
    await T('print', all.trim().split('\n').slice(-1)[0]); await sleep(800);
    await T('type', 'python test_tamper.py   # alter the data 11 ways: the checker must reject each');
    await T('print', await exec('python', ['test_tamper.py']));
    await T('hl', 'altered copies rejected'); await sleep(3000); await shot('checker');
  });

  await page.goto(fileUrl('end'));
  await scene('end', async () => { await sleep(8000); });

  await browser.close();
  console.log('recording done');
})().catch(e => { console.error(e); process.exit(1); });
