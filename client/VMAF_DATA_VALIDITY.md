# VMAF data validity

VMAF measurements produced by clients older than `client/0.1.1` are considered
invalid. VMAF is directional, and those measurements were computed with the
pristine reference as input 0 and the encoded artifact as input 1.

Encoding artifacts are not retained, so historical values cannot be
recomputed. They must not be used for rankings, derived PL scores, or quality
comparisons. A data migration must null these legacy values and invalidate or
recompute any VMAF-derived scores. Measurements from `client/0.1.1` onward use
the encoded/distorted stream as input 0 and the pristine/reference stream as
input 1, as required by libvmaf.
