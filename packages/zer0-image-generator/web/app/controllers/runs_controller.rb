# frozen_string_literal: true

class RunsController < ApplicationController
  before_action :set_site, only: %i[index new create]
  before_action :set_run, only: %i[show cancel]

  def index
    @kind = params[:kind].to_s
    @status = params[:status].to_s
    @runs = @site ? @site.runs.recent : Run.recent.includes(:site)
    @runs = @runs.where(kind: @kind) if @kind.present? && Run::KINDS.include?(@kind)
    @runs = @runs.where(status: @status) if @status.present? && Run::STATUSES.include?(@status)
    @runs = @runs.limit(100)
  end

  def new
    @run = @site.runs.new(kind: params[:kind].presence || "dry_run")
    @scan = safe_scan
    @available_providers = EngineBridge.available_providers(run_environment)
  end

  def create
    @run = @site.runs.new(kind: run_kind, params: run_parameters)
    if @run.save
      GenerationJob.perform_later(@run.id)
      redirect_to run_path(@run), notice: "#{@run.kind} queued."
    else
      @scan = safe_scan
      @available_providers = EngineBridge.available_providers(run_environment)
      render :new, status: :unprocessable_entity
    end
  end

  def show
    @artifacts = @run.artifacts.order(:path)
  end

  # Cooperative cancel: flip the status; the running job's DbInterrupt notices
  # between files and stops scheduling new work. A pending job checks this
  # before it starts.
  def cancel
    @run.update!(status: "cancelled", finished_at: Time.current) unless @run.finished?
    redirect_to run_path(@run), notice: "Cancellation requested."
  end

  private

  def set_site
    @site = Site.find(params[:site_id]) if params[:site_id]
  end

  def set_run
    @run = Run.find(params[:id])
  end

  # dry_run / list_missing / generate / enhance — the mode the user picked.
  def run_kind
    kind = params.dig(:run, :kind).presence || "dry_run"
    Run::SITE_KINDS.include?(kind) ? kind : "dry_run"
  end

  def run_parameters
    permitted = params.fetch(:run, {}).permit(
      :force, :verbose, :file, :collection, :provider, :model, :style,
      :parallel, :batch, :prompt_engine, :review, :rasterizer
    ).to_h
    # Checkboxes arrive as "1"/"0"; store real booleans so the job's `present?`
    # checks read cleanly.
    %w[force verbose].each { |k| permitted[k] = ActiveModel::Type::Boolean.new.cast(permitted[k]) }
    permitted.reject { |_, v| v.nil? || v == "" }
  end

  def run_environment
    AiEnv.snapshot
  end

  def safe_scan
    SiteScanner.new(@site).call
  rescue SiteScanner::Error
    nil
  end
end
