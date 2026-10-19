# frozen_string_literal: true

# `bin/zer0 tags`: which tags on a remote are this repository's own releases
# and which it inherited from Front Matter CMS, the project zer0-CMS was forked
# from.
#
# The fork brought estruyf/vscode-front-matter's release tags with it (v1.15.0
# through v10.x, plus a few bare "3.1.0"-style ones). They are not this
# project's releases: they make v0.3.0 look like a downgrade to every tool that
# sorts tags, and they are a trap for anything that infers "latest" from tags.
# The rule that tells them apart needs no history: a release of this repository
# is a version with a heading in its CHANGELOG.md (`## [0.3.0]`), which
# release-please writes for every tag it cuts. A bare semver tag with no
# heading is inherited. Anything else — a component-prefixed tag such as
# `content-v1.0.0` — is neither and is never touched.

module Zer0Workspace
  class Tags
    SEMVER = /\Av?(\d+\.\d+\.\d+)\z/
    HEADING = /^## \[(\d+\.\d+\.\d+)\]/

    Classified = Struct.new(:own, :inherited, :other, keyword_init: true)

    def initialize(root, changelog: "CHANGELOG.md")
      @root = root
      @changelog = File.join(root, changelog)
    end

    # The versions this repository has released, from its changelog headings.
    def releases
      raise ManifestError, "#{@changelog} not found — the changelog is what says which tags are releases" unless File.file?(@changelog)

      File.read(@changelog, encoding: "UTF-8").scan(HEADING).flatten.uniq
    end

    def classify(tags)
      own = releases
      groups = Classified.new(own: [], inherited: [], other: [])
      tags.sort_by { |t| sort_key(t) }.each do |tag|
        version = tag[SEMVER, 1]
        if version.nil? then groups.other << tag
        elsif own.include?(version) then groups.own << tag
        else groups.inherited << tag
        end
      end
      groups
    end

    # The tag names on `remote` (peeled refs are folded into their tag).
    def remote_tags(remote)
      out = git("ls-remote", "--tags", "--refs", remote)
      raise ManifestError, "git ls-remote --tags #{remote} failed — is #{remote.inspect} a remote here?" if out.nil?

      out.split("\n").filter_map { |line| line.split("\t", 2)[1]&.delete_prefix("refs/tags/") }
    end

    # Deletes `tags` on `remote` (in batches, so one push carries many refs)
    # and from the local clone. Returns the tags whose remote delete failed.
    def delete!(remote, tags, batch: 25)
      failed = []
      tags.each_slice(batch) do |slice|
        ok = system("git", "-C", @root, "push", "--quiet", remote, *slice.map { |t| ":refs/tags/#{t}" })
        failed.concat(slice) unless ok
      end
      local = tags & (git("tag", "--list") || "").split("\n")
      system("git", "-C", @root, "tag", "-d", *local, out: File::NULL) unless local.empty?
      failed
    end

    private

    def sort_key(tag)
      version = tag[SEMVER, 1]
      version ? [0, *version.split(".").map(&:to_i), tag] : [1, 0, 0, 0, tag]
    end

    def git(*args)
      out = IO.popen(["git", "-C", @root, *args], err: File::NULL, &:read)
      $?.success? ? out : nil
    end
  end
end
