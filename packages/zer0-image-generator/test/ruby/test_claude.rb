# frozen_string_literal: true

# Unit + differential tests for the ported Claude layer (claude/client.rb and
# claude/orchestration.rb). Zero-network: the client takes an injectable HTTP
# transport (a Rails app fakes it the same way) and an injectable `which`, so
# credential detection never depends on whether the real `claude` binary is
# installed. The differential half shells out to python3 to prove the analyze +
# review PROMPT construction and _extract_json_object are byte/parse-identical;
# it skips cleanly without python3.
#
#     ruby -Ilib test/ruby/test_claude.rb

require "minitest/autorun"
require "json"
require "base64"
require "open3"
require "tmpdir"
require_relative "../../lib/zer0_image_generator/claude/client"
require_relative "../../lib/zer0_image_generator/claude/orchestration"
require_relative "../../lib/zer0_image_generator/settings"
require_relative "../../lib/zer0_image_generator/content"

module ClaudeTestHelpers
  M = Zer0ImageGenerator
  ORACLE_DIR = File.expand_path("../../lib/zer0_image_generator", __dir__)

  NO_CLI = ->(_program) { nil } # force the CLI fallback out of credential detection

  def python_available?
    out, status = Open3.capture2e("python3", "--version")
    status.success? && out.include?("Python 3")
  rescue StandardError
    false
  end

  def make_settings(**over)
    M::Settings.new(**over)
  end

  def make_content_file
    M::ContentFile.new(
      nil, "Auto-hide Navigation", "Smart nav bar that hides on scroll",
      "docs, features", nil, nil,
      "The top navigation bar gets out of the way while you read.", { "title" => "Auto-hide Navigation" }
    )
  end

  # Captures whatever json() payload the client hands the transport, and returns
  # a canned response (or raises). `handler` receives (url, payload, headers).
  class FakeTransport
    attr_reader :calls

    def initialize(&handler)
      @handler = handler
      @calls = []
    end

    def json(url, payload, headers, timeout: 900)
      @calls << { url: url, payload: Marshal.load(Marshal.dump(payload)), headers: headers, timeout: timeout }
      @handler.call(url, payload, headers)
    end
  end

  # Duck-typed stand-in for AnthropicClient in orchestration tests.
  class FakeClaude
    attr_reader :complete_calls, :vision_calls

    def initialize(text_reply: nil, vision_reply: nil, raise_exc: nil)
      @text_reply = text_reply
      @vision_reply = vision_reply
      @raise_exc = raise_exc
      @complete_calls = []
      @vision_calls = []
    end

    def available?
      true
    end

    def complete(system_text, user_text, model: nil, max_tokens: nil, effort: "")
      @complete_calls << [system_text, user_text, model]
      raise @raise_exc if @raise_exc

      @text_reply || ""
    end

    def complete_vision(system_text, user_text, image_path, model: nil, max_tokens: nil, effort: "")
      @vision_calls << [system_text, user_text, image_path, model]
      raise @raise_exc if @raise_exc

      @vision_reply || ""
    end
  end
end

class TestCredentialDetection < Minitest::Test
  include ClaudeTestHelpers

  def client(env)
    M::AnthropicClient.new(env, which: NO_CLI)
  end

  def test_oauth_token_mode_and_headers
    c = client({ "CLAUDE_CODE_OAUTH_TOKEN" => "sk-ant-oat01-x" })
    assert_equal "oauth", c.mode
    headers = c.headers
    assert_equal "Bearer sk-ant-oat01-x", headers["Authorization"]
    assert_equal M::OAUTH_BETA, headers["anthropic-beta"]
    assert_equal M::ANTHROPIC_VERSION, headers["anthropic-version"]
  end

  def test_auth_token_mode
    assert_equal "oauth", client({ "ANTHROPIC_AUTH_TOKEN" => "tok" }).mode
  end

  def test_api_key_mode_headers
    c = client({ "ANTHROPIC_API_KEY" => "sk-ant-api" })
    assert_equal "api_key", c.mode
    headers = c.headers
    assert_equal "sk-ant-api", headers["x-api-key"]
    refute headers.key?("Authorization")
    refute headers.key?("anthropic-beta")
  end

  def test_cli_fallback_mode
    c = M::AnthropicClient.new({}, which: ->(_) { "/usr/local/bin/claude" })
    assert_equal "cli", c.mode
  end

  def test_no_credentials
    c = client({})
    refute c.available?
    assert_nil c.mode
  end

  def test_precedence_oauth_over_api_key
    c = client({ "CLAUDE_CODE_OAUTH_TOKEN" => "oat", "ANTHROPIC_API_KEY" => "key" })
    assert_equal "oauth", c.mode
    assert_equal "oat", c.token
  end

  def test_empty_token_does_not_select_mode
    # docker/VS Code forward `-e KEY=` as empty strings; an empty token must not
    # win (Python's `if self.env.get(...)` truthiness gate).
    c = M::AnthropicClient.new({ "CLAUDE_CODE_OAUTH_TOKEN" => "", "ANTHROPIC_API_KEY" => "real" }, which: NO_CLI)
    assert_equal "api_key", c.mode
  end

  def test_describe_per_mode
    assert_equal "Anthropic API key", client({ "ANTHROPIC_API_KEY" => "k" }).describe
    assert_equal "none", client({}).describe
  end

  def test_headers_raise_in_cli_mode
    c = M::AnthropicClient.new({}, which: ->(_) { "/bin/claude" })
    assert_raises(RuntimeError) { c.headers }
  end
end

class TestComplete < Minitest::Test
  include ClaudeTestHelpers

  def oauth_client(transport)
    M::AnthropicClient.new({ "CLAUDE_CODE_OAUTH_TOKEN" => "tok" }, transport: transport, which: NO_CLI)
  end

  def api_client(transport)
    M::AnthropicClient.new({ "ANTHROPIC_API_KEY" => "k" }, transport: transport, which: NO_CLI)
  end

  def test_complete_payload_shape
    transport = FakeTransport.new do |_url, _payload, _headers|
      { "stop_reason" => "end_turn",
        "content" => [{ "type" => "thinking", "thinking" => "" },
                      { "type" => "text", "text" => "<svg/>" }] }
    end
    text = oauth_client(transport).complete("system-2", "user prompt")
    assert_equal "<svg/>", text
    payload = transport.calls[0][:payload]
    # Claude Code identity MUST be the first system block (the OAuth gate).
    assert_equal M::CLAUDE_CODE_SYSTEM_PROMPT, payload["system"][0]["text"]
    assert_equal "system-2", payload["system"][1]["text"]
    assert_equal M::DEFAULT_CLAUDE_MODEL, payload["model"]
    assert_equal({ "type" => "adaptive" }, payload["thinking"])
    assert_equal M::CLAUDE_MAX_TOKENS, payload["max_tokens"]
    assert_equal [{ "role" => "user", "content" => "user prompt" }], payload["messages"]
  end

  def test_oauth_sends_bearer_headers
    transport = FakeTransport.new { |_u, _p, _h| { "stop_reason" => "end_turn", "content" => [] } }
    oauth_client(transport).complete("s", "u")
    assert_equal "Bearer tok", transport.calls[0][:headers]["Authorization"]
    assert_equal M::OAUTH_BETA, transport.calls[0][:headers]["anthropic-beta"]
  end

  def test_effort_in_payload_and_default
    transport = FakeTransport.new { |_u, _p, _h| { "stop_reason" => "end_turn", "content" => [{ "type" => "text", "text" => "ok" }] } }
    c = oauth_client(transport)
    c.complete("s", "u", effort: "low")
    assert_equal({ "effort" => "low" }, transport.calls[0][:payload]["output_config"])
    c.complete("s", "u") # no effort → no output_config
    refute transport.calls[1][:payload].key?("output_config")
  end

  def test_api_key_mode_omits_claude_code_block
    transport = FakeTransport.new { |_u, _p, _h| { "stop_reason" => "end_turn", "content" => [{ "type" => "text", "text" => "ok" }] } }
    api_client(transport).complete("system-text", "u")
    system = transport.calls[0][:payload]["system"]
    assert_equal 1, system.length
    assert_equal "system-text", system[0]["text"]
    assert_equal "k", transport.calls[0][:headers]["x-api-key"]
  end

  def test_effort_stripped_on_400
    calls = []
    transport = FakeTransport.new do |url, payload, _headers|
      calls << payload.dup
      if payload.key?("output_config")
        raise M::HttpStatusError.new(400, '{"error": {"message": "output_config is not supported"}}', url)
      end

      { "stop_reason" => "end_turn", "content" => [{ "type" => "text", "text" => "ok" }] }
    end
    text = oauth_client(transport).complete("s", "u", effort: "low")
    assert_equal "ok", text
    assert_equal 2, calls.length
    refute calls[1].key?("output_config")
  end

  def test_thinking_stripped_on_400
    calls = []
    transport = FakeTransport.new do |url, payload, _headers|
      calls << payload.dup
      raise M::HttpStatusError.new(400, '{"error": {"message": "thinking is not supported"}}', url) if payload.key?("thinking")

      { "stop_reason" => "end_turn", "content" => [{ "type" => "text", "text" => "ok" }] }
    end
    assert_equal "ok", api_client(transport).complete("s", "u")
    assert_equal 2, calls.length
    refute calls[1].key?("thinking")
  end

  def test_refusal_raises
    transport = FakeTransport.new do |_u, _p, _h|
      { "stop_reason" => "refusal", "stop_details" => { "category" => "cyber" }, "content" => [] }
    end
    exc = assert_raises(M::ClaudeRefusal) { api_client(transport).complete("s", "u") }
    assert_equal "cyber", exc.category
  end

  def test_truncation_raises
    transport = FakeTransport.new do |_u, _p, _h|
      { "stop_reason" => "max_tokens", "content" => [{ "type" => "text", "text" => "<svg" }] }
    end
    exc = assert_raises(M::ClaudeTruncated) { api_client(transport).complete("s", "u") }
    assert_equal "<svg", exc.message # partial text carried as the message
  end

  def test_no_credential_complete_raises
    c = M::AnthropicClient.new({}, which: NO_CLI)
    assert_raises(RuntimeError) { c.complete("s", "u") }
  end

  def test_complete_vision_api_payload
    transport = FakeTransport.new { |_u, _p, _h| { "stop_reason" => "end_turn", "content" => [{ "type" => "text", "text" => "{}" }] } }
    Dir.mktmpdir do |tmp|
      img = File.join(tmp, "x.png")
      File.binwrite(img, "PNGBYTES")
      api_client(transport).complete_vision("sys", "user", img)
    end
    content = transport.calls[0][:payload]["messages"][0]["content"]
    assert_equal "image", content[0]["type"]
    assert_equal "image/png", content[0]["source"]["media_type"]
    assert_equal "base64", content[0]["source"]["type"]
    assert_equal Base64.strict_encode64("PNGBYTES"), content[0]["source"]["data"]
    assert_equal "user", content[1]["text"]
    assert_equal 1, transport.calls[0][:payload]["system"].length # api_key: no identity block
  end

  def test_complete_vision_oauth_prepends_identity_block
    transport = FakeTransport.new { |_u, _p, _h| { "stop_reason" => "end_turn", "content" => [{ "type" => "text", "text" => "{}" }] } }
    Dir.mktmpdir do |tmp|
      img = File.join(tmp, "x.png")
      File.binwrite(img, "PNG")
      oauth_client(transport).complete_vision("sys", "user", img)
    end
    system = transport.calls[0][:payload]["system"]
    assert_equal M::CLAUDE_CODE_SYSTEM_PROMPT, system[0]["text"]
    assert_equal "sys", system[1]["text"]
  end
end

class TestOrchestration < Minitest::Test
  include ClaudeTestHelpers

  def test_claude_model_for_default_and_override
    assert_equal M::DEFAULT_CLAUDE_MODEL, M::Orchestration.claude_model_for(make_settings)
    assert_equal "claude-sonnet-5-5", M::Orchestration.claude_model_for(make_settings(claude_model: "claude-sonnet-5-5"))
  end

  def test_article_brief_uses_art_director_and_context
    client = FakeClaude.new(text_reply: "A pixel-art nav bar sliding away.")
    brief = M::Orchestration.claude_article_brief(client, make_content_file, make_settings, "base")
    assert_equal "A pixel-art nav bar sliding away.", brief
    system, user, model = client.complete_calls[0]
    assert_equal M::ART_DIRECTOR_SYSTEM, system
    assert_includes user, "Auto-hide Navigation"
    assert_includes user, "hides on scroll"
    assert_equal M::DEFAULT_CLAUDE_MODEL, model
  end

  def test_article_brief_falls_back_on_failure
    client = FakeClaude.new(raise_exc: RuntimeError.new("boom"))
    assert_equal "base", M::Orchestration.claude_article_brief(client, make_content_file, make_settings, "base")
  end

  def test_article_brief_empty_reply_falls_back
    client = FakeClaude.new(text_reply: "   ")
    assert_equal "base", M::Orchestration.claude_article_brief(client, make_content_file, make_settings, "base")
  end

  def test_claude_model_setting_respected
    client = FakeClaude.new(text_reply: "brief")
    M::Orchestration.claude_article_brief(client, make_content_file, make_settings(claude_model: "claude-sonnet-5-5"), "base")
    assert_equal "claude-sonnet-5-5", client.complete_calls[0][2]
  end

  def test_review_approve
    client = FakeClaude.new(vision_reply: '{"verdict": "approve", "critique": "good", "revised_prompt": ""}')
    approved, _critique, revised = M::Orchestration.claude_review_image(client, "x.png", make_content_file, "prompt", make_settings)
    assert approved
    assert_equal "", revised
    assert_equal M::REVIEWER_SYSTEM, client.vision_calls[0][0]
  end

  def test_review_revise_with_prose_wrapped_json
    client = FakeClaude.new(
      vision_reply: 'noise {"verdict": "revise", "critique": "wrong subject", "revised_prompt": "better prompt"} trailing'
    )
    approved, critique, revised = M::Orchestration.claude_review_image(client, "x.png", make_content_file, "prompt", make_settings)
    refute approved
    assert_equal "better prompt", revised
    assert_equal "wrong subject", critique
  end

  def test_review_garbage_counts_as_approval
    client = FakeClaude.new(vision_reply: "I like it a lot!")
    approved, _critique, revised = M::Orchestration.claude_review_image(client, "x.png", make_content_file, "prompt", make_settings)
    assert approved
    assert_equal "", revised
  end

  def test_review_failure_counts_as_approval
    client = FakeClaude.new(raise_exc: RuntimeError.new("api down"))
    approved, = M::Orchestration.claude_review_image(client, "x.png", make_content_file, "prompt", make_settings)
    assert approved
  end

  def test_review_revise_without_revised_prompt_stays_approved
    # verdict "revise" but no replacement prompt → keep the image (Python guard).
    client = FakeClaude.new(vision_reply: '{"verdict": "revise", "critique": "meh", "revised_prompt": ""}')
    approved, = M::Orchestration.claude_review_image(client, "x.png", make_content_file, "prompt", make_settings)
    assert approved
  end

  def test_extract_json_object_basic
    assert_equal({ "a" => 1 }, M::Orchestration.extract_json_object('x {"a": 1} y'))
    assert_nil M::Orchestration.extract_json_object("no json")
    assert_nil M::Orchestration.extract_json_object("{broken")
  end

  # Messy inputs the reviewer might emit despite the "JSON only" instruction.
  MESSY_INPUTS = [
    'x {"a": 1} y',
    "no json",
    "{broken",
    "```json\n{\"verdict\": \"approve\"}\n```",
    "Here is my verdict:\n{\"verdict\": \"revise\", \"revised_prompt\": \"x\"}\nThanks!",
    '{"outer": {"inner": {"deep": 1}}, "b": 2}',
    "prefix {\"a\": [1, 2, {\"b\": 3}]} suffix",
    "{}",
    "[]",
    "{not: valid}",
    'garbage } {"late": true} {',
    ""
  ].freeze

  def test_extract_json_object_matches_python_oracle
    skip "python3 unavailable" unless python_available?

    ruby = MESSY_INPUTS.map { |s| M::Orchestration.extract_json_object(s) }
    python = python_extract(MESSY_INPUTS)
    # Compare the whole arrays at once: Minitest 6 forbids assert_equal with a
    # nil expected, but nil ELEMENTS inside an array compare fine.
    assert_equal python, ruby,
                 "extract_json_object disagreed; per-input: " \
                 "#{MESSY_INPUTS.zip(python, ruby).reject { |_, p, r| p == r }.inspect}"
  end

  # Prove the analyze + review PROMPT strings the client would send are built
  # byte-for-byte like the oracle (whitespace collapse, `or '(none)'`, the
  # "; modifiers" join), across tricky inputs.
  PROMPT_CASES = [
    { title: "Auto-hide Navigation", description: "Smart nav bar that hides on scroll",
      categories: "docs, features",
      content: "The top   navigation\tbar\n\ngets  out of the way while you read.",
      style: "retro pixel art", style_modifiers: "CRT glow" },
    { title: "Empty Bits", description: "", categories: "",
      content: "", style: "flat vector", style_modifiers: "" },
    { title: "Unicode café", description: "naïve façade", categories: "art",
      content: "  leading and   trailing  \n", style: "impressionist", style_modifiers: "soft" }
  ].freeze

  def test_prompt_construction_matches_python_oracle
    skip "python3 unavailable" unless python_available?

    PROMPT_CASES.each do |c|
      settings = make_settings(style: c[:style], style_modifiers: c[:style_modifiers])
      cf = M::ContentFile.new(nil, c[:title], c[:description], c[:categories], nil, nil, c[:content], {})

      brief_client = FakeClaude.new(text_reply: "BRIEF")
      M::Orchestration.claude_article_brief(brief_client, cf, settings, "base")
      ruby_article = brief_client.complete_calls[0][1]

      review_client = FakeClaude.new(vision_reply: '{"verdict": "approve"}')
      M::Orchestration.claude_review_image(review_client, "x.png", cf, "the prompt", settings)
      ruby_context = review_client.vision_calls[0][1]

      py = python_prompts(c)
      assert_equal py["article"], ruby_article, "article prompt for #{c[:title].inspect}"
      assert_equal py["context"], ruby_context, "review context for #{c[:title].inspect}"
    end
  end

  private

  def python_extract(inputs)
    out, status = Open3.capture2("python3", "-c", EXTRACT_DRIVER, ORACLE_DIR, stdin_data: JSON.generate(inputs))
    raise "python driver failed: #{out}" unless status.success?

    JSON.parse(out)
  end

  def python_prompts(kase)
    out, status = Open3.capture2("python3", "-c", PROMPT_DRIVER, ORACLE_DIR, stdin_data: JSON.generate(kase))
    raise "python driver failed: #{out}" unless status.success?

    JSON.parse(out)
  end

  EXTRACT_DRIVER = <<~'PYSRC'
    import sys, json
    sys.path.insert(0, sys.argv[1])
    import preview_generator as pg
    inputs = json.load(sys.stdin)
    print(json.dumps([pg._extract_json_object(s) for s in inputs]))
  PYSRC

  # A capturing fake client records exactly the user/context string the real
  # orchestration functions build, without any network or image read.
  PROMPT_DRIVER = <<~'PYSRC'
    import sys, json
    from pathlib import Path
    sys.path.insert(0, sys.argv[1])
    import preview_generator as pg

    req = json.load(sys.stdin)
    cf = pg.ContentFile(path=Path("x"), title=req["title"], description=req["description"],
                        categories=req["categories"], preview=None, author=None,
                        content=req["content"], front_matter={})
    settings = pg.Settings(style=req["style"], style_modifiers=req["style_modifiers"])

    class Cap:
        def __init__(self):
            self.article = None
            self.context = None
        def complete(self, system, user, model=None, max_tokens=None, effort=""):
            self.article = user
            return "BRIEF"
        def complete_vision(self, system, user, image_path, model=None, max_tokens=None, effort=""):
            self.context = user
            return '{"verdict": "approve"}'

    cap = Cap()
    pg.claude_article_brief(cap, cf, settings, "base")
    pg.claude_review_image(cap, Path("x.png"), cf, "the prompt", settings)
    print(json.dumps({"article": cap.article, "context": cap.context}))
  PYSRC
end
