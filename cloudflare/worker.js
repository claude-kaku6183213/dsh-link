/**
 * DSH Link — state API (Cloudflare Worker + KV)
 *
 *   POST /publish   Authorization: Bearer <PUBLISH_SECRET>   body = encrypted envelope JSON
 *                   → KV me current link ka encrypted payload store
 *   GET  /state     → wahi payload (Cache-Control: no-store, CORS: *)
 *   GET  /healthz   → {ok, t}
 *
 * Kyun: GitHub raw CDN cache-buster ignore karta hai (naya link 1-5 min late dikhta hai).
 * KV read edge-local aur uncached hota hai → link turant visible.
 *
 * Deploy: tools/deploy_worker.sh (wrangler) — secrets: PUBLISH_SECRET
 */

const CORS = {
  "access-control-allow-origin": "*",
  "access-control-allow-headers": "authorization,content-type",
  "access-control-allow-methods": "GET,POST,OPTIONS",
};

const json = (body, status = 200) =>
  new Response(body, {
    status,
    headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store", ...CORS },
  });

const MAX_BODY = 64 * 1024;          // envelope ~400 bytes; 64 KB bahut zyada hai
const TTL = 7 * 24 * 3600;           // 7 din — itne me notebook ka heartbeat aa hi jata hai

function timingSafeEqual(a, b) {
  const enc = new TextEncoder();
  const x = enc.encode(a), y = enc.encode(b);
  if (x.length !== y.length) return false;
  let diff = 0;
  for (let i = 0; i < x.length; i++) diff |= x[i] ^ y[i];
  return diff === 0;
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (request.method === "OPTIONS") return new Response(null, { status: 204, headers: CORS });
    if (url.pathname === "/healthz") return json(JSON.stringify({ ok: true, t: Date.now() }));

    if (url.pathname === "/publish") {
      if (request.method !== "POST") return json('{"error":"method_not_allowed"}', 405);
      if (!env.PUBLISH_SECRET) return json('{"error":"worker_misconfigured"}', 500);

      const auth = request.headers.get("authorization") || "";
      const given = auth.startsWith("Bearer ") ? auth.slice(7) : "";
      if (!given || !timingSafeEqual(given, env.PUBLISH_SECRET)) return json('{"error":"unauthorized"}', 401);

      const text = await request.text();
      if (!text || text.length > MAX_BODY) return json('{"error":"bad_body"}', 400);
      let parsed;
      try {
        parsed = JSON.parse(text);
      } catch {
        return json('{"error":"not_json"}', 400);
      }
      if (!parsed || !parsed.ct || !parsed.iv) return json('{"error":"not_an_envelope"}', 400);

      await env.DSH_LINK.put("current", text, { expirationTtl: TTL });
      return json(JSON.stringify({ ok: true, at: Date.now() }));
    }

    if (url.pathname === "/state") {
      const value = await env.DSH_LINK.get("current");
      return json(value || "{}");
    }

    return json('{"error":"not_found"}', 404);
  },
};
