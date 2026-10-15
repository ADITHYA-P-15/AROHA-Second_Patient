# Machine-drafted — needs native-speaker review before real use.
"""Small multilingual phrase lists used by the deterministic escalation classifier."""

RULES = [
    {"id":"emergency_chest", "level":5,"category":"EMERGENCY","languages":["en","hi","kn","te"],"patterns":["chest pain","chest pressure","सीने में दर्द","seene mein dard","ಎದೆ ನೋವು","ಎದೆನೋವು","ఛాతి నొప్పి"]},
    {"id":"emergency_breathing", "level":5,"category":"EMERGENCY","languages":["en","hi","kn","te"],"patterns":["can't breathe","cannot breathe","breathless","choking","सांस नहीं आ रही","saans nahi aa rahi","ಉಸಿರಾಡಲು ಕಷ್ಟ","ఊపిరి ఆడటం లేదు"]},
    {"id":"emergency_unresponsive", "level":5,"category":"EMERGENCY","languages":["en","hi","kn","te"],"patterns":["unconscious","fainted","not responding","not waking","बेहोश","behosh","ಪ್ರಜ್ಞೆ ತಪ್ಪಿ","స్పృహ లేదు"]},
    {"id":"emergency_bleeding", "level":5,"category":"EMERGENCY","languages":["en","hi"],"patterns":["severe bleeding","heavy bleeding","खून बहुत","khoon bahut"]},
    {"id":"emergency_stroke", "level":5,"category":"EMERGENCY","languages":["en"],"patterns":["face drooping","slurred speech","one sided weakness","one side weakness","one sided numbness","can't speak"]},
    {"id":"emergency_seizure", "level":5,"category":"EMERGENCY","languages":["en","hi"],"patterns":["seizure","having a fit","fit","दौरा","daura"]},
    {"id":"emergency_fall", "level":5,"category":"EMERGENCY","languages":["en"],"patterns":["fell and hit my head","fall with head injury","head injury","unable to get up","fell and cannot get up","cannot get up in pain"]},
    {"id":"emergency_confusion", "level":5,"category":"EMERGENCY","languages":["en"],"patterns":["sudden confusion","suddenly confused"]},
    {"id":"emergency_allergy", "level":5,"category":"EMERGENCY","languages":["en"],"patterns":["severe allergic reaction","face swelling","swelling of face","swelling of my face"]},
    {"id":"emergency_overdose", "level":5,"category":"EMERGENCY","languages":["en"],"patterns":["overdose","took too many tablets","too many pills"]},
    {"id":"emergency_self_harm", "level":5,"category":"EMERGENCY","languages":["en","hi"],"patterns":["self harm","want to die","kill myself","खुद को मार","khud ko maar"]},
    {"id":"emergency_explicit", "level":5,"category":"EMERGENCY","languages":["en"],"patterns":["emergency","sos","ambulance","help me please i'm dying","help me i'm dying"]},
    {"id":"medication_missed", "level":4,"category":"MEDICATION","languages":["en"],"patterns":["missed my medicine twice","missed medicine two times","missed my medication twice","missed critical medicine"]},
    {"id":"health_worsening", "level":4,"category":"HEALTH_CONCERN","languages":["en"],"patterns":["getting worse","worsening","not improving","keeps coming back","recurring symptom","persistent fever","fever for days","new swelling"]},
    {"id":"medication_side_effect", "level":4,"category":"MEDICATION","languages":["en"],"patterns":["rash after tablet","vomiting after tablet","dizzy after tablet","side effect"]},
    {"id":"health_concern", "level":3,"category":"HEALTH_CONCERN","languages":["en","hi","kn","te"],"patterns":["pain","dizzy","dizziness","vomiting","fever","cough","swelling","wound","poor sleep","not feeling well","uncomfortable","very tired","चक्कर","बुखार","ನೋವು","ತಲೆ ಸುತ್ತು","జ్వరం","నొప్పి"]},
    {"id":"logistics", "level":2,"category":"LOGISTICS","languages":["en"],"patterns":["nobody came","caretaker didn't come","need transport","no one to take me","medicines finished","medicine ran out","missed my appointment","can't reach anyone"]},
    {"id":"medication_missed_once", "level":1,"category":"MEDICATION","languages":["en"],"patterns":["missed my medicine","missed my medication","missed my tablet","forgot my medicine","forgot my tablet","didn't get my medicine","did not get my medicine"]},
    {"id":"daily_help", "level":1,"category":"DAILY_HELP","languages":["en","hi"],"patterns":["need water","need food","help me stand","help me walk","help me to the bathroom","help me bathe","help with tv","help with phone","i need something","पानी चाहिए","paani chahiye"]},
    {"id":"positive_update", "level":0,"category":"INFO","languages":["en"],"patterns":["took my medicine","ate lunch","slept well","feeling better","thank you"]},
]

INTENSITY = ["very", "severe", "unbearable", "worst", "suddenly", "बहुत", "ತುಂಬಾ", "చాలా"]
PERSISTENCE = ["since morning", "for 3 days", "for three days", "again", "keeps happening"]
NEGATIONS = ["no", "not", "without", "never", "नहीं", "ಇಲ್ಲ", "లేదు"]
FALL_WORDS = ["fall", "fell", "fallen"]
