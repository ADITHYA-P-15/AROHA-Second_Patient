"""Caretaker accountability: a medicine dose cannot be recorded as done without a proof photo, access-controlled and immutable once done."""
from datetime import timedelta
from zoneinfo import ZoneInfo

from app.core.clock import now
from tests.helpers import H, TINY_JPEG, account, caretaker, give_dose, join_as_professional, primary_contact_with_patient

ZONE = ZoneInfo("Asia/Kolkata")
JPEG = {"Content-Type": "image/jpeg", **H}


def setup():
    coord, pid = primary_contact_with_patient("Synthetic proof-photo patient")
    main_id, main = caretaker(coord, pid, "Main Caretaker", caps=("MEDICATION_ASSIST",), day=1)
    assert coord.put(f"/api/v1/patients/{pid}/main-caretaker", headers=H, json={"caregiver_id": main_id}).status_code == 200
    doctor, _, _ = join_as_professional(coord, pid)
    return coord, pid, doctor, main, main_id


def a_dose(coord, pid, doctor, medicine="Metformin"):
    """A dose due soon (inside the 2h early-completion window), not tomorrow — so /complete can actually succeed."""
    soon = now().astimezone(ZONE) + timedelta(minutes=45)
    doctor.post(f"/api/v1/patients/{pid}/prescriptions", headers=H, json={"medicine": medicine, "dose": "500 mg", "times": [soon.strftime("%H:%M")],
               "start_date": soon.date().isoformat(), "end_date": soon.date().isoformat()})
    items = coord.get(f"/api/v1/patients/{pid}/activities", params={"limit": 100}).json()["items"]
    return next(a for a in items if a["source"] == "PRESCRIPTION" and a["title"].startswith(medicine))


def an_appointment(coord, pid, doctor):
    start = (now() + timedelta(days=2)).astimezone(ZONE).replace(hour=11, minute=0, second=0, microsecond=0)
    made = doctor.post(f"/api/v1/patients/{pid}/appointments", headers=H, json={"title": "Checkup", "start": start.isoformat()})
    return made.json()["id"]


def test_a_dose_cannot_be_completed_without_a_photo_then_can_with_one():
    coord, pid, doctor, main, _ = setup()
    dose = a_dose(coord, pid, doctor)
    blocked = main.post(f"/api/v1/activities/{dose['id']}/complete", headers=H, json={})
    assert blocked.status_code == 422
    uploaded = main.put(f"/api/v1/activities/{dose['id']}/proof-photo", headers=JPEG, content=TINY_JPEG)
    assert uploaded.status_code == 201
    meta = uploaded.json()
    assert meta["location_status"] == "UNAVAILABLE" and meta["mime_type"] == "image/jpeg" and meta["size_bytes"] == len(TINY_JPEG)
    done = main.post(f"/api/v1/activities/{dose['id']}/complete", headers=H, json={})
    assert done.status_code == 200
    photo = main.get(f"/api/v1/activities/{dose['id']}/proof-photo")
    assert photo.status_code == 200 and photo.headers["content-type"].startswith("image/jpeg") and photo.content == TINY_JPEG


def test_only_the_assigned_caretaker_may_upload_the_photo_not_the_primary_contact():
    coord, pid, doctor, main, _ = setup()
    dose = a_dose(coord, pid, doctor)
    outsider = caretaker(coord, pid, "Outsider", caps=("MEDICATION_ASSIST",))[1]
    assert outsider.put(f"/api/v1/activities/{dose['id']}/proof-photo", headers=JPEG, content=TINY_JPEG).status_code == 403
    assert account("PRIMARY_CONTACT")[0].put(f"/api/v1/activities/{dose['id']}/proof-photo", headers=JPEG, content=TINY_JPEG).status_code == 403  # not on this care team
    assert coord.put(f"/api/v1/activities/{dose['id']}/proof-photo", headers=JPEG, content=TINY_JPEG).status_code == 403  # the primary contact reviews; the caretaker gives and photographs the dose
    assert coord.post(f"/api/v1/activities/{dose['id']}/complete", headers=H, json={}).status_code == 403  # and cannot complete the dose directly either
    assert main.put(f"/api/v1/activities/{dose['id']}/proof-photo", headers=JPEG, content=TINY_JPEG).status_code == 201


def test_proof_photos_are_only_for_medicine_doses():
    coord, pid, doctor, main, _ = setup()
    aid = an_appointment(coord, pid, doctor)
    assert coord.put(f"/api/v1/activities/{aid}/proof-photo", headers=JPEG, content=TINY_JPEG).status_code == 409
    assert coord.post(f"/api/v1/activities/{aid}/complete", headers=H, json={}).status_code in (200, 409)  # not blocked by the photo gate either way


def test_the_photo_is_validated_and_cannot_be_swapped_after_completion():
    coord, pid, doctor, main, _ = setup()
    dose = a_dose(coord, pid, doctor)
    assert main.put(f"/api/v1/activities/{dose['id']}/proof-photo", headers={**H, "Content-Type": "text/plain"}, content=TINY_JPEG).status_code == 415
    assert main.put(f"/api/v1/activities/{dose['id']}/proof-photo", headers=JPEG, content=b"too small").status_code == 422
    assert give_dose(main, dose["id"]).status_code == 200
    assert main.put(f"/api/v1/activities/{dose['id']}/proof-photo", headers=JPEG, content=TINY_JPEG).status_code == 409


def test_re_uploading_before_completion_replaces_the_photo():
    coord, pid, doctor, main, _ = setup()
    dose = a_dose(coord, pid, doctor)
    first = main.put(f"/api/v1/activities/{dose['id']}/proof-photo", headers=JPEG, content=TINY_JPEG)
    second_image = TINY_JPEG + b"\x00" * 10
    second = main.put(f"/api/v1/activities/{dose['id']}/proof-photo", headers=JPEG, content=second_image)
    assert first.status_code == 201 and second.status_code == 201 and first.json()["activity_id"] == second.json()["activity_id"]
    photo = main.get(f"/api/v1/activities/{dose['id']}/proof-photo")
    assert photo.content == second_image  # the most recent upload is what is kept and served


def test_an_unrelated_account_cannot_read_the_photo_or_its_metadata():
    coord, pid, doctor, main, _ = setup()
    dose = a_dose(coord, pid, doctor)
    give_dose(main, dose["id"])
    stranger = account("CARETAKER")[0]
    assert stranger.get(f"/api/v1/activities/{dose['id']}/proof-photo").status_code == 403
    assert stranger.get(f"/api/v1/activities/{dose['id']}/proof-photo/meta").status_code == 403
    assert coord.get(f"/api/v1/activities/{dose['id']}/proof-photo/meta").status_code == 200  # the primary contact may review it


def titles(client):
    return [n["title"] for n in client.get("/api/v1/notifications").json()["items"]]


def test_uploading_a_photo_notifies_the_primary_contact_with_the_time_and_location_spelled_out():
    coord, pid, doctor, main, _ = setup()
    dose = a_dose(coord, pid, doctor)
    uploaded = main.put(f"/api/v1/activities/{dose['id']}/proof-photo", headers=JPEG, content=TINY_JPEG,
                         params={"latitude": "12.9716", "longitude": "77.5946", "accuracy_m": "12", "location_status": "AVAILABLE"})
    assert uploaded.status_code == 201
    meta = uploaded.json()
    assert "Location unavailable" not in meta["location_text"] and "12.97160" in meta["location_text"] and "77.59460" in meta["location_text"]
    assert f"Proof photo to review: {dose['title']}" in titles(coord)
    notif = next(n for n in coord.get("/api/v1/notifications").json()["items"] if n["title"].startswith("Proof photo to review"))
    assert "12.97160" in notif["body"] and meta["captured_at_text"] in notif["body"] and notif["requires_ack"] is True
    assert f"Proof photo to review: {dose['title']}" not in titles(main)  # the uploader is not told about their own upload


def test_only_the_primary_contact_can_verify_a_photo_and_it_is_idempotent():
    coord, pid, doctor, main, _ = setup()
    dose = a_dose(coord, pid, doctor)
    main.put(f"/api/v1/activities/{dose['id']}/proof-photo", headers=JPEG, content=TINY_JPEG)
    assert main.post(f"/api/v1/activities/{dose['id']}/proof-photo/verify", headers=H, json={}).status_code == 403  # a caretaker cannot verify their own evidence
    first = coord.post(f"/api/v1/activities/{dose['id']}/proof-photo/verify", headers=H, json={})
    assert first.status_code == 200 and first.json()["verified_by"] is not None and first.json()["verified_at"] is not None
    first_at = first.json()["verified_at"]
    second = coord.post(f"/api/v1/activities/{dose['id']}/proof-photo/verify", headers=H, json={})
    assert second.json()["verified_at"] == first_at  # verifying again keeps the original sign-off


def test_replacing_a_photo_clears_its_verification_and_the_review_list_reflects_it():
    coord, pid, doctor, main, _ = setup()
    dose = a_dose(coord, pid, doctor)
    main.put(f"/api/v1/activities/{dose['id']}/proof-photo", headers=JPEG, content=TINY_JPEG)
    assert coord.post(f"/api/v1/activities/{dose['id']}/proof-photo/verify", headers=H, json={}).status_code == 200
    unverified_before = coord.get(f"/api/v1/patients/{pid}/proof-photos", params={"verified": "false"}).json()["items"]
    assert dose["id"] not in [p["activity_id"] for p in unverified_before]
    main.put(f"/api/v1/activities/{dose['id']}/proof-photo", headers=JPEG, content=TINY_JPEG + b"\x00" * 4)  # a new photo needs a fresh look
    unverified_after = coord.get(f"/api/v1/patients/{pid}/proof-photos", params={"verified": "false"}).json()["items"]
    assert dose["id"] in [p["activity_id"] for p in unverified_after]
