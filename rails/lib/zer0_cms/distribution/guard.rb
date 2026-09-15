# frozen_string_literal: true

require "json"

module Zer0Cms
  module Distribution
    # The mechanical brand guard — the half of review a machine can do.
    #
    # A rule-for-rule port of the VS Code extension's guard
    # (src/core/governance/guard.ts), which is itself the merge of three rule
    # sets: the length and banned-phrase errors from the Python publisher, the
    # thirteen hard bans from bash-365.com's `scripts/content_lint.py`, and the
    # filler, weak-hook and fold checks from the zer0-distribute prototype. The
    # rule names, messages and order are the extension's, so a finding reads the
    # same in the editor, the browser CMS and CI.
    #
    # Levels are a contract:
    #   error    blocks a publish (a person may force past it, never a script)
    #   warning  never blocks — it is an opinion about the writing
    #   info     never blocks; exactly one is always last: the fold preview
    #
    # The human reading the draft before approving it is the other half.
    module Guard
      FOLD = 140
      MAX_LEN = 3000

      Finding = Struct.new(:level, :message) do
        def error?
          level == "error"
        end

        def to_h
          { "level" => level, "message" => message }
        end
      end

      BANNED = [
        ["cutting-edge", /\bcutting[- ]edge\b/i],
        ["next-generation", /\bnext[- ]generation\b/i],
        ["disruptive", /\bdisruptive\b/i],
        ["revolutionary", /\brevolutionar(?:y|ies)\b/i],
        ["in today's ... world/age/era", /\bin\s+today[’']s\s+[^.\n]{0,40}?\b(world|age|era|landscape|climate|environment)\b/i],
        ["leverage synergies", /\bleverag\w*\s+synerg\w*/i],
        ["unlock value", /\bunlock(?:ing|s)?\s+value\b/i],
        ["best-of-breed", /\bbest[- ]of[- ]breed\b/i],
        ["world-class", /\bworld[- ]class\b/i],
        ["solutioning", /\bsolutioning\b/i],
        ["ideate", /\bideat(?:e|es|ed|ing|ion)\b/i],
        ["circle back", /\bcircl(?:e|ing)\s+back\b/i],
        ["low-hanging fruit", /\blow[- ]hanging\s+fruit\b/i]
      ].freeze

      FILLER = [
        [/\bgame[- ]chang(?:er|ing)\b/i, "game-changer"],
        [/\bcutting[- ]edge\b/i, "cutting-edge"],
        [/\bnext[- ]generation\b/i, "next-generation"],
        [/\brevolutionar(?:y|ies)\b/i, "revolutionary"],
        [/\bexcited to announce\b/i, "excited to announce"],
        [/\bthrilled to\b/i, "thrilled to"],
        [/\bhumbled\b/i, "humbled"],
        [/\bsynerg\w*/i, "synergy"],
        [/!{1,}/, "exclamation mark"]
      ].freeze

      module_function

      def check(text, extra: [])
        text = text.to_s
        findings = []
        errored = []

        findings << Finding.new("error", "commentary is #{text.length} chars (max #{MAX_LEN})") if text.length > MAX_LEN

        (BANNED + extra).each do |name, pattern|
          match = pattern.match(text)
          next unless match

          findings << Finding.new("error", "banned phrase \"#{match[0]}\" (#{name})")
          errored << name
        end

        findings << Finding.new("warning", "exclamation mark in commentary (house style: none)") if text.include?("!")

        FILLER.each do |pattern, name|
          next if name == "exclamation mark" || errored.include?(name)

          findings << Finding.new("warning", "reads as filler: #{name}") if pattern.match?(text)
        end

        first = text[0, FOLD].to_s
        if first.include?("\n") && first.split("\n", -1).first.to_s.length < 40
          findings << Finding.new("warning", "weak hook: the first line ends before it says anything")
        end

        findings << Finding.new("info", "fold at #{FOLD} chars: \"#{first}\"")
        findings
      end

      def errors?(findings)
        findings.any?(&:error?)
      end

      # `[{ "name": "…", "pattern": "…", "flags": "i" }]` — the extension's
      # banned-patterns file. Raises on anything malformed.
      def load_patterns(file)
        raw = Doctor::Jsonc.parse(File.read(file, encoding: "UTF-8"))
        raise ArgumentError, "banned-patterns file must be a JSON array: #{file}" unless raw.is_a?(Array)

        raw.each_with_index.map do |entry, index|
          unless entry.is_a?(Hash) && entry["name"].is_a?(String) && entry["pattern"].is_a?(String)
            raise ArgumentError, "banned-patterns entry #{index} needs string name and pattern: #{file}"
          end

          flags = entry.fetch("flags", "i").to_s
          options = (flags.include?("i") ? Regexp::IGNORECASE : 0) | (flags.include?("m") ? Regexp::MULTILINE : 0)
          [entry["name"], Regexp.new(entry["pattern"], options)]
        rescue RegexpError => e
          raise ArgumentError, "banned-patterns entry #{index} has an invalid pattern (#{e.message}): #{file}"
        end
      end

      # A broken addition never bricks the guard: any failure means no extra
      # rules, and the thirteen built-in bans still run.
      def patterns_for(config)
        return [] unless config.banned_patterns_file

        load_patterns(config.path(config.banned_patterns_file))
      rescue ArgumentError, SystemCallError, JSON::ParserError
        []
      end
    end
  end
end
