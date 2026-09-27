/*
 * SXT-022 (#123) — HalfRateFilter::process_block_D2 branch-assignment probe.
 *
 * ORIGINAL WORK of this repository (Apache-2.0, see LICENSE).  This file
 * contains NO code, tables, or assets copied from any GPL source.  It is an
 * API client: at BUILD time it includes headers from the externally checked
 * out, manifest-pinned GPL-3.0-or-later submodule `libs/sst/sst-filters`
 * (commit e92d93a92beabde03fa4ab767b285fa21c6608d6, oracle/manifest.json).
 * The resulting BINARY is a combined work under GPL-3.0-or-later; it is
 * built into an external scratch directory, never committed, and never
 * distributed.  Only its numeric OUTPUT is committed, exactly as engine
 * render output already is.  Licensing method: decision-records/0009
 * (pinned-kernel reference harness) and 0010 (its LP24 instantiation); this
 * probe reuses that shape exactly and adds no new licensing question.
 *
 * Why this exists: the pinned header's PROSE comments and its CODE disagree
 * about which allpass branch is sampled at the even output index.  The
 * comment block above the reconstruction loop asserts
 *
 *     o_i: AllpassCascade_B(L_i), AllpassCascade_A(L_i), ...      (lane 0 = B)
 *     L[i] = A_L[2*i] + B_L[2*i+1]
 *
 * while `set_coefficients` actually writes
 *
 *     va[i] = SIMD_MM(set_ps)(cB[i], cA[i], cB[i], cA[i]);        (lane 0 = A)
 *
 * — `_mm_set_ps(e3,e2,e1,e0)` puts its LAST argument in lane 0 — and the
 * reconstruction reads `tL0 = shuffle_ps(o[k],o[k],SHUFFLE(1,1,1,1))`
 * (lane 1 = B at the even sample) and adds `o[k+1]`'s lane 0 (A at the odd
 * sample).  The comment's own author flags the confusion in-line ("which
 * looks a lot to me like I have a bit flip somewhere wrong in my comments").
 *
 * Reading alone therefore cannot settle it.  This probe EXECUTES the pinned
 * kernel and emits its decimated output so the two candidate scalar
 * reconstructions can be scored against it numerically.
 *
 * Usage:  halfband_d2_probe > out.txt
 *
 * Output (text, machine-readable; one record per line):
 *   case <name> <nsamples>          start of a case (fresh filter instance)
 *   in  <i> <%.9g>                  input sample i (left channel)
 *   out <i> <%.9g>                  decimated output sample i (left channel)
 */

#include <cstdio>
#include <cstdint>
#include <cmath>
#include <vector>

#include "sst/filters/HalfRateFilter.h"

namespace
{

constexpr int kN = 256; // input samples per case (multiple of 8, <= hr_BLOCK_SIZE)

// A deterministic 32-bit LCG so the "noise" case is reproducible anywhere
// without shipping a table.
struct Lcg
{
    uint32_t s;
    explicit Lcg(uint32_t seed) : s(seed) {}
    float next()
    {
        s = s * 1664525u + 1013904223u;
        // map to [-1,1) with 24 significant bits, exactly representable in float32
        return static_cast<float>(static_cast<int32_t>(s >> 8) - (1 << 23)) /
               static_cast<float>(1 << 23);
    }
};

void run_case(const char *name, const std::vector<float> &in)
{
    // process_block_D2 works in place on 16-byte aligned buffers.
    alignas(16) float L[kN];
    alignas(16) float R[kN];
    for (int i = 0; i < kN; ++i)
    {
        L[i] = in[static_cast<size_t>(i)];
        R[i] = 0.f;
    }

    // Fresh filter per case: M = 6, steep -> order 12, rejection 104 dB.
    // This is exactly the instance the voice scene decimator models.
    sst::filters::HalfRate::HalfRateFilter hr(6, true);
    hr.reset();
    hr.process_block_D2(L, R, kN);

    std::printf("case %s %d\n", name, kN);
    for (int i = 0; i < kN; ++i)
        std::printf("in %d %.9g\n", i, static_cast<double>(in[static_cast<size_t>(i)]));
    for (int i = 0; i < kN / 2; ++i)
        std::printf("out %d %.9g\n", i, static_cast<double>(L[i]));
}

} // namespace

int main()
{
    std::vector<float> in(kN);

    for (double f : {0.05, 0.15, 0.25, 0.30, 0.45})
    {
        for (int i = 0; i < kN; ++i)
            in[static_cast<size_t>(i)] = static_cast<float>(std::sin(2.0 * M_PI * f * i));
        char nm[64];
        std::snprintf(nm, sizeof(nm), "sine_f%.2f", f);
        run_case(nm, in);
    }

    {
        Lcg g(0x5eedu);
        for (int i = 0; i < kN; ++i)
            in[static_cast<size_t>(i)] = g.next();
        run_case("lcg_seed_0x5eed", in);
    }

    {
        for (int i = 0; i < kN; ++i)
            in[static_cast<size_t>(i)] = (i == 0) ? 1.f : 0.f;
        run_case("impulse", in);
    }

    return 0;
}
