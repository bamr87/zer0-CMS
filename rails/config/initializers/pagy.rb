# frozen_string_literal: true

require "pagy"
require "pagy/extras/array"
require "pagy/extras/overflow"

Pagy::DEFAULT[:limit] = 40
Pagy::DEFAULT[:overflow] = :last_page
