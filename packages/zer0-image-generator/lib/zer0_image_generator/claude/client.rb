# frozen_string_literal: true

require "base64"
require "open3"
require "timeout"

require_relative "../constants"
require_relative "../http"
require_relative "../logging"

module Zer0ImageGenerator
  # Claude declined the request (Anthropic `stop_reason == "refusal"`). Carries
  # the refusal category so callers can surface an actionable message rather
  # than a generic failure.
  class ClaudeRefusal < StandardError
    attr_reader :category

    def initialize(category)
      @category = category
      # `category or 'unspecified'`: both nil and "" degrade to "unspecified".
      label = category.nil? || category == "" ? "unspecified" : category
      super("request declined (category: #{label})")
    end
  end

  # Claude hit the max_tokens ceiling mid-answer (`stop_reason == "max_tokens"`).
  # Distinct from a refusal so the runner can retry with a smaller ask instead
  # of giving up. The partial text is carried as the message.
  class ClaudeTruncated < StandardError; end

  # Minimal Messages-API client honoring the repo's credential conventions.
  #
  # Modes (first match wins — mirrors templates/deploy/chat-proxy/worker.js):
  #   oauth    CLAUDE_CODE_OAUTH_TOKEN or ANTHROPIC_AUTH_TOKEN -> Bearer +
  #            `anthropic-beta: oauth-2025-04-20` + Claude Code first system block
  #   api_key  ANTHROPIC_API_KEY -> x-api-key header
  #   cli      `claude -p` headless (rides the local Claude Code login)
  #
  # `transport` is an injectable HTTP seam (defaults to the Http module); it must
  # respond to `json(url, payload, headers, timeout:)`. `which` resolves an
  # executable on PATH and is injectable so tests need not depend on whether the
  # real `claude` binary is installed.
  class AnthropicClient
    attr_reader :mode, :token

    def initialize(env = nil, transport: nil, which: nil)
      # `dict(env if env is not None else os.environ)` — a snapshot, not a view.
      @env = env.nil? ? ENV.to_h : env.to_h
      @transport = transport || Http
      @which = which || method(:default_which)
      @mode = nil
      @token = nil

      if present?(@env["CLAUDE_CODE_OAUTH_TOKEN"])
        @mode = "oauth"
        @token = @env["CLAUDE_CODE_OAUTH_TOKEN"]
      elsif present?(@env["ANTHROPIC_AUTH_TOKEN"])
        @mode = "oauth"
        @token = @env["ANTHROPIC_AUTH_TOKEN"]
      elsif present?(@env["ANTHROPIC_API_KEY"])
        @mode = "api_key"
        @token = @env["ANTHROPIC_API_KEY"]
      elsif @which.call("claude")
        @mode = "cli"
      end
    end

    def available?
      !@mode.nil?
    end

    def describe
      {
        "oauth" => "Claude Code OAuth token (Bearer)",
        "api_key" => "Anthropic API key",
        "cli" => "claude CLI (local Claude Code login)",
        nil => "none"
      }[@mode]
    end

    def headers
      case @mode
      when "oauth"
        {
          "Authorization" => "Bearer #{@token}",
          "anthropic-version" => ANTHROPIC_VERSION,
          "anthropic-beta" => OAUTH_BETA
        }
      when "api_key"
        {
          "x-api-key" => @token.to_s,
          "anthropic-version" => ANTHROPIC_VERSION
        }
      else
        raise "no API headers for mode #{@mode}"
      end
    end

    # One Messages-API turn (or CLI run); returns concatenated text blocks.
    # Raises ClaudeRefusal / ClaudeTruncated / HttpStatusError / RuntimeError.
    def complete(system_text, user_text, model: DEFAULT_CLAUDE_MODEL,
                 max_tokens: CLAUDE_MAX_TOKENS, effort: "")
      return complete_cli(system_text, user_text, model) if @mode == "cli"
      raise "no Anthropic credential configured" if @mode.nil?

      payload = {
        "model" => model,
        "max_tokens" => max_tokens,
        "thinking" => { "type" => "adaptive" },
        "system" => system_blocks(system_text),
        "messages" => [{ "role" => "user", "content" => user_text }]
      }
      payload["output_config"] = { "effort" => effort } unless effort.to_s.empty?

      begin
        data = api_call(payload, "Anthropic API")
      rescue HttpStatusError => e
        message = e.status == 400 ? e.error_message.downcase : ""
        if e.status == 400 && (message.include?("output_config") || message.include?("effort"))
          Logging.debug("Retrying without output_config parameter")
          payload.delete("output_config")
          data = api_call(payload, "Anthropic API")
        elsif e.status == 400 && message.include?("thinking")
          Logging.debug("Retrying without thinking parameter")
          payload.delete("thinking")
          data = api_call(payload, "Anthropic API")
        elsif e.status == 401 && @mode == "oauth"
          raise "Anthropic rejected the OAuth token (401). It may be expired " \
                "— mint a fresh one with `claude setup-token`, or use " \
                "ANTHROPIC_API_KEY instead."
        else
          raise
        end
      end

      stop_reason = data["stop_reason"]
      if stop_reason == "refusal"
        details = data["stop_details"] || {}
        raise ClaudeRefusal.new(details.is_a?(Hash) ? details["category"] : nil)
      end

      text = join_text(data)
      raise ClaudeTruncated, text if stop_reason == "max_tokens"

      text
    end

    # One vision turn over a local PNG (review stage). CLI mode passes the file
    # path and lets `claude -p` read it; API modes embed base64.
    def complete_vision(system_text, user_text, image_path, model: DEFAULT_CLAUDE_MODEL,
                        max_tokens: 2048, effort: "")
      if @mode == "cli"
        prompt = "#{system_text}\n\n---\n\nFirst use the Read tool to view the " \
                 "image file at #{File.expand_path(image_path.to_s)} — then respond.\n\n#{user_text}"
        return run_cli(prompt, model, allowed_tools: "Read")
      end
      raise "no Anthropic credential configured" if @mode.nil?

      image_bytes = File.binread(image_path.to_s)
      payload = {
        "model" => model,
        "max_tokens" => max_tokens,
        "thinking" => { "type" => "adaptive" },
        "system" => system_blocks(system_text),
        "messages" => [{
          "role" => "user",
          "content" => [
            { "type" => "image", "source" => {
              "type" => "base64", "media_type" => Zer0ImageGenerator.image_media_type(image_bytes),
              "data" => Base64.strict_encode64(image_bytes)
            } },
            { "type" => "text", "text" => user_text }
          ]
        }]
      }
      payload["output_config"] = { "effort" => effort } unless effort.to_s.empty?

      begin
        data = api_call(payload, "Anthropic API (review)")
      rescue HttpStatusError => e
        message = e.status == 400 ? e.error_message.downcase : ""
        if e.status == 400 && (message.include?("output_config") || message.include?("effort"))
          Logging.debug("Retrying review without output_config parameter")
          payload.delete("output_config")
          data = api_call(payload, "Anthropic API (review)")
        else
          raise
        end
      end

      if data["stop_reason"] == "refusal"
        details = data["stop_details"] || {}
        raise ClaudeRefusal.new(details.is_a?(Hash) ? details["category"] : nil)
      end
      join_text(data)
    end

    private

    # The Claude Code identity block is REQUIRED as the first system block for
    # OAuth tokens (worker.js recipe) and intentionally omitted for plain API
    # keys, matching the chat proxy's per-mode behavior.
    def system_blocks(system_text)
      blocks = [{ "type" => "text", "text" => system_text }]
      blocks.unshift({ "type" => "text", "text" => CLAUDE_CODE_SYSTEM_PROMPT }) if @mode == "oauth"
      blocks
    end

    def api_call(payload, what)
      Http.with_retries(what) do
        @transport.json(ANTHROPIC_API_URL, payload, headers, timeout: 900)
      end
    end

    def join_text(data)
      (data["content"] || [])
        .select { |block| block.is_a?(Hash) && block["type"] == "text" }
        .map { |block| block["text"] || "" }
        .join
    end

    def complete_cli(system_text, user_text, model)
      run_cli("#{system_text}\n\n---\n\n#{user_text}", model)
    end

    def run_cli(prompt, model, allowed_tools: nil)
      cmd = ["claude", "-p", "--model", model, "--output-format", "text"]
      cmd += ["--allowedTools", allowed_tools] if allowed_tools
      begin
        stdout, stderr, status = capture_cli(cmd, prompt, 300)
      rescue SystemCallError, Timeout::Error => e
        # Python catches (OSError, subprocess.TimeoutExpired) → RuntimeError.
        raise "claude CLI failed: #{e}"
      end
      if !status.success? || stdout.strip.empty?
        stripped = (stderr || "").strip
        tail = stripped.length > 300 ? stripped[-300..] : stripped
        raise "claude CLI exited #{status.exitstatus}: #{tail.empty? ? 'no output' : tail}"
      end
      stdout
    end

    # subprocess.run(input=..., capture_output=True, text=True, timeout=300):
    # feed stdin, drain stdout+stderr concurrently (a single sequential read can
    # deadlock when the child fills the other pipe), and kill on timeout.
    def capture_cli(cmd, input, seconds)
      Open3.popen3(*cmd) do |stdin, stdout, stderr, wait_thr|
        out_reader = Thread.new { stdout.read }
        err_reader = Thread.new { stderr.read }
        begin
          Timeout.timeout(seconds) do
            stdin.write(input)
            stdin.close
            [out_reader.value, err_reader.value, wait_thr.value]
          end
        rescue Timeout::Error
          Process.kill("KILL", wait_thr.pid)
          wait_thr.join
          raise
        end
      end
    end

    def present?(value)
      !value.nil? && value != ""
    end

    # shutil.which("claude"): search the real PATH for an executable, returning
    # its path or nil. Reads the process environment (not @env) to match Python,
    # whose shutil.which consults os.environ regardless of the client's env dict.
    def default_which(program)
      (ENV["PATH"] || "").split(File::PATH_SEPARATOR).each do |dir|
        next if dir.empty?

        candidate = File.join(dir, program)
        return candidate if File.file?(candidate) && File.executable?(candidate)
      end
      nil
    end
  end

  # The 4-step credential chain, spelled out for the human when no Claude
  # credential is configured. Precedence matches AnthropicClient's detection.
  CLAUDE_CREDENTIAL_HINT =
    "Claude orchestration (article analysis + image review) needs any ONE of:\n" \
    "  1. CLAUDE_CODE_OAUTH_TOKEN   — run `claude setup-token` (Claude Pro/Max)\n" \
    "  2. ANTHROPIC_AUTH_TOKEN      — short-lived Bearer (e.g. `ant auth print-credentials`)\n" \
    "  3. ANTHROPIC_API_KEY         — key from console.anthropic.com\n" \
    "  4. the `claude` CLI installed and logged in (used automatically)\n" \
    "Falling back to the template prompt and skipping review (or pass " \
    "--prompt-engine template --review none to silence this)."
end
