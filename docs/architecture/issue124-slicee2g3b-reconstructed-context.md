# Issue #124 — E2G3B: reconstructed context verification

This read-only gate accepts a caller-supplied *fresh* teacher-reviewed preview loader; it never creates or reconstructs choices from a stored digest. The gate checks the unique E2G3A durable candidate, its exact current intent digest, the original E2F1 receipt, and stability across rereads. It cannot select academic state or automatically resume.

A successful result is only `verified_for_review`; an explicit teacher `RESUME` through E2G1/E2G2 and the canonical restart port is still required. The calling menu must not interpret this inspection as authority to write or select. This slice does not wire the new gate into navigation, and the caller must independently ensure its preview loader uses actual fresh teacher choices and canonical data.
