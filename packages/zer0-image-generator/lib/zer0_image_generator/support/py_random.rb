# frozen_string_literal: true

module Zer0ImageGenerator
  module Support
    # A bit-exact reimplementation of CPython's `random.Random`.
    #
    # Why this exists: the SVG generators ported from `tools/svg/` derive every
    # coordinate from a seeded stream, and the sample artwork committed under
    # `docs/samples/` was produced by CPython's Mersenne Twister. Ruby ships
    # MT19937 too, but seeds it differently — `Random.new(7)` and
    # `random.Random(7)` diverge on the first draw — so a port built on Ruby's
    # own RNG would silently re-skin every existing piece.
    #
    # Reimplementing CPython's seeding (`init_by_array`) and its derived
    # methods (`random`, `getrandbits`, `_randbelow`, `randrange`, `choice`,
    # `uniform`) keeps the ported generators byte-identical to their Python
    # originals, which `test/test_py_random.rb` and the golden-SVG tests pin.
    #
    # Only the surface the generators actually use is implemented; anything
    # else would be untested weight.
    class PyRandom
      N = 624
      M = 397
      MATRIX_A = 0x9908b0df
      UPPER_MASK = 0x80000000
      LOWER_MASK = 0x7fffffff
      MASK32 = 0xffffffff

      # CPython divides `random()`'s 53 bits as 26 high + 27 low.
      TWO_POW_26 = 67_108_864.0
      TWO_POW_53 = 9_007_199_254_740_992.0

      def initialize(seed = 0)
        @mt = Array.new(N, 0)
        @mti = N + 1
        seed!(seed)
      end

      # CPython's random_seed(): integers are seeded by absolute value, split
      # little-endian into 32-bit words, through init_by_array.
      def seed!(seed)
        n = seed.to_i.abs
        key = []
        if n.zero?
          key << 0
        else
          while n.positive?
            key << (n & MASK32)
            n >>= 32
          end
        end
        init_by_array(key)
      end

      def genrand_uint32
        if @mti >= N
          (0...(N - M)).each do |kk|
            y = (@mt[kk] & UPPER_MASK) | (@mt[kk + 1] & LOWER_MASK)
            @mt[kk] = @mt[kk + M] ^ (y >> 1) ^ (y.odd? ? MATRIX_A : 0)
          end
          ((N - M)...(N - 1)).each do |kk|
            y = (@mt[kk] & UPPER_MASK) | (@mt[kk + 1] & LOWER_MASK)
            @mt[kk] = @mt[kk + (M - N)] ^ (y >> 1) ^ (y.odd? ? MATRIX_A : 0)
          end
          y = (@mt[N - 1] & UPPER_MASK) | (@mt[0] & LOWER_MASK)
          @mt[N - 1] = @mt[M - 1] ^ (y >> 1) ^ (y.odd? ? MATRIX_A : 0)
          @mti = 0
        end

        y = @mt[@mti]
        @mti += 1
        y ^= (y >> 11)
        y ^= (y << 7) & 0x9d2c5680
        y ^= (y << 15) & 0xefc60000
        y &= MASK32
        y ^ (y >> 18)
      end

      # CPython: (a >> 5) * 2**26 + (b >> 6), scaled into [0, 1).
      def random
        a = genrand_uint32 >> 5
        b = genrand_uint32 >> 6
        ((a * TWO_POW_26) + b) / TWO_POW_53
      end

      def getrandbits(k)
        raise ArgumentError, "number of bits must be non-negative" if k.negative?
        return 0 if k.zero?
        return genrand_uint32 >> (32 - k) if k <= 32

        words = ((k - 1) / 32) + 1
        result = 0
        remaining = k
        words.times do |i|
          r = genrand_uint32
          r >>= (32 - remaining) if remaining < 32
          result |= r << (32 * i)
          remaining -= 32
        end
        result
      end

      # CPython's _randbelow_with_getrandbits: rejection-sample bit_length bits.
      def randbelow(n)
        return 0 unless n.positive?

        k = n.bit_length
        r = getrandbits(k)
        r = getrandbits(k) while r >= n
        r
      end

      def randrange(start, stop = nil, step = 1)
        if stop.nil?
          raise ArgumentError, "empty range for randrange(#{start})" unless start.positive?

          return randbelow(start)
        end

        width = stop - start
        if step == 1
          raise ArgumentError, "empty range for randrange(#{start}, #{stop})" unless width.positive?

          return start + randbelow(width)
        end

        n = step.positive? ? ((width + step - 1) / step) : ((width + step + 1) / step)
        raise ArgumentError, "empty range for randrange(#{start}, #{stop}, #{step})" unless n.positive?

        start + (step * randbelow(n))
      end

      def randint(a, b)
        randrange(a, b + 1)
      end

      def choice(seq)
        raise ArgumentError, "cannot choose from an empty sequence" if seq.empty?

        seq[randbelow(seq.length)]
      end

      def uniform(a, b)
        a + ((b - a) * random)
      end

      private

      def init_genrand(s)
        @mt[0] = s & MASK32
        (1...N).each do |i|
          @mt[i] = (1_812_433_253 * (@mt[i - 1] ^ (@mt[i - 1] >> 30)) + i) & MASK32
        end
        @mti = N
      end

      def init_by_array(key)
        init_genrand(19_650_218)
        i = 1
        j = 0
        k = [N, key.length].max
        while k.positive?
          @mt[i] = ((@mt[i] ^ ((@mt[i - 1] ^ (@mt[i - 1] >> 30)) * 1_664_525)) + key[j] + j) & MASK32
          i += 1
          j += 1
          if i >= N
            @mt[0] = @mt[N - 1]
            i = 1
          end
          j = 0 if j >= key.length
          k -= 1
        end

        k = N - 1
        while k.positive?
          @mt[i] = ((@mt[i] ^ ((@mt[i - 1] ^ (@mt[i - 1] >> 30)) * 1_566_083_941)) - i) & MASK32
          i += 1
          if i >= N
            @mt[0] = @mt[N - 1]
            i = 1
          end
          k -= 1
        end

        @mt[0] = UPPER_MASK
      end
    end
  end
end
