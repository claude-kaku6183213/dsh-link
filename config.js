/* DSH Link config — dono values public-safe hain (anon key client-side ke liye hi banti hai). */
window.DSH_LINK_CONFIG = {
  // GitHub fallback (CDN 1-5 min stale ho sakta hai, isliye sirf backup)
  owner: 'claude-kaku6183213',
  repo: 'dsh-link',
  branch: 'main',
  path: 'state/current.json',

  // PRIMARY: Supabase REST (uncached, ~0.2s)
  supabase: {
    url: 'https://lofqgjdfemxkfxpserin.supabase.co',
    anon: 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImxvZnFnamRmZW14a2Z4cHNlcmluIiwicm9sZSI6ImFub24iLCJpYXQiOjE3OTQ4MDk2MTQsImV4cCI6MjExMDM4NTYxNH0.fypvhatoxrHY8rzRGPHblkSJBgIv_JxwEmFRF5U9YeQ',
    table: 'launch_state',
  },

  salt: 'dsh-link-v1',
};
