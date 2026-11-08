"""Shared stimulus-file writer for the `model/**/run_model*.py` runners.

Ten runners each carried a private copy of `write_hex`; this is the single
definition (the wavetable variant, which also returns the word count).  It is
a pure file writer: it makes no fidelity or exactness claim.
"""


def write_hex(path, values, bits=32):
    """Write one 32-bit hex word per line; return the number of words written.

    The return value is the model side's own declaration of how long each
    stimulus file is, collected into `rtl/stimulus_index.json` (issue #194).
    The testbench cannot supply it: its memories are declared generously
    (`ctrl_mem[0:262143]`, `wt_mem[0:131071]`) and a healthy run never fills
    them, so Icarus's `$readmemh(...): Not enough words` WARNING fires for
    every memory on a PASSING run and says nothing about truncation.
    """
    mask = (1 << bits) - 1
    n = 0
    with open(path, "w", encoding="utf-8") as f:
        for v in values:
            f.write(f"{int(v) & mask:08x}\n")
            n += 1
    return n
