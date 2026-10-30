# RC24 — Targeted correction and verification

- Restored the pre-RC22 header and hero vertical sizing; the previous change incorrectly compressed height.
- Added horizontal padding INSIDE the header on both sides (logo left, quote basket right).
- Project previews now show complete source compositions using `object-fit: contain` rather than cropping.
- Project previews open the full source image in a new tab. These are previews, not links to deployed client sites; no unverified live site URLs invented.
- FirstCoreAI remains excluded.
- Browser screenshot and automated checks should be reviewed before production.
