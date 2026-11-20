/* DSH Link config — ram ki file (koi secret nahi, dono values public-safe hain).
   GitHub Pages pe isi naam se commit hoti hai. Local override ke liye config.local.js use karo. */
window.DSH_LINK_CONFIG = {
  // --- Supabase (recommended: uncached + instant) ---------------------------
  // Supabase dashboard → Project Settings → API → "Project URL" + "anon public" key
  supabase: {
    url: 'https://XXXXXXXXXXXX.supabase.co',
    anon: 'eyJhbGciOi...',            // Legacy 'anon public' (ya naya 'sb_publishable_...') -- dono chalte hain
    table: 'launch_state',            // default
  },

  // --- GitHub fallback (CDN ki wajah se 1-3 min stale ho sakta hai) ---------
  // github.io pe auto-detect ho jata hai; yahan sirf tab bharo jab custom domain use karo.
  // owner: 'your-username',
  // repo: 'dsh-link',
  branch: 'main',
  path: 'state/current.json',

  // --- Optional: Cloudflare Worker endpoint (agar LINK_API_URL use kar rahe ho) ---
  // stateUrl: 'https://dsh-link.xxx.workers.dev/state',

  salt: 'dsh-link-v1',                // notebook ke LINK_SALT se match karna chahiye
};
