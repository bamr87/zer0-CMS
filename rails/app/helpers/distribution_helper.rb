# frozen_string_literal: true

# Presentation for the distribution pages. Tones reuse the state badge
# palette the pages index already has, so no new colours enter the theme.
module DistributionHelper
  TONES = { ok: "live", warn: "draft", err: "error", info: "future" }.freeze

  def distribution_badge(text, tone)
    content_tag(:span, text, class: "badge state-#{TONES.fetch(tone)}")
  end

  def version_tone(status)
    { "ok" => :ok, "aging" => :warn }.fetch(status.to_s, :err)
  end

  def draft_tone(status)
    { "published" => :ok, "approved" => :info, "pending" => :warn }.fetch(status.to_s, :err)
  end

  def finding_tone(level)
    { "error" => :err, "warning" => :warn }.fetch(level.to_s, :info)
  end

  # The commentary split where LinkedIn folds it behind "…see more".
  def fold_split(text)
    fold = Zer0Cms::Distribution::Guard::FOLD
    [text.to_s[0, fold].to_s, text.to_s[fold..].to_s]
  end

  def linkedin_post_link(urn)
    link_to urn, Zer0Cms::LinkedIn::Posts.feed_url(urn), target: "_blank", rel: "noopener noreferrer", class: "mono"
  end

  def publish_armed?
    Zer0Cms::Distribution::Config::TRUTHY.include?(ENV[Zer0Cms::Distribution::Config::ARM_VARIABLE].to_s.strip.downcase)
  end
end
