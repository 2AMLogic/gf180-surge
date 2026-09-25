/*
 * SXT-038 (#72) — LP 24 dB pinned-kernel reference harness.
 *
 * ORIGINAL WORK of this repository (Apache-2.0, see LICENSE).  This file
 * contains NO code, tables, or assets copied from any GPL source.  It is an
 * API client: at BUILD time it includes headers from the externally checked
 * out, manifest-pinned GPL-3.0-or-later submodule `libs/sst/sst-filters`
 * (commit e92d93a92beabde03fa4ab767b285fa21c6608d6, oracle/manifest.json)
 * and `libs/sst/sst-basic-blocks` (a32b8aec14d661e415bb676bb2e2a0a4da4efc96).
 * The resulting BINARY is a combined work under GPL-3.0-or-later; it is
 * built into an external scratch directory, never committed, and never
 * distributed.  Only its numeric OUTPUT (reference coefficient planes and
 * filter signals) is committed, exactly as engine render output already is.
 * Licensing decision: decision-records/0010-lp24-pinned-kernel-harness.md.
 *
 * What it does: runs the pinned LP 24 dB coefficient maker and the pinned
 * per-subtype kernel over a declared control plane and a declared input
 * signal, reproducing the pinned engine's per-block voice-path sequence
 * (cited, never copied):
 *
 *   src/common/dsp/SurgeVoice.cpp  SetQFB()  — CM[u].MakeCoeffs(cutoff_a,
 *       reso_a, type, subtype, storage, extend_range); CM[u].updateState(
 *       Q->FU[u], e); per-voice FBP register copy-in
 *   src/common/dsp/SurgeVoice.cpp  GetQFB()  — FBP.FU[u].R[i] read-back and
 *       CM[u].C[i] = get1f(fbq->FU[u].C[i], fbqi) coefficient copy-back
 *   src/common/dsp/SurgeVoice.cpp  sampleRateReset() — the coefficient maker
 *       is configured with (dsamplerate_os, BLOCK_SIZE_OS) = (96000, 64)
 *   SurgeVoice.cpp:629              CM[u].Reset() + FBP zero on type/subtype
 *       change (the `reset` flag below)
 *
 * Two tuning providers are selectable, because the pinned ENGINE supplies
 * its own (SurgeStorage, table-based) provider while the pinned FILTER
 * LIBRARY ships a different default:
 *
 *   surge-lut : reproduces SurgeStorage's table semantics
 *               (SurgeStorage.cpp init_tables() / note_to_pitch_ignoring_
 *               tuning() / note_to_omega_ignoring_tuning(), cited) — the
 *               engine-faithful leg.  Tables are CONSTRUCTED here from the
 *               pinned construction formulas at run time; no table payload
 *               is copied.
 *   exact     : sst-filters' own detail::BasicTuningProvider (pinned code,
 *               zero input from this repository) — an independence leg that
 *               bounds the provider's contribution.
 *
 * Usage:  lp24_ref_harness <control.txt> <input.i32> <out-dir>
 *
 * control.txt (text, one directive per line):
 *   provider  surge-lut|exact
 *   type      <int fut_ id>            (2 = fut_lp24; other ids are refused)
 *   samplerate <float>                 (96000 = dsamplerate_os)
 *   blocksize <int>                    (64 = BLOCK_SIZE_OS)
 *   blocks    <int N>
 *   B <subtype> <reset 0|1> <cut %a> <reso %a>      (exactly N of these)
 *
 * input.i32: N*blocksize little-endian int32 Q10.21 words.  Each word must
 * satisfy |q| < 2^24 so that q/2^21 is EXACTLY representable in float32 —
 * the harness aborts otherwise, so both legs provably see the same input.
 *
 * Outputs (in <out-dir>): coeffs.jsonl, units.bin, regs.bin — see
 * tools/render_lp24_reference.py for the consuming format contract.
 */

#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>

#include "sst/filters.h"

namespace
{

constexpr int kNReg = 5; // R[0..4]: the LP24 kernels' state + clipgain slots
constexpr double kQ = 2097152.0; // 1 << 21 (Q10.21)

[[noreturn]] void die(const char *msg)
{
    std::fprintf(stderr, "REFUSING: %s\n", msg);
    std::exit(2);
}

/*
 * Tuning provider reproducing SurgeStorage's table semantics.
 *
 * Construction formulas cited from SurgeStorage::init_tables() (pinned):
 *   table_pitch[i]        = powf(2, (i - 256) / 12)
 *   table_two_to_the[i]   = pow(2, i / 12 / 1000)            (1001 entries)
 *   table_note_omega[0/1][i] = (float) sin/cos(2*pi*min(0.5,
 *                                440 * table_pitch[i] * dsamplerate_os_inv))
 * Lookup formulas cited from SurgeStorage::note_to_pitch_ignoring_tuning()
 * and SurgeStorage::note_to_omega_ignoring_tuning().  The omega table bakes
 * in dsamplerate_os, which is why the engine IGNORES the sampleRate argument
 * that sst-filters passes.
 */
struct SurgeLutProvider
{
    static constexpr int kTable = 512;
    // Required by other pinned filter types the coefficient maker template
    // instantiates (TriPoleFilter.h); unused on the LP24 paths.
    static constexpr double MIDI_0_FREQ = 8.17579891564371;
    static float tpitch[kTable];
    static float tsin[kTable];
    static float tcos[kTable];
    static float ttwo[1002];
    static double osRate;

    static void init(double dsamplerate_os)
    {
        osRate = dsamplerate_os;
        const double inv = 1.0 / dsamplerate_os;
        for (int i = 0; i < kTable; i++)
        {
            tpitch[i] = powf(2.f, ((float)i - 256.f) * (1.f / 12.f));
            const double a = 2 * M_PI * std::min(0.5, 440.0 * (double)tpitch[i] * inv);
            tsin[i] = (float)std::sin(a);
            tcos[i] = (float)std::cos(a);
        }
        for (int i = 0; i < 1001; ++i)
            ttwo[i] = (float)std::pow(2.0, i * 1.0 / 12.0 / 1000.0);
        ttwo[1001] = ttwo[1000];
    }

    static float note_to_pitch_ignoring_tuning(float x)
    {
        x = std::min(std::max(x + 256.f, 1.e-4f), (float)kTable - 1.e-4f);
        int e = (int)x;
        float a = x - (float)e;
        float pow2pos = a * 1000.0f;
        int pow2idx = (int)pow2pos;
        float pow2frac = pow2pos - (float)pow2idx;
        float pow2v = (1 - pow2frac) * ttwo[pow2idx] + pow2frac * ttwo[pow2idx + 1];
        return tpitch[e] * pow2v;
    }

    static float note_to_pitch(float x) { return note_to_pitch_ignoring_tuning(x); }

    static float note_to_pitch_inv_ignoring_tuning(float x)
    {
        return 1.f / note_to_pitch_ignoring_tuning(x);
    }

    static void note_to_omega_ignoring_tuning(float x, float &sinu, float &cosi, float /*sr*/)
    {
        x = std::min(std::max(x + 256.f, 0.f), (float)kTable - 1.e-4f);
        int e = (int)x;
        float a = x - (float)e;
        sinu = (1 - a) * tsin[e] + a * tsin[(e + 1) & 0x1ff];
        cosi = (1 - a) * tcos[e] + a * tcos[(e + 1) & 0x1ff];
    }
};

float SurgeLutProvider::tpitch[SurgeLutProvider::kTable];
float SurgeLutProvider::tsin[SurgeLutProvider::kTable];
float SurgeLutProvider::tcos[SurgeLutProvider::kTable];
float SurgeLutProvider::ttwo[1002];
double SurgeLutProvider::osRate = 96000.0;

struct BlockCtl
{
    int subtype;
    int reset;
    float cut;
    float reso;
};

struct Job
{
    std::string provider = "surge-lut";
    int type = 2;
    float samplerate = 96000.f;
    int blocksize = 64;
    int blocks = 0;
    std::vector<BlockCtl> ctl;
};

Job readJob(const char *path)
{
    Job j;
    FILE *f = std::fopen(path, "r");
    if (!f)
        die("cannot open control file");
    char line[512];
    while (std::fgets(line, sizeof line, f))
    {
        if (line[0] == '#' || line[0] == '\n')
            continue;
        char key[64];
        if (std::sscanf(line, "%63s", key) != 1)
            continue;
        if (!std::strcmp(key, "provider"))
        {
            char v[64];
            if (std::sscanf(line, "%*s %63s", v) != 1)
                die("bad provider line");
            j.provider = v;
        }
        else if (!std::strcmp(key, "type"))
            std::sscanf(line, "%*s %d", &j.type);
        else if (!std::strcmp(key, "samplerate"))
            std::sscanf(line, "%*s %f", &j.samplerate);
        else if (!std::strcmp(key, "blocksize"))
            std::sscanf(line, "%*s %d", &j.blocksize);
        else if (!std::strcmp(key, "blocks"))
            std::sscanf(line, "%*s %d", &j.blocks);
        else if (!std::strcmp(key, "B"))
        {
            BlockCtl b{};
            char cutbuf[64], resbuf[64];
            if (std::sscanf(line, "%*s %d %d %63s %63s", &b.subtype, &b.reset, cutbuf, resbuf) != 4)
                die("bad B line");
            b.cut = std::strtof(cutbuf, nullptr);
            b.reso = std::strtof(resbuf, nullptr);
            j.ctl.push_back(b);
        }
        else
            die("unknown directive in control file");
    }
    std::fclose(f);
    if ((int)j.ctl.size() != j.blocks)
        die("control block count does not match the declared 'blocks'");
    if (j.type != (int)sst::filters::fut_lp24)
        die("this harness serves fut_lp24 (2) only");
    for (auto &b : j.ctl)
        if (b.subtype < 0 || b.subtype > 2)
            die("subtype outside the engine-declared LP24 set {0,1,2}");
    return j;
}

std::vector<int32_t> readInputs(const char *path, size_t want)
{
    FILE *f = std::fopen(path, "rb");
    if (!f)
        die("cannot open input file");
    std::vector<int32_t> v(want);
    if (std::fread(v.data(), sizeof(int32_t), want, f) != want)
        die("input file shorter than blocks*blocksize");
    int32_t extra;
    if (std::fread(&extra, sizeof(int32_t), 1, f) == 1)
        die("input file longer than blocks*blocksize");
    std::fclose(f);
    for (int32_t q : v)
        if (q >= (1 << 24) || q <= -(1 << 24))
            die("input word not exactly representable in float32 (|q| >= 2^24)");
    return v;
}

template <typename Provider> int run(const Job &j, const std::vector<int32_t> &in, const char *outdir)
{
    using namespace sst::filters;

    FilterCoefficientMaker<Provider> cm;
    cm.setSampleRateAndBlockSize(j.samplerate, j.blocksize);

    QuadFilterUnitState st{};
    std::memset(&st, 0, sizeof st);

    auto path = [&](const char *n) { return std::string(outdir) + "/" + n; };
    FILE *fc = std::fopen(path("coeffs.jsonl").c_str(), "w");
    FILE *fu = std::fopen(path("units.bin").c_str(), "wb");
    FILE *fr = std::fopen(path("regs.bin").c_str(), "wb");
    if (!fc || !fu || !fr)
        die("cannot open an output file");

    uint32_t seq = 0;
    int prevSubtype = -1;
    for (int b = 0; b < j.blocks; b++)
    {
        const BlockCtl &c = j.ctl[b];
        if (c.reset)
        {
            cm.Reset();                     // CM[u].Reset()
            std::memset(&st, 0, sizeof st); // FBP.FU[u] zero (registers AND coefficients)
        }
        else if (c.subtype != prevSubtype && prevSubtype >= 0)
            die("subtype change without a reset flag (engine resets on subtype change)");
        prevSubtype = c.subtype;

        auto fn = GetQFPtrFilterUnit(fut_lp24, (FilterSubType)c.subtype);
        if (!fn)
            die("no kernel for the requested LP24 subtype");

        cm.MakeCoeffs(c.cut, c.reso, fut_lp24, (FilterSubType)c.subtype, nullptr, false);

        std::fprintf(fc,
                     "{\"b\":%d,\"unit\":0,\"lane\":0,\"type\":2,\"sub\":%d,\"first\":%s,"
                     "\"cut\":%.9g,\"reso\":%.9g,\"C\":[",
                     b, c.subtype, c.reset ? "true" : "false", (double)c.cut, (double)c.reso);
        for (int i = 0; i < n_cm_coeffs; i++)
            std::fprintf(fc, "%s%.9g", i ? "," : "", (double)cm.C[i]);
        std::fprintf(fc, "],\"dC\":[");
        for (int i = 0; i < n_cm_coeffs; i++)
            std::fprintf(fc, "%s%.9g", i ? "," : "", (double)cm.dC[i]);
        std::fprintf(fc, "]}\n");

        cm.updateState(st, 0); // SetQFB: C/dC into the unit state, lane 0

        for (int k = 0; k < j.blocksize; k++)
        {
            const int32_t q = in[(size_t)b * j.blocksize + k];
            const float x = (float)((double)q / kQ);
            const auto y = fn(&st, SIMD_MM(set1_ps)(x));
            float yv[4];
            SIMD_MM(storeu_ps)(yv, y);
            const uint32_t tag = 0, lane = 0;
            std::fwrite(&tag, 4, 1, fu);
            std::fwrite(&lane, 4, 1, fu);
            std::fwrite(&seq, 4, 1, fu);
            std::fwrite(&x, 4, 1, fu);
            std::fwrite(&yv[0], 4, 1, fu);
            seq++;
        }

        cm.updateCoefficients(st, 0); // GetQFB: advanced C back into the maker
        for (int i = 0; i < kNReg; i++)
        {
            float rv[4];
            SIMD_MM(storeu_ps)(rv, st.R[i]);
            std::fwrite(&rv[0], 4, 1, fr);
        }
    }

    std::fclose(fc);
    std::fclose(fu);
    std::fclose(fr);
    std::printf("{\"harness\":\"sxt-038-lp24-ref/1\",\"provider\":\"%s\",\"blocks\":%d,"
                "\"samples\":%u}\n",
                j.provider.c_str(), j.blocks, seq);
    return 0;
}

} // namespace

int main(int argc, char **argv)
{
    if (argc != 4)
    {
        std::fprintf(stderr, "usage: %s <control.txt> <input.i32> <out-dir>\n", argv[0]);
        return 2;
    }
    Job j = readJob(argv[1]);
    auto in = readInputs(argv[2], (size_t)j.blocks * j.blocksize);

    if (j.provider == "surge-lut")
    {
        SurgeLutProvider::init(j.samplerate);
        return run<SurgeLutProvider>(j, in, argv[3]);
    }
    if (j.provider == "exact")
        return run<sst::filters::detail::BasicTuningProvider>(j, in, argv[3]);

    die("unknown provider (want surge-lut|exact)");
}
