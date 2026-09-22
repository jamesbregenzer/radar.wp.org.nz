const GITHUB_OWNER = "jamesbregenzer";
const DEFAULT_GITHUB_REPO = "radar.wp.org.nz";
const REVIEWS_PATH = "data/reviews/reviews.json";
const ALLOWED_STATUSES = new Set(["", "shortlist", "watch", "reject", "tested", "commented", "committed"]);

function githubRepo(env) {
  return env.GITHUB_REPO || DEFAULT_GITHUB_REPO;
}

function html(body, status = 200) {
  return new Response(body, {
    status,
    headers: {
      "content-type": "text/html; charset=utf-8",
      "cache-control": "no-store",
    },
  });
}

async function sha256Hex(value) {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value));
  return [...new Uint8Array(digest)].map((x) => x.toString(16).padStart(2, "0")).join("");
}

function safeEqual(a, b) {
  if (!a || !b || a.length !== b.length) return false;
  let result = 0;
  for (let i = 0; i < a.length; i++) result |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return result === 0;
}

function bytesToBase64(bytes) {
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary);
}

function textToBase64(value) {
  return bytesToBase64(new TextEncoder().encode(value));
}

function base64ToText(value) {
  const binary = atob(value.replace(/\n/g, ""));
  const bytes = Uint8Array.from(binary, (char) => char.charCodeAt(0));
  return new TextDecoder().decode(bytes);
}

function base64url(value) {
  return textToBase64(value).replaceAll("+", "-").replaceAll("/", "_").replaceAll("=", "");
}

function base64urlToText(value) {
  const padded = value.replaceAll("-", "+").replaceAll("_", "/") + "===".slice((value.length + 3) % 4);
  return base64ToText(padded);
}

async function sign(value, secret) {
  const key = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"]
  );
  const signature = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(value));
  return bytesToBase64(new Uint8Array(signature)).replaceAll("+", "-").replaceAll("/", "_").replaceAll("=", "");
}

async function createSession(env) {
  const payload = base64url(JSON.stringify({
    exp: Date.now() + 1000 * 60 * 60 * 8,
    csrf: crypto.randomUUID(),
  }));
  return `${payload}.${await sign(payload, env.SESSION_SECRET)}`;
}

async function readSession(request, env) {
  const cookie = request.headers.get("cookie") || "";
  const match = cookie.match(/(?:^|;\s*)radar_admin=([^;]+)/);
  if (!match) return null;

  const [payload, signature] = match[1].split(".");
  if (!payload || !signature) return null;

  const expected = await sign(payload, env.SESSION_SECRET);
  if (!safeEqual(signature, expected)) return null;

  try {
    const session = JSON.parse(base64urlToText(payload));
    if (!session.exp || Date.now() > session.exp) return null;
    return session;
  } catch {
    return null;
  }
}

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#039;",
  }[char]));
}

function layout(title, body) {
  return `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>${esc(title)}</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    body { margin: 0; font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #f6f7f7; color: #1d2327; }
    header { padding: 28px 36px; background: #151922; color: #fff; }
    header h1 { margin: 0 0 6px; font-size: 30px; }
    header p { margin: 0; color: #cbd5e1; }
    main { padding: 24px 36px 48px; }
    a { color: #2271b1; font-weight: 700; }
    .topnav { float: right; margin-top: -44px; display: flex; align-items: center; gap: 10px; }
    .nav-pill { display: inline-flex; align-items: center; gap: 8px; padding: 9px 13px; border: 1px solid rgba(255,255,255,.22); border-radius: 999px; background: rgba(255,255,255,.1); color: #fff !important; font-size: 13px; font-weight: 800; line-height: 1; text-decoration: none; box-shadow: 0 8px 24px rgba(0,0,0,.18); }
    .nav-pill:hover, .nav-pill:focus { background: rgba(255,255,255,.18); border-color: rgba(255,255,255,.4); color: #fff !important; }
    .nav-pill-secondary { background: transparent; }
    .nav-pill-dashboard::before { content: "←"; font-size: 13px; }
    .nav-pill-signout::before { content: "⎋"; font-size: 13px; }
    .summary { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 16px; margin-bottom: 24px; }
    .stat { background: #fff; border: 1px solid #dcdcde; border-radius: 10px; padding: 16px; }
    .stat strong { display: block; font-size: 28px; margin-bottom: 4px; }
    .stat-blue { border-left: 6px solid #2563eb; } .stat-purple { border-left: 6px solid #7c3aed; } .stat-amber { border-left: 6px solid #d97706; }
    section { margin-top: 30px; }
    h2 { display: flex; align-items: baseline; gap: 8px; }
    h2 span { color: #646970; font-size: 14px; }
    .table-wrap { overflow-x: auto; background: #fff; border: 1px solid #dcdcde; border-radius: 10px; }
    table { width: 100%; border-collapse: collapse; font-size: 14px; }
    th, td { padding: 11px 12px; border-bottom: 1px solid #f0f0f1; text-align: left; vertical-align: top; }
    th { background: #f0f0f1; white-space: nowrap; }
    .ticket-row.tier-immediate { border-left: 6px solid #2563eb; } .ticket-row.tier-strong { border-left: 6px solid #7c3aed; } .ticket-row.tier-watching { border-left: 6px solid #d97706; }
    .score { font-weight: 800; font-size: 18px; }
    .drawer-backdrop { position: fixed; inset: 0; z-index: 40; background: rgba(15, 23, 42, .42); backdrop-filter: blur(2px); }
    .drawer { position: fixed; inset: 0 0 0 auto; z-index: 50; width: min(1040px, 96vw); max-width: 100vw; overflow-y: auto; overflow-x: hidden; background: #f6f7f7; box-shadow: -24px 0 70px rgba(0,0,0,.28); border-left: 1px solid #dcdcde; box-sizing: border-box; }
    .drawer-inner { position: relative; padding: 22px; box-sizing: border-box; max-width: 100%; }
    .drawer-close { position: absolute; top: 18px; right: 20px; z-index: 2; display: inline-flex; align-items: center; justify-content: center; width: 34px; height: 34px; border: 1px solid #dcdcde; border-radius: 999px; background: #fff; color: #1d2327; font-size: 20px; font-weight: 900; line-height: 1; text-decoration: none; box-shadow: 0 4px 14px rgba(0,0,0,.08); }
    .drawer-close:hover, .drawer-close:focus { background: #f8fafc; color: #0f172a; text-decoration: none; }
    .tray { padding: 0; }
    .tray-header { display: flex; justify-content: space-between; gap: 18px; background: #fff; border: 1px solid #dcdcde; border-left: 6px solid #2271b1; border-radius: 10px; padding: 14px 16px; margin-bottom: 14px; box-sizing: border-box; width: 100%; }
    .tray-header h3 { margin: 0 0 6px; font-size: 22px; } .tray-header p { margin: 0; font-weight: 700; }
    .tray-meta { display: flex; align-items: center; gap: 10px; white-space: nowrap; flex-wrap: wrap; justify-content: flex-end; }
    .tray-grid { display: grid; grid-template-columns: minmax(300px, 1.1fr) minmax(270px, .85fr) minmax(300px, .95fr); gap: 14px; align-items: stretch; }
    .tray-panel { background: #fff; border: 1px solid #dcdcde; border-radius: 10px; padding: 14px; box-sizing: border-box; min-width: 0; }
    .tray-panel h4 { margin: 0 0 12px; color: #3c434a; font-size: 13px; letter-spacing: .04em; text-transform: uppercase; }
    .ticket-meta { display: flex; flex-wrap: wrap; gap: 10px 18px; margin: 10px 0 0; color: #3c434a; }
    .ticket-meta span { white-space: nowrap; }
    .badge, .tier-label { display: inline-block; border-radius: 999px; padding: 4px 8px; margin: 0 4px 7px 0; font-size: 12px; font-weight: 800; white-space: nowrap; }
    .signal-standard, .tier-label-standard { background: #f3f4f6; color: #4b5563; }
    .signal-priority, .signal-owner { background: #e0f2fe; color: #075985; }
    .signal-patch, .tier-label-immediate { background: #dbeafe; color: #1d4ed8; }
    .signal-testing { background: #dcfce7; color: #166534; }
    .signal-first, .tier-label-watching { background: #fef3c7; color: #92400e; }
    .signal-feedback, .tier-label-strong { background: #ede9fe; color: #6d28d9; }
    .signal-refresh { background: #ffedd5; color: #9a3412; } .signal-recent, .signal-freshness { background: #ccfbf1; color: #115e59; } .signal-age { background: #fee2e2; color: #991b1b; } .signal-momentum { background: #e0e7ff; color: #3730a3; } .signal-component { background: #fce7f3; color: #9d174d; } .signal-complexity { background: #fee2e2; color: #991b1b; }
    .score-breakdown { list-style: none; padding: 0; margin: 0; display: grid; gap: 7px; }
    .score-breakdown li { display: grid; grid-template-columns: 48px minmax(150px, 1fr); gap: 8px; align-items: baseline; }
    .score-breakdown li span:last-child { white-space: nowrap; }
    .score-positive { color: #008a20; font-weight: 900; } .score-negative { color: #b32d2e; font-weight: 900; } .score-neutral { color: #646970; font-weight: 900; }
    .score-total { border-top: 1px solid #dcdcde; margin-top: 12px; padding-top: 10px; font-size: 15px; }
    .tools { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-bottom: 14px; }
    .button-link, .copy-button, button { display: inline-block; text-align: center; border: 0; border-radius: 7px; padding: 9px 11px; background: #2271b1; color: #fff; font-weight: 800; text-decoration: none; cursor: pointer; font: inherit; }
    .copy-button { background: #7c3aed; }
    label { display: block; margin-top: 10px; font-weight: 800; }
    input, select, textarea { width: 100%; box-sizing: border-box; margin-top: 5px; padding: 9px; border: 1px solid #c3c4c7; border-radius: 7px; font: inherit; }
    textarea { min-height: 84px; }
    .review-form { margin-top: 4px; }
    .review-form button[type="submit"] { margin-top: 12px; }
    .notice { background: #fff; border-left: 5px solid #008a20; border-radius: 8px; padding: 14px 16px; margin-bottom: 18px; }
    .muted { color: #646970; }

    .ticket-row { cursor: pointer; }
    .ticket-row:hover td, .ticket-row:focus-within td, .ticket-row.is-active td { background: #f8fafc; }
    .props-badge { background: #fef3c7; color: #92400e; }
    .props-drawer .tray-header { margin-bottom: 14px; }
    .props-form { display: grid; gap: 10px; }
    .props-form button { margin-top: 8px; }

    .login-shell {
      min-height: 100vh;
      box-sizing: border-box;
      display: grid;
      place-items: center;
      padding: 42px 18px;
      background:
        radial-gradient(circle at 18% 18%, rgba(37, 99, 235, .18), transparent 32%),
        radial-gradient(circle at 78% 22%, rgba(124, 58, 237, .15), transparent 30%),
        linear-gradient(135deg, #0f172a 0%, #151922 48%, #1d2327 100%);
    }
    .login-card {
      position: relative;
      width: min(760px, 100%);
      overflow: hidden;
      border: 1px solid rgba(255,255,255,.14);
      border-radius: 22px;
      padding: 34px;
      background:
        linear-gradient(145deg, rgba(255,255,255,.96), rgba(248,250,252,.92));
      box-shadow: 0 24px 70px rgba(0,0,0,.32);
    }
    .login-card::before {
      content: "";
      position: absolute;
      inset: 0;
      pointer-events: none;
      background:
        linear-gradient(90deg, rgba(37,99,235,.13), transparent 28%, transparent 72%, rgba(124,58,237,.12)),
        radial-gradient(circle at 92% 10%, rgba(37,99,235,.16), transparent 24%);
    }
    .login-brand,
    .login-form,
    .login-footer,
    .login-intro,
    .login-error {
      position: relative;
      z-index: 2;
    }
    .login-brand {
      display: flex;
      align-items: center;
      gap: 15px;
      margin-bottom: 16px;
    }
    .login-mark {
      width: 54px;
      height: 54px;
      display: grid;
      place-items: center;
      border-radius: 16px;
      background: #151922;
      box-shadow: inset 0 0 0 1px rgba(255,255,255,.12), 0 12px 28px rgba(15,23,42,.25);
    }
    .login-mark span {
      width: 24px;
      height: 24px;
      border: 3px solid #60a5fa;
      border-radius: 50%;
      position: relative;
    }
    .login-mark span::before,
    .login-mark span::after {
      content: "";
      position: absolute;
      background: #60a5fa;
    }
    .login-mark span::before {
      width: 10px;
      height: 3px;
      top: 8px;
      left: -8px;
    }
    .login-mark span::after {
      width: 3px;
      height: 10px;
      top: -8px;
      left: 8px;
    }
    .login-kicker {
      margin: 0 0 4px;
      color: #2563eb;
      font-size: 12px;
      font-weight: 900;
      letter-spacing: .12em;
      text-transform: uppercase;
    }
    .login-card h1 {
      margin: 0;
      color: #111827;
      font-size: clamp(30px, 4vw, 42px);
      letter-spacing: -.04em;
    }
    .login-intro {
      max-width: 510px;
      margin: 0 0 24px;
      color: #475569;
      font-size: 16px;
      line-height: 1.55;
    }
    .login-form {
      max-width: 430px;
    }
    .login-form label {
      color: #1f2937;
    }
    .login-form input {
      height: 46px;
      border-color: #cbd5e1;
      background: #fff;
      box-shadow: 0 1px 0 rgba(15,23,42,.03);
    }
    .login-form input:focus {
      outline: 3px solid rgba(37,99,235,.18);
      border-color: #2563eb;
    }
    .login-form button {
      width: 100%;
      margin-top: 14px;
      padding: 12px 14px;
      border-radius: 10px;
      background: linear-gradient(135deg, #2563eb, #7c3aed);
      box-shadow: 0 12px 26px rgba(37,99,235,.28);
    }
    .login-footer {
      margin: 18px 0 0;
    }
    .login-footer a {
      color: #334155;
    }
    .login-error {
      max-width: 430px;
      margin: 0 0 14px;
      border-left: 5px solid #b32d2e;
      border-radius: 10px;
      padding: 11px 13px;
      background: #fef2f2;
      color: #991b1b;
      font-weight: 900;
    }
    .login-radar-preview {
      position: absolute;
      right: 36px;
      bottom: 34px;
      width: 210px;
      height: 210px;
      z-index: 1;
      opacity: .82;
    }
    .radar-ring,
    .radar-sweep,
    .radar-dot {
      position: absolute;
      border-radius: 50%;
    }
    .radar-ring {
      inset: 0;
      border: 1px solid rgba(37,99,235,.16);
    }
    .radar-ring-two {
      inset: 35px;
    }
    .radar-ring-three {
      inset: 70px;
      background: rgba(37,99,235,.06);
    }
    .radar-sweep {
      inset: 0;
      background: conic-gradient(from 220deg, rgba(37,99,235,.32), transparent 34%);
      clip-path: circle(50% at 50% 50%);
    }
    .radar-dot {
      width: 9px;
      height: 9px;
      background: #2563eb;
      box-shadow: 0 0 0 6px rgba(37,99,235,.12);
    }
    .radar-dot-one {
      top: 54px;
      left: 118px;
    }
    .radar-dot-two {
      top: 122px;
      left: 54px;
      background: #7c3aed;
      box-shadow: 0 0 0 6px rgba(124,58,237,.12);
    }
    .radar-dot-three {
      right: 44px;
      bottom: 52px;
      background: #d97706;
      box-shadow: 0 0 0 6px rgba(217,119,6,.14);
    }
    @media (max-width: 1050px) {
      .tray-grid { grid-template-columns: 1fr; }
      .topnav { float: none; margin-top: 16px; flex-wrap: wrap; }
    }
    @media (max-width: 720px) {
      .login-card { padding: 26px; }
      .login-radar-preview { opacity: .2; right: -42px; bottom: -42px; }
      .login-form { max-width: none; }
    }
  </style>
</head>
<body>${body}</body>
</html>`;
}

function loginPage(error = "") {
  return html(layout("WP Core Radar Admin", `
    <main class="login-shell">
      <section class="login-card" aria-labelledby="login-title">
        <div class="login-brand">
          <div class="login-mark" aria-hidden="true">
            <span></span>
          </div>
          <div>
            <p class="login-kicker">Protected Console</p>
            <h1 id="login-title">WP Core Radar Admin</h1>
          </div>
        </div>

        <p class="login-intro">
          Review new WordPress Core opportunities, record decisions, and keep contribution targets organized.
        </p>

        <div class="login-radar-preview" aria-hidden="true">
          <div class="radar-ring radar-ring-one"></div>
          <div class="radar-ring radar-ring-two"></div>
          <div class="radar-ring radar-ring-three"></div>
          <div class="radar-sweep"></div>
          <div class="radar-dot radar-dot-one"></div>
          <div class="radar-dot radar-dot-two"></div>
          <div class="radar-dot radar-dot-three"></div>
        </div>

        ${error ? `<p class="login-error">${esc(error)}</p>` : ""}

        <form method="post" action="/admin/login" class="login-form">
          <label for="radar-password">Password</label>
          <input id="radar-password" type="password" name="password" autocomplete="current-password" required>
          <button type="submit">Sign in to Radar</button>
        </form>

        <p class="login-footer">
          <a href="/">← Back to public dashboard</a>
        </p>
      </section>
    </main>
  `));
}

async function githubRequest(env, path, options = {}) {
  return fetch(`https://api.github.com${path}`, {
    ...options,
    headers: {
      accept: "application/vnd.github+json",
      authorization: `Bearer ${env.GITHUB_TOKEN}`,
      "x-github-api-version": "2022-11-28",
      "user-agent": "wp-core-radar-admin",
      ...(options.headers || {}),
    },
  });
}

async function getReviews(env) {
  const response = await githubRequest(env, `/repos/${GITHUB_OWNER}/${githubRepo(env)}/contents/${REVIEWS_PATH}`);
  if (!response.ok) throw new Error(`GitHub read failed: ${response.status}`);
  const file = await response.json();
  return { reviews: JSON.parse(base64ToText(file.content)), sha: file.sha };
}

async function saveReviews(env, reviews, sha, ticket) {
  const response = await githubRequest(env, `/repos/${GITHUB_OWNER}/${githubRepo(env)}/contents/${REVIEWS_PATH}`, {
    method: "PUT",
    body: JSON.stringify({
      message: `Record review decision for #${ticket}`,
      content: textToBase64(JSON.stringify(reviews, null, 2) + "\n"),
      sha,
      branch: "main",
    }),
  });
  if (!response.ok) throw new Error(`GitHub write failed: ${response.status} ${await response.text()}`);
}

async function getAdminData(env) {
  const response = await env.ASSETS.fetch(new Request("https://radar-assets.local/admin-data.json", {
    headers: { "cache-control": "no-cache" },
  }));
  if (!response.ok) throw new Error(`Admin data read failed: ${response.status}`);
  return response.json();
}

function statusOptions(current) {
  const labels = {
    "": "Choose action...",
    shortlist: "Shortlist",
    watch: "Watch",
    reject: "Reject",
    tested: "Tested",
    commented: "Commented",
    committed: "Committed",
  };
  return Object.entries(labels).map(([value, label]) => `<option value="${esc(value)}" ${value === current ? "selected" : ""}>${esc(label)}</option>`).join("");
}

function hasReceivedProps(review) {
  return review?.received_props === true || review?.status === "props";
}

function reviewStats(reviews) {
  const entries = Object.values(reviews || {});
  const reviewed = entries.length;
  const propsReceived = entries.filter(hasReceivedProps).length;
  const actedOn = entries.filter((review) => ["tested", "commented", "committed"].includes(review.status)).length;
  const propsRate = actedOn ? Math.round((propsReceived / actedOn) * 100) : 0;

  return {
    reviewed,
    propsReceived,
    actedOn,
    propsRate,
  };
}

function renderPropsDrawer(session, ticket = "") {
  return `
    <div class="drawer-backdrop" data-close-drawer></div>
    <aside class="drawer props-drawer" aria-label="Record historical props">
      <div class="drawer-inner">
        <a class="drawer-close" href="/admin/" data-close-drawer aria-label="Close">×</a>
        <div class="tray">
          <div class="tray-header">
            <div>
              <h3>Record historical props</h3>
              <p>Use this when WordPress.org shows contributor credit for a ticket that is no longer in the active Radar opportunity data.</p>
            </div>
            <div class="tray-meta"><span class="badge props-badge">🏆 Props Outcome</span></div>
          </div>
          <div class="tray-panel props-panel">
            <form method="post" action="/admin/props" class="review-form props-form">
              <input type="hidden" name="csrf" value="${esc(session.csrf)}">
              <label>Ticket ID</label>
              <input name="ticket" inputmode="numeric" pattern="[0-9]+" value="${esc(ticket)}" placeholder="64937" required>
              <label>Changeset <span class="muted">(optional)</span></label>
              <input name="changeset" inputmode="numeric" pattern="[0-9]*" placeholder="62481">
              <label>Reason</label>
              <input name="reason" maxlength="160" value="Props received" placeholder="Props received">
              <label>Notes <span class="muted">(optional)</span></label>
              <textarea name="notes" maxlength="1000" placeholder="Add contribution details or profile/SVN context..."></textarea>
              <button type="submit">Record props</button>
            </form>
          </div>
        </div>
      </div>
    </aside>`;
}

function renderBadges(signals) {
  return (signals || []).map((signal) => `<span class="badge signal-${esc(signal.class || "standard")}">${esc(signal.label)}</span>`).join(" ");
}

function renderBreakdown(items) {
  return `<ul class="score-breakdown">${(items || []).map((item) => `<li><span class="score-${esc(item.polarity)}">${esc(item.points)}</span><span>${esc(item.label)}</span></li>`).join("")}</ul>`;
}

function copyContext(item) {
  const scoring = (item.score_breakdown || [])
    .map((entry) => `- ${entry.label}: ${entry.points}`)
    .join("\n");

  const signals = (item.signals || [])
    .map((signal) => signal.label)
    .join(", ");

  return [
    "Please review this WordPress Core contribution opportunity and help me choose the fastest legitimate contribution path.",
    "",
    `Ticket: #${item.ticket_id}`,
    `URL: ${item.url}`,
    `Summary: ${item.summary}`,
    `Score: ${item.score}`,
    `Priority tier: ${item.tier_label}`,
    `Track: ${item.track}`,
    `Discovery track: ${item.discovery_track || "Unknown"}`,
    "",
    "Ticket fields:",
    `- Component: ${item.component || "Unknown"}`,
    `- Status: ${item.status || "Unknown"}`,
    `- Owner: ${item.owner || "Unknown"}`,
    `- Keywords: ${item.keywords || "Unknown"}`,
    `- Signals: ${signals || "Unknown"}`,
    `- Comments: ${item.comments || "Unknown"}`,
    `- Created: ${item.created || "Unknown"}`,
    `- Modified: ${item.modified || "Unknown"}`,
    "",
    "Radar scoring details:",
    scoring || "- No scoring details available",
    "",
    "Contribution assessment requested:",
    "- Green Light, Yellow Light, or Red Light",
    "- Contribution difficulty: Very Easy, Easy, Moderate, or Difficult",
    "- Fastest legitimate contribution path: comment only, code review, Playground testing, local testing, patch development, or watch only",
    "- Evidence needed before leaving a useful Core comment",
    "- Specific next steps I should perform",
    "- Likelihood of visible contribution / props: High, Medium, or Low",
    "- Risk of wasting time: High, Medium, or Low",
    "",
    "Radar entry format requested:",
    "- Recommended Action: Shortlist, Watch, Reject, Tested, Commented, or Committed",
    "- Props should not be recommended as an action; props are recorded later only after contributor credit is received.",
    "- Short Reason: one concise sentence suitable for the Radar reason field",
    "- Review Notes: 2-6 concise sentences suitable for the Radar review notes field, including testing performed, outcome, whether a Trac/GitHub comment was left, and whether keywords were updated",
    "",
    "If I complete the recommended work successfully, please also provide:",
    "- Suggested Trac/GitHub comment",
    "- Suggested Radar entry with Action, Short Reason, and Review Notes",
  ].join("\n");
}

function renderTicketDrawer(item, session, reviews) {
  const review = reviews[item.ticket_id] || item.review || {};
  const ticket = esc(item.ticket_id);
  const tier = esc(item.tier_class);
  const propsBadge = hasReceivedProps(review) ? '<span class="badge props-badge">🏆 Props Received</span>' : "";
  const changesetMeta = review.changeset ? `<span>Changeset: <strong><a href="https://core.trac.wordpress.org/changeset/${esc(review.changeset)}" target="_blank">${esc(review.changeset)}</a></strong></span>` : "";

  return `
    <div class="drawer-backdrop" data-close-drawer></div>
    <aside class="drawer" aria-label="Ticket details">
      <div class="drawer-inner">
        <div class="tray">
          <div class="tray-header">
            <div>
              <h3>#${ticket}</h3>
              <p>${esc(item.summary)}</p>
              <div class="ticket-meta">
                <span>Component: <strong>${esc(item.component || "Unknown")}</strong></span>
                <span>Status: <strong>${esc(item.status || "Unknown")}</strong></span>
                <span>Created: <strong>${esc(item.created || "Unknown")}</strong></span>
                <span>Updated: <strong>${esc(item.modified || "Unknown")}</strong></span>
                ${changesetMeta}
              </div>
            </div>
            <div class="tray-meta">${propsBadge}<span class="tier-label tier-label-${tier}">${esc(item.tier_label)}</span><strong>Score ${esc(item.score)}</strong></div>
          </div>
          <div class="tray-grid">
            <div class="tray-panel">
              <h4>Ranking signals</h4>
              <div>${renderBadges(item.signals)}</div>
              <p class="muted">These signals contributed to this ticket's score.</p>
            </div>
            <div class="tray-panel">
              <h4>Score breakdown</h4>
              ${renderBreakdown(item.score_breakdown)}
              <p class="score-total">Final score: <strong>${esc(item.score)}</strong></p>
            </div>
            <div class="tray-panel">
              <h4>Review tools & decision</h4>
              <div class="tools">
                <a class="button-link" href="${esc(item.url)}" target="_blank">Open Trac ↗</a>
                <button type="button" class="copy-button" data-context="${esc(copyContext(item))}">Copy ⧉</button>
              </div>
              <form method="post" action="/admin/save" class="review-form">
                <input type="hidden" name="csrf" value="${esc(session.csrf)}">
                <input type="hidden" name="ticket" value="${ticket}">
                <label>Decision</label>
                <select name="status" required>${statusOptions(review.status || "")}</select>
                <label>Reason</label>
                <input name="reason" maxlength="160" value="${esc(review.reason || "")}" placeholder="Short reason">
                <label>Review notes</label>
                <textarea name="notes" maxlength="1000" placeholder="Add notes about this ticket...">${esc(review.notes || "")}</textarea>
                ${hasReceivedProps(review) ? `<p class="muted">🏆 Props received${review.props_recorded_at ? ` on ${esc(review.props_recorded_at.slice(0, 10))}` : ""}.</p>` : `<p class="muted"><a href="/admin/props?ticket=${ticket}">Record props for this ticket</a> after contributor credit appears on WordPress.org.</p>`}
                <button type="submit">Save review</button>
              </form>
            </div>
          </div>
        </div>
      </div>
    </aside>`;
}

function renderRow(item, session, reviews, activeTicket = "") {
  const review = reviews[item.ticket_id] || item.review || {};
  const ticket = esc(item.ticket_id);
  const tier = esc(item.tier_class);
  const isActive = String(item.ticket_id) === String(activeTicket);
  const propsMarker = hasReceivedProps(review) ? ' <span class="badge props-badge" title="Props received">🏆</span>' : "";

  return `
    <tr class="ticket-row tier-${tier} ${isActive ? "is-active" : ""}" data-ticket="${ticket}" tabindex="0" role="button" aria-expanded="${isActive ? "true" : "false"}">
      <td class="score">${esc(item.score)}</td>
      <td><span class="tier-label tier-label-${tier}">${esc(item.tier_label)}</span></td>
      <td><a href="${esc(item.url)}" target="_blank">#${ticket}</a>${propsMarker}</td>
      <td>${esc(item.summary)}</td>
    </tr>`;
}

function renderSection(title, items, session, reviews, activeTicket = "", limit = null) {
  const display = limit ? items.slice(0, limit) : items;
  const rows = display.map((item) => renderRow(item, session, reviews, activeTicket)).join("") || `<tr><td colspan="4" class="muted">No tickets in this section.</td></tr>`;
  return `<section><h2>${esc(title)} <span>${items.length}</span></h2><div class="table-wrap"><table><thead><tr><th>Score</th><th>Tier</th><th>Ticket</th><th>Summary</th></tr></thead><tbody>${rows}</tbody></table></div></section>`;
}

function activeTicketFromPath(pathname) {
  const match = pathname.match(/^\/admin\/ticket\/(\d+)\/?$/);
  return match ? match[1] : "";
}

function noticeFromUrl(url) {
  const saved = url.searchParams.get("saved");
  if (/^\d+$/.test(saved || "")) return `Saved review decision for #${saved}.`;

  const props = url.searchParams.get("props");
  if (/^\d+$/.test(props || "")) return `Recorded props for #${props}.`;

  return "";
}

function findTicket(groups, ticketId) {
  if (!ticketId) return null;
  for (const items of Object.values(groups || {})) {
    const match = (items || []).find((item) => String(item.ticket_id) === String(ticketId));
    if (match) return match;
  }
  return null;
}

async function adminPage(request, env) {
  const session = await readSession(request, env);
  if (!session) return loginPage();

  const [data, reviewFile] = await Promise.all([getAdminData(env), getReviews(env)]);
  const reviews = reviewFile.reviews || {};
  const reviewSummary = reviewStats(reviews);
  const summary = data.summary || {};
  const groups = data.groups || {};
  const url = new URL(request.url);
  const activeTicket = activeTicketFromPath(url.pathname);
  const activeItem = findTicket(groups, activeTicket);
  const notice = noticeFromUrl(url);
  const ticketNotInRadar = activeTicket && !activeItem;

  return html(layout("WP Core Radar Admin", `
    <header>
      <h1>WP Core Radar Admin</h1>
      <p>Protected review console. Writes are restricted to ${esc(REVIEWS_PATH)}.</p>
      <nav class="topnav" aria-label="Admin navigation">
        <a class="nav-pill nav-pill-dashboard" href="/">Public dashboard</a>
        <a class="nav-pill" href="/admin/props">Record props</a>
        <a class="nav-pill nav-pill-secondary nav-pill-signout" href="/admin/logout">Sign out</a>
      </nav>
    </header>
    <main>
      ${notice ? `<div class="notice"><strong>${esc(notice)}</strong></div>` : ""}
      ${ticketNotInRadar ? `<div class="notice"><strong>Ticket #${esc(activeTicket)} is not in the current Radar opportunity data.</strong> Use the historical props drawer if this ticket received contributor credit.</div>` : ""}
      <div class="summary">
        <div class="stat"><strong>${esc(summary.unique_tickets || 0)}</strong>Unique tickets</div>
        <div class="stat"><strong>${esc(summary.priority_targets || 0)}</strong>Priority targets</div>
        <div class="stat stat-blue"><strong>${esc(summary.immediate || 0)}</strong>Immediate Review</div>
        <div class="stat stat-purple"><strong>${esc(summary.strong || 0)}</strong>Strong Candidates</div>
        <div class="stat stat-amber"><strong>${esc(summary.watching || 0)}</strong>Worth Watching</div>
        <div class="stat"><strong>${esc(reviewSummary.reviewed)}</strong>Reviews loaded</div>
        <div class="stat"><strong>${esc(reviewSummary.propsReceived)}</strong>Props received</div>
        <div class="stat"><strong>${esc(reviewSummary.propsRate)}%</strong>Props rate</div>
      </div>
      ${(url.pathname === "/admin/props" || ticketNotInRadar) ? renderPropsDrawer(session, activeTicket || url.searchParams.get("ticket") || "") : ""}
      ${renderSection("Priority Targets", groups.priority || [], session, reviews, activeTicket)}
      ${renderSection("Shortlisted", groups.shortlist || [], session, reviews, activeTicket)}
      ${renderSection("Watching", groups.watch || [], session, reviews, activeTicket)}
      ${renderSection("Completed / Acted On", groups.completed || [], session, reviews, activeTicket)}
      ${renderSection("Rejected", groups.rejected || [], session, reviews, activeTicket)}
      ${renderSection("Top Opportunities", groups.top || [], session, reviews, activeTicket, 50)}
      ${activeItem ? renderTicketDrawer(activeItem, session, reviews) : ""}
    </main>
    <script>
      document.addEventListener("click", async (event) => {
        const row = event.target.closest(".ticket-row");
        if (row && !event.target.closest("a, button, input, select, textarea, label")) {
          window.location.href = "/admin/ticket/" + row.dataset.ticket;
          return;
        }

        const closeDrawer = event.target.closest("[data-close-drawer]");
        if (closeDrawer) {
          event.preventDefault();
          window.location.href = "/admin/";
          return;
        }

        const copyButton = event.target.closest(".copy-button");
        if (copyButton) {
          await navigator.clipboard.writeText(copyButton.dataset.context || "");
          copyButton.textContent = "Copied";
          setTimeout(() => copyButton.textContent = "Copy ⧉", 1200);
        }
      });

      document.addEventListener("keydown", (event) => {
        if (event.key === "Escape" && document.querySelector(".drawer")) {
          window.location.href = "/admin/";
          return;
        }

        const row = event.target.closest(".ticket-row");
        if (!row || (event.key !== "Enter" && event.key !== " ")) return;
        event.preventDefault();
        window.location.href = "/admin/ticket/" + row.dataset.ticket;
      });
    </script>
  `));
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (url.pathname === "/health/live") {
      return Response.json({ status: "ok", service: "radar-wp-org-nz" }, {
        headers: { "cache-control": "no-store" },
      });
    }

    if (url.pathname === "/health/ready") {
      const response = await env.ASSETS.fetch(new Request("https://radar-assets.local/admin-data.json"));
      return Response.json({
        status: response.ok ? "ready" : "not_ready",
        assets: response.ok,
      }, {
        status: response.ok ? 200 : 503,
        headers: { "cache-control": "no-store" },
      });
    }

    // Legacy paths from the previous james.bregenzer.dev/radar setup.
    // Keep these redirects while bookmarks/search/history catch up.
    if (url.pathname === "/radar" || url.pathname === "/radar/") {
      return Response.redirect(`${url.origin}/`, 301);
    }

    if (url.pathname === "/radar/contributions" || url.pathname === "/radar/contributions/") {
      return Response.redirect(`${url.origin}/contributions`, 301);
    }

    if (url.pathname === "/radar/admin" || url.pathname === "/radar/admin/") {
      return Response.redirect(`${url.origin}/admin/`, 301);
    }

    if (url.pathname.startsWith("/radar/admin/")) {
      return Response.redirect(`${url.origin}${url.pathname.replace(/^\/radar\/admin/, "/admin")}${url.search}`, 301);
    }

    if (url.pathname.startsWith("/radar/")) {
      return Response.redirect(`${url.origin}${url.pathname.replace(/^\/radar/, "")}${url.search}`, 301);
    }

    if (url.pathname === "/admin/login" && request.method === "POST") {
      const form = await request.formData();
      const password = String(form.get("password") || "");
      const hash = await sha256Hex(password);
      if (!safeEqual(hash, env.ADMIN_PASSWORD_HASH)) return loginPage("Invalid password.");
      const session = await createSession(env);
      return new Response(null, {
        status: 303,
        headers: {
          location: "/admin/",
          "set-cookie": `radar_admin=${session}; Path=/admin; HttpOnly; Secure; SameSite=Strict; Max-Age=28800`,
        },
      });
    }

    if (url.pathname === "/admin/logout") {
      return new Response(null, {
        status: 303,
        headers: {
          location: "/admin/",
          "set-cookie": "radar_admin=; Path=/admin; HttpOnly; Secure; SameSite=Strict; Max-Age=0",
        },
      });
    }

    if (url.pathname === "/admin/save" && request.method === "POST") {
      const session = await readSession(request, env);
      if (!session) return loginPage();
      const form = await request.formData();
      if (String(form.get("csrf") || "") !== session.csrf) return html("Invalid CSRF token.", 403);

      const ticket = String(form.get("ticket") || "").trim();
      const status = String(form.get("status") || "").trim();
      const reason = String(form.get("reason") || "").trim();
      const notes = String(form.get("notes") || "").trim();
      if (!/^[0-9]+$/.test(ticket)) return html("Invalid ticket ID.", 400);
      if (!ALLOWED_STATUSES.has(status) || !status) return html("Invalid status.", 400);

      const { reviews, sha } = await getReviews(env);
      reviews[ticket] = {
        ...(reviews[ticket] || {}),
        status,
        reason,
        notes,
        updated_at: new Date().toISOString(),
      };
      await saveReviews(env, reviews, sha, ticket);
      return new Response(null, {
        status: 303,
        headers: { location: `/admin/ticket/${ticket}?saved=${ticket}` },
      });
    }

    if (url.pathname === "/admin/props" && request.method === "POST") {
      const session = await readSession(request, env);
      if (!session) return loginPage();
      const form = await request.formData();
      if (String(form.get("csrf") || "") !== session.csrf) return html("Invalid CSRF token.", 403);

      const ticket = String(form.get("ticket") || "").trim();
      const changeset = String(form.get("changeset") || "").trim();
      const reason = String(form.get("reason") || "Props received").trim() || "Props received";
      const notes = String(form.get("notes") || "").trim();

      if (!/^[0-9]+$/.test(ticket)) return html("Invalid ticket ID.", 400);
      if (changeset && !/^[0-9]+$/.test(changeset)) return html("Invalid changeset.", 400);

      const { reviews, sha } = await getReviews(env);
      const existing = reviews[ticket] || {};
      const now = new Date().toISOString();

      reviews[ticket] = {
        ...existing,
        status: existing.status && existing.status !== "props" ? existing.status : "committed",
        reason,
        notes: notes || existing.notes || "",
        received_props: true,
        props_recorded_at: existing.props_recorded_at || now,
        updated_at: now,
      };

      if (changeset) reviews[ticket].changeset = changeset;

      await saveReviews(env, reviews, sha, ticket);
      return new Response(null, {
        status: 303,
        headers: { location: `/admin/props?props=${ticket}` },
      });
    }

    if (url.pathname === "/admin" || url.pathname.startsWith("/admin/")) {
      return adminPage(request, env);
    }

    // Public pages and assets are deployed atomically with this Worker from
    // docs/radar. There is no separate Pages origin to drift or fail over.
    return env.ASSETS.fetch(request);
  },
};
