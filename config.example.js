/* Optional override. GitHub Pages pe iski zarurat nahi (auto-detect hota hai).
   Sirf local test ya custom domain / custom backend ke liye banao: config.js
   (config.js .gitignore me hai) */
window.DSH_LINK_CONFIG = {
  owner: 'YOUR_GITHUB_USERNAME',
  repo: 'dsh-link',
  branch: 'main',
  path: 'state/current.json',
  salt: 'dsh-link-v1',        // ise change kar sakte ho, notebook me bhi same rakhna
  // stateUrl: 'https://dsh-link-api.example.workers.dev/state',  // Cloudflare Worker backend
};
