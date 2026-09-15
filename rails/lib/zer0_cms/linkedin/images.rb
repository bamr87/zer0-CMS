# frozen_string_literal: true

module Zer0Cms
  module LinkedIn
    # A link card's thumbnail through the Images API: reserve an upload, send
    # the bytes to the signed slot, then — best effort — wait for processing.
    #
    # LinkedIn accepts JPG, GIF and PNG under 36,152,320 pixels. An SVG preview
    # (which some zer0 sites draw) is not uploadable, and `uploadable?` says so
    # before any call, so the publisher can post without a card image and say
    # why rather than fail the post.
    module Images
      TYPES = { ".png" => "image/png", ".jpg" => "image/jpeg", ".jpeg" => "image/jpeg", ".gif" => "image/gif" }.freeze
      MAX_BYTES = 20 * 1024 * 1024

      module_function

      # [true, nil] or [false, reason].
      def uploadable?(path)
        ext = File.extname(path.to_s).downcase
        return [false, "#{File.basename(path.to_s)}: LinkedIn takes PNG, JPG or GIF, not #{ext.empty? ? "this file" : ext}"] unless TYPES.key?(ext)
        return [false, "#{path} does not exist"] unless File.file?(path.to_s)
        return [false, "#{File.basename(path.to_s)} is over #{MAX_BYTES / 1024 / 1024} MB"] if File.size(path.to_s) > MAX_BYTES

        [true, nil]
      end

      def upload(client, owner:, path:, sleeper: ->(seconds) { sleep(seconds) }, polls: 3)
        ok, reason = uploadable?(path)
        raise Error, reason unless ok
        raise ArgumentError, "image owner must be an organization or person URN" unless LinkedIn.author_type(owner)

        value = client.json(:images_initialize, query: [["action", "initializeUpload"]],
                                                json: { "initializeUploadRequest" => { "owner" => owner } })["value"] || {}
        upload_url = value["uploadUrl"].to_s
        urn = value["image"].to_s
        raise Error, "initializeUpload returned no uploadUrl or image URN" if upload_url.empty? || urn.empty?

        client.request(:images_upload, url: upload_url, raw: File.binread(path.to_s),
                                       content_type: TYPES.fetch(File.extname(path.to_s).downcase))
        wait_available(client, urn, sleeper, polls)
        urn
      end

      # The URN is usable in an article card while it processes, so this never
      # fails the publish: a status it cannot read ends the wait.
      def wait_available(client, urn, sleeper, polls)
        polls.times do
          status = client.json(:images_get, path: { urn: urn })["status"]
          return status if status.nil? || status == "AVAILABLE" || status == "PROCESSING_FAILED"

          sleeper.call(2)
        end
        nil
      rescue Error
        nil
      end
    end
  end
end
