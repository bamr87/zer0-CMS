// Config as code — which is exactly why `readSiteConfigFacts` refuses to read
// it and warns instead of running a regex over somebody's JavaScript.
module.exports = {
  title: 'Fixture Docusaurus',
  url: 'https://example.dev',
  baseUrl: '/',
  presets: [['classic', { docs: { path: 'docs' }, blog: { path: 'blog' } }]],
};
