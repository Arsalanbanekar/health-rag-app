"""
Query Classifier Module
Parses user queries to categorize them according to the approved 
taxonomy of Topics and Categories for downstream metadata filtering.
"""
import re
import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# Approved Taxonomies
TOPICS = [
    "Hair Health", "Weight Loss", "Muscle Building", "Nutrition", 
    "Skin Health", "Cardiovascular Health", "Digestive Health", 
    "Sleep", "Hormones", "General Wellness"
]

CATEGORIES = [
    "Causes", "Symptoms", "Diagnosis", "Prevention", "Treatment", 
    "Nutrition", "Exercise", "Supplements", "Lifestyle", "Research"
]

def classify_query(query: str) -> Dict[str, Optional[str]]:
    """
    Classifies the user query using high-density keyword maps.
    Returns:
        Dict containing Optional[str] 'topic' and 'category'.
    """
    q_lower = query.lower()
    
    extracted_topic = None
    extracted_category = None
    
    # Topic keyword maps
    topic_keywords = {
        "Hair Health": [r"\bhair\b", r"\bbald", r"\balopecia\b", r"\bminoxidil\b", r"\bfinasteride\b", r"\brogaine", r"\bpropecia", r"\bfollicle"],
        "Weight Loss": [r"\bweight\s*loss\b", r"\bfat\s*loss\b", r"\blose\s*weight\b", r"\bdieting\b", r"\bcaloric\s*deficit\b", r"\bcut\b", r"\bbmr\b", r"\btdee\b", r"\bcalorie\b"],
        "Muscle Building": [r"\bmuscle\b", r"\bhypertrophy\b", r"\bbulk", r"\bstrength\b", r"\blifting\b", r"\bcreatine\b", r"\bprogressive\s*overload\b", r"\bbench\s*press\b", r"\bsquat", r"\bdeadlift"],
        "Nutrition": [r"\bnutrition\b", r"\bdiet\b", r"\bmacros\b", r"\bprotein\b", r"\bcarb\b", r"\bfat\b", r"\bvitamin", r"\bmineral", r"\biron\b", r"\bmagnesium\b", r"\bferritin\b"],
        "Skin Health": [r"\bskin\b", r"\bacne\b", r"\btretinoin\b", r"\bdermatolog", r"\bpimple", r"\bbenzoyl\s*peroxide\b", r"\bsalicylic\b"],
        "Cardiovascular Health": [r"\bheart\b", r"\bcardio\b", r"\bblood\s*pressure\b", r"\bcholesterol\b", r"cvd", r"\bhypertension\b"],
        "Digestive Health": [r"\bgut\b", r"\bdigest", r"\bbloat", r"\bmicrobiome\b", r"\bprobiotic", r"\bprebiotic", r"\bfiber\b", r"\bibs\b", r"\bstomach\b"],
        "Sleep": [r"\bsleep\b", r"\binsomnia\b", r"\bmelatonin\b", r"\bcircadian\b", r"\brem\b", r"\bbedtime\b"],
        "Hormones": [r"\bhormone", r"\btestosterone\b", r"\bestrogen\b", r"\bthyroid\b", r"\bcortisol\b", r"\btsh\b", r"\bt3\b", r"\bt4\b", r"\bpcos\b"],
        "General Wellness": [r"\bwellness\b", r"\bstress\b", r"\banxiety\b", r"\bmeditat", r"\bbreath", r"\bforest\s*bath", r"\bcbt\b", r"\bmental\s*health\b", r"\bimmunit", r"\bimmune\b", r"\bcold\b", r"\bflu\b"]
    }
    
    # Category keyword maps
    category_keywords = {
        "Causes": [r"\bcause", r"\bwhy\b", r"\broot\b", r"\btrigger", r"\betiolog"],
        "Symptoms": [r"\bsymptom", r"\bsign", r"\bfeel\b", r"\bwarn", r"\bindicat"],
        "Diagnosis": [r"\bdiagnos", r"\btest\b", r"\bcheck\b", r"\bscreen\b", r"\bblood\s*work\b", r"\bpanel\b"],
        "Prevention": [r"\bprevent", r"\bavoid\b", r"\bstop\b", r"\breduce\s*risk\b", r"\bprotect\b"],
        "Treatment": [r"\btreat", r"\bcure\b", r"\bmedicin", r"\bdrug\b", r"\bprescrip", r"\bdosage\b", r"\bheal\b"],
        "Nutrition": [r"\beat\b", r"\bfood\b", r"\bdiet\b", r"\bmeal\b", r"\brecipe\b", r"\bnutrition"],
        "Exercise": [r"\bexercise\b", r"\bworkout\b", r"\btrain\b", r"\blift\b", r"\bcardio\b", r"\bgym\b", r"\bneat\b"],
        "Supplements": [r"\bsupplement\b", r"\bpill\b", r"\bpowder\b", r"\bcreatine\b", r"\bwhey\b", r"\bmelatonin\b"],
        "Lifestyle": [r"\blifestyle\b", r"\bhabit\b", r"\bstress\b", r"\broutine\b", r"\bsleep\s*hygiene\b"],
        "Research": [r"\bresearch\b", r"\bstudy\b", r"\bclinical\s*trial\b", r"\bevidence\b", r"\bpub-?med", r"\bmeta-analysis\b"]
    }

    # Regex matches
    for topic, pattern_list in topic_keywords.items():
        if any(re.search(pat, q_lower) for pat in pattern_list):
            extracted_topic = topic
            break

    for cat, pattern_list in category_keywords.items():
        if any(re.search(pat, q_lower) for pat in pattern_list):
            extracted_category = cat
            break

    logger.info(f"Classifier output: Topic={extracted_topic}, Category={extracted_category}")
    return {"topic": extracted_topic, "category": extracted_category}
