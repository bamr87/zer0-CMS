# frozen_string_literal: true

class CompositionsController < ApplicationController
  before_action :set_composition, only: %i[show destroy compose]

  def index
    @compositions = Composition.recent.limit(50)
  end

  def new
    EngineBridge.load!
    @composition = Composition.new(
      provider: "local", prompt_engine: "claude", review_engine: "claude",
      style: Zer0ImageGenerator::DEFAULTS["style"]
    )
    @claude_available = Credential.claude_available?(run_env)
    @xai_available = Credential.xai_available?(run_env)
    @available_providers = EngineBridge.available_providers(run_env)
  rescue EngineBridge::Error
    @composition ||= Composition.new(provider: "local", prompt_engine: "claude", review_engine: "claude")
    @claude_available = Credential.claude_available?(run_env)
    @xai_available = Credential.xai_available?(run_env)
    @available_providers = ["local"]
  end

  def show
    @claude_available = Credential.claude_available?(run_env)
    @xai_available = Credential.xai_available?(run_env)
    @openai_available = run_env["OPENAI_API_KEY"].present?
  end

  def create
    @composition = Composition.new(composition_params.merge(status: "draft"))
    if @composition.save
      ComposeJob.perform_later(@composition.id)
      redirect_to @composition, notice: "Creating your image…"
    else
      @claude_available = Credential.claude_available?(run_env)
      @xai_available = Credential.xai_available?(run_env)
      @available_providers = EngineBridge.available_providers(run_env)
      render :new, status: :unprocessable_entity
    end
  end

  # Regenerate: re-run the pipeline (a fresh render + review) on the same brief.
  def compose
    return redirect_to(@composition, alert: "Already working.") if @composition.working?

    ComposeJob.perform_later(@composition.id)
    redirect_to @composition, notice: "Regenerating…"
  end

  def destroy
    @composition.destroy
    redirect_to compositions_path, notice: "Composition deleted."
  end

  private

  def set_composition
    @composition = Composition.find(params[:id])
  end

  def composition_params
    params.require(:composition).permit(
      :title, :brief, :style, :style_modifiers, :provider, :model, :size,
      :quality, :prompt_engine, :review_engine
    )
  end

  def run_env
    @run_env ||= AiEnv.snapshot
  end
end
