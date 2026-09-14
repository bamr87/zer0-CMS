# frozen_string_literal: true

class FilesController < ApplicationController
  skip_before_action :load_nav

  IMAGE_TYPES = {
    ".png" => "image/png", ".svg" => "image/svg+xml",
    ".jpg" => "image/jpeg", ".jpeg" => "image/jpeg", ".webp" => "image/webp"
  }.freeze

  def show
    requested = Pathname.new("/#{params[:path]}").cleanpath
    real = requested.exist? ? requested.realpath : nil
    return head(:not_found) unless real&.file?
    return head(:forbidden) unless allowed?(real)

    ext = real.extname.downcase
    return head(:unsupported_media_type) unless IMAGE_TYPES.key?(ext)

    send_file real.to_s, type: IMAGE_TYPES[ext], disposition: "inline"
  rescue SystemCallError
    head :not_found
  end

  private

  def allowed?(real)
    Site.pluck(:path).filter_map { |p|
      Pathname.new(p).realpath
    rescue SystemCallError
      nil
    }.any? { |root| real.to_s == root.to_s || real.to_s.start_with?("#{root}/") }
  end
end
