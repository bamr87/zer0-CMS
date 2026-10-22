#!/usr/bin/env ruby
# frozen_string_literal: true

# =============================================================================
# generate-reference.rb
# =============================================================================
#
# Writes the generated reference pages under docs/reference/ from the files
# they describe, so no hand-kept table can drift from its source (the fleet
# documentation framework's UPS-DOC-05):
#
#   docs/reference/agent-guidance.md  .github/instructions/*.instructions.md
#                                     (applyTo + description), .github/prompts,
#                                     .github/skills, .claude/skills and
#                                     .claude/agents — from their front matter
#   docs/reference/commands.md        scripts/bin/* entry points, the
#                                     test/test_runner.sh suites, Makefile
#                                     targets (## comments), Rakefile tasks
#                                     (desc) and package.json scripts
#   docs/reference/installer.md       the installer's subcommands, options and
#                                     examples, from its help text in
#                                     scripts/install/cli.sh
#   docs/reference/workflows.md       every .github/workflows/*.yml: name,
#                                     triggers and jobs
#
# Usage:
#   ruby scripts/generate-reference.rb           # rewrite the pages in place
#   ruby scripts/generate-reference.rb --check   # exit 1 if any page is stale
#   ruby scripts/generate-reference.rb --stdout  # print the pages, write nothing
#
# docs/ pages carry front matter (scripts/docs/lint-frontmatter.sh). `date`
# and `lastmod` are kept from the page already on disk, and `lastmod` moves to
# the current time only when the generated body changes — so --check never
# depends on the clock. To change a row, edit its source file, then re-run.
#
# This script has no gem dependencies beyond the Ruby stdlib.
# =============================================================================

require 'yaml'
require 'json'
require 'date'
require 'time'
require 'optparse'

ROOT    = File.expand_path('..', __dir__)
COMMAND = 'ruby scripts/generate-reference.rb'

def read(rel)
  File.read(File.join(ROOT, rel), encoding: 'UTF-8')
end

def files(glob)
  Dir.glob(File.join(ROOT, glob)).map { |p| p.delete_prefix("#{ROOT}/") }.sort
end

# [front-matter YAML text, body] of a Markdown text (front matter nil when absent).
def split_front_matter(text)
  return [nil, text] unless text.start_with?("---\n")

  close = text.index(/^---[ \t]*$/, 4) or return [nil, text]
  [text[4...close], text[close..].sub(/\A---[ \t]*\n?/, '')]
end

# Front matter of a Markdown file as a Hash ({} when it has none).
def front_matter(rel)
  data = YAML.safe_load(split_front_matter(read(rel)).first.to_s, permitted_classes: [Date, Time], aliases: true)
  data.is_a?(Hash) ? data : {}
rescue Psych::Exception => e
  abort "#{rel}: unreadable front matter (#{e.message.lines.first.strip})"
end

# An applyTo value split on the commas that are not inside a {brace,glob}.
def globs(value)
  depth = 0
  value.to_s.chars.each_with_object(['']) do |ch, parts|
    depth += 1 if ch == '{'
    depth -= 1 if ch == '}'
    ch == ',' && depth.zero? ? parts << '' : parts[-1] += ch
  end.map(&:strip).reject(&:empty?)
end

def oneline(value)
  value.to_s.gsub(/\s+/, ' ').strip
end

def cell(value)
  text = oneline(value)
  text.empty? ? '—' : text.gsub('|', '\|')
end

def code(text)
  "`#{text}`"
end

def table(headers, rows)
  out = ["| #{headers.join(' | ')} |", "|#{' --- |' * headers.size}"]
  rows.each { |r| out << "| #{r.join(' | ')} |" }
  out.join("\n")
end

# Link from a page in docs/reference/ to a file at the theme's root.
def link(rel, label = rel)
  "[#{code(label)}](../../#{rel})"
end

# --- agent guidance ----------------------------------------------------------

def agent_guidance
  instructions = files('.github/instructions/*.instructions.md').map do |rel|
    fm = front_matter(rel)
    [link(rel, File.basename(rel)), globs(fm['applyTo']).map { |g| code(g.gsub('|', '\|')) }.join(', '), cell(fm['description'])]
  end

  cursor = files('.cursor/commands/*.md').map { |rel| File.basename(rel, '.md') }
  prompts = files('.github/prompts/*.prompt.md').map do |rel|
    name = File.basename(rel, '.prompt.md')
    mirror = cursor.include?(name) ? code("/#{name}") : '—'
    [link(rel, "/#{name}"), mirror, cell(front_matter(rel)['description'])]
  end

  skills = (files('.github/skills/*/SKILL.md') + files('.claude/skills/*/SKILL.md')).map do |rel|
    fm = front_matter(rel)
    name = fm['name'] || File.basename(File.dirname(rel))
    [link(rel, name), cell(fm['description'].to_s.sub(/\A\*\*WORKFLOW SKILL\*\*\s*[—-]\s*/, ''))]
  end

  agents = files('.claude/agents/*.md').map do |rel|
    fm = front_matter(rel)
    [link(rel, fm['name'] || File.basename(rel, '.md')), cell(fm['description'])]
  end

  <<~MD
    ## File-scoped instructions

    Load the file whose `applyTo:` glob matches the path you are editing (Copilot does this by itself). When one of them conflicts with a generic best practice, the file-scoped rule wins.

    #{table(['Instructions', 'Applies to', 'What it covers'], instructions)}

    ## Reusable prompts

    Multi-step workflows for chat and agent modes. The second column names the Cursor slash-command that mirrors the prompt in `.cursor/commands/`.

    #{table(['Prompt', 'Cursor command', 'What it does'], prompts)}

    ## Skills

    Operational checklists: `.github/skills/` for every agent, `.claude/skills/` for Claude Code. Read the matching skill before the action it covers.

    #{table(['Skill', 'When to use it'], skills)}

    ## Claude Code subagents

    The specialised lanes `/issue-implement` and the autonomous pipeline route work to (`_data/routing.yml`).

    #{table(['Subagent', 'Role'], agents)}
  MD
end

# --- commands ----------------------------------------------------------------

SKIP_COMMENT = /\A(Features?:|Usage:|=+|-+|kit:)/.freeze

# The first sentence of a script's header comment: what the script is.
def script_summary(rel)
  name = File.basename(rel)
  lines = read(rel).lines.first(30).map(&:rstrip)
  start = lines.index do |l|
    text = l.sub(/\A#+\s?/, '').strip
    l.start_with?('#') && !l.start_with?('#!') && !text.empty? && text !~ SKIP_COMMENT
  end
  return '' unless start

  # A wrapped sentence continues on a line that starts in lower case.
  para = lines[start..].map { |l| l.start_with?('#') ? l.sub(/\A#+\s?/, '').strip : '' }
  para = para.each_with_index.take_while { |t, i| i.zero? || t.match?(/\A[a-z(`]/) }.map(&:first)
  text = para.join(' ')
  text = text.sub(/\A(?:\.?\/?scripts\/bin\/)?#{Regexp.escape(name)}\s*[—-]\s*/, '')
  text[/\A.+?[.!?](?=\s|\z)/] || text
end

def bash_array(source, name)
  m = source.match(/^#{name}=\((.*)\)\s*$/) or abort "test/test_runner.sh: #{name}=(…) not found"
  m[1].scan(/"([^"]*)"/).flatten
end

def test_suites
  src = read('test/test_runner.sh')
  keys    = bash_array(src, 'TEST_SUITE_KEYS')
  scripts = bash_array(src, 'TEST_SUITE_SCRIPTS')
  names   = bash_array(src, 'TEST_SUITE_NAMES')
  rows = keys.each_with_index.map do |key, i|
    [code("--suites #{key}"), link("test/#{scripts[i]}", scripts[i]), cell(names[i])]
  end
  groups = src.scan(/== "(\w+)" \]\]; then\s*\n(?:\s*#.*\n)*\s*suites_to_run=\(([^)]*)\)/).map do |group, list|
    [code("--suites #{group}"), '—', cell(list.scan(/"([^"]*)"/).flatten.join(', '))]
  end
  groups + rows
end

def make_targets
  read('Makefile').scan(/^([A-Za-z0-9_.-]+):[^\n#]*##\s*(.+)$/).map do |target, desc|
    [code("make #{target}"), cell(desc)]
  end
end

def rake_tasks
  rows = []
  namespace = nil
  desc = nil
  read('Rakefile').each_line do |line|
    if (m = line.match(/^namespace :(\w+) do/))
      namespace = m[1]
    elsif line =~ /^end\b/
      namespace = nil
    elsif (m = line.match(/^\s*desc ["'](.+)["']\s*$/))
      desc = m[1]
    elsif (m = line.match(/^\s*task :(\w+)/)) && desc
      rows << [code("rake #{[namespace, m[1]].compact.join(':')}"), cell(desc)]
      desc = nil
    elsif (m = line.match(/^task default: ["']([\w:]+)["']/))
      rows << [code('rake'), cell("Default task: `#{m[1]}`")]
    end
  end
  rows
end

def npm_scripts
  JSON.parse(read('package.json')).fetch('scripts', {}).sort.map do |name, cmd|
    [code("npm run #{name}"), code(cmd.gsub('|', '\|'))]
  end
end

def commands
  bins = files('scripts/bin/*').select { |rel| File.file?(File.join(ROOT, rel)) }.map do |rel|
    [link(rel, "./#{rel}"), cell(script_summary(rel))]
  end

  <<~MD
    ## Entry points (`scripts/bin/`)

    The canonical implementations; `scripts/build`, `scripts/release` and `scripts/validate` are thin wrappers that forward here. Each prints its options with `--help`.

    #{table(['Command', 'What it does'], bins)}

    ## Test suites (`./test/test_runner.sh`)

    `./scripts/bin/test` runs the lib, theme and integration tiers; `./test/test_runner.sh --suites <list>` runs theme suites by name (comma-separated). The groups come first.

    #{table(['Option', 'Script', 'What it runs'], test_suites)}

    ## Make targets

    #{table(['Command', 'What it does'], make_targets)}

    ## Rake tasks

    `bundler/gem_tasks` also provides `rake build`, `rake install` and `rake release`.

    #{table(['Command', 'What it does'], rake_tasks)}

    ## npm scripts

    #{table(['Command', 'Runs'], npm_scripts)}
  MD
end

# --- workflows ---------------------------------------------------------------

def triggers(on)
  case on
  when String then [code(on)]
  when Array  then on.map { |e| code(e) }
  when Hash
    on.map do |event, cfg|
      label = code(event)
      if event.to_s == 'schedule' && cfg.is_a?(Array)
        "#{label} (#{cfg.map { |c| code(c['cron']) }.join(', ')})"
      elsif cfg.is_a?(Hash) && (cfg['paths'] || cfg['paths-ignore'])
        "#{label} (paths)"
      else
        label
      end
    end
  else []
  end
end

def workflows
  rows = files('.github/workflows/*.yml').map do |rel|
    doc = YAML.safe_load(read(rel), aliases: true) || {}
    on = doc.key?('on') ? doc['on'] : doc[true] # YAML 1.1 reads a bare `on:` as true
    jobs = (doc['jobs'] || {}).keys
    [link(rel, File.basename(rel)), cell(doc['name']), triggers(on).join(', '), jobs.map { |j| code(j) }.join(', ')]
  rescue Psych::Exception => e
    abort "#{rel}: unreadable YAML (#{e.message.lines.first.strip})"
  end

  <<~MD
    GitHub runs only a repository's root `.github/workflows/`. In zer0-CMS these files are the theme's own copies: its pull-request gate is ported to the root `zer0-mistakes.yml`, and the standalone `bamr87/zer0-mistakes` repository runs the rest until its cutover (zer0-CMS `docs/MONOREPO.md`). What each workflow does in depth: [`.github/workflows/README.md`](../../.github/workflows/README.md).

    #{table(['Workflow', 'Name', 'Triggers', 'Jobs'], rows)}
  MD
end

# --- installer ---------------------------------------------------------------

# The installer's own `help` text, from the heredoc in scripts/install/cli.sh.
def installer_help
  src = read('scripts/install/cli.sh')
  m = src.match(/^_cmd_help\(\) \{\n\s*cat >&2 <<'USAGE'\n(.*?)\nUSAGE$/m) or
    abort "scripts/install/cli.sh: the _cmd_help <<'USAGE' heredoc was not found"
  sections = {}
  current = nil
  m[1].each_line do |line|
    if (h = line.match(/\A(\S[^:]*):\s*\z/))
      current = sections[h[1]] = []
    elsif current && !line.strip.empty?
      current << line.rstrip.sub(/\A  /, '')
    end
  end
  sections
end

def installer
  help = installer_help
  pairs = lambda do |key|
    (help[key] || []).map { |l| l.split(/\s{2,}/, 2) }.map { |a, b| [code(a.gsub('|', '\|')), cell(b)] }
  end
  subcommands = pairs.call('Subcommands').map { |c, d| [c.sub('`', '`./scripts/bin/install '), d] }

  <<~MD
    The modular installer's command surface, as `./scripts/bin/install help` prints it. How the pieces fit together: [`docs/installation/`](../installation/index.md).

    ## Subcommands

    #{table(['Command', 'What it does'], subcommands)}

    ## Global options

    #{table(['Option', 'Effect'], pairs.call('Global options'))}

    ## Examples

    ```bash
    #{(help['Examples'] || []).join("\n")}
    ```
  MD
end

# --- pages -------------------------------------------------------------------

PAGES = [
  {
    path: 'docs/reference/agent-guidance.md',
    title: 'Agent guidance reference',
    description: 'Every file-scoped instruction set with its applyTo globs, every reusable prompt, skill and Claude Code subagent, generated from their front matter.',
    tags: %w[reference agents],
    body: -> { agent_guidance }
  },
  {
    path: 'docs/reference/commands.md',
    title: 'Command reference',
    description: 'Every scripts/bin entry point, test suite, Make target, Rake task and npm script in the theme, generated from the files that define them.',
    tags: %w[reference commands],
    body: -> { commands }
  },
  {
    path: 'docs/reference/installer.md',
    title: 'Installer reference',
    description: 'Every subcommand, global option and example of the modular installer, generated from the help text in scripts/install/cli.sh.',
    tags: %w[reference installation],
    body: -> { installer }
  },
  {
    path: 'docs/reference/workflows.md',
    title: 'Workflow inventory',
    description: 'Every GitHub Actions workflow the theme carries, with its name, triggers and jobs, generated from the workflow files themselves.',
    tags: %w[reference ci],
    body: -> { workflows }
  }
].freeze

def now
  Time.now.utc.strftime('%Y-%m-%dT%H:%M:%S.000Z')
end

def existing(path)
  full = File.join(ROOT, path)
  return [nil, nil, nil] unless File.exist?(full)

  fm, body = split_front_matter(File.read(full, encoding: 'UTF-8'))
  meta = YAML.safe_load(fm.to_s, permitted_classes: [Date, Time]) || {}
  stamp = ->(v) { v.is_a?(Time) ? v.utc.strftime('%Y-%m-%dT%H:%M:%S.000Z') : v&.to_s }
  [stamp.call(meta['date']), stamp.call(meta['lastmod']), body.sub(/\A\n/, '')]
end

def body_for(page)
  <<~MD
    <!-- GENERATED by `#{COMMAND}` — do not edit by hand. -->

    # #{page[:title]}

    > #{page[:description]}

    #{page[:body].call.rstrip}
  MD
end

def render(page, date, lastmod, body)
  <<~MD + "\n" + body
    ---
    title: "#{page[:title]}"
    description: "#{page[:description]}"
    date: #{date}
    lastmod: #{lastmod}
    categories: [docs]
    tags: [#{page[:tags].join(', ')}]
    author: bamr87
    ---
  MD
end

mode = :write
OptionParser.new do |o|
  o.banner = "Usage: #{COMMAND} [--check | --stdout]"
  o.on('--check', 'Exit 1 if any generated page is stale') { mode = :check }
  o.on('--stdout', 'Print the pages instead of writing them') { mode = :stdout }
end.parse!

stale = []
PAGES.each do |page|
  date, lastmod, old_body = existing(page[:path])
  body = body_for(page)
  changed = old_body != body
  text = render(page, date || now, changed && mode != :check ? now : (lastmod || now), body)
  full = File.join(ROOT, page[:path])

  case mode
  when :stdout
    puts text
  when :check
    stale << page[:path] if changed || !File.exist?(full)
  else
    next unless changed || !File.exist?(full)

    Dir.mkdir(File.dirname(full)) unless Dir.exist?(File.dirname(full))
    File.write(full, text, encoding: 'UTF-8')
    puts "wrote #{page[:path]}"
  end
end

if mode == :check
  if stale.empty?
    puts '✓ docs/reference/ is up to date with its sources'
  else
    warn "✗ stale: #{stale.join(', ')} — run `#{COMMAND}`"
    exit 1
  end
end
