"""SXT-020 patch-image compiler package.

Compiles SXT-011 normalized patch graphs (corpus/normalized/graphs.jsonl)
into versioned patch images: a header (source hashes, profile/bundle
identity), the verbatim normalized graph (lossless), derived voice/FX views,
deterministic allocations from the SXT-015 resource model, event-timing
requirements, and strong checksums.

Gate semantics are the SXT-017 DRAFT profile predictor's own evaluator
(tools/profile_predict.py) against the selected DRAFT bundle (B4-broad), so
compiler outcomes reconcile with reports/sxt-017/predictions/ by
construction. The compiler adds the checks an *image emitter* must make
(complete asset references, expressible send routing) and is therefore
stricter where the predictor could stay silent.

Claim discipline: a patch image is a structural artifact. Compiling a
preset establishes NO fidelity, preset-support, or preset-quality claim,
and every allocation number inherits the SXT-015 placeholder model
([PENDING-SXT-016]). The compiled profile is DRAFT-NOT-FROZEN; images
record that status in their headers.
"""
from .version import COMPILER_VERSION, IMAGE_FORMAT_VERSION

__all__ = ["COMPILER_VERSION", "IMAGE_FORMAT_VERSION"]
