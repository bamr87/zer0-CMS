# Changelog

All notable changes to zer0-CMS are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.1.0](https://github.com/bamr87/zer0-CMS/compare/v1.0.0...v1.1.0) (2026-10-31)


### Features

* **sites:** zer0-pages moves to the Jekyll-theme option, the last site's Ruby gone ([bcdd672](https://github.com/bamr87/zer0-CMS/commit/bcdd67253adf9c35624ef5377d3a541a6cf10eca))
* **voice:** the Voice tab maps who reads which layer, and every badge can be read ([778ab22](https://github.com/bamr87/zer0-CMS/commit/778ab22cc066f8c543dd37d677268b610408d177))
* **voice:** V0 — compose a site's voice in one place and show it in the studio ([15ce35d](https://github.com/bamr87/zer0-CMS/commit/15ce35dfdc51040d759e3d1becba14af55b7b783))


### Bug Fixes

* **studio:** the Sites list asks for checkouts only for someone who may register a site ([780b0fa](https://github.com/bamr87/zer0-CMS/commit/780b0fa8bb75d909652378bd1d55fdb4f5622fdf))
* **voice:** show what the guard actually applies, and keep findings to their scope ([756348e](https://github.com/bamr87/zer0-CMS/commit/756348e53161a7d23edf9e2718e6fb9f3208cc91))
* **web:** the page picker searches the platform, so every page is within reach ([861d09b](https://github.com/bamr87/zer0-CMS/commit/861d09b76f0c8bf320618e5e94b1b113c5f93dcc))


### Performance Improvements

* **ci:** cut Actions minutes in content, CodeQL and the uncapped jobs ([508971f](https://github.com/bamr87/zer0-CMS/commit/508971ff462a337ab43edafb54737b8b8582e450))
* **ci:** cut Actions minutes in content, CodeQL and the uncapped jobs ([7cb8993](https://github.com/bamr87/zer0-CMS/commit/7cb8993a9437472b256554f5e7b3cffb29e27a51))

## [1.0.0](https://github.com/bamr87/zer0-CMS/compare/v0.3.0...v1.0.0) (2026-10-28)


### ⚠ BREAKING CHANGES

* **theme:** land "the theme goes home" on main (ADR 0005, PLAN Phase T)
* **theme:** `bin/zer0` no longer knows a `zer0-mistakes` project; a site that wants a local theme checkout names it with `ZER0_THEME_LOCAL` (drsai) or its own Gemfile `path:`.
* **parodynews:** DJANGO_SETTINGS_MODULE for the news app is config.settings.<env>; the workflow, compose files and docs in the tree are updated, external deployments must follow.

### Features

* **accounts:** G3 — sign-in through django-allauth (OIDC, MFA, passkeys), scoped tokens and the account menu ([73bb647](https://github.com/bamr87/zer0-CMS/commit/73bb6472509b81a152dc949ace2b35ffd3f61171))
* **accounts:** scoped person tokens, issued, listed and revoked over /api/v2/account/tokens/, accepted by GraphQL ([92e2336](https://github.com/bamr87/zer0-CMS/commit/92e2336cf4a6ff970afd1e40c845a60d23720706))
* **accounts:** sign in through django-allauth — local accounts, OpenID Connect IdPs from the environment, MFA, passkeys, the admins routed to it ([8f7254b](https://github.com/bamr87/zer0-CMS/commit/8f7254ba610948d61bb5c7a81283253a4c4ca516))
* **accounts:** the studio signs in through allauth's headless API, and the account menu ([2c391d4](https://github.com/bamr87/zer0-CMS/commit/2c391d48314540d1b10b60d11592d208c60dd93a))
* **ai:** /api/v2/ai/ and the ai.* tools ([6e3e94c](https://github.com/bamr87/zer0-CMS/commit/6e3e94c9bf5c5e90fbd53f3792cc84e334c4e99e))
* **aieo:** AIEO on the platform — audits, rewrites, patterns, agents, citations, connectors, reports ([deb463d](https://github.com/bamr87/zer0-CMS/commit/deb463d4b6e6caf1b6a849d90408bc011f5478ed))
* **aieo:** an audit's neighbours in meaning, on the platform's vectors in place of Qdrant ([b774745](https://github.com/bamr87/zer0-CMS/commit/b7747459cb5525ba124371f7d6f806bd6579acd7))
* **aieo:** the analyzers and the scoring engine, ported with AIEO's recorded outputs ([f87bd2e](https://github.com/bamr87/zer0-CMS/commit/f87bd2e8ec1c2b30688327b24a542897faf07eed))
* **ai:** image parts in a message, for the providers that can see ([ec9c6da](https://github.com/bamr87/zer0-CMS/commit/ec9c6dac0de66de381e69f08c9dfea5d3ba9ef96))
* **ai:** run an assistant or a pipeline on a page, its answer proposed there as suggestions ([f1af98c](https://github.com/bamr87/zer0-CMS/commit/f1af98c3716dfc77d309a3877d9afbe58234e26e))
* **ai:** run kinds, brief context and web search for the apps built on the AI layer ([a3e7544](https://github.com/bamr87/zer0-CMS/commit/a3e75441054255150be1b1768ac61c79f2f312ad))
* **ai:** the AI content layer's provider registry, tables and runs ([cd7da10](https://github.com/bamr87/zer0-CMS/commit/cd7da10a0017e282dc7f35948117f333f1bb3822))
* **automations:** triggers, JMESPath conditions and owner-run actions, every run logged (G16) ([4b07df0](https://github.com/bamr87/zer0-CMS/commit/4b07df04ba625c1d43ef35201da59b3424242f69))
* **books:** a book or its site may switch the brand guard's built-in bans off for its chapters ([acffdd9](https://github.com/bamr87/zer0-CMS/commit/acffdd9413e11cdc28520a6b43c07786486e7f9b))
* **books:** a book or its site may switch the brand guard's built-in bans off for its chapters ([1771807](https://github.com/bamr87/zer0-CMS/commit/177180751a4da1d91c261664b39190e09f3ffcff))
* **books:** books in the platform — the generated library, the bookshelf's commands and AI-assisted writing ([94a1a5b](https://github.com/bamr87/zer0-CMS/commit/94a1a5b76b6aab198bcbfb2892a96f27684bf277))
* **cms:** a book's and a chapter's manuscript fields ([d63085c](https://github.com/bamr87/zer0-CMS/commit/d63085c69c0e47c41597278b47bbc170e32a8f6f))
* **cms:** SEO fields beyond Wagtail's own — canonical URL, Open Graph, noindex ([87f13a5](https://github.com/bamr87/zer0-CMS/commit/87f13a59dbabc8a1317b3140cdca3dff99bbbbeb))
* **compose:** the platform carries distribution's settings and runs its own consumers ([7cec500](https://github.com/bamr87/zer0-CMS/commit/7cec5004b9d21db71201d6e6e42e2a9575bb50a9))
* **content:** a page's file path and raw front matter in the API and the studio ([7113867](https://github.com/bamr87/zer0-CMS/commit/71138677a08d68598569c13c1cfd7fe42d660ac8))
* **content:** a person's API token, for the VS Code extension ([6aadc19](https://github.com/bamr87/zer0-CMS/commit/6aadc19541e4df771660c3bfb83c8ab7ada4052e))
* **content:** find the pages a file was imported into ([a48ea70](https://github.com/bamr87/zer0-CMS/commit/a48ea7022e96077e3e8cbef3887efcb9d8fa20f2))
* **content:** G2's blocks — table, typed table, embed, document, raw HTML, Liquid, callout ([1d74448](https://github.com/bamr87/zer0-CMS/commit/1d74448f60ca3b9e47cfb17fce1f5eb5b7cc9170))
* **content:** jobs and the site registry — sync, write-back under the stale-write guard, and zer0 doctor in Python ([c2aaead](https://github.com/bamr87/zer0-CMS/commit/c2aaead98bb65d08b3a3d9bf05fa192a10aac9f7))
* **content:** log actions for suggestion, run and token events ([aca06e9](https://github.com/bamr87/zer0-CMS/commit/aca06e94e924fe2ae2f26ca8d8bd3a06dc56ba4d))
* **content:** one platform — ADR 0004, PLAN Phase G/H, and the ops baseline (G0 + G1) ([48d5276](https://github.com/bamr87/zer0-CMS/commit/48d52764f78ae365b54bc8a2e64bda7fde7344d7))
* **content:** P4's remaining items — G2's blocks, brand rules per site, the Editorial workflow, log actions, SEO fields ([a250e4d](https://github.com/bamr87/zer0-CMS/commit/a250e4d17f768ec3e4cef4c60fbd41ef97ca7208))
* **content:** the Jekyll catalog, front-matter surgery and the confined writer in Python ([f45a628](https://github.com/bamr87/zer0-CMS/commit/f45a62828f47b32580d1923e3864a9cc67aafb2f))
* **content:** the ops baseline — probes, request ids, the error envelope, JSON logging, throttling, CORS, OpenAPI ([5f8c9a9](https://github.com/bamr87/zer0-CMS/commit/5f8c9a92de6662a5426fc7276cec66a16e078b3c))
* **content:** the outbox desk — view, manage, run and publish onto the outbox harness from the studio ([d0a572f](https://github.com/bamr87/zer0-CMS/commit/d0a572fbb5237886b6339322d3f64f0f4895b356))
* **content:** the outbox desk — view, manage, run and publish onto the outbox harness from the studio ([f6264de](https://github.com/bamr87/zer0-CMS/commit/f6264de975cadd27b1e3fe2f792f4e5ddeea97d9))
* **content:** the studio's API — session, sites, pages, revisions, publishing, review inbox (P4) ([30cc910](https://github.com/bamr87/zer0-CMS/commit/30cc910f5f018185252e04ccf2aaf4344520d812))
* **distribution:** channels, the queue, the ledger and statistics on the platform ([641e400](https://github.com/bamr87/zer0-CMS/commit/641e40045220ed8d3746a5162b53a45bdcd4fade))
* **distribution:** manage.py linkedin mcp — the lane's MCP server in Python ([2e058ea](https://github.com/bamr87/zer0-CMS/commit/2e058eae2101f8b363e8abb2d92f153a590b9acd))
* **distribution:** the LinkedIn client in Python over httpx ([518496f](https://github.com/bamr87/zer0-CMS/commit/518496fd35d0e40f8c8a1fb22b0465556c5453aa))
* **docs:** generate the installer reference from its help text ([c769d7b](https://github.com/bamr87/zer0-CMS/commit/c769d7be916db63652f9e7ce8e36d311fb7cfbb3))
* **docs:** generate the settings reference in docs/CONFIG.md §5 from package.json ([fb24830](https://github.com/bamr87/zer0-CMS/commit/fb24830c6734fc5d33e5fb9caf91c15a393c5c6f))
* **docs:** generate the theme's command, workflow and agent-guidance reference ([43776eb](https://github.com/bamr87/zer0-CMS/commit/43776ebd3c726ce2d907131f6301ebca1e93fe8d))
* **extension:** the studio bridge asks before main's other live changes ([673e990](https://github.com/bamr87/zer0-CMS/commit/673e990093f25ed131ddda48155bb2309e96ec9b))
* **extension:** the studio's workspaces in the webviews when a platform is configured ([e4bde52](https://github.com/bamr87/zer0-CMS/commit/e4bde52e1c6f4585198dff4e6428080074267778))
* **extension:** the token prompt points to the studio's account menu ([8b83287](https://github.com/bamr87/zer0-CMS/commit/8b83287c0fb5ea68c043d671f8ac7fd127b14b37))
* **feedback:** adopt the universal page-feedback widget (kit v0.2.0) ([81ff49d](https://github.com/bamr87/zer0-CMS/commit/81ff49d2696a66969be5db77b0a8beb9cbe0f4f3))
* **image-gen:** illustration loop for the claude provider (plan → author → shape → look → critique) ([6519af6](https://github.com/bamr87/zer0-CMS/commit/6519af697374553be1e4406537d01e2f3c1ac788))
* **image-gen:** plan → author → shape → look → critique loop for the claude provider (WIP) ([34b2bcd](https://github.com/bamr87/zer0-CMS/commit/34b2bcdea87d3bbb52556c61eb422103d8832313))
* **image-gen:** Ruby twins, --shape, forge on the production path, CI + docs ([285fb6c](https://github.com/bamr87/zer0-CMS/commit/285fb6c7aebf6b8669d9648e71d4dcb0cbd02eb2))
* **importers:** barodybroject's AI tables onto the AI content layer ([235d857](https://github.com/bamr87/zer0-CMS/commit/235d85778d1a071b82db2ae530ecb25edd82095b))
* **newsroom:** desks, stories and the newsroom workflow, with fronts, bylines, corrections and newsletters ([5344ccb](https://github.com/bamr87/zer0-CMS/commit/5344ccbcd7dc162d2a69926fe962157b422f82be))
* **parodynews:** route the news app's Jekyll sidecar at /parodynews/ (PLAN C5) ([8c83b76](https://github.com/bamr87/zer0-CMS/commit/8c83b7648fd6aa56a545f9f62d31ff1807f50090))
* **research,ideas:** the research library and boards of ideas (G14 backend and API) ([27917fb](https://github.com/bamr87/zer0-CMS/commit/27917fb57c6c99f7d4d00b798b2ed486a4db622f))
* **site:** improve the frontend and fix production-only remote-theme defects (bamr87/wargames[#14](https://github.com/bamr87/zer0-CMS/issues/14)) ([0d34252](https://github.com/bamr87/zer0-CMS/commit/0d34252f0feeed5db470b8ccc88e1b16d8c82f3d))
* **sites:** brand rules per site — a site's banned phrases beside its voice ([e817621](https://github.com/bamr87/zer0-CMS/commit/e817621177fe44e84f2d5b9216fcba3cd08f1a3e))
* **sites:** eight sites render with the Jekyll-theme option; their Ruby goes (PLAN P2) ([9965fcf](https://github.com/bamr87/zer0-CMS/commit/9965fcfd14ae9344b5c1e4d67e5505df05f97a8f))
* **studio:** capture from any page with a bookmarklet; brief and research-brief flows tested ([8844429](https://github.com/bamr87/zer0-CMS/commit/8844429656bdc8873d32abf9b4ac630ed3989bad))
* **studio:** share boards, collections, ideas and sources; feeds, the drawer's save and exact corrections tested ([6b63f9e](https://github.com/bamr87/zer0-CMS/commit/6b63f9e93f86e97d9c656e52736084d2efe2b635))
* **studio:** the Ideas and Research workspaces, and research in the editor ([3a9a5eb](https://github.com/bamr87/zer0-CMS/commit/3a9a5eb9e39606d814e57a593327a2129aff5c4d))
* the agent-native content plane (PLAN M0, M3–M15) + fork-tag tooling ([#34](https://github.com/bamr87/zer0-CMS/issues/34)) ([31a308a](https://github.com/bamr87/zer0-CMS/commit/31a308a30eadbe0974bcb62beaea939244060f1a))
* the agent-native content plane (PLAN M0, M3–M15) + fork-tag tooling ([#34](https://github.com/bamr87/zer0-CMS/issues/34)) ([df8fe42](https://github.com/bamr87/zer0-CMS/commit/df8fe42c43ae70525fbfe7137e537f56c7891fa0))
* the agent-native content plane (PLAN M0, M3–M15) + fork-tag tooling ([#34](https://github.com/bamr87/zer0-CMS/issues/34)) ([54eb759](https://github.com/bamr87/zer0-CMS/commit/54eb7590fcb1e9684d1676e9da52c09bf344c8ed))
* **tools:** bin/zer0 doctor and zer0-doctor.yml run the platform's Python doctor; no Ruby ([ce41b25](https://github.com/bamr87/zer0-CMS/commit/ce41b258629cac681950e52c311812ec36910b41))
* **tools:** ratchet zer0-mistakes dependencies down to the Jekyll-theme option ([32cc380](https://github.com/bamr87/zer0-CMS/commit/32cc3801767adcc561b4475b33674a9ff1872880))
* **tools:** site_manifest.py records and compares what a site builds (PLAN P1) ([bd0b486](https://github.com/bamr87/zer0-CMS/commit/bd0b4864f5e3d0a0a5873c935ac521cae26d1706))
* **tools:** the absorption gate — the Ruby ratchet and the capability ledger (ADR 0006) ([87fb9e5](https://github.com/bamr87/zer0-CMS/commit/87fb9e5a1af20a1fbef05a19d47597c666901327))
* **tools:** the Jekyll-theme option — a site rendered with the zer0 theme by a Jekyll server (PLAN P2) ([ca96745](https://github.com/bamr87/zer0-CMS/commit/ca96745f6202871f20ae27bb21631d5f1f89054b))
* **tools:** the ledger's `specified` status — a source the owner deleted before it moved ([a68650d](https://github.com/bamr87/zer0-CMS/commit/a68650d9182bec50928bebdf5b3cacebe288f793))
* **tools:** the theme ratchet does not count recorded site builds ([6a6c45e](https://github.com/bamr87/zer0-CMS/commit/6a6c45ee9ff517a8402b4d81f06ecc0cad81c591))
* **tools:** zer0-pages's Obsidian bridge in Python (PLAN P2) ([ff55209](https://github.com/bamr87/zer0-CMS/commit/ff5520988ddb9b0527cf2786ed3c76d40dffbd0f))
* **web:** a finished audit names the audits closest to it in meaning ([96e2374](https://github.com/bamr87/zer0-CMS/commit/96e237412268d5d585bf038ac728f96f13cba010))
* **web:** a workspace registry and the site picker in @zer0/ui ([3592f79](https://github.com/bamr87/zer0-CMS/commit/3592f797c9522cff03bcfa172dca0c941fab8fd6))
* **web:** authors and their pages in the Newsroom ([bbaf14c](https://github.com/bamr87/zer0-CMS/commit/bbaf14cbc0260b95698523bafd96032433919e00))
* **web:** filter a conversation's messages, and the providers' status on Home ([7f50107](https://github.com/bamr87/zer0-CMS/commit/7f5010727a29f043d1235f9a302e90fe85bd6df5))
* **web:** re-record every routed site as site-manifest/v2, and record 2005 and irony-works ([0422bc6](https://github.com/bamr87/zer0-CMS/commit/0422bc630c783f8a2acdebe476baab2a7c1cb1bb))
* **web:** record every routed site's Jekyll build (PLAN P1) ([0745eb0](https://github.com/bamr87/zer0-CMS/commit/0745eb0b0e3d0d1f367482794af10fbdf10185cb))
* **web:** the AI workspace in the studio — providers, models, assistants, pipelines, schemas, briefs, conversations, the editor's AI panel ([2d79f54](https://github.com/bamr87/zer0-CMS/commit/2d79f54acb3cf49c54d2fe0db7c6ab26fc1e5eca))
* **web:** the AIEO workspace under Sites, and the editor's citability panel ([dbaf9d5](https://github.com/bamr87/zer0-CMS/commit/dbaf9d51dfedfd14613911498ff476a2786673ea))
* **web:** the extension's webviews as a package built from @zer0/ui ([ebb71b9](https://github.com/bamr87/zer0-CMS/commit/ebb71b92a3fb633b92fe745b96b93fd2d0433206))
* **web:** the extension's webviews render every workspace main has ([2874919](https://github.com/bamr87/zer0-CMS/commit/28749195e5d12904b739cc674e9fd64b62a9dbeb))
* **web:** the five dimensions as a radar in an audit's score card ([eb2116a](https://github.com/bamr87/zer0-CMS/commit/eb2116a6b02996dd6ebc014c9ae494ec1c5d86ab))
* **web:** the studio and its shared packages (P4) ([4e166a7](https://github.com/bamr87/zer0-CMS/commit/4e166a77fa252891e99c56d9da6740999c4a6e4d))
* **web:** the studio's AI -&gt; Automations (G16) ([f4e8d5a](https://github.com/bamr87/zer0-CMS/commit/f4e8d5af4aa96082869655ae22bd2462c8d76bf2))
* **web:** the studio's Books workspace ([7bf4f67](https://github.com/bamr87/zer0-CMS/commit/7bf4f679c5a381d4b1f41222af827addc53551f5))
* **web:** the studio's Distribution area and Distribute in the editor and the story panel ([cba930b](https://github.com/bamr87/zer0-CMS/commit/cba930b0d5458b26ca98eb81ad1a3298954571c1))
* **web:** the studio's Newsroom workspace ([2b855c6](https://github.com/bamr87/zer0-CMS/commit/2b855c60e65067dc07a213451282eeea6f5cdc57))
* **web:** the studio's Sites area — the registry, a site's overview and settings, its jobs followed live, its findings ([f04d62e](https://github.com/bamr87/zer0-CMS/commit/f04d62e7f8816bc0305c5f081c5dcb318b80f051))
* **workflow:** the seeded "Editorial" workflow — brand review, then a moderator ([642f486](https://github.com/bamr87/zer0-CMS/commit/642f486d420450a860e657ea2767c4a3f5a30d9f))
* **workspace:** bin/zer0 in Python, with the same commands, output and exit codes (P5) ([4bf8afe](https://github.com/bamr87/zer0-CMS/commit/4bf8afeac3795d32764f24a76403d628fb3f05a1))


### Bug Fixes

* **aieo:** a pattern's citation boost is bounded at 100%, not by the database ([24cca0b](https://github.com/bamr87/zer0-CMS/commit/24cca0b8f8fb8e6ce241fccdf76845e7cc6b28bb))
* **aieo:** a report lists tied patterns in its scorer's order on Postgres too ([483afc5](https://github.com/bamr87/zer0-CMS/commit/483afc5e3972dde5a9d9d66574764e438a43ec0d))
* **aieo:** reports keep the scorer's pattern order on Postgres; a stricter inline-script check ([bc87b27](https://github.com/bamr87/zer0-CMS/commit/bc87b27451906c98f260809d3f8dbb6fa1670edf))
* **aieo:** rotating the AI keys moves the connectors' credentials too ([b88b080](https://github.com/bamr87/zer0-CMS/commit/b88b080abe24587f46d1cc4eb6929d6a338179ab))
* **ai:** one rotation re-encrypts every secret kept under the credential keys ([2bc9585](https://github.com/bamr87/zer0-CMS/commit/2bc9585244a76e68c1255f51bf03ead1fd7089aa))
* **ai:** provider adapters keep a row's settings away from the worker ([60f8a2a](https://github.com/bamr87/zer0-CMS/commit/60f8a2a80b1102c74f08d6f1d9fcf1c9a58103dc))
* **ai:** runs act for the person who started them and recheck what they use ([4adf6bb](https://github.com/bamr87/zer0-CMS/commit/4adf6bb8b77b95dd92c3cfebeede0f98ac6dd255))
* **ai:** swap only the text a person selected, propose through the registry, and only for people ([494558e](https://github.com/bamr87/zer0-CMS/commit/494558e1d25d092e19f9a71f25d4a521ff712f82))
* **api:** request bodies are their own components, without read-only fields ([b4a93ec](https://github.com/bamr87/zer0-CMS/commit/b4a93ec4d945397a6ab39c270560195f89a39efa))
* **api:** request bodies as their own components, so the client asks only for what a caller sends ([004515d](https://github.com/bamr87/zer0-CMS/commit/004515db6fa2a58e869e1ab76c72cbdb63304eac))
* **automations:** runs stay their owner's, email and webhooks are bounded, every site rule holds (G16 review) ([6e0474d](https://github.com/bamr87/zer0-CMS/commit/6e0474d5b7be5bf7178c1716d4223634b63d6834))
* **automations:** the events consumer's test puts the handler table back ([8276892](https://github.com/bamr87/zer0-CMS/commit/827689251d00506c517d37a8b81b17108de217d5))
* **books:** an edited ABC letter exports a plate planned for its word, and its spec sidecar ([481c26f](https://github.com/bamr87/zer0-CMS/commit/481c26f4e476f8f592d9e251f619c1dd9305a10c))
* **books:** find a chapter in the read model by its path, and leave room for an assistant's read tool ([a092cb3](https://github.com/bamr87/zer0-CMS/commit/a092cb3ed6b9f387d7420b2751dad264e7638e77))
* **books:** match library/ case-sensitively and stop at the filesystem root ([9b1aab9](https://github.com/bamr87/zer0-CMS/commit/9b1aab900b165b2c554dae2e0b1aae7b21f53cf2))
* **books:** nothing lost between the platform and its generated library, and the review's other findings ([0b79525](https://github.com/bamr87/zer0-CMS/commit/0b795253ad858124d996e0e6f14a41e0b4050a50))
* both zer0:content consumers reach the outbox desk's belt ([7a8a407](https://github.com/bamr87/zer0-CMS/commit/7a8a4073767bf62cb06dc4c2a23d5e823cb57026))
* **cms:** the editor's preview renders every page type ([6559c4b](https://github.com/bamr87/zer0-CMS/commit/6559c4b4bf64552b5f6b9f27367157ef4683c8e8))
* **cms:** the preview shows a raw HTML block as escaped source ([adf916f](https://github.com/bamr87/zer0-CMS/commit/adf916f018754269925e0819852ea25002357b9d))
* **compose:** mount the books library into the content service; ignore local agent/editor scratch ([36fc7ba](https://github.com/bamr87/zer0-CMS/commit/36fc7bab1356eb46731850ff04cdc342ae9ea40e))
* **compose:** the content service mounts the books library, which the image does not carry ([639141d](https://github.com/bamr87/zer0-CMS/commit/639141d5752cfa042b722849a2bef17dcf2db618))
* **content:** a file finds only its own site's pages ([4f4ea12](https://github.com/bamr87/zer0-CMS/commit/4f4ea12afa5df44dc7c5fc2ee102a3ac400aabaf))
* **content:** one hashed bearer token for agents and people, used without a write in the request ([8050d18](https://github.com/bamr87/zer0-CMS/commit/8050d18ce67268bdac09b5508d37158331fa9c30))
* **content:** redact person tokens in logs, error reports and Sentry ([c6b9d48](https://github.com/bamr87/zer0-CMS/commit/c6b9d4818bfadf7fb1c39b91438efc52963f198e))
* **content:** serve the platform on threaded workers, so a run's stream survives ([6495188](https://github.com/bamr87/zer0-CMS/commit/64951883556bef0207a495ea24d6482d511e2f6f))
* **content:** the image installs both requirement files while git is present ([9660e52](https://github.com/bamr87/zer0-CMS/commit/9660e522b21612f716b90c02a601a27090cbdc4d))
* **content:** the studio API's review findings — links, access, locks, the save guard, one scope ([1c42baa](https://github.com/bamr87/zer0-CMS/commit/1c42baa9e2064ec3e1b2324fe5440b74b2ad96f4))
* **distribution:** a delivery claims its attempt, so a redelivered task never posts twice ([c2dbcd0](https://github.com/bamr87/zer0-CMS/commit/c2dbcd00b1ae77a5dea7c7bc4fac09b1a019ab89))
* **distribution:** a site ledger the platform cannot reach blocks the channel ([d5086ca](https://github.com/bamr87/zer0-CMS/commit/d5086ca83afe6f31b29ef74fe102e75009e8c1ac))
* **distribution:** rotating the AI layer's keys rotates every channel's credential ([4be39a1](https://github.com/bamr87/zer0-CMS/commit/4be39a146ae11aeb77b9c12cdf1005971fa40a73))
* **docs:** escape backslashes as well as pipes in reference table cells ([16c1c13](https://github.com/bamr87/zer0-CMS/commit/16c1c13c881da72a70de2c5589ddb963e2285f3b))
* **drsai:** floor github-pages at 228 so Liquid renders on Ruby 3.2+ ([02a65a9](https://github.com/bamr87/zer0-CMS/commit/02a65a9b49adb41324fcf00c824455a38ec00698))
* **extension:** admit @zer0/ui's drag-and-drop library into dist/studio.js ([08e05a5](https://github.com/bamr87/zer0-CMS/commit/08e05a54c78633073619f4d9223d11078bb0736b))
* **extension:** an alias inside the node it names reads as unknown ([a508b04](https://github.com/bamr87/zer0-CMS/commit/a508b04606379fd1b6f3565331782449eda83be8))
* **extension:** date patterns keep file mode's vocabulary ([752779c](https://github.com/bamr87/zer0-CMS/commit/752779c62b2145d0e55467a80c4eb12a291fc7e0))
* **extension:** decide platform mode per file, and keep the file dashboard in either mode ([e793657](https://github.com/bamr87/zer0-CMS/commit/e7936577d94e0b00783ad499ac5063b93a10822b))
* **extension:** keep schemas/books/ out of the vsix ([8c8b162](https://github.com/bamr87/zer0-CMS/commit/8c8b1629be17e5c8958a096036590184f247b7f4))
* **extension:** keep web/ out of the vsix ([e8c7128](https://github.com/bamr87/zer0-CMS/commit/e8c712875de860ea1dba9ca2f31569e265be13b8))
* **extension:** the studio bridge gates the request it sends, and carries the headers the platform reads ([8cc174e](https://github.com/bamr87/zer0-CMS/commit/8cc174eab9f0aea0ab6ccac23e35e089c7047874))
* **extension:** the vsix leaves out schemas/books/ ([caf3e36](https://github.com/bamr87/zer0-CMS/commit/caf3e3676b47f2f8a00530e1661e5c314c610bce))
* github-pages floor for drsai and the installer demos' latest_posts Liquid ([96edc00](https://github.com/bamr87/zer0-CMS/commit/96edc0013b16f8fc22eb171aa2cc20e949db820a))
* **ideas,research:** an idea shows only what its reader may see; only an owner re-shares a row ([5646fc3](https://github.com/bamr87/zer0-CMS/commit/5646fc3f4a2de1e89042827fa10e9680b071d2d2))
* **image-gen:** edit rounds revise the pre-outline source, not glyph paths ([8b2e285](https://github.com/bamr87/zer0-CMS/commit/8b2e2854686d58d2d5643bbaec54619b2a563cde))
* **image-gen:** trim spaces/quotes by index scan in text_to_paths.rb (CodeQL rb/polynomial-redos) ([7754de6](https://github.com/bamr87/zer0-CMS/commit/7754de6af00c55f68c8091b0723162c666108e19))
* **importers:** a file the site does not build imports as a draft or scheduled ([d32582f](https://github.com/bamr87/zer0-CMS/commit/d32582f2aa7c15834cfa17d0fdec3044630043bb))
* **importers:** find a preview where Jekyll serves it, under assets/, SVG included ([3f8a530](https://github.com/bamr87/zer0-CMS/commit/3f8a53017819b730e29cf753b93b3ac503d99e13))
* **importers:** re-importing barodybroject leaves what people changed here ([f9a2fb5](https://github.com/bamr87/zer0-CMS/commit/f9a2fb5a50625cf712994224a727286049c77535))
* **irony-works:** the landing page no longer prints the build's date ([2cff8b6](https://github.com/bamr87/zer0-CMS/commit/2cff8b6ba8f5fa48485e4741727890869c51b50c))
* **jobs:** the OpenAPI document is the same on SQLite and Postgres ([f0a97a0](https://github.com/bamr87/zer0-CMS/commit/f0a97a0150a479e1854a08ba882b7806daa1982f))
* **ledger:** a proof must be a test; the eight site publish rows are partial ([19efc0a](https://github.com/bamr87/zer0-CMS/commit/19efc0acc65b6f7ee46611c6fc2c866307700f70))
* **newsroom:** a create's body is its writable fields, and a change is a PATCH ([9b600eb](https://github.com/bamr87/zer0-CMS/commit/9b600ebb831bb38fe92c70c2fb14f97c28a9c468))
* **newsroom:** a planning change writes only its fields; an issue's stories are read once per send ([cee3cbe](https://github.com/bamr87/zer0-CMS/commit/cee3cbe9e3ef77ff9e891460662193a5d8e6136a))
* **newsroom:** hold every publish path to a story's rules, and the review's other platform findings ([d387560](https://github.com/bamr87/zer0-CMS/commit/d3875607471719bc637f0cc44ed8657b2a4840c6))
* **outbox:** consume_events outlasts an idle stream's read ([755dbf1](https://github.com/bamr87/zer0-CMS/commit/755dbf1bf23a5dd23eb934421e48f204b1e92776))
* **outboxdesk:** a published handoff stays on its piece's trace ([fba8f5d](https://github.com/bamr87/zer0-CMS/commit/fba8f5d7ddad902ecd60ac97915813468c7b5025))
* **outboxdesk:** importing a site sends nothing onto the belt ([8df0e62](https://github.com/bamr87/zer0-CMS/commit/8df0e62e5a0f0ece558794c032f363eb30cd6c9a))
* **outbox:** the events consumer survives quiet spells and reads EVENTS_STREAM ([912d884](https://github.com/bamr87/zer0-CMS/commit/912d884092dc7675dd4671fc823e0a7969df858f))
* **parodynews:** bump djangorestframework and setuptools past advisories ([254c7ea](https://github.com/bamr87/zer0-CMS/commit/254c7eab3cc231d08c09dcc4c5df861940a24286))
* **parodynews:** bump djangorestframework and setuptools past advisories ([4be214b](https://github.com/bamr87/zer0-CMS/commit/4be214bf13895bb0dde8b02cd1f55e7566953bd8))
* **parodynews:** repair what the rename surfaced ([8862d54](https://github.com/bamr87/zer0-CMS/commit/8862d54ab7f780c452c6fe3ca408f45f2b4e13a5))
* **research:** a fetch ends at its deadline, on a queue of its own, throttled per person ([fbf9758](https://github.com/bamr87/zer0-CMS/commit/fbf9758b3aca14e2e36b4361cde061ae63cda302))
* **research:** fact-checks read the draft's citations first and propose exact corrections through the registry ([b92afbe](https://github.com/bamr87/zer0-CMS/commit/b92afbe6cf85c0b95579d704caf0f63f57bc6072))
* **research:** fetch.post, a notification under the fetcher's guard and one deadline ([a64be1f](https://github.com/bamr87/zer0-CMS/commit/a64be1f4612ac2e902a69bad7a112885456fa113))
* **research:** read a feed from the bytes fetched, never a file its body names ([769b548](https://github.com/bamr87/zer0-CMS/commit/769b5487d3306b96c24719992d0611454a7b6f6b))
* **research:** read text in its own encoding and keep NUL out of what is stored ([596f1ca](https://github.com/bamr87/zer0-CMS/commit/596f1cad926eee9b716f2da1d04e96d568582ef4))
* **research:** workers write only what a fetch owns, and claim a feed before reading it ([e83fdb2](https://github.com/bamr87/zer0-CMS/commit/e83fdb2e40ed760e2053c63a7708c37cc792ae74))
* **schema:** dedent page docstrings with inspect.cleandoc ([#37](https://github.com/bamr87/zer0-CMS/issues/37)) ([5da1418](https://github.com/bamr87/zer0-CMS/commit/5da14182d083389c5431b5e7e5086ad270722186))
* **sites:** a page that is not live reaches its Jekyll file as published: false ([55577a0](https://github.com/bamr87/zer0-CMS/commit/55577a0f234640df94cd6ba1e6c25b2f74978242))
* **sites:** a registration whose _config.yml does not read is refused, not a 500; one manage query per site list ([61213c0](https://github.com/bamr87/zer0-CMS/commit/61213c0045a98d594fc464a7b6051cd4b339209f))
* **sites:** a write-back never writes a page into another page's file ([1cd00c7](https://github.com/bamr87/zer0-CMS/commit/1cd00c72ca5ddfa9b6104de60d3fc53f156f1467))
* the four off-Linux defects from the 2026-10-20 validation ([9a5e44f](https://github.com/bamr87/zer0-CMS/commit/9a5e44f832e4cad6407cdd7e522f90231e2f6822))
* the platform's open bugs and main's CI, with G16, G7 and G10 merged ([b56100e](https://github.com/bamr87/zer0-CMS/commit/b56100ef23c267a87fcffef89448cf10468a5c11))
* **tools:** check_absorption --tighten keeps the comments inside a ratchet block ([ffdd157](https://github.com/bamr87/zer0-CMS/commit/ffdd1576cefbb40a012d7d0edc1cb60c9ec65bf4))
* **tools:** graft.sh works on a main that already holds a merged graft ([b08585d](https://github.com/bamr87/zer0-CMS/commit/b08585d9be312831af8500b9ff5a20ccb783598a))
* **tools:** re-vendor docs_index.py with multi-line comment stripping ([fa111bd](https://github.com/bamr87/zer0-CMS/commit/fa111bd8789c5eb0e648dc48fcb079497084c4d0))
* **tools:** re-vendor docs_index.py with multi-line comment stripping ([de44af9](https://github.com/bamr87/zer0-CMS/commit/de44af945665ef646a133224a0851ca4fdae6c8e))
* **tools:** site_manifest records a page's own content, feed dates and what the build resolved ([3614b94](https://github.com/bamr87/zer0-CMS/commit/3614b94a1c79d2ca10a760a585b391e724b6df20))
* **tools:** the Jekyll-theme option never deletes a directory it did not write ([2d7ba29](https://github.com/bamr87/zer0-CMS/commit/2d7ba29d978dd7075dede3f8cef2756f37643b61))
* **web:** a modal's scroll lock in the extension's webviews carries the CSP nonce ([7324a30](https://github.com/bamr87/zer0-CMS/commit/7324a302eb96936d15dfbbdfcb52dae22108f9b3))
* **web:** offer to apply a brief only to whoever may, and render each area's routes in its tab panel ([c13991b](https://github.com/bamr87/zer0-CMS/commit/c13991bfff8d1d5ba7d7cf606e99c274114e2bc3))
* **web:** one request per action, briefs saved once, and a conversation paged from its newest messages ([85b51da](https://github.com/bamr87/zer0-CMS/commit/85b51dadff9b251e21240a5fedf0af3c29135b4e))
* **web:** templates in monospace without their labels, and selects wide enough to read ([5f088b4](https://github.com/bamr87/zer0-CMS/commit/5f088b477cd8877b761d2460674c82b53a6cd5d6))
* **web:** the automations view says whose its runs are, and what email and webhooks take ([aa48af1](https://github.com/bamr87/zer0-CMS/commit/aa48af11cf95a9b1a1ba1e53207cfe732c970e63))
* **web:** the Books area's review findings — a book's other files, the library's shelf, the chapter writer under test ([525105a](https://github.com/bamr87/zer0-CMS/commit/525105a727f19225a6287878888a8987b7489600))
* **web:** the editor's AI panel sends where a selection is ([20cab34](https://github.com/bamr87/zer0-CMS/commit/20cab341f256c3249016e3e8013dcd483146d1d2))
* **web:** the Newsroom asks before anything goes live, pages its board, and leaves the desk's decisions to the desk ([27fb6ba](https://github.com/bamr87/zer0-CMS/commit/27fb6baffc7b52d62aff078af4f7c51ed2795f09))
* **web:** the studio's review findings — block keys, drafting, locks, expiry, accept-all, the live timeline ([a539de8](https://github.com/bamr87/zer0-CMS/commit/a539de8f984f3a70c02ceb34f7fdfa7de14f3b57))
* **workspace:** affected reads git's paths with -z, tested on every kind of change (P5) ([a0b7740](https://github.com/bamr87/zer0-CMS/commit/a0b77407be90b68e7fc270dd566cbab662d0b79d))
* **workspace:** every path the manifest names stays inside the repository (P5) ([ae96f65](https://github.com/bamr87/zer0-CMS/commit/ae96f650935e4f765e0d2225258e66892735ffe6))
* **workspace:** without PyYAML, bin/zer0 runs on the repository's .venv and names routes that work (P5) ([a6d3c68](https://github.com/bamr87/zer0-CMS/commit/a6d3c68b37d1f52b5090cb4e8f0746e6c7b151b4))
* **zer0-mistakes:** assign the latest-posts limit before the for loop ([927f434](https://github.com/bamr87/zer0-CMS/commit/927f43466e904d8889a345294966d5c9161b8aec))


### Performance Improvements

* **ideas,research:** clusters compared by pgvector; retrieval's word stage through Wagtail search ([b0efb3d](https://github.com/bamr87/zer0-CMS/commit/b0efb3d20e36835b86ff64990291aacc4ff02719))


### Code Refactoring

* **parodynews:** rename barodybroject to parodynews and strip the brand (ADR 0003) ([19e838f](https://github.com/bamr87/zer0-CMS/commit/19e838f98876c9ef6017b792a8e9667abe8a2a22))
* **theme:** land "the theme goes home" on main (ADR 0005, PLAN Phase T) ([be7b2a1](https://github.com/bamr87/zer0-CMS/commit/be7b2a1b7ee1c8359e13a4a78a2d163debe1f122))
* **theme:** the theme returns to bamr87/zer0-mistakes — remove packages/zer0-mistakes ([bf03bf6](https://github.com/bamr87/zer0-CMS/commit/bf03bf6e0eff277c5c955c98c63227d2f5b71231))

## [0.3.0](https://github.com/bamr87/zer0-CMS/compare/v0.2.0...v0.3.0) (2026-10-18)


### Features

* **cms:** doctor — the zer0 stack consumer contract check ([0ed8d0f](https://github.com/bamr87/zer0-CMS/commit/0ed8d0fbb2d18c9e2ed9b339ea1d627c271fdcaf))
* **distribution:** LinkedIn distribution — a declared-call API client, the governed lane, CLI, workflow, MCP and fleet CMS screens ([64db526](https://github.com/bamr87/zer0-CMS/commit/64db5260664ab37c74afe739a4aba8147461affc))
* **distribution:** the governed LinkedIn lane — queue, guard, ledger, pipeline, CLI, MCP ([601c772](https://github.com/bamr87/zer0-CMS/commit/601c772ab58478d6ad48b039215c84fa29cff40a))
* **doctor:** check a site's LinkedIn distribution settings ([96ad097](https://github.com/bamr87/zer0-CMS/commit/96ad097361b6755e0a40b71397049c0d3dd3c61e))
* **linkedin:** a stdlib LinkedIn client whose every call is declared ([ae27019](https://github.com/bamr87/zer0-CMS/commit/ae270190ee4bc8ea7134bab20953f1ea989e9a72))
* **rails:** LinkedIn distribution and channels in the fleet CMS ([a41bca4](https://github.com/bamr87/zer0-CMS/commit/a41bca43741a94752aa12fa4f87d2af925012339))
* **rails:** Site/Page/Asset/Term index rebuilt from disk by SiteSync ([41a7f15](https://github.com/bamr87/zer0-CMS/commit/41a7f15505f844c15b7e49a0d29dd8851498e4f2))
* **rails:** the fleet CMS on Administrate — disk-synced index, safe write-back, image-engine bridge, zer0 doctor (contains PR A) ([27db8e6](https://github.com/bamr87/zer0-CMS/commit/27db8e6eaf72d2ed735be87af3fa10689babdfb2))
* **rails:** the fleet CMS platform — a site registry, in-place front matter, media, taxonomy, search ([e456a92](https://github.com/bamr87/zer0-CMS/commit/e456a92dc2d8e22a3680be1fb60fe4d7a8b4a74f))
* **rails:** the image-engine bridge — missing previews and a local preview per page ([8671131](https://github.com/bamr87/zer0-CMS/commit/8671131a1b673d09a93f995df667ce559d2d5afe))
* **rails:** the panel on Administrate — dashboards, custom fields, PageEditor ([ac80405](https://github.com/bamr87/zer0-CMS/commit/ac80405339f58291f2abdd06d4fc15acf783819a))
* re-land console v2 ([#18](https://github.com/bamr87/zer0-CMS/issues/18)–[#21](https://github.com/bamr87/zer0-CMS/issues/21)) with fleet, parser and docs fixes ([b8864b7](https://github.com/bamr87/zer0-CMS/commit/b8864b7de1bf3eeefa716a4d5c5742391c36b94a))


### Bug Fixes

* **ci:** keep compose out of the vsix, pin the boot pid, drop a ReDoS regex ([91da9d5](https://github.com/bamr87/zer0-CMS/commit/91da9d55ad32bcfceef34c43dd36d606f7852749))
* **cms:** Jekyll-exact catalog, the extension's front-matter surgery, a confined writer ([3e68a25](https://github.com/bamr87/zer0-CMS/commit/3e68a2500444ba0d9a3a1644b6c545f5acd89b59))
* **core:** read wrapped quotes, keywords and anchored quotes like YAML ([77de536](https://github.com/bamr87/zer0-CMS/commit/77de5366d6579f328e623d0efbac60cb9e85abec))
* **doctor:** a preview fork reads preview_images, not just the filename ([fcbef06](https://github.com/bamr87/zer0-CMS/commit/fcbef0608c1a0ce5619dd2b6bb55eba343b741ab))
* **extension:** keep root AGENTS.md out of the vsix ([#32](https://github.com/bamr87/zer0-CMS/issues/32)) ([fd3df63](https://github.com/bamr87/zer0-CMS/commit/fd3df6327b430fa6cfc02f5daaa37a13dd27ee7c))
* **fleet:** an unread workflow, run or pull list is null, never [] ([1d4273b](https://github.com/bamr87/zer0-CMS/commit/1d4273b9a3cb9fa5bf54bce6e0f1da05521f5288))
* **rails:** an empty ZER0_CMS_USER means the default user ([95da0b5](https://github.com/bamr87/zer0-CMS/commit/95da0b573f2d617fe405fccee653c31baa47e2d5))
* **rails:** basic auth or loopback only, CSP nonce, confined /files, explicit ABC export target ([600882f](https://github.com/bamr87/zer0-CMS/commit/600882f8960ce6eff4271ae35d1a82d7387a33a1))

## [Unreleased]

### 🛰 The fleet, not one repository

Slice 1 was one repository and two verbs. This is a fleet: a **roster** — the folders open in this window that carry a manifest, plus repositories you enrol in your settings, plus, only when you ask for it, the hub's registry — and a **Monitor** tab showing every repository against every lane: its switch, its newest run, the open pull requests attributed to it, what it has cost, and the grade the shared audit gives its workflows.

Three verbs act on a run rather than on configuration: **re-run** the last failure, **cancel** what is in flight, **enable or disable** the workflow file. Each says plainly what it does — re-running queues a new attempt and the original stays on the record; cancelling leaves the run recorded as cancelled, which is not the same as failed; disabling registers the workflow with GitHub and **does not touch the file**, which is why it is not an edit and why a person who wants the lane gone still has to delete it.

A refresh costs **four calls per repository, whatever the lane count** — variables, workflows, recent runs, open pull requests, joined locally. The previous slice cost one per gated lane plus one per lane, which on lifehacker alone was thirty-one. The whole nine-manifest roster now refreshes in thirty-six calls where it would have taken eighty-seven, and opening the Monitor reads nothing at all: a row's own button is the only thing that opens a socket.

**The honesty rule matters more here than anywhere else, because a fleet view is mostly cells.** A cell nobody has read says `unknown` and looks different from `off`. A repository with no checkout and no refresh shows as unread rather than empty. Nothing renders `$0.00` for an unmeasured cost. `listVariables` returning `null` rather than an empty list is that rule in the type system: "there are no variables" and "you may not read them" are different answers, and rendering both as blank would be lying about one.

### 🔒 The plan grew, and the guard got stricter

The declared call plan went from six entries to fifteen. The guard that keeps it a boundary was tightened in the same change rather than after it.

`fleetSurfaceIsRepoScopedOnly` used to check only that a path *began with* `/repos/{owner}/{repo}`. That would have admitted `/issues`, `/hooks`, `/keys`, `/collaborators` and `/actions/secrets` the moment anyone added one. It now matches an explicit allow-list of sub-roots, whole-segment. A second guard, `fleetPlanHasNoMergeVerbs`, refuses `/merge`, `/reviews`, `/update-branch`, `/actions/secrets`, `/collaborators`, any `DELETE`, and any write to `/labels`. Both are asserted from both directions — every planned call passes, and a hand-written forbidden one fails.

A `..` path segment is now refused before a URL is built, because `fetch` would have normalised `…/contents/../../../user` into an endpoint the plan never named.

This console never merges, approves, closes, removes a review label, or reads a secret. Those are the boundary, not a backlog.

### 🧭 The harness, inventoried

An agent file, a skill, a workflow, a manifest lane, a kill switch, a token and a line in a spend ledger are seven files describing **one lane**, and holding that join in your head was the only way to see it. The **Harness** tab reads them and reports the joins — and, more usefully, where they disagree: an agent a workflow names that does not exist, a skill nothing references, a lane with no workflow, a workflow with no lane, a switch the manifest claims that no workflow reads.

The rules were tuned against the real fleet rather than fixtures, and five of them were wrong on the first pass. Each guard now names the case that taught it: a metering line's `--agent` flag is a ledger role, not an agent reference; `<x> subagent` names an agent, not a skill; a comment *about* a token trap is not the trap. The strongest evidence they are right now: over lifehacker.dev the inventory reports twelve token-chain findings, and they are **byte-identical to the twelve workflows that repository's own token lint hand-maintains as migrating debt** — a list a person curated, rediscovered from scratch.

A lane reader ports what `wtd fleet adopt` does, so the console and that tool agree about what a workflow *is*: **45 of 45 lanes across five repositories match** on every parity field. It is used only to agree — a derived lane is never written over a committed manifest, and a disagreement is reported as drift.

### 🛠 Lanes you can write

Describe a lane — what it should do, when, as whom — and get the files that make it real: a workflow calling the fleet's shared runner, an agent, a skill stub, and a manifest entry. Not a wizard that hides its output: a plan you read, a diff you review, and files you commit yourself.

**It refuses more than it writes, and that is the point.** Modelled on lifehacker's own `content-review` lane, the generator classifies it **bespoke** and produces nothing — because expressing it as a shared-runner caller would silently drop the `github.event.action != 'synchronize'` loop-breaker, re-creating an infinite retrigger loop that fleet has already had to fix once. A lane it cannot express honestly comes back with reasons a person can act on, not a shrug.

House rules are enforced rather than documented: the kit stamp is line 1; a cron is never on the hour (every lane in a fleet firing at `:00` queues behind the rest of GitHub); a token is never `secrets.X || github.token` (that degrades to a token which cannot open a pull request, silently, mid-run); every generated lane carries its `*_ENABLED` switch; and nothing ever targets a `factory--*.yml`.

**Writing the files never arms the lane.** The variable that turns it on is named in the modal and deliberately not created — writing a file somebody reviews and arming a loop to run are different powers, and the console holds only the first.

Three MCP tools join the set (sixteen): `zer0_harness_inventory` and `zer0_lane_preview` are read-only; `zer0_lane_scaffold` is double-gated by an environment flag *and* a per-call confirmation, exactly as publishing is.

### 🗂 Many sites, one window

A window can hold more than one site. The fleet's own workspace holds twelve folders — seven of them Jekyll sites this extension can detect, audit and publish — and until now eleven of them were invisible, because everything resolved the first folder.

The unit is still one folder: one configuration, one snapshot, one cache key, one MCP server. Multi-root is composition above that rather than a second model threaded through it. A **site registry** holds one store per folder, and a **Sites** tree and dashboard tab show what is in the window: each folder's platform, whether it is configured, its content roots, its counts, whether it carries a fleet manifest.

**Which site a command acts on is decided by the command, not by the window.** A command invoked on a file acts on *that file's* site — registering a folder edits that folder's `zer0.json`, a draft goes into its own site's queue, diagnostics validate against the owning site's content types. Only a command with no argument falls back to the active site, resolved as: an explicit pick that still exists, then the folder owning the active editor, then the first folder. That rule is a pure function with tests, because a rule like this quietly acquires a fourth case.

The panel's persisted state is namespaced per site, so two sites no longer overwrite each other's collapsed sections. The MCP provider offers one server per configured site rather than one per window — on the twelve-folder workspace that is two or three servers, not twelve. `zer0Cms.site.preview` runs the detected platform's own serve command through a VS Code task and offers the preview URL when it is ready.

### 🤝 One harness vocabulary

The agent in this editor and the AI lanes in CI shared nothing. The editor did not read the repository's model configuration, did not know its `.claude/agents` roles, did not attach this extension's own MCP server, and defaulted to a model the fleet does not use — so "run this as the content role" was possible in a workflow and impossible at the desk, and the two disagreed about the model without anyone noticing.

A **harness profile** now resolves a repository's roles, skills and model once, in the CI runner's own precedence — a setting, then `zer0.json`, then the site's `_data/ai.yml`, then a built-in fallback — and projects to either an editor run or the equivalent CI invocation. `zer0Cms.agent.runAsRole` picks a role from the repository's own agents and runs it under the approval card; **Copy the CI equivalent** hands you the `run.sh` line or the workflow `with:` block for that role. On lifehacker.dev the editor now resolves the same model that repository's own lanes use, instead of a different one.

The extension's own MCP server is attached to an agent run, with eight read-only tools auto-allowed and the other eight on the card — the six that write or spawn, plus `zer0_harness_inventory` and `zer0_lane_preview`, which only read but are not on the auto-allow list yet. The publish and scaffold flags are explicitly deleted from the child environment: an editor run must not inherit whatever armed something else.

### 🔒 A gate that was not holding

**`permissionMode: 'acceptEdits'` bypassed the approval card entirely, and this extension offered it as a setting.** Measured against the Agent SDK rather than assumed: with that mode a `Write` landed on disk and `canUseTool` — the single gate the whole agent design rests on (decision D10) — was never called at all.

It is gone from the manifest, removed from the type, and clamped at both configuration layers, so a settings file or a `zer0.json` that still names it falls through to `default` rather than disarming the gate. `plan` remains, because planning without acting needs no gate. Two related things were measured and are worth writing down: a repository-committed `permissions.allow` rule does *not* bypass the card, and a repository-committed escalating default mode is dropped by the CLI's own trust filter.

Loading a repository's `.claude/settings.json` into an editor run is off unless the workspace is trusted **and** you opt in for that run — those files can declare hooks, which are command lines running under your credential.

### 🌍 Every site, not just this one

zer0-CMS now knows what kind of site it is looking at. Jekyll, MkDocs, Wiki.js, Hugo, Docusaurus, Astro and a generic fallback are **profiles** — content roots, front-matter dialect and keys, the draft convention, date keys and formats, the slug and permalink rules, the directories a build writes and the command that serves the site locally — resolved once from marker files, with an explicit `platform.id` in `zer0.json` always winning. Everything platform-specific that used to be hard-coded in the core now comes from one of them.

zer0-mistakes is an **overlay on Jekyll**, never a sibling identity: a site using that theme is a Jekyll site with extra conventions, and modelling it as its own platform would have meant restating every Jekyll rule to keep it true.

Three things this immediately fixed, each found by pointing the code at real repositories rather than fixtures:

- **The theme overlay matched one site out of six.** The probe looked for the literal `remote_theme: bamr87/zer0-mistakes`, and five of the six sites in this fleet write it aligned and quoted — `remote_theme             : "bamr87/zer0-mistakes"`. A detector that only recognises tidy files is a detector for fixtures. Probes now read past spacing, quoting and case.
- **A site whose `collections_dir` carries a YAML anchor was invisible.** it-journey.dev writes `collections_dir: &collections_dir pages`, and treating that as unresolvable meant **none** of its 409 content files were seen. An anchor is a *label on* a value — the value is right there, and reading it is not a guess. An alias, which points at a value defined elsewhere, still reports as unknown rather than being invented.
- **Jekyll's loose pages were not content.** Deriving only the declared collections left fourteen of lifehacker.dev's 383 files unseen. Jekyll builds every markdown file under the source directory, and a CMS that cannot see a page cannot report a problem with it. Coverage on the two largest sites in the fleet went from 368/383 and 0/409 to **383/383 and 408/409** — the one remaining file has no front matter and is skipped on purpose.

Publishing follows the platform too. `PublishTarget` was an open interface with exactly one implementation and a registry that **threw** for anything else, so a detected MkDocs site would have crashed the publish preview. One factory now serves every file-writing platform, with the same exclusive-write and adopt-a-retry semantics Jekyll always had. `governance.target` defaults to empty, meaning *follow the platform* — so naming one is a real choice rather than an indistinguishable default, and Jekyll sites publish exactly as they did.

### 🔍 The front-matter audit

Every page checked against its content type, its site's own schema and its platform's conventions — thirteen rules using **lifehacker.dev's own rule id strings**, so a finding raised in the editor and one filed by that site's CI are the same finding rather than two. It reads the schema the site already has (`frontmatter_schema.yml`, a `.cms/` contract, `zer0.json`, or the platform's defaults) instead of asking you to restate it, and every report names which one answered — because "required" means something different in each case.

A finding that a script can honestly fix offers a fix; the rest say why not. `title: ''` is not a repair, and neither is `draft: true`. Applying one re-reads the file, re-runs the rule against what is actually on disk now, shows the real diff in a diff editor and asks — in that order, so a fix for a finding you have since edited away cannot land. The parser also grew a **warnings channel**: a file using YAML anchors, aliases, merge keys or multi-line flow collections is reported as unreadable rather than audited on a misreading, and fix-it refuses it outright.

Available as an Audit tab, three commands, and a read-only `zer0_audit` MCP tool — the thirteenth; the harness tools above bring the set to sixteen. Over lifehacker.dev's 382 real posts it reports **zero errors and two warnings**, both genuine over-long descriptions — the rules were tuned against a real corpus, and one that fired ten times on correct files was fixed rather than shipped.

### 🐛 Found by pointing the console at the real fleet

- **An unread list is not an empty one.** `listWorkflows`, `recentRuns` and `openPulls` answered `[]` on a 403 or 404, so a repository whose Actions nobody could read drew every lane as never having run and every workflow as unregistered. They now return `null`, as `listVariables` always did: the Monitor and Fleet tabs draw unknown, the run verbs refuse with "could not be read", and the engines adapter throws rather than handing the package a fabricated `[]`.
- **A quoted value PyYAML wrapped is read whole.** A `'…'` or `"…"` scalar continued on a more-indented line was truncated to its first line and reported as unreadable, and every one of it-journey's 131 quest reports tripped it. It is now folded the way YAML folds it — those 131 pages match PyYAML on all 1,826 of their string values — and a quote that never closes is still reported. Reading them also exposes what the audit had been skipping on those pages, including 121 `duplicate-slug` findings that come from how a dated file name's slug is derived.
- **`keywords` is not a taxonomy.** The zer0-mistakes overlay listed it, and the theme never reads it as a list, so it-journey's 218 `keywords: {primary, secondary}` mappings were 218 false `tags-not-array` errors. The rule also called a mapping "a scalar" and offered to fix it; it now says mapping, and offers no fix.
- **An anchored quoted value loses its quotes.** `title: &title "Lifehacker.dev"` was read as `"Lifehacker.dev"`, quotes and all, on lifehacker.dev, it-journey and zer0-mistakes; an anchored `""` now reads as absent, exactly as an unanchored one does.
- **This repository's own `fleet.manifest.yml` parses.** Its `CLAUDE_CODE_OAUTH_TOKEN` purpose was a single-quoted scalar wrapped at column 80 and continued at column 0 — the `wtd fleet adopt` wrap PyYAML forgives and the `yaml` package rejects. It is one line now, and both read the same value.

## [0.2.0](https://github.com/bamr87/zer0-CMS/compare/v0.1.0...v0.2.0) (2026-09-11)


### Features

* **core:** close the feedback loop — analytics, portfolio, media ([#11](https://github.com/bamr87/zer0-CMS/issues/11)) ([159de61](https://github.com/bamr87/zer0-CMS/commit/159de61114d52552e824e45c735d949e593dd6a9))
* **core:** fold multi-line plain scalars in the YAML subset parser ([5088da9](https://github.com/bamr87/zer0-CMS/commit/5088da9be39c84ce88fa081ce652c6047bab7a6f))
* **core:** the fleet domain — manifest, gate, and a declared GitHub surface ([9207603](https://github.com/bamr87/zer0-CMS/commit/92076039f761c22c13543a8ddbf772cc4dc3412d))
* **fleet:** the Fleet console — dashboard tab, two gated commands, an MCP read ([cf41ced](https://github.com/bamr87/zer0-CMS/commit/cf41ced25e2c92c7711fa061c71daced506062a7))
* **fleet:** the Fleet console — read this repo's lanes, gate switch and dispatch on a human (slice 1) ([c83f8aa](https://github.com/bamr87/zer0-CMS/commit/c83f8aad99189a1f18c1b8e20f842ca58ca4060a))

### 🧱 Foundations

This release turns zer0-CMS from a CMS for *this* repository into the foundation of one that can operate a fleet of them. Nothing here is a new feature you can point at; it is the floor the next four slices stand on — platform profiles, a site-wide front-matter audit, a multi-root site registry, a harness inventory with lane generation, and the fleet console's second slice. Two long-standing bugs fall out of it, and one promise the documentation had been making for a year becomes true.

- **The AI agent panel was never wired up.** `AgentPanel` installs itself as the agent host in its constructor, and nothing in the extension ever constructed one — so every `zer0Cms.agent.*` command ended at "the AI agent panel is not available in this window", for the whole of 0.1.0, while `src/agent/README.md` described the wiring in the present tense. `activate()` now builds it at step 8. The bundle is asserted to contain that wiring, because the test process and the running extension are different module instances and a runtime check would have passed for the wrong reason.
- **Workspace Trust is now the outer gate on everything that runs (decision D13).** Five paths in this extension can start a process — the content engine, the front-matter normalizer, a `placeholders[].script`, the new verify command, and the agent — and in an untrusted workspace all five refuse, as a result value rather than an exception, and the extension registers no MCP server at all. The manifest declares `untrustedWorkspaces: limited` and names the eighteen settings that decide *what* runs or *whether a gate is armed*, so a cloned repository's own `.vscode/settings.json` cannot aim them. Trust is re-checked inside each function that spawns: the `when` clause is the courtesy, the function is the gate. A script path that resolves outside the workspace root is refused whichever layer supplied it, and every spawn is now logged with its interpreter, its script and which configuration layer supplied them — so the output channel shows what a repository *tried* to run even when nothing ran. The engine also grew a ten-minute timeout, which it had never had.
- **The fleet's shared engines arrive by dependency, not by copy (decisions D3 and D14).** `@bamr87/fleet-engines` is an exact-pinned `devDependency` that the bundler admits into `dist/extension.js` alone; the MCP bundle's allow-list is now **empty**, so the layering gate that has always guarded `vscode` guards every package, and `dist/mcp-server.js` stays standalone by construction rather than by habit. One seam, `src/core/fleet/engines.ts`, is the only importer and is never re-exported through the core barrel. `dependencies` is still `{}` and still will be.
- **Four of the fleet's seven committed `fleet.manifest.yml` files are invalid YAML**, and the upstream parser was hiding it. `wtd fleet adopt` wraps a single-quoted scalar at column 80 and writes the continuation at column 0, outside the block indent; the engines' parser swallows the error and returns an *empty* manifest reporting *zero* skipped lanes, so a console consuming it would show a repository with no AI lanes at all and no indication anything went wrong. This repository's own manifest is one of the four. Keeping our own tolerant reader — which parses all seven — is what caught it, and a parity test now pins both halves: exact agreement where the package can read the file, and the silent-failure disagreement where it cannot.
- **Comparing what a manifest claims against what its workflows do.** `manifestDrift` reports where the two disagree, and on the real fleet it immediately found a lane declaring `opens_pull_requests: false` that demonstrably opens pull requests, a kill switch named in a manifest that no workflow reads, a schedule recorded for a cron that is commented out, and a token claimed but never used.
- **Performance, measured rather than assumed.** Cold indexing of a 382-file site went from 54 ms to 27 ms via a bounded worker pool whose results are folded back by candidate index, so page order and object identity are unchanged. The page-index cache is no longer rewritten when nothing changed — that write was 0.5–1.4 MB per rebuild per root — and its key is now per-root, because entries are keyed by absolute path and one shared key would rewrite every root's entries whenever any one of them refreshed.
- **The design decisions have somewhere to live.** Fifteen source and documentation files cited a plan document by section number; that plan was a conversation, not a file, and had never been in this repository. `docs/ARCHITECTURE.md` now states D1–D14 from the code, each with the mechanism that enforces it, alongside the contract map (what this console consumes, who owns it, where it is pinned) and a plain statement of what it will never do.

### ✨ New features

- **Six new settings, and a manifest that says what may run untrusted.** `fleet.roster`, `fleet.hub` and `fleet.gitfactoryUrl` (the multi-repository roster and the hand-off to GitFactory), `fleet.scaffoldAllow` (settings-only, like `dispatchAllow`, for writing a lane's files), and `cms.aiConfigPath` and `cms.verifyCommand` (the site's own model configuration and its verification command). The 44 settings are grouped into eleven titled sections, and most are now folder-scoped so one window can hold several sites without their settings leaking into each other. `SETTING_IDS` and the manifest are asserted equal, in order, and `tools/check-config-docs.py` fails the build when the documentation and the manifest disagree.
- **A release path.** `release-please` owns the version and the changelog; a repo-owned job packages the `.vsix`, attaches it to the GitHub release so any machine can `code --install-extension` it, and publishes to the Marketplace and Open VSX when those tokens exist — skipping with a notice, not a failure, while they do not. The packaged file list is committed and diffed in CI, so a packaging regression is a reviewed change. `docs/RELEASING.md` writes down what a person still has to do by hand.
- **The route registry.** The eleven dashboard routes and the tabs currently offered are one table, shared by the host and the webview, with a renderer table total over the union — a route can no longer be declared without a renderer. Operator primitives (status pills that distinguish *unknown* from *neutral*, scrolling data tables, empty states, gated buttons, diff views, a keyed staged form) moved into the shared component library where the five coming tabs can use them.

### 🐛 Fixes

- The bundled MCP server reported a hard-coded `0.1.0` that nobody remembered to bump; it now reports the extension's own version, and a test asserts the two cannot drift.
- The ABC generator under `rails/` is no longer called "the content engine" — that name belongs to the `.cms/` contract engine — and it has its own CI workflow, so an extension pull request stops running Ruby and a generator change stops downloading VS Code. Its README documented two commands that never worked: there is no `bin/rails` binstub and no Rakefile.
- Three claims the documentation made that CI had never checked are now tests: that `--vscode-` appears only in the token layer, that field widgets mount and dispose without leaking listeners, and that every route renders its empty state. A fourth was quietly false — `el()`'s `style` prop could never work under the strict Content-Security-Policy — and is gone.

---

Found by running the core over a real 100-file content repository instead of the seven-file fixture workspace.

### 🐛 Fixes

- **Slugs no longer lose words that carry meaning.** `slugify` inherited Front Matter's SMART stop-word list, which contains `back`, `new`, `value`, `use`, `way`, `thing`, `vs` and `without`. Over a real 72-post site it cost a meaningful word in 31% of titles: `"MCP for the back office"` became `mcp-office`, and `"… without losing data"` became `…-losing-data` — the opposite claim, in a permanent URL. The default list is now `minimal`, the closed class of English function words.
- **An uncounted body reports "unknown", not "0 words".** Without a `.cms/` contract the filesystem scan reads front matter and never bodies, and `pageToRecord` filled `wordCount` and `headingCount` with `0` — a claim, not an absence. The content tree drew "0 words" under every article in a repository with no engine, and the MCP `zer0_get_content` answer told a model that a two-thousand-word page was empty. Both now carry `UNKNOWN_COUNT` (`-1`), the sentinel `health` already used, and render through `countLabel`.

### ✨ New features

- **The Fleet console — this repository's AI lanes, and two verbs a human has to answer for.** With `zer0Cms.fleet.enabled` the dashboard grows a Fleet tab that reads `fleet.manifest.yml` (spec `fleet/v1`, the shared vocabulary `wtd fleet adopt` writes) and draws every lane: kind, harness, workflow, triggers, guardrails, the `*_ENABLED` repository variable that gates it, and the tokens it spends. After a GitHub sign-in you answer, two more columns arrive — the switch's current value and the workflow's newest run — and two buttons: flip the switch, or dispatch the lane once. The buttons post `{lane}` and nothing else; `doToggleSwitch` and `doDispatchLane` re-read the manifest from disk, re-run `evaluateFleetGates()` (a fixed, tested blocker order, exactly like the publish gate) and ask modally, naming the repository, the lane, the variable and the value — which for a toggle is derived from the variable as fetched a moment earlier, never from a message. The master gate, `zer0Cms.fleet.dispatchAllow`, is read from your settings alone, so a cloned `zer0.json` or manifest cannot arm it; a lane whose own manifest admits to merging or writing to the default branch is refused outright. Decision D11 states the one relaxation of the activation promise: network only from an explicit user action, through a `fetch` injected into `core/fleet`, whose every call is declared as data and checked against that plan before a socket opens. No token is stored. `zer0_fleet_status`, the twelfth MCP tool, reads the manifest only and says the switch state is unknown from there.
- **The YAML subset folds multi-line plain scalars.** A value continued on more-indented lines was read as its first line and the rest skipped — a documented gap, until the manifest's 80-column-wrapped `summary:` made it a bug. Continuation lines now fold the way YAML folds them (one space per line break, a newline per blank line); a line that reads as a key or a sequence item still ends the value, as before, so nothing that parsed previously parses differently.
- **The feedback loop closes.** `catering/` could already turn engagement into a worklist and `contract/` could already store it, but nothing turned a platform's statistics into the `performance.json` those two agree on — so Lanes B–D were empty unless somebody hand-wrote the file. `core/analytics` adds the join: statistics arrive keyed by a post id, the ledger says which post came from which page, and they leave keyed by content path. `zer0_ingest` runs it from any MCP client and `zer0_worklist` ranks on the result.
- **The read surface is declared as data, and the boundary is a test.** `readPlan()` enumerates every call the analytics lane would make, with what each returns, so it can be printed and reviewed before a credential exists. `readSurfaceIsOwnContentOnly` checks each one describes the author's *own* content; the suite asserts it for both shipped plans and asserts that a follower-enumeration call fails it. Reaching another person's data is a failing build rather than a review comment. There is deliberately no `fetch` here — invented numbers would silently poison the worklist that decides what somebody writes next.
- **`core/portfolio` — the published track record.** Volume, cadence, streak and collections, computed from the ledger, so it is meaningful from the first entry rather than waiting on statistics. The streak is anchored to the newest month *in the data*, not to today: a portfolio that reported a broken run because you opened it in a quiet week would be measuring the calendar, not the work. Exposed as `zer0_portfolio`.
- **`core/media` — reuse the image the site already made.** Resolves a page's preview image from front matter, then from `assets/images/previews/<slug>.*`, and when there is none emits the zer0-image-generator command that would produce it. It generates nothing: rendering stays where the provider matrix and review stage live. Publishing already read the image and silently posted without one, which let a repository drift into publishing untreated links; `zer0_media` makes that askable across the whole content set before anything ships. Shares `THUMBNAIL_KEYS` and `previewImageValue` with `governance/publish` rather than restating them, so the report and the publish path cannot disagree.
- **`slug.stopWords`** in `zer0.json` — `"minimal"` (default), `"smart"` (Front Matter verbatim, for a repository whose permalinks FM already minted), `"none"`, or a literal array. An unrecognised value falls back to the default rather than to "none", so a typo cannot silently re-slug a site. See [`docs/CONFIG.md` §3.11](docs/CONFIG.md).

### 📝 Documentation

- `docs/CONFIG.md` said the bundled MCP server parses `zer0.json` with `JSON.parse` and would choke on a comment. It reads it with `readJsonc`, exactly as the extension does, and always has.

## [0.1.0] - 2026-07-31

The first release of zer0-CMS as its own extension. Everything before this point was a fork of Front Matter CMS; that history stays in git, but none of it ships. See [ATTRIBUTION.md](ATTRIBUTION.md).

### ✨ New features

- **Metadata panel** — the active content file's front matter as real controls: 18 field types, required-field validation, taxonomy pickers with freeform creation, image preview fields, and grouped field collections.
- **Content dashboard** — grid, list and structure views over every registered content folder, with search, filters, sorting, grouping and pagination.
- **SEO insights** — title, description, slug, content-length and keyword checks against the thresholds in `zer0.json`.
- **Governed publishing** — a draft queue where approval is a human decision recorded in the file: draft → brand guard → approve → publish → ledger. Publishing is off until `zer0Cms.governance.publishAllow` is enabled.
- **Brand guard** — length limits, the fold preview, banned phrases, filler detection, and a workspace-supplied pattern file.
- **Idempotency ledger** — keyed by canonical URL, byte-compatible with the Python publishing lane, so a repo and its CI never double-publish.
- **Distribution lanes** — what to write next, derived from the `.cms/` contract and the ledger, exportable as a worklist.
- **`.cms/` contract** — per-file health, freshness and the mechanical/substantive issue lanes when the content engine has run; an honest filesystem scan when it hasn't.
- **Bundled MCP server** — eight tools for Copilot agent mode and any MCP client. Publishing is double-gated: an environment flag *and* an explicit per-call confirmation. The editor sets that flag only when `zer0Cms.governance.publishAllow` is set in your own settings — a `zer0.json` arriving with a cloned repository can enable publishing for the in-editor gates, which sit behind a modal, but never for an agent.
- **Optional AI agent** — the `cms-curator` skill through the Claude Agent SDK, with an approve/deny gate on every mutating tool. Off by default.

### 🎨 Enhancements

- Zero runtime dependencies. The agent SDK is an optional dependency, dynamically imported, and never required to use the CMS.
- `src/core` and `src/mcp` cannot import `vscode` — enforced by eslint and by the MCP bundle's build.
- Front matter is edited by line surgery, so comments and formatting survive an edit.
- Every publish gate is re-checked host-side, in the same function the command palette calls. A webview is UI, never the gate — including for deleting and renaming, where the host re-derives the target against the page index and asks before it acts.
