import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import worker, { getReviews, handleApiRequest } from "../cloudflare/worker-radar.js";

const root = new URL("../docs/radar/", import.meta.url);

function assets(overrides = {}) {
  return {
    async fetch(request) {
      const requestedPath = new URL(request.url).pathname;
      const path = requestedPath.endsWith("/") ? `${requestedPath}index.html` : requestedPath;
      if (Object.hasOwn(overrides, path)) return new Response(overrides[path]);
      try {
        return new Response(await readFile(new URL(`.${path}`, root)), { status: 200 });
      } catch {
        return new Response("missing", { status: 404 });
      }
    },
  };
}

async function api(path, options = {}, overrides = {}) {
  return handleApiRequest(new Request(`https://radar.example${path}`, options), { ASSETS: assets(overrides) });
}

async function sha256(value) {
  const bytes = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value));
  return [...new Uint8Array(bytes)].map((item) => item.toString(16).padStart(2, "0")).join("");
}

test("health describes the verified certified snapshot", async () => {
  const response = await api("/api/v1/health");
  const body = await response.json();
  assert.equal(response.status, 200);
  assert.equal(body.status, "healthy");
  assert.match(body.snapshot_id, /^snapshot-v1-/);
  assert.equal(body.opportunity_count > 0, true);
  assert.ok(response.headers.get("etag"));
});

test("canonical snapshot, collection, and opportunity feed are projected", async () => {
  for (const name of ["snapshot", "collection", "opportunities"]) {
    const response = await api(`/api/v1/${name}`);
    assert.equal(response.status, 200);
    assert.equal(response.headers.get("content-type"), "application/json; charset=utf-8");
    assert.ok(response.headers.get("x-radar-snapshot-id"));
  }
});

test("opportunity feed preserves certified deterministic ordering", async () => {
  const source = JSON.parse(await readFile(new URL("../data/certified/current/opportunities.json", import.meta.url), "utf8"));
  const projected = await (await api("/api/v1/opportunities")).json();
  assert.deepEqual(projected.opportunities.map((item) => item.ticket.id),
    source.opportunities.map((item) => item.ticket.id));
});

test("individual record is byte-equivalent in content to feed record", async () => {
  const feed = await (await api("/api/v1/opportunities")).json();
  const expected = feed.opportunities[0];
  const response = await api(`/api/v1/opportunities/${expected.ticket.id}`);
  assert.deepEqual(await response.json(), expected);
});

test("multi-query provenance survives feed and individual projection", async () => {
  const snapshot = JSON.parse(await readFile(new URL("../data/certified/current/snapshot.json", import.meta.url), "utf8"));
  const feed = JSON.parse(await readFile(new URL("../data/certified/current/opportunities.json", import.meta.url), "utf8"));
  const first = feed.opportunities[0];
  first.discovery.sources.push({ ...first.discovery.sources[0], query_slug: "second_query", source_identity: "second_query", track: "second-track" });
  first.discovery.tracks.push("second-track");
  const feedText = JSON.stringify(feed) + "\n";
  snapshot.dataset_sha256 = await sha256(feedText);
  const snapshotText = JSON.stringify(snapshot) + "\n";
  const overrides = {
    "/api/v1/opportunities.json": feedText,
    "/api/v1/snapshot.json": snapshotText,
    "/api/v1/snapshot.sha256": `${await sha256(snapshotText)}  snapshot.json\n`,
  };
  const record = await (await api(`/api/v1/opportunities/${first.ticket.id}`, {}, overrides)).json();
  assert.equal(record.discovery.sources.length, 2);
  assert.deepEqual(record.discovery.sources, first.discovery.sources);
});

test("ticket errors and methods are explicit JSON failures", async () => {
  assert.equal((await api("/api/v1/opportunities/not-a-ticket")).status, 400);
  assert.equal((await api("/api/v1/opportunities/999999999")).status, 404);
  assert.equal((await api("/api/v1/opportunities", { method: "POST" })).status, 405);
});

test("ETag is stable and supports conditional GET", async () => {
  const first = await api("/api/v1/opportunities");
  const etag = first.headers.get("etag");
  const second = await api("/api/v1/opportunities", { headers: { "if-none-match": etag } });
  assert.equal(second.status, 304);
  assert.equal(second.headers.get("etag"), etag);
});

test("tampered certified data can never report healthy", async () => {
  const response = await api("/api/v1/health", {}, { "/api/v1/opportunities.json": "{}\n" });
  assert.equal(response.status, 503);
  assert.equal((await response.json()).code, "CERTIFIED_BUNDLE_INVALID");
});

test("missing certified data can never report healthy", async () => {
  const response = await handleApiRequest(new Request("https://radar.example/api/v1/health"), {
    ASSETS: { fetch: async () => new Response("missing", { status: 404 }) },
  });
  assert.equal(response.status, 503);
  assert.equal((await response.json()).code, "CERTIFIED_BUNDLE_MISSING");
});

test("malformed snapshot can never report healthy", async () => {
  const response = await api("/api/v1/health", {}, { "/api/v1/snapshot.json": "{\n" });
  assert.equal(response.status, 503);
  assert.equal((await response.json()).code, "CERTIFIED_BUNDLE_MALFORMED");
});

test("private review and authorization fields are absent from feed", async () => {
  const text = await (await api("/api/v1/opportunities")).text();
  for (const forbidden of ["review notes", "private_notes", "credentials", "authorization_token"]) {
    assert.equal(text.toLowerCase().includes(forbidden.toLowerCase()), false);
  }
});

test("existing static asset fallback remains intact", async () => {
  const response = await worker.fetch(new Request("https://radar.example/example.txt"), { ASSETS: assets({ "/example.txt": "static" }) });
  assert.equal(await response.text(), "static");
});

test("root serves the committed Radar dashboard asset", async () => {
  const response = await worker.fetch(new Request("https://radar.wp.org.nz/"), { ASSETS: assets() });
  assert.equal(response.status, 200);
  assert.match(await response.text(), /WP Core Radar/);
});

test("contributions route serves the committed static asset", async () => {
  const response = await worker.fetch(new Request("https://radar.wp.org.nz/contributions/"), { ASSETS: assets() });
  assert.equal(response.status, 200);
  assert.match(await response.text(), /WP Core Radar Contributions/);
});

test("existing admin route remains protected", async () => {
  const response = await worker.fetch(new Request("https://radar.example/admin/"), { ASSETS: assets() });
  assert.equal(response.status, 200);
  assert.match(await response.text(), /Protected Console/);
});

test("unauthenticated admin writes remain blocked", async () => {
  const response = await worker.fetch(new Request("https://radar.example/admin/save", {
    method: "POST",
    body: new URLSearchParams({ ticket: "65661", status: "watch" }),
  }), { ASSETS: assets() });
  assert.equal(response.status, 200);
  assert.match(await response.text(), /Protected Console/);
});


test("admin review reads use deployed credential-free projection", async () => {
  let externalFetches = 0;
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (...args) => {
    externalFetches += 1;
    return originalFetch(...args);
  };
  try {
    const reviews = await getReviews({ ASSETS: assets() });
    assert.equal(typeof reviews, "object");
    assert.equal(externalFetches, 0);
    for (const review of Object.values(reviews)) {
      assert.equal(Object.hasOwn(review, "notes"), false);
    }
  } finally {
    globalThis.fetch = originalFetch;
  }
});

async function adminSession(secret, csrf = "csrf-test") {
  const payload = Buffer.from(JSON.stringify({ exp: Date.now() + 3600000, csrf })).toString("base64url");
  const key = await crypto.subtle.importKey("raw", new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const signature = Buffer.from(await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(payload))).toString("base64url");
  return { cookie: `radar_admin=${payload}.${signature}`, csrf };
}

test("authenticated admin renders without any GitHub runtime credential", async () => {
  const secret = "test-session-secret";
  const session = await adminSession(secret);
  const response = await worker.fetch(new Request("https://radar.example/admin/", {
    headers: { cookie: session.cookie },
  }), { ASSETS: assets(), SESSION_SECRET: secret });
  assert.equal(response.status, 200);
  const body = await response.text();
  assert.match(body, /WP Core Radar Admin/);
  assert.match(body, /Read-only mode/);
  assert.match(body, /persistence is not currently available/i);
  assert.doesNotMatch(body, /Writes are restricted to data\/reviews\/reviews\.json/);
  assert.doesNotMatch(body, /GitHub read failed/);
});

test("review writes fail closed when executor is unavailable", async () => {
  const secret = "test-session-secret";
  const session = await adminSession(secret);
  const response = await worker.fetch(new Request("https://radar.example/admin/save", {
    method: "POST",
    headers: { cookie: session.cookie, "content-type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({ csrf: session.csrf, ticket: "65661", status: "watch" }),
  }), { ASSETS: assets(), SESSION_SECRET: secret });
  assert.equal(response.status, 503);
  const body = await response.text();
  assert.match(body, /EXECUTOR_UNAVAILABLE/);
  assert.match(body, /PERSIST_REVIEW_DECISION/);
  assert.match(body, /No durable review state was changed/);
});

test("props writes fail closed when executor is unavailable", async () => {
  const secret = "test-session-secret";
  const session = await adminSession(secret);
  const response = await worker.fetch(new Request("https://radar.example/admin/props", {
    method: "POST",
    headers: { cookie: session.cookie, "content-type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({ csrf: session.csrf, ticket: "64937", changeset: "62481" }),
  }), { ASSETS: assets(), SESSION_SECRET: secret });
  assert.equal(response.status, 503);
  const body = await response.text();
  assert.match(body, /EXECUTOR_UNAVAILABLE/);
  assert.match(body, /RECORD_PROPS_OUTCOME/);
});
