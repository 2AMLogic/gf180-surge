"""Version identity for the SXT-020 patch-image compiler.

Bump rules (compiler/format.md section 9): any change to the header or body
field set, the container layout, the allocation layout, or the rejection
catalog classes requires a format major/minor bump and a golden-regeneration
commit; a gate-semantics change additionally requires a visible note in the
scan reconciliation. No silent format drift.
"""

COMPILER_VERSION = "sxt-020-compile/1.1.0"
IMAGE_FORMAT_VERSION = "sxt-020-patch-image/1.1.0"
IMAGE_FORMAT_MAJOR = 1
IMAGE_FORMAT_MINOR = 1
CONTAINER_MAGIC = b"SXP1"
