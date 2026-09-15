# frozen_string_literal: true

module Admin
  # LinkedIn distribution for the registered sites: the queue, the exact
  # payload each draft would send, approval, publishing and statistics.
  #
  # Every action runs Zer0Cms::Distribution::Pipeline — the same code the CLI,
  # the reusable workflow and the MCP server run — against the site's files.
  # The page renders the pipeline's blockers so a person can see why a button
  # is disabled, but the button is a courtesy: `approve` and `publish`
  # re-read the draft from disk and re-run every gate before they act, and a
  # live publish additionally needs ZER0_LINKEDIN_PUBLISH=1 in the server's
  # environment, which nothing in a request or a repository can set.
  class DistributionController < ::ApplicationController
    before_action :load_site, except: :index
    rescue_from Zer0Cms::Distribution::ConfigError, Zer0Cms::Cms::UnsafePath, with: :config_problem

    def index
      @rows = Site.named.map do |site|
        [site, LinkedinGateway.pipeline(site).status]
      rescue Zer0Cms::Distribution::ConfigError, Zer0Cms::Cms::UnsafePath => e
        [site, { "errors" => [e.message] }]
      end
    end

    def show
      @pipeline = LinkedinGateway.pipeline(@site)
      @config = @pipeline.config
      @status = @pipeline.status
      @previews = @pipeline.drafts.map { |draft| @pipeline.preview(draft) }
      @sources = @pipeline.sources
      @pages = @site.pages.where(relative: @sources.map { |s| s.entry.relative }).index_by(&:relative)
      @performance = Zer0Cms::Distribution::Analytics.load(@config)
      @channel = LinkedinGateway.channel_for(@site, @config)
    end

    def draft
      @pipeline = LinkedinGateway.pipeline(@site)
      @config = @pipeline.config
      @draft = @pipeline.draft(params[:draft])
      @preview = @pipeline.preview(@draft)
    rescue ArgumentError => e
      redirect_to admin_distribution_site_path(@site), alert: e.message, status: :see_other
    end

    def create_draft
      page = @site.pages.find(params.require(:page_id))
      draft = LinkedinGateway.pipeline(@site).compose(page.relative, commentary: params[:commentary].presence)
      redirect_to admin_distribution_draft_path(@site, draft.id), status: :see_other,
                                                                  notice: "Drafted #{draft.relative}. It is pending until a person approves it."
    rescue ArgumentError => e
      redirect_back_or_to admin_distribution_site_path(@site), alert: e.message, status: :see_other
    end

    def approve
      pipeline = LinkedinGateway.pipeline(@site)
      outcome = pipeline.approve(pipeline.draft(params[:draft]))
      finish(outcome)
    rescue ArgumentError => e
      redirect_to admin_distribution_site_path(@site), alert: e.message, status: :see_other
    end

    def publish
      pipeline = LinkedinGateway.pipeline(@site)
      draft = pipeline.draft(params[:draft])
      unless params[:confirm] == "1"
        return redirect_to admin_distribution_draft_path(@site, draft.id), status: :see_other,
                                                                           alert: "Tick the confirmation to publish this draft to LinkedIn."
      end

      finish(pipeline.publish(draft, live: true))
    rescue ArgumentError => e
      redirect_to admin_distribution_site_path(@site), alert: e.message, status: :see_other
    end

    def statistics
      result = LinkedinGateway.pipeline(@site).statistics(write: true)
      redirect_to admin_distribution_site_path(@site), status: :see_other,
                                                       notice: "Read statistics for #{result[:matched].size} post(s) into #{result[:path]}."
    rescue Zer0Cms::LinkedIn::Error => e
      redirect_to admin_distribution_site_path(@site), alert: "LinkedIn: #{e.message}", status: :see_other
    end

    private

    def load_site
      @site = Site.find(params[:site_id])
    end

    def finish(outcome)
      message = "#{outcome.state.to_s.capitalize}: #{outcome.messages.join(" · ")}"
      target = outcome.draft ? admin_distribution_draft_path(@site, outcome.draft.id) : admin_distribution_site_path(@site)
      if outcome.ok?
        redirect_to target, notice: message, status: :see_other
      else
        redirect_to target, alert: message, status: :see_other
      end
    end

    def config_problem(error)
      redirect_to admin_distribution_path, alert: "#{@site&.name}: #{error.message}", status: :see_other
    end
  end
end
