"""
Tagging Module
Assigns controlled-vocabulary tags to chunks.

Why a controlled vocabulary rather than keyword extraction:
retrieval filters on `md.tags && filter_tags` (Postgres array overlap, exact
string match) against the fixed lists in services/retrieval/metadata_filter.py.
Free-form tags would simply never intersect those lists, so every filtered
search would return nothing and the pipeline would fall through to unfiltered
global search — hybrid retrieval silently degraded to plain vector search, with
no error anywhere. Tags therefore have to be drawn from the same vocabulary the
filters use.

All tags are lowercase. Array overlap is case-sensitive, so "CVD" in a row and
"cvd" in a filter do not match; lowercasing both sides removes that trap.
"""
import logging
import re
from typing import Dict, List, Set

from services.retrieval.metadata_filter import TOPIC_TO_TAGS_MAP

logger = logging.getLogger(__name__)

# ────────────────────────────────────────────────────────────
# CONTROLLED VOCABULARY
# canonical tag -> alias patterns that imply it.
# Matching is case-insensitive whole-word.
# ────────────────────────────────────────────────────────────
TAG_VOCABULARY: Dict[str, List[str]] = {
    # Hair
    "alopecia": ["alopecia", "pattern baldness", "balding", "bald"],
    "hair follicle": ["hair follicle", "follicular", "anagen", "telogen"],
    "minoxidil": ["minoxidil", "rogaine"],
    "finasteride": ["finasteride", "propecia"],
    "dht": ["dht", "dihydrotestosterone"],
    # Weight
    "caloric deficit": ["caloric deficit", "calorie deficit", "energy balance"],
    "fat loss": ["fat loss", "body fat", "adiposity"],
    "dieting": ["diet", "dieting", "weight loss"],
    "fasting": ["fasting", "intermittent fasting", "eating window"],
    "tdee": ["tdee", "total daily energy", "bmr", "basal metabolic"],
    "obesity": ["obesity", "obese", "overweight", "bmi"],
    # Muscle / exercise
    "progressive overload": ["progressive overload"],
    "hypertrophy": ["hypertrophy", "muscle growth", "muscle mass"],
    "creatine": ["creatine"],
    "lifting": ["resistance training", "strength training", "weight training", "lifting"],
    "squat": ["squat", "deadlift", "bench press", "compound movement"],
    "cardio": ["cardio", "aerobic", "endurance", "hiit"],
    # Nutrition
    "protein": ["protein", "amino acid", "leucine", "whey"],
    "macros": ["macronutrient", "macros", "carbohydrate", "dietary fat"],
    "vitamin d": ["vitamin d", "cholecalciferol", "25-hydroxyvitamin"],
    "vitamin c": ["vitamin c", "ascorbic acid"],
    "biotin": ["biotin", "vitamin b7"],
    "zinc": ["zinc"],
    "iron": ["iron", "ferritin", "anemia", "anaemia"],
    "magnesium": ["magnesium"],
    "omega-3": ["omega-3", "omega 3", "epa", "dha", "fish oil"],
    "fiber": ["fiber", "fibre"],
    "supplementation": ["supplement", "supplementation", "dietary supplement"],
    "deficiency": ["deficiency", "deficient", "insufficiency"],
    # Skin
    "acne": ["acne", "pimple", "comedone", "blackhead"],
    "benzoyl peroxide": ["benzoyl peroxide"],
    "tretinoin": ["tretinoin", "retinoid", "isotretinoin", "accutane"],
    "salicylic": ["salicylic"],
    # Cardiovascular
    "cvd": ["cardiovascular disease", "cvd", "heart disease", "coronary"],
    "cholesterol": ["cholesterol", "lipid", "triglyceride", "statin"],
    "ldl": ["ldl", "low-density lipoprotein", "hdl"],
    "blood pressure": ["blood pressure", "hypertension", "systolic", "diastolic"],
    "stroke": ["stroke"],
    # Digestive
    "microbiome": ["microbiome", "gut bacteria", "gut flora"],
    "probiotics": ["probiotic", "lactobacillus", "bifidobacterium"],
    "prebiotics": ["prebiotic"],
    "ibs": ["ibs", "irritable bowel"],
    # Sleep
    "sleep hygiene": ["sleep hygiene", "sleep quality", "bedtime"],
    "melatonin": ["melatonin"],
    "circadian rhythm": ["circadian"],
    "rem": ["rem sleep", "rapid eye movement"],
    "insomnia": ["insomnia", "sleep disorder", "sleep apnea"],
    # Hormones
    "testosterone": ["testosterone", "androgen"],
    "cortisol": ["cortisol"],
    "thyroid": ["thyroid", "hypothyroid", "hyperthyroid", "levothyroxine"],
    "tsh": ["tsh", "thyroid stimulating"],
    "t3": ["triiodothyronine", r"\bt3\b"],
    "t4": ["thyroxine", r"\bt4\b"],
    "insulin": ["insulin", "diabetes", "glucose", "a1c"],
    # Wellness
    "meditation": ["meditation", "mindfulness"],
    "immunity": ["immune", "immunity", "infection"],
    "stress": ["stress", "anxiety", "burnout"],
    "mental health": ["mental health", "depression", "therapy"],
    "exercise": ["exercise", "physical activity", "workout"],
    "smoking": ["smoking", "tobacco", "nicotine"],
}

# ────────────────────────────────────────────────────────────
# ANCHOR TAGS
# Applied to every chunk of a topic regardless of text content.
#
# These guarantee the array-overlap filter always has something to match on, so
# a chunk can never become invisible to filtered retrieval just because its
# wording avoided the vocabulary. Each entry MUST be a member of that topic's
# list in TOPIC_TO_TAGS_MAP — enforced by validate_vocabulary().
# ────────────────────────────────────────────────────────────
ANCHOR_TAGS: Dict[str, List[str]] = {
    "Hair Health": ["alopecia", "hair follicle"],
    "Weight Loss": ["fat loss", "dieting"],
    "Muscle Building": ["hypertrophy", "lifting"],
    "Nutrition": ["macros", "protein"],
    "Skin Health": ["acne"],
    "Cardiovascular Health": ["cvd", "blood pressure"],
    "Digestive Health": ["microbiome", "fiber"],
    "Sleep": ["sleep hygiene", "circadian rhythm"],
    "Hormones": ["testosterone", "thyroid"],
    "General Wellness": ["immunity", "meditation"],
}

MAX_TAGS_PER_CHUNK = 10

_COMPILED: Dict[str, List[re.Pattern]] = {
    tag: [
        re.compile(alias if alias.startswith(r"\b") else r"\b" + re.escape(alias), re.IGNORECASE)
        for alias in aliases
    ]
    for tag, aliases in TAG_VOCABULARY.items()
}


def validate_vocabulary() -> List[str]:
    """
    Check the tagger against the retrieval filters. Returns a list of errors.

    Run at seed time. Catches the failure mode where someone edits
    TOPIC_TO_TAGS_MAP or ANCHOR_TAGS and quietly breaks filtered retrieval for a
    whole topic — a bug that otherwise produces no error, just worse answers.
    """
    errors: List[str] = []

    for topic, anchors in ANCHOR_TAGS.items():
        filter_tags = TOPIC_TO_TAGS_MAP.get(topic)
        if filter_tags is None:
            errors.append(f"Topic '{topic}' has anchors but no entry in TOPIC_TO_TAGS_MAP.")
            continue

        filter_set = {t.lower() for t in filter_tags}
        for anchor in anchors:
            if anchor.lower() not in filter_set:
                errors.append(
                    f"Anchor tag '{anchor}' for topic '{topic}' is not in "
                    f"TOPIC_TO_TAGS_MAP['{topic}'] ({sorted(filter_set)}). "
                    f"Chunks tagged this way would never match a filtered search."
                )

    for topic in TOPIC_TO_TAGS_MAP:
        if topic not in ANCHOR_TAGS:
            errors.append(f"Topic '{topic}' has filter tags but no anchor tags defined.")

    return errors


def extract_tags(text: str, topic: str, heading: str = "") -> List[str]:
    """
    Tag a chunk: vocabulary matches found in its text, plus the topic anchors.

    The heading is searched too — section titles like "Symptoms" or "Treatment"
    carry signal the body sometimes only implies.
    """
    haystack = f"{heading} {text}"
    matched: Set[str] = set()

    for tag, patterns in _COMPILED.items():
        if any(pattern.search(haystack) for pattern in patterns):
            matched.add(tag)

    anchors = [t.lower() for t in ANCHOR_TAGS.get(topic, [])]
    matched.update(anchors)

    # Order matters because of MAX_TAGS_PER_CHUNK: whatever falls off the end is
    # lost. Anchors first (they carry the retrieval guarantee), then tags this
    # topic actually filters on, then everything else. Without this a hair-loss
    # chunk that happens to mention stress and smoking can push "minoxidil" and
    # "biotin" off the list.
    topic_filter_tags = {t.lower() for t in TOPIC_TO_TAGS_MAP.get(topic, [])}
    remaining = matched - set(anchors)

    on_topic = sorted(t for t in remaining if t in topic_filter_tags)
    off_topic = sorted(remaining - topic_filter_tags)

    return (anchors + on_topic + off_topic)[:MAX_TAGS_PER_CHUNK]
