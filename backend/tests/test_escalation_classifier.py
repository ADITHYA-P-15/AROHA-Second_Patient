import pytest
from app.engine.escalation_classifier import classify_message

@pytest.mark.parametrize("text,level", [
    ("chest pain",5),("chest pressure",5),("can't breathe",5),("breathless",5),("choking",5),("unconscious",5),("fainted",5),("not responding",5),("not waking",5),("severe bleeding",5),("heavy bleeding",5),("face drooping",5),("slurred speech",5),("one sided weakness",5),("seizure",5),("having a fit",5),("fell and hit my head",5),("unable to get up",5),("sudden confusion",5),("severe allergic reaction",5),("overdose",5),("took too many tablets",5),("self harm",5),("want to die",5),("ambulance",5),("SOS",5),
    ("chest pain please",5),("my chest pressure is bad",5),("I cannot breathe",5),("not responding",5),("not waking",5),("one sided numbness",5),("fit",5),("head injury",5),("cannot get up in pain",5),("swelling of my face",5),("help me I'm dying",5),("खून बहुत निकल रहा",5),("ನನಗೆ ಎದೆ ನೋವು",5),("నాకు ఛాతి నొప్పి",5),("सीने में दर्द",5),("seene mein dard",5),("सांस नहीं आ रही",5),("saans nahi aa rahi",5),("बेहोश",5),("behosh",5),("खून बहुत",5),("ಎದೆ ನೋವು",5),("ಎದೆನೋವು",5),("ಉಸಿರಾಡಲು ಕಷ್ಟ",5),("ಪ್ರಜ್ಞೆ ತಪ್ಪಿ",5),("ఛాతి నొప్పి",5),("ఊపిరి ఆడటం లేదు",5),("స్పృహ లేదు",5),
    ("rash after tablet",4),("vomiting after tablet",4),("dizzy after tablet",4),("getting worse",4),("worsening",4),("keeps coming back",4),("fever for days",4),("new swelling",4),("pain",3),("vomiting",3),("cough",3),("feeling better",0),("ate lunch",0),("medicines finished",2),("missed my appointment",2),("help me to the bathroom",1),("need food",1),("rash after tablet",4),("persistent fever",4),("missed my medicine twice",4),("not improving",4),("dizzy",3),("poor sleep",3),("need water",1),("help me walk",1),("nobody came",2),("need transport",2),("took my medicine",0),("slept well",0),("thank you",0),
])
def test_rules(text, level):
    assert classify_message(text).level == level

@pytest.mark.parametrize("text", ["no chest pain", "not breathless", "without seizure", "never fainted"])
def test_red_flag_negation_routes_to_human_review(text):
    result = classify_message(text)
    assert result.level == 3 and result.negation_detected

@pytest.mark.parametrize("text", ["my husband has chest pain", "my mother is having a seizure"])
def test_third_person_red_flag_stays_emergency(text):
    assert classify_message(text).level == 5

def test_single_missed_medicine_goes_to_the_caretaker_first():
    result = classify_message("I missed my medicine")
    assert result.level == 1 and result.category == "MEDICATION"
    assert classify_message("I missed my medicine twice").level == 4

def test_unknown_is_never_information_and_repeat_raises():
    assert classify_message("blue curtains today").category == "UNCLASSIFIED"
    assert classify_message("blue curtains today").level == 2
    assert classify_message("need water", context={"repeat_category":"DAILY_HELP"}).level == 2

def test_intensity_persistence_repeat_and_critical_activity_modifiers():
    intense=classify_message("very dizzy")
    assert intense.level == 4 and intense.severity == "HIGH"
    persistent=classify_message("dizzy since morning")
    assert persistent.level == 3 and persistent.severity == "HIGH"
    repeated=classify_message("need water",context={"repeat_category":"DAILY_HELP"})
    assert repeated.level == 2 and "repeat_24h" in repeated.modifiers
    critical=classify_message("nobody came",context={"critical_activity_within_3h":True})
    assert critical.severity == "HIGH"

@pytest.mark.parametrize("text", ["pain today", "I feel dizzy", "fever and cough", "not feeling well", "nobody came", "need a ride", "need food", "help with my phone", "I need something", "took my medicine", "feeling better", "no fever", "not dizzy", "without pain"])
def test_symptoms_and_negative_terms_never_become_l0(text):
    result = classify_message(text)
    if any(word in text.lower() for word in ("pain", "dizzy", "fever", "cough", "not", "no", "without")):
        assert result.level > 0

def test_sos_and_mobility_override():
    assert classify_message("hello", sos=True).level == 5
    assert classify_message("I fell", context={"mobility_level":"BEDBOUND"}).level == 5

def test_advisor_only_raises_and_is_deterministic():
    class Advisor:
        def __init__(self, value): self.value = value
        def advise(self, text, context): return self.value
    assert classify_message("chest pain", advisor=Advisor(1)).level == 5
    assert classify_message("need water", advisor=Advisor(4)).level == 4
    assert classify_message("need water", advisor=Advisor(8)).advisor["error"] == "advisor_unavailable"
    assert classify_message("need water").as_dict() == classify_message("need water").as_dict()
