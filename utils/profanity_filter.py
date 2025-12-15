from detoxify import Detoxify
import re
from better_profanity import profanity


# Initialize detoxify model (use 'original' for faster performance)
detoxify_model = Detoxify('original')

# Filipino/Tagalog profanity words to add to the existing wordset
FILIPINO_PROFANITY_WORDS = [
    # Filipino/Tagalog profanity - common curse words
    'putang', 'putangina', 'puta', 'tangina', 'tanga', 'gago', 'gaga',
    'ulol', 'bobo', 'kingina', 'leche', 'peste', 'pokpok', 'tarantado',
    'hudas', 'kupal', 'kantot', 'pakyu', 'tamod', 'bayag',
    'bilat', 'etits', 'jakol', 'kantutan', 'iyot', 'hindot', 'ungas',
    # Variations and common misspellings
    'putanginamo', 'putanginang', 'gagong', 'bobong', 'tangong',
    'ulul', 'hinayupak', 'amputa', 'tanginamo', 'pakinggan',
    'walanghiya', 'walang hiya', 'shet', 'p0ta', 'p*ta', 'tang*na',
    'g*go', 'b*bo', 'ul*l', 'put*ng*na'
]

# Basic profanity word list for censoring (you can expand this)
# You can use the 'better_profanity' package to get a comprehensive profanity word list
try:
    # Convert to list and combine with Filipino profanity words
    # Ensure all words are properly converted to strings
    english_words = [str(word) for word in profanity.CENSOR_WORDSET]
    PROFANITY_WORDS = english_words + FILIPINO_PROFANITY_WORDS
except ImportError:
    # Fallback to a basic list if package is not available including Filipino/Tagalog profanity
    PROFANITY_WORDS = [
        # English profanity
        'fuck', 'shit', 'bitch', 'ass', 'damn', 'hell', 'bastard', 'crap',
        'piss', 'dick', 'cock'
    ] + FILIPINO_PROFANITY_WORDS

def check_toxicity(text: str, threshold: float = 0.7) -> dict:
    """
    Check toxicity of the text using Detoxify.
    Returns a dict with is_toxic (bool) and scores (dict).
    """
    if not text or not text.strip():
        return {"is_toxic": False, "scores": {}}
    
    # Ensure text is a proper Python string
    text = str(text) if text is not None else ""
    
    results = detoxify_model.predict(text)
    is_toxic = (
        results.get('toxicity', 0) > threshold or
        results.get('severe_toxicity', 0) > threshold or
        results.get('obscene', 0) > threshold or
        results.get('threat', 0) > threshold or
        results.get('insult', 0) > threshold or
        results.get('identity_attack', 0) > threshold
    )
    return {
        "is_toxic": is_toxic,
        "scores": results
    }

def censor_profanity(text: str) -> str:
    """
    Censor profane words in text using a basic word list.
    Args:
        text: The text to censor
    Returns:
        Censored text with profane words replaced by asterisks
    """
    # Ensure text is a proper Python string
    text = str(text) if text is not None else ""

    if not text or not text.strip():
        return text

    # Ensure all profanity words are strings (they should be already, but double-check)
    profanity_words_str = [str(word).lower() for word in PROFANITY_WORDS if word and str(word).strip()]
    
    # Create pattern with word boundaries for exact matches
    if profanity_words_str:
        pattern = re.compile(r'\b(' + '|'.join(re.escape(word) for word in profanity_words_str) + r')\b', re.IGNORECASE)
        return pattern.sub(replace, text)
    
    return text

def replace(match):
    word = match.group(0)
    return "*" * len(word)


def moderate_text(text: str, toxicity_threshold: float = 0.7, auto_censor: bool = False) -> dict:
    """
    Moderate text for toxicity and optionally censor profanity.
    Args:
        text: The text to moderate
        toxicity_threshold: Toxicity threshold (0-1)
        auto_censor: If True, automatically censor profanity instead of rejecting
    Returns:
        dict with 'approved' (bool), 'moderated_text' (str), 'reason' (str)
    """
    if not text:
        return {
            "approved": True,
            "moderated_text": text,
            "reason": None
        }

    # Ensure text is a proper Python string
    text = str(text).strip() if text is not None else ""

    if not text:
        return {
            "approved": True,
            "moderated_text": "",
            "reason": None
        }

    # Check for profanity first (regardless of toxicity detection)
    censored_text = censor_profanity(text)
    has_profanity = censored_text != text
    
    # Check toxicity
    toxicity_check = check_toxicity(text, toxicity_threshold)
    is_toxic = toxicity_check["is_toxic"]
    
    # If we have profanity or toxicity
    if has_profanity or is_toxic:
        if auto_censor:
            return {
                "approved": True,
                "moderated_text": censored_text,
                "reason": "Content was automatically censored due to profanity" if has_profanity else "Content was automatically censored due to toxicity"
            }
        else:
            reasons = []
            if has_profanity:
                reasons.append("profanity detected")
            if is_toxic:
                scores = toxicity_check["scores"]
                if scores.get('toxicity', 0) > toxicity_threshold:
                    reasons.append(f"toxicity ({scores['toxicity']:.2f})")
                if scores.get('obscene', 0) > toxicity_threshold:
                    reasons.append(f"obscene language ({scores['obscene']:.2f})")
                if scores.get('insult', 0) > toxicity_threshold:
                    reasons.append(f"insults ({scores['insult']:.2f})")
                if scores.get('threat', 0) > toxicity_threshold:
                    reasons.append(f"threats ({scores['threat']:.2f})")
            return {
                "approved": False,
                "moderated_text": text,
                "reason": f"Content contains inappropriate language: {', '.join(reasons)}"
            }
    
    return {
        "approved": True,
        "moderated_text": text,
        "reason": None
    }
