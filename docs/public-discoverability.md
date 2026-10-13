# Public documentation and discoverability

The public overview under docs/public is the introductory product description for AI Agile, the product delivered by ai-coding-standards2. It explains engineering-management needs, objectives, mechanisms and limits. Detailed product/process definitions remain in docs/product/orchestrator, agent files and pipeline/pipeline.json. Do not invent capabilities or fork those authorities to improve marketing language.

## Publication

The repository is public. At the October 13, 2026 review it had no GitHub Pages site enabled. The documentation workflow builds a strict MkDocs preview on pull requests and main changes. It publishes only when manually dispatched on main, after approved content is merged and repository Pages is configured to use GitHub Actions. It does not enable repository administration settings.

The prepared default site URL is https://m-a-operating-system.github.io/ai-coding-standards2/. This is a deployment target, not a claim that the site is currently live. After merging:

1. A repository administrator enables Pages with GitHub Actions as its source.
2. Run Public product documentation on main.
3. Check the published pages and sitemap anonymously, including HTTP status, canonical URL and visible text.
4. Add a public documentation link to the repository README/homepage and an appropriate M&A Operating System website page after the URL is verified.
5. Verify the site in Google Search Console using an authorized account and submit its sitemap. No Search Console property, credential or indexing submission is created by this PR.

Repeat publication after approved public-content changes; the push build alone does not update the deployed site. If a custom domain is selected, update site_url and regenerate canonical URLs/sitemap before deployment. The project-path deployment cannot control the organization domain's root robots.txt; no misleading project-subdirectory robots file is supplied.

## Search and AI discovery

MkDocs generates static, anonymously accessible HTML with descriptive page titles, descriptions, canonical links, navigation and a sitemap. The main product wording uses terms people can reasonably search for: AI software development lifecycle, AI coding agents, engineering management, GitHub orchestration, coding standards, verification and human approval. Use these naturally; do not add keyword stuffing or pages that repeat the same claim without useful information.

Google's guidance says its AI search experiences build on ordinary search eligibility and useful, reliable content. No special AI schema or llms.txt file guarantees inclusion. This proposal deliberately uses normal HTML and a sitemap rather than presenting a crawler hint as a ranking mechanism. Other AI services apply their own retrieval/indexing policies; public access does not guarantee their inclusion.

Keep implemented capabilities and target designs distinct. Public pages link to current product/implementation sources and label V3 as proposed. Do not publish unsupported speed/cost improvements, adoption statistics, customer endorsements or feature comparisons. Do not attribute the repository's own goals or positioning to third-party articles or authors.

## Evidence and maintenance

Track whether key pages are indexed, relevant search queries/impressions/clicks where accessible, referring links and inaccuracies in AI-generated descriptions. Record observations with dates and actual URLs. Do not report ranking, traffic or AI citation improvements without measurements.

The engineering-management page states observing agent work, verifying output and measuring process changes as this repository's own goals, without attributing them to any third-party source.

Primary guidance: [Google Search Essentials](https://developers.google.com/search/docs/essentials), [Google AI optimization](https://developers.google.com/search/docs/fundamentals/ai-optimization-guide), [sitemaps](https://developers.google.com/search/docs/crawling-indexing/sitemaps/build-sitemap), [GitHub Pages workflows](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages) and [MkDocs configuration](https://www.mkdocs.org/user-guide/configuration/).
