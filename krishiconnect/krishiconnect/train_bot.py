import json
import joblib
import os
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS 
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler 
from sklearn.naive_bayes import MultinomialNB
from nltk.stem import PorterStemmer 
from sklearn.pipeline import make_pipeline


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INTENTS_PATH = os.path.join(BASE_DIR, 'intents.json')
MODEL_PATH = os.path.join(BASE_DIR, 'chatbot_model.pkl')
RESPONSES_PATH = os.path.join(BASE_DIR, 'bot_responses.pkl')

stemmer = PorterStemmer()

def preprocess_text(text):
    """Applies lowercasing, stop word removal, and stemming."""
    text = text.lower()
    words = [stemmer.stem(word) for word in text.split() if word not in ENGLISH_STOP_WORDS]
    return " ".join(words)

def train_and_save_model():
    print(f"Loading intents from {INTENTS_PATH}...")
    
    try:
        with open(INTENTS_PATH, 'r', encoding='utf-8') as file:
            intents = json.load(file)
    except FileNotFoundError:
        print("Error: intents.json not found! Please create it first.")
        return

    X_train, y_train, tag_to_responses = [], [], {}

    for intent in intents['intents']:
        tag = intent['tag']
        tag_to_responses[tag] = intent['responses']
        for pattern in intent['patterns']:
            X_train.append(preprocess_text(pattern))
            y_train.append(tag)

    print("Training the Naive Bayes model...")
    model = make_pipeline(
        TfidfVectorizer(
            ngram_range=(1, 2), # Use unigrams and bigrams
            stop_words=list(ENGLISH_STOP_WORDS) # Convert frozenset to list for compatibility
        ),
        StandardScaler(with_mean=False),
        LogisticRegression(solver='lbfgs', C=1.0, max_iter=1000, random_state=42)
    )
    model.fit(X_train, y_train)

    print("Saving the model and responses...")
    joblib.dump(model, MODEL_PATH)
    joblib.dump(tag_to_responses, RESPONSES_PATH)
    print("✅ Training complete! Models safely saved as .pkl files.")

if __name__ == "__main__":
    train_and_save_model()
