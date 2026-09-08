"""
Approved Taxonomy
Shared vocabulary for topics, categories and source types.

Extracted from scripts/seed_database.py so the ingestion pipeline and the
seeding script validate against exactly one definition. Field names are
unchanged — this is the same metadata schema, just importable.
"""
from typing import Optional
import re

VALID_TOPICS = {
    "Hair Health", "Weight Loss", "Muscle Building", "Nutrition",
    "Skin Health", "Cardiovascular Health", "Digestive Health",
    "Sleep", "Hormones", "General Wellness",
}

VALID_CATEGORIES = {
    "Causes", "Symptoms", "Diagnosis", "Prevention", "Treatment",
    "Nutrition", "Exercise", "Supplements", "Lifestyle", "Research",
}

VALID_SOURCE_TYPES = {
    "systematic_review", "meta_analysis", "clinical_trial",
    "clinical_guideline", "review_article", "position_stand",
    "reference_standard",
    # Consumer-facing fact sheets from government health resources
    # (MedlinePlus, NIH ODS, CDC). Authoritative and well-reviewed, but
    # patient education rather than primary research — labelling them as
    # systematic_review would overstate them in the UI's source panel.
    "government_health_resource",
}

# Credibility defaults by source type, surfaced in the UI source panel.
DEFAULT_CREDIBILITY = {
    "systematic_review": 0.95,
    "meta_analysis": 0.95,
    "clinical_trial": 0.94,
    "clinical_guideline": 0.93,
    "position_stand": 0.94,
    "reference_standard": 0.92,
    "review_article": 0.90,
    "government_health_resource": 0.95,
}

# Section heading -> category. First match wins, so order matters: the more
# specific patterns are listed before the general ones.
#
# MedlinePlus topic-summary sections are headed with natural questions rather
# than clean single-word labels — "What causes long-term stress?", "How are
# sleep disorders diagnosed?", "Who is more likely to develop heart disease?" —
# so patterns need to catch question phrasing, not just the bare noun.
HEADING_CATEGORY_PATTERNS = [
    (re.compile(r"\b(cause|risk factor|why|etiolog|who is (more likely|at risk))", re.I), "Causes"),
    (re.compile(r"\b(symptom|sign|what does it feel|warning sign)", re.I), "Symptoms"),
    (re.compile(r"\b(diagnos|screen|exam(ine|ination)?\b|blood work|health care provider|see a doctor|when (should|to) (i|you))", re.I), "Diagnosis"),
    (re.compile(r"\b(prevent|avoid|reduce (my |your )?risk|protect)", re.I), "Prevention"),
    (re.compile(r"\b(treat|therap|medicat|drug|surgery|manage|cure)", re.I), "Treatment"),
    (re.compile(r"\b(supplement|vitamin|mineral|dose|dosage)", re.I), "Supplements"),
    (re.compile(r"\b(exercis|physical activity|workout|training|fitness)", re.I), "Exercise"),
    (re.compile(r"\b(diet|nutrition|food|eating|meal)", re.I), "Nutrition"),
    (re.compile(r"\b(lifestyle|habit|daily|routine|coping|stay healthy|keep .* healthy|good night)", re.I), "Lifestyle"),
    (re.compile(r"\b(research|stud(y|ies)|clinical trial|evidence|statistic)", re.I), "Research"),
]

# Fallback for when the heading gives no signal at all (e.g. "What is X?",
# "What are the parts of X?", or a page with no sub-headings). Same categories,
# scored against the chunk body rather than a short heading, so a category
# needs multiple keyword occurrences to win — one incidental word should not
# be enough to file a whole chunk under a category.
_CONTENT_MIN_OCCURRENCES = 2


def category_from_heading(heading: str) -> Optional[str]:
    """
    Infer a category from a section heading, or None if nothing matches.

    Callers fall back to category_from_text(), then the source's declared
    default category.
    """
    if not heading:
        return None
    for pattern, category in HEADING_CATEGORY_PATTERNS:
        if pattern.search(heading):
            return category
    return None


def category_from_text(text: str) -> Optional[str]:
    """
    Infer a category from chunk body text when the heading gave no signal.

    Scores each category by how many times its keyword pattern occurs in the
    text, and returns the top scorer only if it clears a minimum count — a
    single incidental word (e.g. "test" appearing once in a 500-token chunk)
    should not be enough to file the whole chunk under Diagnosis.
    """
    if not text:
        return None

    scores: dict[str, int] = {}
    for pattern, category in HEADING_CATEGORY_PATTERNS:
        hits = len(pattern.findall(text))
        if hits:
            scores[category] = scores.get(category, 0) + hits

    if not scores:
        return None

    best_category = max(scores, key=scores.get)
    if scores[best_category] < _CONTENT_MIN_OCCURRENCES:
        return None
    return best_category
