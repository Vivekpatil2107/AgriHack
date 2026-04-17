import random
import joblib
import os
import json
import logging

logger = logging.getLogger(__name__)

# Build absolute paths so Django can find the files regardless of where manage.py is run from
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH = os.path.join(BASE_DIR, 'chatbot_model.pkl')
RESPONSES_PATH = os.path.join(BASE_DIR, 'bot_responses.pkl')
INTENTS_PATH = os.path.join(BASE_DIR, 'intents.json')

# Configure the confidence threshold for responses. This value needs to be tuned.
CONFIDENCE_THRESHOLD = 0.055 # A good starting point, adjust based on testing (e.g., 0.60 to 0.80)

model = None
tag_to_responses = None

try:
    model = joblib.load(MODEL_PATH)
    tag_to_responses = joblib.load(RESPONSES_PATH)
    logger.info("Chatbot brain successfully loaded.")
except FileNotFoundError:
    logger.error("Chatbot model files not found! Please run 'python train_bot.py' to generate them.")

def get_all_patterns():
    """Returns a list of all patterns from intents.json for autocomplete."""
    patterns = []
    try:
        with open(INTENTS_PATH, 'r', encoding='utf-8') as f:
            intents_data = json.load(f)
            for intent in intents_data.get('intents', []):
                if 'patterns' in intent:
                    patterns.extend(intent['patterns'])
    except FileNotFoundError:
        logger.error(f"Could not find {INTENTS_PATH}. Make sure it exists in {BASE_DIR}")
    logger.info(f"Loaded {len(patterns)} patterns for autocomplete.")
    return sorted(list(set(patterns))) # Return unique and sorted patterns

def get_response(user_input):
    if model is None or tag_to_responses is None:
        return "The chatbot is currently undergoing maintenance. Please try again later!"

    predicted_tag = model.predict([user_input])[0]
    
    probabilities = model.predict_proba([user_input])[0]
    max_prob = max(probabilities)

    logger.info(f"Input: '{user_input}' | Predicted Intent: '{predicted_tag}' | Confidence: {max_prob:.4f}")

    if max_prob < CONFIDENCE_THRESHOLD:
        logger.warning(f"Low confidence prediction for '{user_input}'. Predicted: '{predicted_tag}' with {max_prob:.4f} confidence.")
        return "I'm not quite sure I understand. Could you rephrase your question or provide more details?"

    return random.choice(tag_to_responses[predicted_tag])
