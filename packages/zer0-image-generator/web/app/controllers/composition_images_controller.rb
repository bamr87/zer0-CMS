# frozen_string_literal: true

class CompositionImagesController < ApplicationController
  before_action :set_image

  # Queue an OpenAI enhance of this specific version.
  def enhance
    if @image.composition.working?
      return redirect_to(@image.composition, alert: "Already working.")
    end

    EnhanceJob.perform_later(@image.id, prompt: params[:prompt].presence)
    redirect_to @image.composition, notice: "Processing further with OpenAI…"
  end

  def favorite
    @image.update!(favorite: !@image.favorite)
    redirect_to @image.composition
  end

  private

  def set_image
    @image = CompositionImage.find(params[:id])
  end
end
