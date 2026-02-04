# Product Requirements Document (PRD): VS CMS Extension for Visual Studio Code

## 1. Document Information
- **Product Name**: VS CMS
- **Version**: 0.1.0 (Initial Development)
- **Author**: Product Team
- **Date**: December 3, 2025
- **Status**: Draft
- **Repository**: TBD
- **Related Documentation**: TBD

## 2. Revision History
| Version | Date       | Author | Changes |
|---------|------------|--------|---------|
| 0.1.0   | 2025-12-03 | Product Team | Initial PRD for new VS Code CMS extension. |

## 3. Overview
### 3.1 Product Summary
VS CMS is a modern Visual Studio Code extension that transforms VS Code into a comprehensive Content Management System. It provides an intuitive interface for creating, organizing, and managing content across various formats including Markdown, MDX, and JSON. The extension offers real-time preview capabilities, built-in SEO optimization tools, asset management, and workflow automation. Designed for developers, content creators, and teams working with static sites, headless CMS architectures, or documentation projects, VS CMS streamlines the entire content lifecycle from creation to publication.

### 3.2 Background and Context
VS CMS is being developed to address the growing need for a unified, developer-friendly content management solution within VS Code. While existing tools like Front Matter provide SSG-specific functionality, there's an opportunity to create a more flexible, framework-agnostic CMS that adapts to modern workflows including JAMstack, headless CMS, and API-driven architectures. The extension will emphasize modularity, extensibility, and AI-powered content assistance to help users manage increasingly complex content operations without leaving their development environment.

### 3.3 Goals and Objectives
- **Primary Goal**: Create a versatile, intuitive CMS extension that works seamlessly with modern web frameworks and content workflows, eliminating the need for external content management tools.
- **Business Objectives**:
  - Achieve 10k+ installations within first year through VS Code Marketplace.
  - Build active community with 50+ contributors.
  - Establish partnerships with 3+ major SSG/framework communities.
  - Maintain 95% satisfaction rating from user feedback.
- **Success Metrics**:
  - User Adoption: 60% 30-day retention rate.
  - Engagement: 200+ GitHub stars within 6 months.
  - Performance: <100ms UI response time, handle 50k+ files.
  - Quality: <5% bug rate per release.

## 4. Scope
### 4.1 In Scope
- **Core CMS Features**: Content dashboard, CRUD operations, search/filter, collection management.
- **Content Types**: Markdown, MDX, JSON, YAML, TOML front matter support.
- **Framework Integration**: Adapters for Hugo, Next.js, Astro, Gatsby, Jekyll, Eleventy, Docusaurus.
- **Asset Management**: Media library, image optimization, metadata handling.
- **Content Tools**: Live preview, SEO analysis, schema validation, AI-assisted writing.
- **Workflow Automation**: Git integration, publishing workflows, content scheduling.
- **Extensibility**: Plugin system, custom content types, template library.
- **Team Features**: Multi-user settings, content review workflows, role-based access.

### 4.2 Out of Scope
- Native mobile applications (VS Code desktop only).
- Backend hosting services (local/git-based only).
- Real-time analytics dashboards (integration via APIs only).
- WYSIWYG drag-and-drop page builders.
- Database management for traditional CMS backends.

## 5. Target Audience
### 5.1 User Personas
| Persona | Description | Needs | Pain Points |
|---------|-------------|-------|-------------|
| **Developer Blogger (e.g., Sarah, 29)** | Full-stack developer maintaining a personal tech blog using Astro/Next.js. | Fast content creation, version control integration, code syntax highlighting, SEO tools. | Context switching between editor and CMS, manual metadata management, preview inconsistencies. |
| **Technical Writer (e.g., James, 35)** | Documentation specialist working on product docs with Docusaurus. | Structured content, validation, collaborative review, multi-version support. | Complex folder structures, broken links, outdated content tracking, approval workflows. |
| **Content Team Lead (e.g., Maria, 42)** | Manages content team for SaaS company using headless CMS with Next.js. | Team workflows, content templates, bulk operations, analytics integration. | Inconsistent formatting, workflow bottlenecks, training overhead for new tools. |
| **Agency Developer (e.g., Alex, 31)** | Freelance developer building client sites with various SSGs. | Framework flexibility, reusable templates, efficient media handling, client handoff. | Per-project tooling setup, client training complexity, maintenance across multiple stacks. |

### 5.2 User Requirements
- **Functional**: 
  - Visual content dashboard with filtering and search
  - Framework-agnostic content model with adapters
  - Real-time content preview with hot reload
  - Git-integrated publishing workflows
  - Template and snippet library
  - AI-powered content suggestions
- **Non-Functional**: 
  - Performance: <10MB bundle size, <1s dashboard load, handles 100k+ files
  - Reliability: 99.9% uptime, graceful error recovery
  - Usability: WCAG 2.1 AA compliant, keyboard navigation
  - Compatibility: VS Code 1.85+, Node.js 18+
  - Security: No telemetry without consent, local-first data storage

## 6. Features and Requirements
Features are prioritized using MoSCoW method (Must-have, Should-have, Could-have, Won't-have). Requirements include user stories and acceptance criteria.

### 6.1 Must-Have Features
1. **Universal Content Dashboard**
   - User Story: As a content creator, I want a unified dashboard to view, search, filter, and manage all content regardless of framework.
   - Acceptance Criteria:
     - Grid and list views with customizable columns
     - Advanced search with filters (status, date, author, tags)
     - Bulk actions (delete, update metadata, move)
     - Collection-based organization
     - Quick preview and edit from dashboard

2. **Framework Adapters**
   - User Story: As a developer, I want automatic detection of my framework so the CMS configures itself correctly.
   - Acceptance Criteria:
     - Auto-detect Hugo, Next.js, Astro, Gatsby, Jekyll, 11ty, Docusaurus
     - Load framework-specific content schemas
     - Support custom adapter configuration
     - Fallback to generic Markdown mode

3. **Content Editor with Validation**
   - User Story: As a writer, I want guided content creation with real-time validation to prevent errors.
   - Acceptance Criteria:
     - Form-based front matter editor with field types (text, date, select, array)
     - Schema validation with error messages
     - Rich Markdown editor with toolbar
     - Auto-save and version history
     - Template selection on creation

4. **Live Preview**
   - User Story: As a content creator, I want to see how my content looks in real-time without running build commands.
   - Acceptance Criteria:
     - Side-by-side or split preview modes
     - Hot reload on content changes
     - Framework-aware rendering (respects templates)
     - Device responsive preview options

5. **SEO & Content Optimization**
   - User Story: As a blogger, I want automated SEO analysis to improve content discoverability.
   - Acceptance Criteria:
     - Meta description length and quality checks
     - Title tag optimization
     - Keyword density analysis
     - Readability scoring
     - Image alt text validation
     - Internal/external link analysis

### 6.2 Should-Have Features
1. **Advanced Media Library**
   - User Story: As a content creator, I want professional media management with optimization and organization.
   - Acceptance Criteria:
     - Visual media browser with thumbnails
     - Drag-and-drop upload with progress
     - Automatic image optimization (WebP, compression)
     - Metadata editor (alt text, captions, credits)
     - Folder organization and tagging
     - Usage tracking (where media is referenced)
     - Bulk operations (optimize, move, delete)

2. **Content Workflows**
   - User Story: As a team lead, I want structured workflows to manage content through draft, review, and publish stages.
   - Acceptance Criteria:
     - Configurable workflow states (draft, review, approved, published)
     - Assignment and notification system
     - Approval tracking and comments
     - Git branch integration for review
     - Scheduled publishing with calendar view

3. **AI Content Assistant**
   - User Story: As a writer, I want AI-powered suggestions to improve writing efficiency and quality.
   - Acceptance Criteria:
     - Content outline generation
     - SEO-optimized title suggestions
     - Meta description generation
     - Content summarization
     - Tone and readability improvements
     - Integration with GitHub Copilot or OpenAI

4. **Template & Snippet Library**
   - User Story: As a developer, I want reusable templates to standardize content creation.
   - Acceptance Criteria:
     - Create custom content templates
     - Insert snippets via command palette
     - Variable substitution in templates
     - Share templates across team
     - Import/export template collections

5. **Taxonomy & Metadata Management**
   - User Story: As a content manager, I want centralized control over tags, categories, and custom fields.
   - Acceptance Criteria:
     - Taxonomy dashboard with CRUD operations
     - Auto-suggest from existing content
     - Bulk update across content
     - Custom field definitions
     - Validation rules for taxonomies

### 6.3 Could-Have Features
1. **Content Analytics Dashboard**
   - View metrics integration (page views, engagement)
   - Content performance insights
   - Link to external analytics (Google Analytics, Plausible)

2. **Multi-Language (i18n) Support**
   - Content translation workflow
   - Locale-specific content variants
   - Translation status tracking

3. **Content Import/Export**
   - Import from WordPress, Medium, other CMS
   - Bulk export to various formats
   - Migration tools and documentation

4. **Advanced Git Integration**
   - Visual merge conflict resolution for content
   - Branch comparison for content changes
   - Content-specific commit messages

5. **Plugin Marketplace**
   - Community extensions
   - Custom field types
   - Framework adapter plugins

### 6.4 Won't-Have (This Release)
- Real-time collaborative editing (use VS Code Live Share)
- Visual page builders or drag-and-drop interfaces
- E-commerce or shopping cart functionality
- User authentication and permission systems (rely on git/filesystem)
- Database-backed CMS features (focus on file-based content)
- Mobile app or web-based interface

## 7. User Stories and Use Cases
### 7.1 Key Flows
1. **First-Time Setup**: Install extension → Open project → Auto-detect framework → Configure content collections → View welcome tour → Create first content.

2. **Daily Content Creation**: Open dashboard → Click "New Content" → Select template/type → Fill form fields → Write in editor → Preview live → Run SEO check → Save draft → Request review (if workflow enabled) → Publish.

3. **Content Management**: Open dashboard → Filter by status/date → Select multiple items → Bulk update metadata → Move to folder → Publish batch.

4. **Media Management**: Open media library → Drag images to upload → Auto-optimize → Add metadata → Copy markdown reference → Insert into content.

5. **Team Collaboration**: Create content → Save to branch → Request review → Reviewer opens PR in dashboard → Add comments → Approve → Merge and publish.

6. **Framework Migration**: Install extension → Run framework detection → Review adapter config → Import existing content → Validate schemas → Fix issues → Continue working.

## 8. Technical Requirements
### 8.1 System Architecture
- **Frontend**: 
  - React 18+ with TypeScript for webview UI
  - TailwindCSS for styling
  - Zustand or Redux for state management
  - React Query for data fetching

- **Backend/Extension**:
  - TypeScript with VS Code Extension API
  - Node.js for file operations and content processing
  - Gray-matter for front matter parsing
  - Unified/Remark/Rehype for Markdown processing
  - Sharp for image optimization
  - Framework adapters (pluggable architecture)

- **Data Layer**:
  - File-based content (Markdown, MDX, JSON)
  - SQLite for indexing and search (`.vscms/content.db`)
  - JSON for configuration (`.vscms/config.json`)
  - Git for versioning and collaboration

- **Key Components**:
  - Content Scanner: Indexes files and builds content database
  - Framework Adapter: Detects and configures for specific SSG
  - Preview Server: Renders content in framework context
  - Media Processor: Optimizes and manages assets
  - Schema Validator: Ensures content meets requirements
  - AI Service: Integrates with LLM APIs for assistance

- **External Integrations**:
  - Git (via VS Code SCM API)
  - Framework CLIs (Hugo, Next.js, etc.)
  - Optional: OpenAI API, GitHub Copilot
  - Optional: Analytics APIs (GA, Plausible)

### 8.2 Non-Functional Requirements
- **Performance**: 
  - Dashboard loads in <1 second for 10k files
  - Content indexing <5 seconds for 1k files
  - Preview updates <500ms after edit
  - Search results <200ms
  - Memory footprint <200MB

- **Scalability**:
  - Support projects with 100k+ content files
  - Handle 10k+ media assets
  - Concurrent operations without blocking UI

- **Reliability**:
  - Graceful degradation when framework not detected
  - Auto-recovery from corrupted index
  - Data integrity checks on operations
  - Comprehensive error logging

- **Security**:
  - No data sent to external servers without explicit consent
  - Secure API key storage (VS Code secrets)
  - Sanitize user input to prevent XSS
  - File system access only within workspace

- **Accessibility**:
  - WCAG 2.1 AA compliance
  - Full keyboard navigation
  - Screen reader support
  - High contrast theme support

- **Compatibility**:
  - VS Code 1.85+ (latest stable - 6 months)
  - Node.js 18+ (LTS)
  - Windows 10+, macOS 11+, Linux (Ubuntu 20.04+)
  - Works with VS Code Web (limited features)

### 8.3 Constraints and Assumptions
- **Constraints**: 
  - VS Code extension API limitations
  - File-based content only (no database backends)
  - Local execution (no cloud services)
  - Single workspace at a time

- **Assumptions**:
  - Users have basic git knowledge
  - Framework build tools installed locally
  - Modern web browser for preview
  - Reasonable project sizes (<1M files)

## 9. Design and UX Guidelines
- **Design Principles**:
  - **Native First**: Match VS Code UI patterns and behaviors
  - **Progressive Disclosure**: Show simple options first, advanced on demand
  - **Consistency**: Unified patterns across all dashboards and views
  - **Feedback**: Immediate visual response to all user actions
  - **Efficiency**: Minimize clicks, support keyboard shortcuts

- **Visual Design**:
  - Follow VS Code design language (Codicons, colors, spacing)
  - Support all VS Code themes (dark, light, high contrast)
  - Custom icons for CMS-specific actions
  - Responsive layouts for different panel sizes

- **Interaction Patterns**:
  - Command Palette integration for all major actions
  - Context menus for item-specific operations
  - Inline editing where appropriate
  - Drag-and-drop for media and content organization
  - Keyboard shortcuts for power users

- **Information Architecture**:
  - Primary Sidebar: Content collections tree view
  - Panel Views: Dashboard, Media Library, Settings
  - Editor Integration: Inline metadata editor, preview panel
  - Status Bar: Quick stats and actions

- **Error Handling**:
  - Toast notifications for transient messages
  - Inline validation errors with suggestions
  - Error recovery options (undo, retry, ignore)
  - Help links to documentation
  - Detailed logs in Output panel

## 10. Roadmap and Future Considerations

### Phase 1: MVP (Q1 2026 - 3 months)
- Core content dashboard and CRUD operations
- Framework detection for Hugo, Next.js, Astro
- Basic front matter editor with validation
- Simple media library
- Live Markdown preview
- SEO basic checks
- Git integration (status, commit, push)

### Phase 2: Enhanced Features (Q2 2026 - 3 months)
- Additional framework adapters (Gatsby, Jekyll, 11ty, Docusaurus)
- Advanced media management with optimization
- Template and snippet library
- Content workflows (draft, review, publish)
- Enhanced search and filtering
- Bulk operations
- Team settings and collaboration basics

### Phase 3: Advanced Capabilities (Q3-Q4 2026 - 6 months)
- AI content assistant integration
- Plugin system and marketplace
- i18n and multi-language support
- Content analytics dashboard
- Advanced Git workflows (branch comparison, PR integration)
- Import/export tools
- Custom field types and validators

### Future Considerations
- **VS Code Web Support**: Lightweight version for browser-based editing
- **Cloud Sync**: Optional team settings and template sync
- **GraphQL API**: Query content programmatically
- **Custom Renderers**: Support for non-web content (PDF, ebooks)
- **Integration Marketplace**: Third-party plugins (CMS APIs, analytics, etc.)

### Risks and Mitigation
| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| VS Code API breaking changes | High | Medium | Version pinning, active monitoring of VS Code releases |
| Framework ecosystem changes | Medium | High | Pluggable adapter architecture, community contributions |
| Performance with large projects | High | Medium | Incremental indexing, virtual scrolling, lazy loading |
| User adoption challenges | Medium | Medium | Comprehensive docs, video tutorials, migration guides |
| Maintenance burden | Medium | High | Modular architecture, automated testing, clear contribution guidelines |
| Competition from existing tools | Low | High | Focus on developer experience, unique AI features, framework flexibility |

## 11. Appendix

### 11.1 Glossary
- **CMS**: Content Management System - software for creating and managing digital content
- **SSG**: Static Site Generator - tool that generates HTML from templates and content
- **Front Matter**: Metadata block at the beginning of Markdown files (YAML, TOML, or JSON)
- **MDX**: Markdown with embedded JSX components
- **JAMstack**: JavaScript, APIs, and Markup architecture pattern
- **Headless CMS**: Backend-only CMS that provides content via API
- **Content Collection**: Group of related content items with shared schema
- **Adapter**: Plugin that provides framework-specific functionality
- **Schema**: Definition of content structure and validation rules
- **Taxonomy**: System of classification (tags, categories, etc.)

### 11.2 References
- VS Code Extension API: https://code.visualstudio.com/api
- Framework Documentation:
  - Hugo: https://gohugo.io/
  - Next.js: https://nextjs.org/
  - Astro: https://astro.build/
  - Gatsby: https://www.gatsbyjs.com/
- Inspiration:
  - Front Matter CMS: https://frontmatter.codes
  - Sanity: https://www.sanity.io/
  - Tina CMS: https://tina.io/

### 11.3 Success Metrics Tracking
- Install/uninstall rates (VS Code Marketplace)
- Active users (optional telemetry with consent)
- GitHub activity (stars, issues, PRs)
- User satisfaction surveys
- Performance benchmarks
- Bug rates per release

### 11.4 Approval and Sign-off
- **Product Owner**: ___________________ Date: ___________
- **Engineering Lead**: ___________________ Date: ___________
- **Design Lead**: ___________________ Date: ___________
- **Stakeholders**: ___________________ Date: ___________