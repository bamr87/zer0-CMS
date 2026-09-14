# frozen_string_literal: true

class SearchController < ApplicationController
  def show
    @q = params[:q].to_s.strip
    @hits = []
    return if @q.length < 2

    needle = @q.downcase
    Site.named.each do |site|
      site.catalog.entries.each do |entry|
        hay = "#{entry.title} #{entry.relative} #{entry.author} #{entry.description} #{entry.tags.join(" ")}"
        next unless hay.downcase.include?(needle)

        @hits << [site, entry]
        break if @hits.size >= 80
      end
      break if @hits.size >= 80
    end
  end
end
