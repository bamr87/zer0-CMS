# frozen_string_literal: true

require "uri"

module Zer0Cms
  module LinkedIn
    # Posts: the payloads (pure) and the four calls that act on them.
    #
    # Two shapes are built, both organic and public on the main feed:
    #
    # * a text update — `commentary` only;
    # * an article share — `commentary` above a link card. LinkedIn does not
    #   scrape the URL, so the card's title, description and thumbnail travel in
    #   the payload, and the thumbnail is an image URN uploaded first.
    #
    # `commentary` is escaped to the little text format here, so a payload is
    # always what LinkedIn will read, and a preview shows exactly that.
    module Posts
      DISTRIBUTION = {
        "feedDistribution" => "MAIN_FEED",
        "targetEntities" => [],
        "thirdPartyDistributionChannels" => []
      }.freeze

      # What a read returns to a caller: a whitelist, so a field LinkedIn adds
      # later reaches nobody until somebody decides it should.
      FIELDS = %w[id author commentary lifecycleState visibility publishedAt createdAt lastModifiedAt content].freeze

      module_function

      def text_payload(author:, commentary:)
        check_author!(author)
        {
          "author" => author,
          "commentary" => LittleText.escape(commentary.to_s),
          "visibility" => "PUBLIC",
          "distribution" => {
            "feedDistribution" => DISTRIBUTION["feedDistribution"],
            "targetEntities" => [],
            "thirdPartyDistributionChannels" => []
          },
          "lifecycleState" => "PUBLISHED",
          "isReshareDisabledByAuthor" => false
        }
      end

      def article_payload(author:, commentary:, source:, title:, description:, thumbnail: nil)
        raise ArgumentError, "an article share needs an http(s) source URL" unless http_url?(source)
        raise ArgumentError, "an article share needs a title" if title.to_s.strip.empty?

        article = { "source" => source.to_s, "title" => title.to_s, "description" => description.to_s }
        article["thumbnail"] = thumbnail if thumbnail
        text_payload(author: author, commentary: commentary).merge("content" => { "article" => article })
      end

      # The escaped length LinkedIn counts against COMMENTARY_MAX.
      def commentary_length(text)
        LittleText.escape(text.to_s).length
      end

      # POST /rest/posts → the new post's URN, from `x-restli-id`.
      def create(client, payload)
        response = client.request(:posts_create, json: payload)
        urn = response.header("x-restli-id").to_s
        urn = URI.decode_www_form_component(urn) if urn.include?("%3A")
        raise Error, "LinkedIn created the post (HTTP #{response.status}) but returned no x-restli-id" if urn.empty?

        urn
      end

      def get(client, urn)
        check_post!(urn)
        slice(client.json(:posts_get, path: { urn: urn }))
      end

      def by_author(client, author:, count: 10)
        check_author!(author)
        count = count.to_i.clamp(1, 100)
        data = client.json(:posts_by_author, query: [["q", "author"], ["author", author], ["count", count],
                                                     ["sortBy", "LAST_MODIFIED"]])
        Array(data["elements"]).map { |post| slice(post) }
      end

      def delete(client, urn)
        check_post!(urn)
        client.request(:posts_delete, path: { urn: urn })
        true
      end

      def feed_url(urn)
        "https://www.linkedin.com/feed/update/#{urn}/"
      end

      def slice(post)
        post.is_a?(Hash) ? post.slice(*FIELDS) : {}
      end

      def http_url?(value)
        uri = URI.parse(value.to_s)
        uri.is_a?(URI::HTTP) && !uri.host.to_s.empty?
      rescue URI::InvalidURIError
        false
      end

      def check_author!(author)
        return if LinkedIn.author_type(author)

        raise ArgumentError, "author must be urn:li:organization:{id} or urn:li:person:{id}, got #{author.inspect}"
      end

      def check_post!(urn)
        return if urn.to_s.match?(/\Aurn:li:(share|ugcPost):[0-9]+\z/)

        raise ArgumentError, "not a post URN: #{urn.inspect}"
      end
    end
  end
end
