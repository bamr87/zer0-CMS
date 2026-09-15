# frozen_string_literal: true

# Kept out of the logs: credentials, and the OAuth callback's single-use
# `code` and `state` (partial matches, as Rails applies them).
Rails.application.config.filter_parameters += %i[
  passw email secret token _key crypt salt certificate otp code state
]
