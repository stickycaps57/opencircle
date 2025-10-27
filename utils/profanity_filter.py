from detoxify import Detoxify
import re
from better_profanity import profanity


# Initialize detoxify model (use 'original' for faster performance)
detoxify_model = Detoxify('original')

# Basic profanity word list for censoring (you can expand this)
# You can use the 'better_profanity' package to get a comprehensive profanity word list
try:
    PROFANITY_WORDS = profanity.CENSOR_WORDSET
except ImportError:
    # Fallback to a basic list if package is not available
    PROFANITY_WORDS = [
        'fuck', 'shit', 'bitch', 'ass', 'damn', 'hell', 'bastard', 'crap',
        'piss', 'dick', 'cock'
    ]

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

    # Convert all profanity words to strings to avoid SQLAlchemy type issues
    profanity_words_str = [str(word) for word in PROFANITY_WORDS]
    pattern = re.compile(r'\b(' + '|'.join(re.escape(word) for word in profanity_words_str) + r')\b', re.IGNORECASE)

    return pattern.sub(replace, text)

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

    toxicity_check = check_toxicity(text, toxicity_threshold)
    if toxicity_check["is_toxic"]:
        if auto_censor:
            censored_text = censor_profanity(text)

            return {
                "approved": True,
                "moderated_text": censored_text,
                "reason": "Content was automatically censored due to profanity"
            }
        else:
            scores = toxicity_check["scores"]
            reasons = []
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
