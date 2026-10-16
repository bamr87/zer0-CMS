# frozen_string_literal: true

# Metadata for the SVG studio: every generator, its knobs, and their allowed
# values. This is the UI's source of truth — the knob forms, the validation of
# incoming params, and the labels all read from here.
#
# The values mirror each Python generator's argparse (choices and defaults),
# which the Ruby port preserves. Keeping them in one table means a new knob is
# a one-line change here, not a hunt through views.
module StudioCatalog
  Knob = Struct.new(:key, :label, :type, :default, :choices, :min, :max, keyword_init: true)
  Generator = Struct.new(:key, :label, :blurb, :knobs, keyword_init: true)

  # A seed knob is on every generator; factored out to avoid repetition.
  def self.seed(default = 1)
    Knob.new(key: "seed", label: "Seed", type: :int, default: default, min: 0, max: 2_147_483_647)
  end

  def self.palette(choices, default)
    Knob.new(key: "palette", label: "Palette", type: :enum, default: default, choices: choices)
  end

  GENERATORS = [
    Generator.new(
      key: "banner", label: "Banner (engine local template)",
      blurb: "The engine's own deterministic local-provider banner — the real template a site gets, not a lookalike. Drive it by seed or by a post slug.",
      knobs: [
        seed(7),
        Knob.new(key: "slug", label: "Slug (overrides seed via crc32)", type: :string, default: ""),
      ]
    ),
    Generator.new(
      key: "flowfield", label: "Flow field",
      blurb: "The canonical generator-with-knobs: streamlines advected through value noise.",
      knobs: [
        seed(1),
        palette(%w[ember cyanic moss], "cyanic"),
        Knob.new(key: "lines", label: "Lines", type: :int, default: 240, min: 10, max: 800),
        Knob.new(key: "steps", label: "Steps", type: :int, default: 70, min: 5, max: 300),
        Knob.new(key: "scale", label: "Noise scale", type: :float, default: 180.0, min: 20, max: 600),
      ]
    ),
    Generator.new(
      key: "lsystem", label: "L-system plant",
      blurb: "Recursive turtle over an L-system string; depth-shaded branches and bloom tips.",
      knobs: [
        seed(7),
        Knob.new(key: "species", label: "Species", type: :enum, default: "bush", choices: %w[bush fern tree weed]),
        palette(%w[verdant autumn sakura frost], "verdant"),
        Knob.new(key: "iters", label: "Iterations (blank = ruleset default)", type: :int, default: nil, min: 1, max: 8),
      ]
    ),
    Generator.new(
      key: "lowpoly", label: "Low-poly field",
      blurb: "Jittered triangle grid with value-noise facet shading and an off-center sun glow.",
      knobs: [
        seed(5),
        palette(%w[dusk cyanic moss ember], "dusk"),
        Knob.new(key: "cols", label: "Columns", type: :int, default: 16, min: 4, max: 40),
        Knob.new(key: "rows", label: "Rows", type: :int, default: 11, min: 3, max: 30),
      ]
    ),
    Generator.new(
      key: "mandala", label: "Mandala",
      blurb: "N-fold concentric motif bands via defs + rotated use, with one phase-broken ring.",
      knobs: [seed(11), palette(%w[jewel solar ocean rose], "jewel")]
    ),
    Generator.new(
      key: "starmap", label: "Star map",
      blurb: "Library icons recolored over a generated starfield and low-poly hills — the reuse-gathered-content path.",
      knobs: [seed(5)]
    ),
    Generator.new(
      key: "invaders", label: "Invaders (pixel)",
      blurb: "Procedural fixed-shooter scene; aliens are mirrored half-grids so blobs read as creatures.",
      knobs: [seed(3), palette(%w[dusk cyanic moss magma], "cyanic")]
    ),
    Generator.new(
      key: "pixelquest", label: "Pixel quest",
      blurb: "Side-scroller vignette from hand-designed ASCII sprites with seeded layout.",
      knobs: [seed(7), palette(%w[dusk cyanic moss magma], "dusk")]
    ),
  ].freeze

  BY_KEY = GENERATORS.index_by(&:key).freeze

  def self.generators = GENERATORS
  def self.find(key) = BY_KEY[key.to_s]
  def self.keys = BY_KEY.keys
end
