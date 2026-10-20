# frozen_string_literal: true

class CredentialsController < ApplicationController
  before_action :set_credential, only: %i[edit update destroy]

  def index
    stored = Credential.all.index_by(&:provider)
    # Show every provider slot, filled or not, so the page doubles as a
    # checklist of what the app can currently render with.
    @rows = Credential::PROVIDERS.map do |provider|
      { provider: provider, credential: stored[provider], from_env: ENV[Credential::ENV_VARS[provider]].present? }
    end
  end

  def new
    @credential = Credential.new(provider: params[:provider])
  end

  def edit; end

  def create
    @credential = Credential.new(credential_params)
    if @credential.save
      redirect_to credentials_path, notice: "#{@credential.provider} key stored (encrypted)."
    else
      render :new, status: :unprocessable_entity
    end
  end

  def update
    # A blank key field on the edit form means "keep the current key", not
    # "clear it" — drop it so the encrypted value survives a label-only edit.
    attrs = credential_params
    attrs = attrs.except(:api_key) if attrs[:api_key].blank?
    if @credential.update(attrs)
      redirect_to credentials_path, notice: "#{@credential.provider} key updated."
    else
      render :edit, status: :unprocessable_entity
    end
  end

  def destroy
    @credential.destroy
    redirect_to credentials_path, notice: "#{@credential.provider} key removed."
  end

  private

  def set_credential
    @credential = Credential.find(params[:id])
  end

  def credential_params
    params.require(:credential).permit(:provider, :label, :api_key)
  end
end
