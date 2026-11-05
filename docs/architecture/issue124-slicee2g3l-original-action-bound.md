# Meridian #124 — E2G3L Original Action-Bound Composite Recovery

This test-only slice follows E2G3K (`56384271197e79a7403ce9cd9e00797ee0a5aa44`). The two additions are a focused regression module and this architecture note; no production source changes.

The synthetic workspace uses Core class metadata, a current academic calendar, an assessment registration, and a rebuilt derived catalog. It persists real immutable Grade Item and included membership revisions, real #122 receipts, and an exact monotone E2A correlation record bound to the original action IDs and target digests. Receipt preparation and correlation binding precede the corresponding simulated interrupted academic write.

Six tests qualify the read-only original receipt witness, a cancelled or wrong-ID resume, an explicit original Grade Item RESUME, an explicit original membership RESUME, registration drift, and corrupt original journal rejection. The two successful RESUME paths invoke the existing #122 restart ports and select only previously persisted canonical revisions; no recovery writer is provided. A repeated resume after current selection must be refused without changing files.

The actor checker used by the tests is intentionally synthetic and bypasses the real local teacher-profile lookup. This verifies storage and exact action binding, **not** production teacher authentication or full crash/process concurrency safety. Test fixture writes are confined to pytest temporary directories. There is no producer read, student record, eligibility decision, Score, Grade calculation, automatic RESUME, or implicit publication authorization.

This is a narrow fixture-backed integration gate. Additional manual teacher-interface acceptance and current installation/dependency checks remain necessary before issue #124 can be considered production-ready.
