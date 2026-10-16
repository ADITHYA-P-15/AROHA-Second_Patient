# Feature log

One entry per feature, newest first. Local dev-workflow notes, not part of the submission docs.

## Proof-photo fix + primary-contact verification

Follow-up to the proof-photo feature below, from live demo testing.

**Bug fixed:** every upload failed with "That file could not be read as a photo." Cause: the app's
`Content-Security-Policy` only allowed `img-src 'self' data:`, so the browser silently refused the `blob:` object URL
that `loadImage()` and the preview `<img>` both use. Added `blob:` to `img-src` in `backend/app/main.py`.

**New: the primary contact must review and verify every proof photo.**
- `activity_proof_photos` gets `verified_by`/`verified_at` (migration `0022`, written with `batch_alter_table` since
  SQLite's plain `DROP COLUMN` leaves a dangling FK clause behind on downgrade otherwise).
- `POST /activities/{id}/proof-photo/verify` — primary-contact-only (`patient:update`), idempotent (keeps the first
  sign-off; re-verifying doesn't reset the timestamp).
- `GET /patients/{id}/proof-photos?verified=` — the review list, newest first, joined with the activity's title.
- Uploading a photo now notifies the primary contact (`family_ids`, excluding the uploader) with the dose title, a
  formatted capture time, and a plain-text location line spelled out in the notification body itself — not just relying
  on the burned-in watermark on the image. Re-uploading a replacement photo clears any existing verification, since a
  different photo needs a fresh look.
- Frontend: `ProofPhotoReview.tsx`, shown on Care Plan to the primary contact only — each pending photo's thumbnail,
  `captured_at_text` and `location_text` as plain text (clock/pin icons, not just the image), with a Verify button.

Verified live end to end in the browser (two caretaker/patient pairs): upload → "Proof photo to review" notification
with time + location spelled out → Care Plan review panel shows the photo and facts → Verify → panel clears. 348
backend tests pass; full frontend gate passes. Committed and fast-forwarded into local `main` — not pushed.

## Caretaker proof-photo accountability

Caretakers can no longer tap "Done" on a medicine dose with nothing to back it up. A photo is now required before a
`PRESCRIPTION`-sourced care activity can be recorded as complete; the requirement is enforced server-side
(`require_proof_photo`, called from `POST /activities/{id}/complete`), not just hidden behind a UI gate.

**Backend**
- New table `activity_proof_photos` (migration `0021_activity_proof_photos`, chained after the bug-bounty RLS lock-down
  `0020`, and extends that same RLS lock-down to itself): one photo per activity, JPEG/PNG/WebP, 500B–8MB, with
  `captured_at`, `latitude`/`longitude`/`location_accuracy_m` and a `location_status` (`AVAILABLE`/`DENIED`/`UNAVAILABLE`).
- `backend/app/api/proof_photos.py`: `PUT /activities/{id}/proof-photo` (upload/replace, only before completion),
  `GET /activities/{id}/proof-photo` (raw image), `GET .../proof-photo/meta` (JSON metadata). Same access rule as
  completing the activity: the primary contact, or the caretaker it's confirmed-assigned to. Gated behind the
  `proof_photos` feature flag (on by default).
- `complete_activity` in `domain.py` now calls `require_proof_photo` before allowing a PRESCRIPTION dose to complete;
  once completed, the photo is immutable (re-upload returns 409).
- Demo/synthetic seed data (`population.py`, `demo.py`) sets `lifecycle_status` directly via the ORM, bypassing the API
  route entirely, so historical synthetic doses are unaffected by the gate.

**Frontend**
- `frontend/src/lib/proofPhoto.ts`: best-effort geolocation (`getLocation`, never blocks on denial), and `watermark()`,
  which draws the photo to a canvas and burns a visible timestamp + location banner into the image client-side before
  upload — the uploaded file *is* the watermarked one, not a separate overlay.
- `frontend/src/ProofPhoto.tsx` (`ProofPhotoCapture`): inline capture panel — take/pick a photo (`capture="environment"`
  opens the camera on mobile), watermark it, preview, confirm (uploads, then completes) or retake.
- Wired into `MyDay.tsx`: for a `PRESCRIPTION` task, "Done" / "Record as done (late)" opens the capture panel instead of
  completing directly. Other activity types (appointments, etc.) are unaffected. `CarePlan.tsx` / `CommandCenter.tsx`
  surface the backend's 422 as a toast if a dose is completed from there without a photo, rather than silently failing.

**Tests:** `backend/tests/test_proof_photos.py` (upload/complete happy path, access control, non-PRESCRIPTION rejection,
mime/size validation, immutability after completion, unrelated-account read denial). Updated three existing tests
(`test_care_feeds.py` x2, `test_notifications.py`) that completed PRESCRIPTION doses directly, via a new `give_dose()`
test helper. Also had to rebase migration `0020`'s already-applied RLS coverage test to be forward-looking (any later
migration may lock down its own new table) rather than hardcoded to one file — see `test_public_api_migration.py`.

Status: implemented, tested (345 backend tests pass, full frontend lint/typecheck/test/build gate passes), verified live
in the browser (photo-required panel replaces "Done" for a medicine task). Committed locally on `claude/bug-bounty-review-25ba12`
and fast-forwarded into local `main` — **not pushed** yet.
