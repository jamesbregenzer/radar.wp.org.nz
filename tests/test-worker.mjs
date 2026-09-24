import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import worker, { handleApiRequest } from "../cloudflare/worker-radar.js";

const root = new URL("../docs/radar/", import.meta.url);

function assets(overrides = {}) {
  return {
    async fetch(request) {
      const path = new URL(request.url).pathname;
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

test("private review and contributor fields are absent from feed", async () => {
  const text = await (await api("/api/v1/opportunities")).text();
  for (const forbidden of ["review notes", "Eden", "HWP", "private contributor"]) {
    assert.equal(text.toLowerCase().includes(forbidden.toLowerCase()), false);
  }
});

test("existing static asset fallback remains intact", async () => {
  const response = await worker.fetch(new Request("https://radar.example/example.txt"), { ASSETS: assets({ "/example.txt": "static" }) });
  assert.equal(await response.text(), "static");
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
