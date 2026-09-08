"""
Metadata Filtering Module
Structures category and tag filters depending on query classifications.
"""
from typing import Dict, Any, List, Optional

# Match topic keywords to document tags to increase retrieval accuracy.
#
# All tags are lowercase. The SQL filter is `md.tags && filter_tags`, a
# case-sensitive array overlap — "CVD" stored on a row does not match "cvd" in a
# filter. Keeping both sides lowercase (see services/ingestion/tagger.py, which
# lowercases every tag it writes) removes that mismatch.
TOPIC_TO_TAGS_MAP = {
    "Hair Health": ["alopecia", "minoxidil", "finasteride", "hair follicle", "biotin"],
    "Weight Loss": ["caloric deficit", "fat loss", "fasting", "dieting", "cardio", "tdee"],
    "Muscle Building": ["progressive overload", "hypertrophy", "creatine", "squat", "lifting"],
    "Nutrition": ["macros", "vitamin d", "biotin", "zinc", "iron", "protein"],
    "Skin Health": ["acne", "benzoyl peroxide", "tretinoin", "salicylic"],
    "Cardiovascular Health": ["cvd", "cholesterol", "blood pressure", "ldl"],
    "Digestive Health": ["microbiome", "probiotics", "prebiotics", "fiber"],
    "Sleep": ["sleep hygiene", "melatonin", "circadian rhythm", "rem"],
    "Hormones": ["testosterone", "cortisol", "thyroid", "tsh", "t3", "t4"],
    "General Wellness": ["cortisol", "meditation", "immunity", "zinc", "vitamin c"]
}

def build_metadata_filters(classification: Dict[str, Optional[str]]) -> Dict[str, Any]:
    """
    Transforms extracted query classifications into SQL-ready query filters.
    """
    topic = classification.get("topic")
    category = classification.get("category")
    
    filter_category: Optional[str] = category
    filter_tags: Optional[List[str]] = None
    
    # If a topic was classified, supply matching tags to focus the search
    if topic in TOPIC_TO_TAGS_MAP:
        filter_tags = TOPIC_TO_TAGS_MAP[topic]
        
    return {
        "filter_category": filter_category,
        "filter_tags": filter_tags
    }
