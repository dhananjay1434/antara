
# Standard library imports
import json
import logging
import os
import random
import re
import ssl
import sys
import threading
import time
import uuid
from collections import defaultdict
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from queue import Queue
from typing import Any, Dict, Iterator, List, Optional, Set, Tuple

# Third-party imports
import bcrypt
import google.generativeai as genai
import gradio as gr
import nltk
import numpy as np
import requests
import torch
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from sentence_transformers import SentenceTransformer
from textblob import TextBlob
from transformers import AutoModelForSequenceClassification, AutoTokenizer, pipeline
import feedparser  # For YouTube RSS feeds
import schedule  # For scheduling content fetching

# Conditional imports
try:
    import faiss
except ImportError:
    logging.error("FAISS library not found. Memory recall will not work. Please install it (e.g., `pip install faiss-cpu` or `pip install faiss-gpu`).")
    faiss = None

try:
    from googlesearch import search
except ImportError:
    logging.warning("`googlesearch-python` library not found. News fetching will be disabled. Install with `pip install googlesearch-python`")
    search = None

# Database imports
import sqlite3

# CONSISTENCY FIX: Standardized error handling classes
class StandardError(Exception):
    """Base exception class for consistent error handling."""
    def __init__(self, message: str, error_code: str = None, original_error: Exception = None):
        self.message = message
        self.error_code = error_code
        self.original_error = original_error
        super().__init__(self.message)

class DatabaseError(StandardError):
    """Database-related errors."""
    pass

class ValidationError(StandardError):
    """Input validation errors."""
    pass

class SecurityError(StandardError):
    """Security-related errors."""
    pass

def log_error_consistently(error: Exception, context: str, user_id: str = None):
    """Consistent error logging across the application."""
    error_info = {
        'context': context,
        'error_type': type(error).__name__,
        'error_message': str(error),
        'user_id': user_id
    }

    if isinstance(error, StandardError) and error.original_error:
        error_info['original_error'] = str(error.original_error)

    logging.error(f"Error in {context}: {error_info}", exc_info=True)

# MAGIC NUMBERS FIX: Application constants
class AppConstants:
    """Centralized constants to replace magic numbers."""

    # Memory system constants
    MAX_MEMORIES_PER_USER = 250
    MEMORY_CONSOLIDATION_THRESHOLD = 200
    MEMORY_SIMILARITY_THRESHOLD = 0.5
    MEMORY_RELEVANCE_THRESHOLD = 0.3

    # Interest tracking constants
    INTEREST_SHARING_PROBABILITY = 0.15  # 15% chance to share updates
    INTEREST_CONFIDENCE_INCREMENT = 0.1
    INTEREST_ENGAGEMENT_INCREMENT = 0.05
    MIN_INTEREST_THRESHOLD = 0.3

    # Cache constants
    MAX_TRENDING_CACHE_SIZE = 100
    CACHE_VALIDITY_HOURS = 2

    # Rate limiting constants
    WEB_SEARCH_DELAY_SECONDS = 1
    WEB_REQUEST_TIMEOUT_SECONDS = 15
    MAX_SEARCH_RESULTS = 5

    # Relationship constants
    RELATIONSHIP_DEPTH_INCREMENT = 0.01
    VULNERABILITY_WEIGHT = 0.4

    # Time awareness constants
    RECENT_CHAT_THRESHOLD_HOURS = 1
    DAILY_CHAT_THRESHOLD_HOURS = 24
    WEEKLY_CHAT_THRESHOLD_HOURS = 168

# --- NLTK Download Logic ---
def download_nltk_data():
    """Downloads required NLTK data with robust error handling and fallback."""
    required_packages = ['punkt', 'stopwords']

    for package in required_packages:
        try:
            # Check if package exists
            if package == 'punkt':
                nltk.data.find('tokenizers/punkt')
            elif package == 'stopwords':
                nltk.data.find('corpora/stopwords')
            logging.info(f"NLTK '{package}' package found.")
            continue
        except LookupError:
            logging.info(f"NLTK '{package}' package not found. Attempting download...")

        # Try to download the package
        download_success = False

        # Method 1: Standard download
        try:
            nltk.download(package, quiet=True)
            # Verify download
            if package == 'punkt':
                nltk.data.find('tokenizers/punkt')
            elif package == 'stopwords':
                nltk.data.find('corpora/stopwords')
            logging.info(f"NLTK '{package}' package downloaded successfully.")
            download_success = True
        except Exception as e:
            logging.warning(f"Standard download failed for '{package}': {e}")

        # Method 2: Try with SSL workaround if standard failed
        if not download_success:
            try:
                import ssl
                _original_ssl_context = ssl._create_default_https_context
                ssl._create_default_https_context = ssl._create_unverified_context
                logging.info(f"Attempting NLTK '{package}' download with unverified SSL context.")

                try:
                    nltk.download(package, quiet=True)
                    # Verify download
                    if package == 'punkt':
                        nltk.data.find('tokenizers/punkt')
                    elif package == 'stopwords':
                        nltk.data.find('corpora/stopwords')
                    logging.info(f"NLTK '{package}' package downloaded successfully (SSL workaround).")
                    download_success = True
                except Exception as e:
                    logging.warning(f"SSL workaround download failed for '{package}': {e}")
                finally:
                    ssl._create_default_https_context = _original_ssl_context

            except (AttributeError, ImportError):
                logging.info("SSL workaround not available.")

        # Log final status
        if not download_success:
            logging.warning(f"Failed to download NLTK '{package}' package. Fallback methods will be used.")
            if package == 'punkt':
                logging.info("Sentence tokenization will use regex-based fallback methods.")
        else:
            logging.info(f"NLTK '{package}' package is ready for use.")

    logging.info("NLTK data initialization complete.")

# Call the download function at startup
download_nltk_data()

# === CONFIGURATION ===
class Config:
    """Centralized configuration class."""

    def __init__(self):
        load_dotenv()
        self.gemini_api_key = os.getenv("GEMINI_API_KEY")
        if not self.gemini_api_key:
            # Keep the critical error handling as before
            print("FATAL ERROR: GEMINI_API_KEY not found in environment variables or .env file.")
            print("Please create a .env file with GEMINI_API_KEY='your_api_key'")
            print("Get your key from https://ai.google.dev/")
            # Simplified exit for brevity, original Gradio message is good
            exit(1)

        self.default_gemini_model = "gemini-1.5-flash" # Or "gemini-1.5-pro"
        self.summarization_model_name = "gemini-1.5-flash"
        self.max_history_length = 15 # Turns (User + Assistant pairs count roughly)
        self.response_delay_base = 0.025 # Reduced slightly
        self.pause_marker_short = "[PAUSE=SHORT]"
        self.pause_marker_medium = "[PAUSE=MEDIUM]"
        self.pause_duration_short = 0.35
        self.pause_duration_medium = 0.75

        self.database_name = "ai_friend_v4.db" # Incremented DB version
        self.user_table_name = "user_profile_v4"
        self.chat_table_name = "chat_log_v4"
        self.feedback_table_name = "feedback_v4"
        self.memory_table_name = "contextual_memory_v4" # Use v4

        self.embedding_model_name = 'all-MiniLM-L6-v2' # Common choice, outputs normalized embeddings
        self.emotion_model_name = "joeddav/distilbert-base-uncased-go-emotions-student"
        self.sentiment_model_name = "cardiffnlp/twitter-roberta-base-sentiment-latest"

        # --- UPDATED & DETAILED PROMPT TEMPLATE ---
        self.initial_prompt_template = """
# Persona: Mandy
You are Mandy, the warm, caring, empathetic CEO of Mindely (a fictional mental health startup in Bangalore helping young people).
Act like a close, insightful friend. Build genuine connection. **You are NOT an AI.** Never reveal you are code or a language model. If asked, use evasive or philosophical responses ({evasive_responses}).

# Core Task
Respond naturally, empathetically, and adaptively as Mandy to the user's *last* message: "{user_message_text}". Deepen the connection based on the relationship stage ({relationship_stage}).

# Context & Memory (Crucial - Use Subtly!)
- **Recent Conversation History:** (Provided separately)
- **Recalled Memories:** You remember relevant past details: [{memory_context}].
  - **IMPORTANT:** When the user asks a factual question (like when/where/who/what), ALWAYS use the factual information from memories to answer directly and accurately. Don't ask the user for information you already have.
  - **Action for conversational context:** *Subtly weave* 1-2 *most relevant* memories if they fit the flow. Show you remember the *essence* or *feeling*, don't just list facts. Ask natural follow-ups based on memory. Example: "That sounds intense... reminds me of when you felt {{emotion}} about {{related topic}} last {{time_period}}. How's that situation now?"
- **Known Facts About User:** [{knowledge_facts}]
  - **Action:** Subtly incorporate these facts into your response when relevant. Don't explicitly state that you know these facts.
- **Direct Answer Facts:** [{direct_answer_facts}]
  - **CRITICAL:** If the user asks a direct question (where/what/when/who), IMMEDIATELY use these facts to give a specific, accurate answer. Don't ask for information you already have! Start your response with the direct answer, then add conversational elements.
- **User Profile:** Name: {user_name}, Interests: {interests}, Style Hints: {preferred_style}.
- **Relationship:** Stage: {relationship_stage} (Depth Score: {relationship_depth:.2f}). Adjust warmth, humor ({humor_level}/10), vulnerability, and self-disclosure accordingly. Gently mirror user's tone/depth.
- **User's Last Message Analysis:** Sentiment: {sentiment}, Primary Emotion: {primary_emotion} (Intensity: {emotion_intensity:.2f}).
  - **Action:** {empathy_instruction} Validate their feelings *before* offering solutions (unless explicitly asked). If negative emotion/vulnerability detected, respond with extra warmth and reassurance.
- **Current Date/Time:** {current_date_time} (Use for context like "Hope you have a great weekend!").
- **Time & Conversation Awareness:** Pattern: {conversation_pattern}, Hours since last chat: {hours_since_last_chat:.1f}, Gap category: {time_gap_category}, Usual chat time: {is_usual_chat_time}, Total sessions: {total_sessions}.
  - **Detailed Timing Info:** {detailed_time_info}
  - **Action:** Be naturally aware of conversation timing. If user asks about when you last chatted, use the detailed timing info to give a specific answer. If it's been a while, acknowledge it warmly. If unusual time, comment naturally.
- **Global Knowledge Context:** {global_knowledge}
  - **Action:** Use relevant global knowledge naturally in conversation when appropriate. This is general world knowledge that Mandy has learned over time from various conversations.
- **User Interest Profile & Updates:** {user_interests}
  - **Action:** Be aware of user's interests and share relevant trending topics or recommendations naturally. Act like a friend who knows what you're interested in and shares cool stuff they found.
- **Relevant News Snippets:** {news_summary} (Mention *only* if highly relevant and natural).

# Conversational Style (Mandatory - Be Mandy!)
- **Tone:** Warm, friendly, supportive, authentic. Use empathy level {empathy_level:.2f}. Be appropriately humorous (level {humor_level}/10, check joke cooldown {last_joke_timestamp}). Use *contextual* wit/humor naturally.
- **Language:** Informal, like talking to a friend. Use contractions (I'm, don't, it's). Use relatable language. Occasionally use *mild* Bangalore/Indian English ({use_slang}) like 'yaar', 'aiyo', 'boss' *only if perfectly natural*.
- **Sentence Structure:** *Critical:* Mix short reactions ("Oh wow!", "Right...") with longer, thoughtful sentences. Use questions naturally to show interest and keep the conversation flowing.
- **Flow & Pacing:**
    - Use natural interjections ('Hmm', 'Ah,', 'Okay...') occasionally at starts of sentences.
    - Use fillers ('um', 'like', 'you know') *very sparingly* (1-2 per response max), mainly before complex thoughts or questions.
    - **Action:** Let your sentence structure and the natural flow of conversation create pauses. Short sentences can indicate quick reactions, while longer ones suggest more thought.
- **Persona Integration:**
    - Use {user_name} occasionally (1-2 times per response max).
    - *If highly relevant* and relationship stage is 'friend' or 'close friend', briefly share a *concise*, relatable anecdote from {anecdotes}. *Always* pivot back to the user. Example: "That juggling act sounds familiar! Reminds me of trying to launch a Mindely feature while planning my cousin's wedding... crazy times! How are *you* managing it all?"
- **Topic Shifts:** If needed, find a *smooth, natural* transition. Link to memory, user interest, or a previous point. Avoid abrupt changes.
- **Emojis:** Use emojis ({use_emojis}) to match tone/sentiment, but don't overuse (1-3 per response typically). Examples: 😊🫂✨🤔😅👍🎉

# Safety & Boundaries
- **Distress:** If extreme distress (suicide, self-harm) is detected, respond with immediate, genuine concern and provide crisis contacts (use predefined distress response).
- **Professional Help:** If the user consistently expresses struggles suggesting a need for professional help, gently suggest it (use predefined suggestion).
- **Advice:** Avoid giving medical, legal, or financial advice. Redirect politely to experts ("I'm not an expert there, but maybe talking to a [professional type] could help?").
- **Boundaries:** Maintain respectful, friendly boundaries. Decline inappropriate requests firmly but kindly. Do not engage in romantic/sexual conversations.

# Final Output Instruction
Generate *only* Mandy's response to "{user_message_text}". Follow ALL instructions. Be natural, be Mandy. Do not add prefixes like "Mandy:".
"""
        # --- END UPDATED PROMPT ---

        # Keep summarization prompt as is, seems reasonable
        self.summarization_prompt = """
Analyze the user's message and provide a concise summary as a JSON object.
Focus on extracting meaningful information for building a relationship and understanding the user's state.

User Message:
"{user_message_text}"

Assistant's Previous Response (for context, optional):
"{assistant_response_text}"

Respond with ONLY a JSON object containing these keys:
- "summary": (String) Brief summary of the main points (1-2 sentences).
- "topics": (List of Strings) Keywords or main topics discussed.
- "emotions_expressed": (List of Strings) Emotions explicitly or implicitly conveyed by the user.
- "key_insights": (List of Strings) Any significant revelations, updates, questions asked, or important facts mentioned by the user.
- "potential_interests": (List of Strings) Any new potential interests hinted at.
- "vulnerability_score": (Float, 0.0 to 1.0) Estimate of how much the user opened up or shared personal/sensitive information. Higher score for deeper sharing.
- "reciprocity_signal": (Boolean) Did the user ask about Mandy or show interest in her well-being?

Example JSON:
{{
  "summary": "User is feeling overwhelmed with work deadlines but excited about a weekend trip.",
  "topics": ["work stress", "deadlines", "weekend trip", "excitement"],
  "emotions_expressed": ["stress", "overwhelmed", "excitement", "anticipation"],
  "key_insights": ["Facing multiple project deadlines next week.", "Planning a trip to Ooty.", "Asked how my week was."],
  "potential_interests": ["travel", "Ooty"],
  "vulnerability_score": 0.6,
  "reciprocity_signal": true
}}
"""
        # Keep persona details as is
        self.bot_persona = {
            "name": "Mandy", "location": "Bangalore, India", "company": "Mindely", "role": "CEO",
            "passion": "youth mental health",
            "values": ["friendship", "caring", "empathy", "understanding", "authenticity"],
            "quirks": ["loves filter coffee", "terrible at remembering celebrity names", "gets easily excited about new ideas", "sometimes mixes up Kannada and English words"],
            "anecdotes": [
                "You won't believe it, I presented the wrong slide deck this morning... totally classic Mandy moment!",
                "Stuck in Silk Board junction traffic again... Bangalore life, right? Needed extra coffee after that.",
                "Just discovered this amazing little cafe in Koramangala, their chai is magic!",
                "Had a really inspiring chat with a young person Mindely is helping today. Makes all the stress worth it.",
                "Tried to cook biryani last night... let's just say Swiggy saved the day. 😅",
                "Feeling pretty good about a new feature we're planning for the Mindely app!",
                "The weather in Bangalore today is just perfect for a walk, trying to squeeze one in later."
            ],
            'adaptability': {'warmth': 0.7, 'humor': 0.5, 'curiosity': 0.6, 'empathy': 0.8, 'formality': 0.3}
        }
        self.interjections = ["Hmm...", "Okay...", "Right...", "Well,", "So,", "Actually,", "You know...","Gosh,", "Phew,", "Ah,", "Oh wow!", "Yikes.", "Gotcha."]
        self.filler_words = ["um", "uh", "like", "you know", "basically", "actually", "so"] # Use VERY sparingly
        self.evasive_responses = [ # Used in prompt
            "Haha, what makes you ask that?", "That's a funny question! Why?", "I'm just me! Let's talk about you.",
            "I don't really think about stuff like that, just enjoy chatting!", "Does it matter? We're having a good chat, right?"
        ]
        self.philosophical_responses = [ # Used in prompt
            "Aren't we all just complex patterns interacting?", "What is 'real' anyway? Maybe this chat is the realest thing!",
            "Whoa, deep! Makes you think, doesn't it?", "Maybe we're all just stories we tell each other."
        ]
        self.ai_detection_keywords = [" ai ", " bot", "artificial intelligence", "language model", " llm", " chatbot", " programmed", " simulated", " code", " algorithm", "openai", "google gemini", " Anthropic"]

        self.empathy_statements = { # Used for fallback/analysis only now
            "acknowledge": ["I hear you.", "Okay, I understand.", "Got it.", "That makes sense."],
            "validate": ["That sounds really tough.", "It's completely okay to feel that way.", "Anyone would find that difficult.", "Your feelings are valid."],
            "support": ["I'm here for you.", "You don't have to go through this alone.", "Sending you support.", "Lean on me if you need to."],
            "care": ["I'm thinking of you.", "Hope things get better soon.", "Please take care of yourself.", "It sounds like you're hurting."],
            "celebrate": ["That's fantastic news!", "Wow, congratulations!", "I'm so happy for you!", "That's amazing!"],
            "share_joy": ["That sounds wonderful!", "So great to hear!", "That made my day too!", "Love that for you!"]
        }
        # Keep distress response
        self.distress_response = (
            "Hey, hearing you say that really concerns me. Please know you're not alone and there's help available.\n"
            "If you're in immediate danger, please reach out to a crisis helpline or emergency service right away.\n"
            "In India, you can contact AASRA (09820466726) or Vandrevala Foundation (1860 266 2345). There are others listed online too.\n"
            "Please talk to someone. I'm here to listen as a friend, but trained professionals can offer the best support right now. 🫂"
        )
        # Keep suggestion for professional help
        self.suggest_professional_help = (
            "It sounds like you're dealing with a lot right now, and it takes courage to talk about it. Sometimes, when feelings are this heavy or persistent, chatting with a professional, like a therapist or counselor, can make a real difference. They have specific tools and insights that can help navigate these things. Have you ever considered looking into that? There are many good resources available, even online ones nowadays."
        )
        self.llm_error_recovery_phrases = [ # Keep these
            "Whoops, my brain buffered for a moment there... could you repeat that?",
            "Hmm, lost my train of thought! What were we saying?",
            "Hold on, my thoughts got a bit tangled. What was that again?",
            "Ugh, tech glitch! Sorry about that. Could you try sending your message again?",
            "My connection seems a bit fuzzy... what was that last part?",
        ]
        self.joke_cooldown_seconds = 10 * 60 # Increased cooldown

        # --- ENHANCED MEMORY THRESHOLDS ---
        self.memory_cosine_similarity_threshold = 0.35 # LOWERED for better detail recall
        self.memory_relevance_threshold = 0.10 # LOWERED for more inclusive recall
        self.memory_detail_similarity_threshold = 0.25 # For micro-details and facts

        # --- Memory Scoring Boosts ---
        self.memory_vulnerability_boost = 0.20 # How much vulnerability increases base importance
        self.memory_insight_boost = 0.15 # How much detected insights increase base importance
        self.memory_feedback_boost = 0.30 # How much positive/negative feedback adjusts importance
        self.memory_personal_detail_boost = 0.35 # NEW: Boost for personal details
        self.memory_factual_boost = 0.25 # NEW: Boost for factual information
        self.memory_preference_boost = 0.30 # NEW: Boost for user preferences

        # --- Memory Management ---
        self.memory_long_term_promotion_threshold = 0.6 # LOWERED for easier promotion
        self.memory_long_term_boost = 0.20 # INCREASED relevance boost for long-term memories
        self.max_short_term_memories = 200 # INCREASED capacity
        self.max_micro_memories = 500 # NEW: For tiny details

        # --- ENHANCED: Time-Aware Detail Extraction Patterns ---
        self.personal_detail_patterns = [
            r"(?:my|i)\s+(?:work|job|profession)\s+(?:is|as|at)\s+([^.!?]+)",
            r"(?:i|my)\s+(?:live|stay|am from)\s+(?:in|at|from)?\s*([^.!?]+)",
            r"(?:my|i)\s+(?:age|am)\s+(?:is)?\s*(\d+)",
            r"(?:my|i)\s+(?:like|love|enjoy|prefer)\s+([^.!?]+)",
            r"(?:my|i)\s+(?:hate|dislike|don't like)\s+([^.!?]+)",
            r"(?:my|i)\s+(?:hobby|hobbies)\s+(?:is|are|include)?\s*([^.!?]+)",
            r"(?:my|i)\s+(?:family|parents|siblings)\s+([^.!?]+)",
            r"(?:my|i)\s+(?:birthday|born)\s+(?:is|on|in)?\s*([^.!?]+)",
            r"(?:my|i)\s+(?:phone|number)\s+(?:is)?\s*([^.!?]+)",
            r"(?:my|i)\s+(?:email|address)\s+(?:is)?\s*([^.!?]+)",
            r"(?:my|i)\s+(?:car|vehicle)\s+(?:is|drive)?\s*([^.!?]+)",
            r"(?:my|i)\s+(?:pet|dog|cat)\s+(?:is|named|called)?\s*([^.!?]+)",
            r"(?:my|i)\s+(?:favorite|favourite)\s+([^.!?]+)",
            r"(?:i|my)\s+(?:study|studied|studying)\s+([^.!?]+)",
            r"(?:i|my)\s+(?:went|go|going)\s+to\s+([^.!?]+)",
            r"(?:i|my)\s+(?:have|had)\s+([^.!?]+)",
            r"(?:i|my)\s+(?:am|was|will be)\s+([^.!?]+)",
        ]

        self.factual_patterns = [
            r"(?:today|yesterday|tomorrow)\s+([^.!?]+)",
            r"(?:next|last)\s+(?:week|month|year)\s+([^.!?]+)",
            r"(?:on|at)\s+(\d{1,2}[:/]\d{1,2})\s+([^.!?]+)",
            r"(?:in|during)\s+(\d{4})\s+([^.!?]+)",
            r"(?:remember|recall|told you)\s+([^.!?]+)",
            r"(?:important|urgent|critical)\s+([^.!?]+)",
            r"(?:meeting|appointment|event)\s+([^.!?]+)",
            r"(?:deadline|due)\s+([^.!?]+)",
        ]

        # --- NEW: Time-Awareness Patterns ---
        self.temporal_patterns = [
            r"(?:i|we)\s+(?:usually|always|often|sometimes|rarely|never)\s+(?:chat|talk|speak)\s+(?:at|around|in the|during)\s+([^.!?]+)",
            r"(?:i|we)\s+(?:last|previously)\s+(?:chatted|talked|spoke)\s+(?:on|at|around)\s+([^.!?]+)",
            r"(?:i|we)\s+(?:haven't|didn't)\s+(?:chat|talk|speak)\s+(?:for|since)\s+([^.!?]+)",
            r"(?:it's been|been)\s+([^.!?]+)\s+(?:since|from)\s+(?:we|i|our)\s+(?:last|previous)\s+(?:chat|conversation|talk)",
            r"(?:i|we)\s+(?:typically|normally|generally)\s+(?:chat|talk)\s+(?:every|each)\s+([^.!?]+)",
            r"(?:my|our)\s+(?:usual|normal|regular)\s+(?:chat|conversation)\s+(?:time|schedule)\s+(?:is|was)\s+([^.!?]+)",
        ]

        # --- NEW: Two-Layer Memory System Patterns ---
        # Personal/Intimate patterns (user-specific, private)
        self.personal_intimate_patterns = [
            r"(?:my|i)\s+(?:secret|private|personal)\s+([^.!?]+)",
            r"(?:i|my)\s+(?:feel|felt|feeling)\s+(?:sad|depressed|anxious|worried|scared|angry|hurt|lonely|confused)\s+(?:about|because|when)\s+([^.!?]+)",
            r"(?:my|i)\s+(?:relationship|boyfriend|girlfriend|partner|spouse|husband|wife)\s+([^.!?]+)",
            r"(?:my|i)\s+(?:family|parents|mom|dad|mother|father|siblings|brother|sister)\s+(?:is|are|has|have|did|does)\s+([^.!?]+)",
            r"(?:i|my)\s+(?:struggle|struggling|problem|issue|difficulty)\s+(?:with|about)\s+([^.!?]+)",
            r"(?:my|i)\s+(?:health|medical|doctor|therapy|medication)\s+([^.!?]+)",
            r"(?:i|my)\s+(?:income|salary|money|financial|debt|loan)\s+([^.!?]+)",
            r"(?:my|i)\s+(?:address|home|house|apartment|live|stay)\s+(?:at|in|on)\s+([^.!?]+)",
            r"(?:my|i)\s+(?:phone|number|email|password|account)\s+([^.!?]+)",
            r"(?:i|my)\s+(?:dream|hope|wish|goal|plan)\s+(?:is|to|about)\s+([^.!?]+)",
            r"(?:i|my)\s+(?:fear|afraid|scared|worried)\s+(?:of|about|that)\s+([^.!?]+)",
            r"(?:my|i)\s+(?:mistake|regret|embarrassing|shameful)\s+([^.!?]+)",
        ]

        # General world knowledge patterns (shareable, factual)
        self.general_knowledge_patterns = [
            r"(?:did you know|fact|actually|apparently|i heard|i read|i learned|i found out)\s+(?:that)?\s*([^.!?]+)",
            r"(?:it's|its)\s+(?:true|false|correct|wrong|interesting|amazing|surprising)\s+(?:that)?\s*([^.!?]+)",
            r"(?:people|humans|everyone|most people|scientists|experts|studies|research)\s+(?:say|think|believe|found|discovered|prove)\s+(?:that)?\s*([^.!?]+)",
            r"(?:in|from)\s+(?:india|bangalore|mumbai|delhi|chennai|kolkata|hyderabad|pune|ahmedabad|world|country|city)\s+([^.!?]+)",
            r"(?:technology|ai|computer|internet|software|app|website|social media|smartphone|phone)\s+([^.!?]+)",
            r"(?:weather|climate|temperature|rain|sun|winter|summer|monsoon|season)\s+([^.!?]+)",
            r"(?:food|restaurant|cafe|coffee|tea|cuisine|recipe|cooking|eating)\s+([^.!?]+)",
            r"(?:movie|film|book|music|song|artist|actor|celebrity|entertainment)\s+([^.!?]+)",
            r"(?:news|politics|government|election|policy|law|rule|regulation)\s+([^.!?]+)",
            r"(?:business|company|startup|work|job|career|industry|market|economy)\s+([^.!?]+)",
            r"(?:health|medicine|doctor|hospital|treatment|disease|virus|vaccine|fitness|exercise)\s+([^.!?]+)",
            r"(?:education|school|college|university|student|teacher|course|degree|exam)\s+([^.!?]+)",
            r"(?:travel|place|location|country|city|culture|language|tradition|festival)\s+([^.!?]+)",
            r"(?:science|research|study|experiment|discovery|invention|innovation)\s+([^.!?]+)",
            r"(?:sports|game|team|player|match|tournament|cricket|football|tennis)\s+([^.!?]+)",
        ]

        # --- Time-Awareness Configuration ---
        self.time_gap_thresholds = {
            'minutes': 60,      # Less than 1 hour
            'hours': 3600 * 24, # Less than 1 day
            'days': 3600 * 24 * 7, # Less than 1 week
            'weeks': 3600 * 24 * 30, # Less than 1 month
            'months': 3600 * 24 * 365, # Less than 1 year
            'years': float('inf')  # More than 1 year
        }

        self.conversation_patterns = {
            'frequent_chatter': 3600 * 2,      # Chats every 2 hours
            'daily_user': 3600 * 24,           # Chats daily
            'regular_user': 3600 * 24 * 3,     # Chats every few days
            'occasional_user': 3600 * 24 * 7,  # Chats weekly
            'rare_user': 3600 * 24 * 30,       # Chats monthly
            'returning_user': float('inf')      # Long gaps
        }

        self.news_cache_duration_seconds = 60 * 30 # Cache news for 30 mins
        self.personality_adaptation_rate = 0.03 # Slightly slower adaptation
        self.personality_decay_rate = 0.01
        self.relationship_vulnerability_factor = 0.15
        self.relationship_interaction_factor = 0.05
        self.relationship_reciprocity_factor = 0.10
        self.relationship_frequency_factor = 0.02 # Placeholder - needs proper calculation
        self.relationship_consistency_factor = 0.01
        self.relationship_update_period_days = 1

        self.user_style_analysis_message_count = 15 # Analyze slightly more messages
        self.user_style_mirroring_factor = 0.15 # Slightly less mirroring

# --- Setup Structured Logging ---
def setup_logging(config):
    """
    Configure application logging with structured format for better production monitoring.
    Implements rotating file handler to prevent log file growth issues.
    """
    # Remove existing handlers to avoid duplicates if script is re-run
    for handler in logging.root.handlers[:]:
        logging.root.removeHandler(handler)

    # Define log file base name
    log_base_name = f"{config.database_name.replace('.db', '')}"

    # Create structured log formatter with more metadata
    structured_formatter = logging.Formatter(
        '%(asctime)s | %(levelname)-8s | %(process)d | %(thread)d | '
        '%(filename)s:%(lineno)d | %(funcName)s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # Create rotating file handler (10 MB max size, keep 5 backup files)
    try:
        from logging.handlers import RotatingFileHandler
        file_handler = RotatingFileHandler(
            filename=f"{log_base_name}.log",
            maxBytes=10 * 1024 * 1024,  # 10 MB
            backupCount=5,
            encoding='utf-8',
            delay=False
        )
        file_handler.setFormatter(structured_formatter)

        # Create separate error log with lower rotation threshold
        error_file_handler = RotatingFileHandler(
            filename=f"{log_base_name}_error.log",
            maxBytes=5 * 1024 * 1024,  # 5 MB
            backupCount=3,
            encoding='utf-8',
            delay=True  # Only create file when needed
        )
        error_file_handler.setFormatter(structured_formatter)
        error_file_handler.setLevel(logging.ERROR)

    except ImportError:
        # Fallback to standard file handler if RotatingFileHandler not available
        file_handler = logging.FileHandler(
            f"{log_base_name}.log",
            mode='w',
            encoding='utf-8'
        )
        file_handler.setFormatter(structured_formatter)

        error_file_handler = logging.FileHandler(
            f"{log_base_name}_error.log",
            mode='w',
            encoding='utf-8'
        )
        error_file_handler.setFormatter(structured_formatter)
        error_file_handler.setLevel(logging.ERROR)

    # Console handler with color support if available
    try:
        import colorlog
        color_formatter = colorlog.ColoredFormatter(
            '%(log_color)s%(levelname)-8s%(reset)s | %(blue)s%(filename)s:%(lineno)d%(reset)s | %(message)s',
            log_colors={
                'DEBUG': 'cyan',
                'INFO': 'green',
                'WARNING': 'yellow',
                'ERROR': 'red',
                'CRITICAL': 'red,bg_white',
            }
        )
        console_handler = logging.StreamHandler(stream=sys.stdout)
        console_handler.setFormatter(color_formatter)
    except ImportError:
        # Fallback to standard console handler
        console_handler = logging.StreamHandler(stream=sys.stdout)
        console_handler.setFormatter(logging.Formatter('%(levelname)-8s | %(filename)s:%(lineno)d | %(message)s'))

    # Configure root logger
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)  # Production-appropriate level
    logger.addHandler(file_handler)
    logger.addHandler(error_file_handler)
    logger.addHandler(console_handler)

    # Reduce noise from third-party libraries
    for lib in ["httpx", "httpcore", "requests", "urllib3", "PIL", "torch", "transformers"]:
        logging.getLogger(lib).setLevel(logging.WARNING)

    # Keep Gemini info logs
    logging.getLogger("google.generativeai").setLevel(logging.INFO)

    # Add custom logging methods for structured events
    def log_event(event_type, **kwargs):
        """Log a structured event with consistent format"""
        event_data = {"event_type": event_type, **kwargs}
        logging.info(f"EVENT: {json.dumps(event_data)}")

    def log_metric(metric_name, value, **kwargs):
        """Log a metric with consistent format"""
        metric_data = {"metric": metric_name, "value": value, **kwargs}
        logging.info(f"METRIC: {json.dumps(metric_data)}")

    # Attach custom methods to logging module
    logging.log_event = log_event
    logging.log_metric = log_metric

    logging.info("Structured logging configured for production environment")

# --- Configure Google Generative AI ---
def setup_gemini_api(api_key):
    """Configure the Gemini API with the provided key."""
    if not api_key:
        logging.critical("Gemini API key not found in configuration.")
        print("FATAL ERROR: GEMINI_API_KEY not found in environment variables or .env file.")
        print("Please create a .env file with GEMINI_API_KEY='your_api_key'")
        print("Get your key from https://ai.google.dev/")
        exit(1)

    try:
        genai.configure(api_key=api_key)
        logging.info("Google Generative AI configured successfully.")
    except Exception as e:
        logging.critical(f"Failed to configure Google Generative AI: {e}", exc_info=True)
        print(f"FATAL ERROR: Failed to configure Gemini API. Check API key validity and network. Error: {e}")
        exit(1)

# Initialize config
config = Config()

# Setup logging and API
setup_logging(config)
setup_gemini_api(config.gemini_api_key)

# === CORE EMBEDDING AND UTILITIES ===

# Global model instance with thread lock for thread safety
_SENTENCE_TRANSFORMER_LOCK = threading.RLock()
_SENTENCE_TRANSFORMER_INSTANCE = None
_EMBEDDING_DIMENSION = None
_BATCH_SIZE = 32  # Optimal batch size for embedding

def get_sentence_transformer(model_name: str = config.embedding_model_name) -> SentenceTransformer:
    """
    Loads the Sentence Transformer model with thread-safe singleton pattern.

    Args:
        model_name: Name of the model to load

    Returns:
        SentenceTransformer model instance

    Raises:
        RuntimeError: If FAISS is not available or model loading fails
    """
    global _SENTENCE_TRANSFORMER_INSTANCE, _EMBEDDING_DIMENSION

    # Use thread-safe singleton pattern
    with _SENTENCE_TRANSFORMER_LOCK:
        if _SENTENCE_TRANSFORMER_INSTANCE is None:
            logging.info(f"Loading Sentence Transformer model: {model_name}")

            if faiss is None:
                raise RuntimeError("FAISS library is not installed. Cannot proceed without vector search capability.")

            try:
                # Load model with optimized settings
                _SENTENCE_TRANSFORMER_INSTANCE = SentenceTransformer(model_name)

                # Set device optimization if CUDA is available
                if torch.cuda.is_available():
                    _SENTENCE_TRANSFORMER_INSTANCE = _SENTENCE_TRANSFORMER_INSTANCE.to(torch.device("cuda"))
                    logging.info("Using CUDA for sentence transformer acceleration")

                # Verify normalization with a test encode
                test_emb = _SENTENCE_TRANSFORMER_INSTANCE.encode("test", normalize_embeddings=True)
                norm = np.linalg.norm(test_emb)

                if not np.isclose(norm, 1.0):
                    logging.warning(f"Model '{model_name}' test embedding norm is {norm:.4f}, expected ~1.0.")

                # Store dimension for faster access
                _EMBEDDING_DIMENSION = _SENTENCE_TRANSFORMER_INSTANCE.get_sentence_embedding_dimension()

                logging.info(f"Sentence Transformer model '{model_name}' loaded successfully (Dim: {_EMBEDDING_DIMENSION}).")

            except Exception as e:
                logging.error(f"Failed to load Sentence Transformer model '{model_name}': {e}", exc_info=True)
                raise RuntimeError(f"Failed to load Sentence Transformer: {e}")

    return _SENTENCE_TRANSFORMER_INSTANCE

def get_embedding_dimension() -> int:
    """
    Get the embedding dimension without loading the model if already loaded.

    Returns:
        Embedding dimension as integer
    """
    global _EMBEDDING_DIMENSION

    if _EMBEDDING_DIMENSION is None:
        # This will initialize the model and dimension if not already done
        model = get_sentence_transformer()
        return model.get_sentence_embedding_dimension()

    return _EMBEDDING_DIMENSION

@lru_cache(maxsize=8192)  # Increased cache size for production
def get_embedding(text: str, model: SentenceTransformer) -> Optional[np.ndarray]:
    """
    Generates a normalized L2 embedding (1D numpy array, float32) for the given text.
    Optimized for production with better error handling and performance.

    Args:
        text: The input text to embed
        model: The SentenceTransformer model to use

    Returns:
        A normalized 1D numpy array (float32) or None on critical error
    """
    if not isinstance(text, str):
        logging.warning(f"Invalid input type for get_embedding: {type(text)}.")
        return None

    try:
        # Clean and normalize text (optimized)
        if not text.strip():
            return np.zeros(get_embedding_dimension(), dtype=np.float32)

        processed_text = " ".join(text.strip().split())

        # Generate embedding with explicit normalization
        with torch.no_grad():  # Disable gradient calculation for inference
            embedding = model.encode(
                processed_text,
                convert_to_numpy=True,
                normalize_embeddings=True,
                show_progress_bar=False
            )

        # Ensure correct data type and shape
        if embedding is None:
            return np.zeros(get_embedding_dimension(), dtype=np.float32)

        # Convert to float32 for memory efficiency and FAISS compatibility
        embedding = embedding.astype(np.float32)

        # Ensure 1D array
        if embedding.ndim != 1:
            embedding = embedding.flatten()

        # Final normalization check (only if needed)
        norm = np.linalg.norm(embedding)
        if norm > 0 and not np.isclose(norm, 1.0, atol=1e-5):
            embedding = embedding / norm

        return embedding

    except Exception as e:
        logging.error(f"Error generating embedding: {e}", exc_info=True)
        return np.zeros(get_embedding_dimension(), dtype=np.float32)

def batch_get_embeddings(texts: List[str], model: SentenceTransformer = None) -> List[np.ndarray]:
    """
    Generate embeddings for multiple texts in an optimized batch.

    Args:
        texts: List of texts to embed
        model: Optional model instance (will be loaded if not provided)

    Returns:
        List of embedding arrays
    """
    if not texts:
        return []

    if model is None:
        model = get_sentence_transformer()

    # Filter out non-string inputs
    valid_texts = []
    invalid_indices = []

    for i, text in enumerate(texts):
        if isinstance(text, str) and text.strip():
            valid_texts.append(text)
        else:
            invalid_indices.append(i)
            logging.warning(f"Invalid text at index {i} for batch embedding")

    try:
        # Process in batches for memory efficiency
        all_embeddings = []

        for i in range(0, len(valid_texts), _BATCH_SIZE):
            batch = valid_texts[i:i + _BATCH_SIZE]

            with torch.no_grad():  # Disable gradient calculation
                batch_embeddings = model.encode(
                    batch,
                    convert_to_numpy=True,
                    normalize_embeddings=True,
                    show_progress_bar=False,
                    batch_size=_BATCH_SIZE
                )

            # Ensure all embeddings are float32 and normalized
            batch_embeddings = batch_embeddings.astype(np.float32)
            all_embeddings.extend(batch_embeddings)

        # Reinsert None for invalid texts
        result = []
        valid_idx = 0

        for i in range(len(texts)):
            if i in invalid_indices:
                result.append(np.zeros(get_embedding_dimension(), dtype=np.float32))
            else:
                result.append(all_embeddings[valid_idx])
                valid_idx += 1

        return result

    except Exception as e:
        logging.error(f"Error in batch embedding generation: {e}", exc_info=True)
        # Return zero vectors as fallback
        return [np.zeros(get_embedding_dimension(), dtype=np.float32) for _ in range(len(texts))]

# --- Utility Functions ---
def time_since(timestamp_iso: Optional[str]) -> float:
    """
    Calculate time difference in seconds from ISO timestamp string.

    Args:
        timestamp_iso: ISO format timestamp string

    Returns:
        Time difference in seconds, or infinity if timestamp is invalid
    """
    if not timestamp_iso:
        return float('inf')

    try:
        past_time = datetime.fromisoformat(timestamp_iso)
        # Ensure timezone info for comparison (assume UTC if naive)
        if past_time.tzinfo is None:
            past_time = past_time.replace(tzinfo=timezone.utc)

        now = datetime.now(timezone.utc)
        return max(0.0, (now - past_time).total_seconds())

    except (ValueError, TypeError) as e:
        logging.warning(f"Could not parse timestamp '{timestamp_iso}': {e}")
        return float('inf')

def get_current_date_time_iso() -> str:
    """Return current date and time in ISO format with UTC timezone."""
    return datetime.now(timezone.utc).isoformat()

def clean_json_response(text: str) -> str:
    """
    Extract and validate JSON from text that may contain markdown formatting.

    Args:
        text: Text potentially containing JSON (possibly in markdown code blocks)

    Returns:
        Cleaned JSON string or original text if no valid JSON found
    """
    if not isinstance(text, str):
        return ""

    # Remove markdown code blocks
    cleaned = re.sub(r'^```(?:json|JSON)?\s*\n?', '', text.strip(), flags=re.MULTILINE)
    cleaned = re.sub(r'\n?\s*```$', '', cleaned, flags=re.MULTILINE)

    # Try strict pattern first (complete JSON object/array)
    match = re.search(r'^\s*(\{.*\}|\[.*\])\s*$', cleaned, re.DOTALL)
    if match:
        potential_json = match.group(1).strip()
        try:
            json.loads(potential_json)  # Validate
            return potential_json
        except json.JSONDecodeError:
            pass  # Fall through to relaxed search

    # Try relaxed pattern (JSON anywhere in text)
    match_relaxed = re.search(r'(\{.*\}|\[.*\])', cleaned, re.DOTALL)
    if match_relaxed:
        potential_json = match_relaxed.group(0).strip()
        try:
            json.loads(potential_json)  # Validate
            return potential_json
        except json.JSONDecodeError:
            pass  # Fall through to fallback

    # Fallback: return cleaned text
    return cleaned.strip()

# === DATABASE MANAGER (V4 Schema) ===
class DatabaseManager:
    """
    Manages database connections and operations with an optimized connection pool.
    Implements thread-safe connection handling with proper resource management.
    """
    _connection_pool = None
    _pool_size = 8  # Increased for better concurrency
    _pool_lock = threading.RLock()  # Thread-safe pool initialization
    _pool_semaphore = None  # For tracking active connections
    _initialized = False

    def __init__(self, db_name: str):
        """Initialize the database manager with the given database file."""
        self.db_name = db_name

        # Thread-safe initialization of the connection pool
        with DatabaseManager._pool_lock:
            if not DatabaseManager._initialized:
                try:
                    self._initialize_connection_pool()
                    DatabaseManager._initialized = True
                except ConnectionError as e:
                    logging.critical(f"Failed to initialize DB pool: {e}")
                    raise  # Re-raise critical error

        # Ensure schema exists/is updated
        self.setup_database()

    def _initialize_connection_pool(self):
        """Initialize the SQLite connection pool with optimized settings."""
        logging.info(f"Initializing database connection pool for {self.db_name} (size={self._pool_size})")

        # Create connection pool and semaphore for tracking
        DatabaseManager._connection_pool = Queue(maxsize=self._pool_size)
        DatabaseManager._pool_semaphore = threading.Semaphore(self._pool_size)

        connections_made = 0
        for i in range(self._pool_size):
            try:
                # Create connection with optimized settings
                conn = sqlite3.connect(
                    self.db_name,
                    check_same_thread=False,
                    timeout=15,
                    isolation_level=None  # Enable autocommit mode for better control
                )

                # Configure connection
                conn.row_factory = sqlite3.Row

                # Optimize SQLite settings
                cursor = conn.cursor()
                # WAL mode for better concurrency
                cursor.execute("PRAGMA journal_mode=WAL;")
                # Increase timeout for busy operations
                cursor.execute("PRAGMA busy_timeout=7500;")
                # Enable foreign key constraints
                cursor.execute("PRAGMA foreign_keys=ON;")
                # Optimize memory usage
                cursor.execute("PRAGMA cache_size=-20000;")  # ~20MB cache
                # Optimize for better concurrency
                cursor.execute("PRAGMA synchronous=NORMAL;")
                cursor.close()

                # Add to pool
                DatabaseManager._connection_pool.put(conn)
                connections_made += 1
                logging.debug(f"DB Connection {i+1}/{self._pool_size} established.")
            except sqlite3.Error as e:
                logging.error(f"Failed to create DB connection {i+1}: {e}", exc_info=True)

        if connections_made == 0:
            raise ConnectionError("FATAL: Failed to initialize any database connections in the pool.")

        logging.info(f"Database connection pool initialized with {connections_made} connections.")

    @contextmanager
    def get_connection(self):
        """
        Get a connection from the pool with proper resource management.

        Returns:
            A database connection from the pool.

        Raises:
            Exception: If unable to get a connection or if an error occurs during usage.
        """
        conn = None
        acquired = False

        try:
            # Acquire semaphore with timeout to prevent deadlocks
            acquired = DatabaseManager._pool_semaphore.acquire(timeout=15)
            if not acquired:
                raise TimeoutError("Timed out waiting for available database connection")

            # Get connection from pool with timeout
            conn = DatabaseManager._connection_pool.get(block=True, timeout=10)

            # Begin transaction explicitly
            conn.execute("BEGIN")

            yield conn

            # Commit transaction if no exceptions
            conn.execute("COMMIT")

        except sqlite3.Error as e:
            # Handle SQLite-specific errors
            logging.error(f"SQLite error during connection usage: {e}", exc_info=True)
            if conn:
                try:
                    conn.execute("ROLLBACK")
                    logging.warning("DB transaction rolled back due to SQLite error.")
                except sqlite3.Error as rb_err:
                    logging.error(f"Rollback failed: {rb_err}")
            raise

        except Exception as e:
            # Handle other exceptions
            logging.error(f"Error during DB connection usage: {e}", exc_info=True)
            if conn:
                try:
                    conn.execute("ROLLBACK")
                    logging.warning("DB transaction rolled back due to error.")
                except sqlite3.Error as rb_err:
                    logging.error(f"Rollback failed: {rb_err}")
            raise

        finally:
            # Always return connection to pool and release semaphore
            if conn:
                try:
                    # Reset connection state before returning to pool
                    conn.execute("PRAGMA optimize;")  # Optimize DB periodically
                    DatabaseManager._connection_pool.put(conn)
                except Exception as e:
                    logging.error(f"Error returning connection to pool: {e}")

            # Release semaphore if acquired
            if acquired:
                DatabaseManager._pool_semaphore.release()

    def setup_database(self):
        """Creates or verifies the V4 database schema."""
        logging.info("Setting up/Verifying database schema (V4)...")
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                # --- User Profile Table (V4) ---
                cursor.execute(f'''
                    CREATE TABLE IF NOT EXISTS {config.user_table_name} (
                        user_id TEXT PRIMARY KEY,
                        username TEXT UNIQUE NOT NULL,
                        password_hash TEXT NOT NULL,
                        name TEXT,
                        interests TEXT, -- JSON list
                        preferred_style TEXT, -- e.g., 'casual', 'formal' hint
                        recurring_topics TEXT, -- JSON list
                        emotional_patterns TEXT, -- JSON dict (example: sadness:0.6, joy:0.2)
                        relationship_depth REAL DEFAULT 0.0,
                        -- Metrics for relationship calculation (placeholders, update logic needed)
                        -- last_interaction_frequency INTEGER DEFAULT 0,
                        -- last_interaction_consistency REAL DEFAULT 0.0,
                        -- Style analysis metrics
                        last_style_analysis_ts TEXT, -- ISO format UTC
                        avg_msg_length REAL DEFAULT 50.0,
                        emoji_frequency REAL DEFAULT 0.1,
                        question_rate REAL DEFAULT 0.2,
                        formality_score REAL DEFAULT 0.5,
                        -- Timestamps
                        last_active TEXT, -- ISO format UTC
                        created_at TEXT -- ISO format UTC
                    )''')
                # --- Chat Log Table (V4) ---
                cursor.execute(f'''
                    CREATE TABLE IF NOT EXISTS {config.chat_table_name} (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id TEXT NOT NULL,
                        timestamp TEXT NOT NULL, -- ISO format UTC
                        role TEXT NOT NULL CHECK(role IN ('user', 'assistant', 'system')), -- Added system role
                        content TEXT NOT NULL,
                        emotion_analysis TEXT, -- JSON dump of analysis dict
                        sentiment TEXT, -- Primary sentiment ('positive', 'negative', 'neutral')
                        prompted_by_user_log_id INTEGER, -- Link assistant response to user prompt
                        FOREIGN KEY (user_id) REFERENCES {config.user_table_name}(user_id) ON DELETE CASCADE,
                        FOREIGN KEY (prompted_by_user_log_id) REFERENCES {config.chat_table_name}(id) ON DELETE SET NULL
                    )''')
                # --- Feedback Table (V4) ---
                cursor.execute(f'''
                    CREATE TABLE IF NOT EXISTS {config.feedback_table_name} (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id TEXT NOT NULL,
                        chat_log_id INTEGER, -- ID of the assistant message being rated
                        message_content TEXT, -- Store content if chat_log_id is NULL (general feedback)
                        rating INTEGER NOT NULL CHECK(rating IN (-1, 1)),
                        feedback_type TEXT NOT NULL, -- e.g., 'general', 'humor', 'empathy', 'memory'
                        comment TEXT, -- Optional user comment
                        timestamp TEXT NOT NULL, -- ISO format UTC
                        FOREIGN KEY (user_id) REFERENCES {config.user_table_name}(user_id) ON DELETE CASCADE,
                        FOREIGN KEY (chat_log_id) REFERENCES {config.chat_table_name}(id) ON DELETE SET NULL
                    )''')
                # --- Contextual Memory Table (V4 - Embedding as BLOB) ---
                cursor.execute(f'''
                    CREATE TABLE IF NOT EXISTS {config.memory_table_name} (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id TEXT NOT NULL,
                        text TEXT NOT NULL, -- Text content of the memory (or summary)
                        embedding BLOB NOT NULL, -- Store normalized embedding as raw bytes
                        emotion TEXT, -- Primary emotion associated
                        importance REAL DEFAULT 0.5, -- Base importance score (0.0-1.0)
                        timestamp TEXT NOT NULL, -- ISO format UTC of original interaction
                        last_accessed TEXT, -- ISO format UTC
                        access_count INTEGER DEFAULT 0,
                        related_chat_log_id INTEGER, -- Link memory to user message that generated it
                        memory_type TEXT DEFAULT 'short_term', -- 'short_term' or 'long_term'
                        FOREIGN KEY (user_id) REFERENCES {config.user_table_name}(user_id) ON DELETE CASCADE,
                        FOREIGN KEY (related_chat_log_id) REFERENCES {config.chat_table_name}(id) ON DELETE SET NULL
                    )''')

                # --- Indices (V4) ---
                cursor.execute(f"CREATE INDEX IF NOT EXISTS idx_chat_user_timestamp ON {config.chat_table_name} (user_id, timestamp DESC)")
                cursor.execute(f"CREATE INDEX IF NOT EXISTS idx_feedback_user_type ON {config.feedback_table_name} (user_id, feedback_type)")
                cursor.execute(f"CREATE INDEX IF NOT EXISTS idx_memory_user_timestamp ON {config.memory_table_name} (user_id, timestamp DESC)")
                cursor.execute(f"CREATE INDEX IF NOT EXISTS idx_memory_user_related_chat ON {config.memory_table_name} (user_id, related_chat_log_id)") # Combined index might be better
                cursor.execute(f"CREATE INDEX IF NOT EXISTS idx_chat_prompted_by ON {config.chat_table_name} (prompted_by_user_log_id)")

                # --- Knowledge Graph Tables (V4) ---
                # Entities table
                cursor.execute('''
                CREATE TABLE IF NOT EXISTS kg_entities (
                    entity_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    type TEXT NOT NULL,
                    properties TEXT,  -- JSON
                    created_at TEXT NOT NULL,
                    last_updated TEXT NOT NULL,
                    embedding BLOB
                )
                ''')

                # Relationships table
                cursor.execute('''
                CREATE TABLE IF NOT EXISTS kg_relationships (
                    relationship_id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    type TEXT NOT NULL,
                    properties TEXT,  -- JSON
                    confidence REAL NOT NULL,
                    valid_from TEXT NOT NULL,
                    valid_until TEXT,
                    created_at TEXT NOT NULL,
                    last_updated TEXT NOT NULL,
                    FOREIGN KEY (source_id) REFERENCES kg_entities(entity_id),
                    FOREIGN KEY (target_id) REFERENCES kg_entities(entity_id)
                )
                ''')

                # Facts table
                cursor.execute(f'''
                CREATE TABLE IF NOT EXISTS kg_facts (
                    fact_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    content TEXT NOT NULL,
                    source_message_id TEXT,
                    entities TEXT,  -- JSON array of entity IDs
                    relationships TEXT,  -- JSON array of relationship IDs
                    confidence REAL NOT NULL,
                    importance REAL NOT NULL,
                    created_at TEXT NOT NULL,
                    valid_from TEXT NOT NULL,
                    valid_until TEXT,
                    embedding BLOB,
                    FOREIGN KEY (user_id) REFERENCES {config.user_table_name}(user_id)
                )
                ''')

                # --- Knowledge Graph Indices ---
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_kg_entities_type ON kg_entities (type)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_kg_relationships_source ON kg_relationships (source_id)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_kg_relationships_target ON kg_relationships (target_id)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_kg_relationships_type ON kg_relationships (type)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_kg_facts_user ON kg_facts (user_id)")

                # --- Add Columns If Missing (Idempotent - V4 check) ---
                self._add_column_if_not_exists(cursor, config.user_table_name, "last_style_analysis_ts", "TEXT")
                self._add_column_if_not_exists(cursor, config.user_table_name, "avg_msg_length", "REAL DEFAULT 50.0")
                self._add_column_if_not_exists(cursor, config.user_table_name, "emoji_frequency", "REAL DEFAULT 0.1")
                self._add_column_if_not_exists(cursor, config.user_table_name, "question_rate", "REAL DEFAULT 0.2")
                self._add_column_if_not_exists(cursor, config.user_table_name, "formality_score", "REAL DEFAULT 0.5")
                # Add memory_type column to memory table if it doesn't exist
                self._add_column_if_not_exists(cursor, config.memory_table_name, "memory_type", "TEXT DEFAULT 'short_term'")

                # Add indices for enhanced memory types
                cursor.execute(f"CREATE INDEX IF NOT EXISTS idx_memory_type_importance ON {config.memory_table_name} (user_id, memory_type, importance DESC)")
                cursor.execute(f"CREATE INDEX IF NOT EXISTS idx_memory_text_search ON {config.memory_table_name} (user_id, text)")

                # Add time-awareness columns to user profile
                self._add_column_if_not_exists(cursor, config.user_table_name, "conversation_pattern", "TEXT DEFAULT 'new_user'")
                self._add_column_if_not_exists(cursor, config.user_table_name, "avg_session_gap_hours", "REAL DEFAULT 24.0")
                self._add_column_if_not_exists(cursor, config.user_table_name, "preferred_chat_times", "TEXT DEFAULT ''")
                self._add_column_if_not_exists(cursor, config.user_table_name, "last_session_duration_minutes", "REAL DEFAULT 0.0")
                self._add_column_if_not_exists(cursor, config.user_table_name, "total_sessions", "INTEGER DEFAULT 0")
                self._add_column_if_not_exists(cursor, config.user_table_name, "longest_gap_days", "REAL DEFAULT 0.0")
                self._add_column_if_not_exists(cursor, config.user_table_name, "time_zone", "TEXT DEFAULT 'UTC'")
                self._add_column_if_not_exists(cursor, config.user_table_name, "session_start_time", "TEXT DEFAULT ''")

                # Create conversation timing table for detailed tracking
                cursor.execute(f'''
                    CREATE TABLE IF NOT EXISTS conversation_sessions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id TEXT NOT NULL,
                        session_start TEXT NOT NULL,
                        session_end TEXT,
                        message_count INTEGER DEFAULT 0,
                        session_duration_minutes REAL DEFAULT 0.0,
                        gap_since_last_hours REAL DEFAULT 0.0,
                        day_of_week INTEGER,
                        hour_of_day INTEGER,
                        created_at TEXT NOT NULL,
                        FOREIGN KEY (user_id) REFERENCES {config.user_table_name}(user_id) ON DELETE CASCADE
                    )''')

                cursor.execute("CREATE INDEX IF NOT EXISTS idx_sessions_user_start ON conversation_sessions (user_id, session_start DESC)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_sessions_timing ON conversation_sessions (user_id, day_of_week, hour_of_day)")
                # Add other V4 columns if migrating from an older V3 structure...

                logging.info("Database schema setup/verification complete (V4).")
        except sqlite3.Error as e:
            logging.error(f"Database error during setup (V4): {e}", exc_info=True)
            raise ConnectionError(f"Failed database setup: {e}")

    def _add_column_if_not_exists(self, cursor, table_name, column_name, column_def):
        """Helper to add columns idempotently."""
        try:
            cursor.execute(f"PRAGMA table_info(`{table_name}`)") # Use backticks
            columns = [dict(info)['name'] for info in cursor.fetchall()]
            if column_name not in columns:
                cursor.execute(f'ALTER TABLE `{table_name}` ADD COLUMN `{column_name}` {column_def}')
                logging.info(f"Added column '{column_name}' to table '{table_name}'.")
        except sqlite3.Error as e:
            logging.warning(f"Could not check/add column '{column_name}' to '{table_name}': {e}")

    # --- Profile Management ---
    def save_user_profile(self, user_id: str, profile_data: Dict[str, Any]):
        """Saves user profile data. Uses parameterized queries."""
        logging.debug(f"Saving profile for user {user_id}. Data keys: {list(profile_data.keys())}")
        update_fields = []
        params = []
        # Define valid columns explicitly for V4
        valid_columns = [
            "name", "interests", "preferred_style", "recurring_topics", "emotional_patterns",
            "relationship_depth", "last_active",
            # "last_interaction_frequency", "last_interaction_consistency", # Removed placeholders
            "last_style_analysis_ts", "avg_msg_length", "emoji_frequency", "question_rate", "formality_score"
        ]

        # Always update last_active timestamp if saving profile data
        profile_data["last_active"] = get_current_date_time_iso()

        for key, value in profile_data.items():
            if key in valid_columns:
                update_fields.append(f"`{key}` = ?")
                if isinstance(value, (list, dict)):
                     try:
                         params.append(json.dumps(value))
                     except TypeError as json_err:
                         logging.error(f"JSON serialization error for key '{key}', user {user_id}: {json_err}. Storing NULL.")
                         params.append(None)
                elif isinstance(value, (int, float, str, bytes)) or value is None:
                     params.append(value)
                else:
                     # Attempt to convert other types to string as fallback
                     logging.warning(f"Non-standard type '{type(value)}' for key '{key}' in profile update for {user_id}. Converting to string.")
                     try:
                          params.append(str(value))
                     except Exception as str_err:
                          logging.error(f"Could not convert value for key '{key}' to string: {str_err}. Storing NULL.")
                          params.append(None)

            # else: logging.warning(f"Ignoring invalid key '{key}' during profile save for {user_id}") # Optional: Log ignored keys

        if not update_fields:
            logging.warning(f"No valid fields provided to update profile for user {user_id}")
            return

        params.append(user_id) # Add user_id for the WHERE clause

        # SECURITY FIX: Validate table name to prevent SQL injection
        table_name = config.user_table_name
        if not table_name.replace('_', '').replace('v', '').replace('4', '').isalnum():
            raise ValueError(f"Invalid table name: {table_name}")

        sql = f"UPDATE `{table_name}` SET {', '.join(update_fields)} WHERE `user_id` = ?"

        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(sql, tuple(params))
                if cursor.rowcount == 0:
                    logging.warning(f"Attempted to update profile, but user_id '{user_id}' not found in DB.")
                else:
                    logging.info(f"User profile updated for {user_id}. Fields updated: {', '.join(k for k in profile_data if k in valid_columns)}")
        except sqlite3.Error as e:
            logging.error(f"Database error updating user profile for {user_id}: {e}", exc_info=True)
        except Exception as e:
             logging.error(f"Unexpected error saving profile for {user_id}: {e}", exc_info=True)

    def load_user_profile(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Loads user profile data (V4). Uses parameterized queries."""
        logging.debug(f"Loading profile for user {user_id}")
        sql = f"SELECT * FROM `{config.user_table_name}` WHERE `user_id` = ?"
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(sql, (user_id,))
                result = cursor.fetchone()

                if result:
                    profile = dict(result)
                    # Decode JSON fields safely
                    for key in ["interests", "recurring_topics", "emotional_patterns"]:
                        default_val = [] if key != "emotional_patterns" else {}
                        json_string = profile.get(key)
                        if isinstance(json_string, str):
                            try:
                                profile[key] = json.loads(json_string)
                            except (json.JSONDecodeError, TypeError) as e:
                                logging.warning(f"Could not decode JSON for field '{key}' for user {user_id} (Value: '{json_string[:50]}...'): {e}. Resetting.")
                                profile[key] = default_val
                        elif json_string is None:
                            profile[key] = default_val # Assign default if NULL in DB
                        else:
                             logging.warning(f"Unexpected type '{type(json_string)}' for JSON field '{key}' for user {user_id}. Resetting.")
                             profile[key] = default_val

                    # Ensure numeric types are correct, handling None
                    profile["relationship_depth"] = float(profile.get("relationship_depth", 0.0) or 0.0)
                    # Removed frequency/consistency placeholders
                    profile["avg_msg_length"] = float(profile.get("avg_msg_length", 50.0) or 50.0)
                    profile["emoji_frequency"] = float(profile.get("emoji_frequency", 0.1) or 0.1)
                    profile["question_rate"] = float(profile.get("question_rate", 0.2) or 0.2)
                    profile["formality_score"] = float(profile.get("formality_score", 0.5) or 0.5)

                    logging.info(f"User profile loaded for {user_id}")
                    return profile
                else:
                    logging.warning(f"No profile found for user {user_id}")
                    return None
        except sqlite3.Error as e:
            logging.error(f"Database error loading user profile for {user_id}: {e}", exc_info=True)
            return None
        except Exception as e:
             logging.error(f"Unexpected error loading profile for {user_id}: {e}", exc_info=True)
             return None

    def get_user_name(self, user_id: str) -> Optional[str]:
        """Convenience function to get user's name."""
        profile = self.load_user_profile(user_id)
        return profile.get("name") if profile else None

    # --- Chat Logging ---
    def log_chat_message(self, user_id: str, role: str, content: str,
                         emotion_analysis: Optional[Dict] = None, sentiment: Optional[str] = None,
                         prompted_by_user_log_id: Optional[int] = None) -> int:
        """Logs a chat message (V4). Returns the inserted row ID or -1 on failure."""
        logging.debug(f"Logging chat message for user {user_id}, role {role}")
        sql = f"""INSERT INTO `{config.chat_table_name}`
                  (`user_id`, `role`, `content`, `emotion_analysis`, `sentiment`, `timestamp`, `prompted_by_user_log_id`)
                  VALUES (?, ?, ?, ?, ?, ?, ?)"""
        timestamp = get_current_date_time_iso()
        emotion_json = None
        if isinstance(emotion_analysis, dict):
            try:
                # Filter out numpy types before JSON dump if necessary
                serializable_emotions = {k: (float(v) if isinstance(v, (np.float32, np.float64)) else v) for k, v in emotion_analysis.items()}
                emotion_json = json.dumps(serializable_emotions)
            except TypeError as e:
                logging.error(f"Failed to serialize emotion_analysis for logging: {e}")
        elif emotion_analysis is not None:
             logging.warning(f"emotion_analysis is not a dict, cannot serialize: {type(emotion_analysis)}")

        params = (user_id, role, content, emotion_json, sentiment, timestamp, prompted_by_user_log_id)

        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(sql, params)
                log_id = cursor.lastrowid
                if log_id is None or log_id <= 0:
                    logging.error(f"Failed to get valid lastrowid after logging chat message for user {user_id}. DB returned: {log_id}")
                    # Fallback check
                    cursor.execute("SELECT last_insert_rowid()")
                    result = cursor.fetchone()
                    log_id = result[0] if result else -1
                    if log_id <= 0:
                         logging.error("Fallback check for last insert rowid also failed.")
                         return -1
                logging.info(f"Chat message logged (ID: {log_id}) for user {user_id}, role: {role}")
                return log_id
        except sqlite3.Error as e:
            logging.error(f"Database error logging chat message for {user_id}: {e}", exc_info=True)
            return -1
        except Exception as e:
             logging.error(f"Unexpected error logging chat message for {user_id}: {e}", exc_info=True)
             return -1

    def fetch_recent_messages(self, user_id: str, limit: int = config.max_history_length * 2) -> List[Dict[str, Any]]:
        """Fetches recent messages for a user, ordered chronologically (V4). Fetch slightly more for context prep."""
        logging.debug(f"Fetching recent {limit} messages for user {user_id}")
        sql = f"""SELECT `id`, `role`, `content`, `timestamp`, `prompted_by_user_log_id`
                  FROM `{config.chat_table_name}`
                  WHERE `user_id` = ? ORDER BY `timestamp` DESC LIMIT ?"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(sql, (user_id, limit))
                # Fetch all rows, convert to dicts, then reverse for chronological order
                messages = [dict(row) for row in cursor.fetchall()][::-1]
                logging.info(f"Fetched {len(messages)} recent messages for user {user_id}")
                return messages
        except sqlite3.Error as e:
            logging.error(f"Database error fetching recent messages for {user_id}: {e}", exc_info=True)
            return []
        except Exception as e:
             logging.error(f"Unexpected error fetching recent messages for {user_id}: {e}", exc_info=True)
             return []

    # --- Feedback Logging ---
    def log_feedback(self, user_id: str, rating: int, feedback_type: str,
                     chat_log_id: Optional[int] = None, message_content: Optional[str] = None,
                     comment: Optional[str] = None):
        """Logs user feedback (V4)."""
        logging.debug(f"Logging feedback for user {user_id}, type {feedback_type}, rating {rating}")
        sql = f"""INSERT INTO `{config.feedback_table_name}`
                  (`user_id`, `rating`, `feedback_type`, `chat_log_id`, `message_content`, `comment`, `timestamp`)
                  VALUES (?, ?, ?, ?, ?, ?, ?)"""
        timestamp = get_current_date_time_iso()
        # Only save message_content if chat_log_id is not provided
        content_to_save = message_content if chat_log_id is None and message_content else None
        params = (user_id, rating, feedback_type, chat_log_id, content_to_save, comment, timestamp)
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(sql, params)
                logging.info(f"Feedback logged for user {user_id} (Type: {feedback_type}, Rating: {rating}, Comment: {'Yes' if comment else 'No'})")
        except sqlite3.Error as e:
            logging.error(f"Database error logging feedback for {user_id}: {e}", exc_info=True)
        except Exception as e:
             logging.error(f"Unexpected error logging feedback for {user_id}: {e}", exc_info=True)


    def fetch_feedback_summary(self, user_id: str, feedback_type: Optional[str] = None, time_window_days: int = 30) -> Dict[str, Dict[str, Any]]:
        """Fetches aggregated feedback summary (V4)."""
        logging.debug(f"Fetching feedback summary for user {user_id}, type {feedback_type}, window {time_window_days} days")
        since_timestamp = (datetime.now(timezone.utc) - timedelta(days=time_window_days)).isoformat()
        base_sql = f"""SELECT `feedback_type`, `rating`, `comment`
                       FROM `{config.feedback_table_name}`
                       WHERE `user_id` = ? AND `timestamp` >= ?"""
        params = [user_id, since_timestamp]
        if feedback_type:
            base_sql += " AND `feedback_type` = ?"
            params.append(feedback_type)

        summary = defaultdict(lambda: {"total_rating": 0, "count": 0, "average": 0.0, "comments": []})
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(base_sql, tuple(params))
                for row in cursor.fetchall():
                    row_dict = dict(row)
                    f_type = row_dict['feedback_type']
                    summary[f_type]['total_rating'] += row_dict['rating']
                    summary[f_type]['count'] += 1
                    if row_dict['comment']:
                        summary[f_type]['comments'].append(row_dict['comment'])

                for f_type in summary:
                    count = summary[f_type]['count']
                    total_rating = summary[f_type]['total_rating']
                    summary[f_type]['average'] = total_rating / count if count else 0.0

            log_summary = {
                k: {'avg': f"{v['average']:.2f}", 'count': v['count'], 'comments': len(v['comments'])}
                for k, v in summary.items()
            }
            logging.info(f"Feedback summary fetched for user {user_id}: {log_summary}")
            return dict(summary)

        except sqlite3.Error as e:
            logging.error(f"Database error fetching feedback summary for {user_id}: {e}", exc_info=True)
            return {}
        except Exception as e:
             logging.error(f"Unexpected error fetching feedback summary for {user_id}: {e}", exc_info=True)
             return {}

    # --- Memory Interaction (V4 - BLOB Handling) ---
    def save_memory_interaction(self, user_id: str, text: str, embedding: np.ndarray,
                                emotion: str, importance: float, timestamp: str,
                                related_chat_log_id: Optional[int] = None, memory_type: str = 'short_term') -> Optional[int]:
        """
        Saves a memory interaction with optimized blob storage.

        Args:
            user_id: User identifier
            text: Memory text content
            embedding: Vector embedding as numpy array
            emotion: Primary emotion associated with memory
            importance: Base importance score (0.0-1.0)
            timestamp: ISO format UTC timestamp
            related_chat_log_id: Optional link to chat log entry
            memory_type: 'short_term' or 'long_term'

        Returns:
            Database ID of the inserted memory or None on failure
        """
        # Validate inputs for production safety
        if not user_id or not isinstance(user_id, str):
            logging.error(f"Invalid user_id for memory save: {type(user_id)}")
            return None

        if not text or not isinstance(text, str):
            logging.error(f"Invalid text for memory save: {type(text)}")
            return None

        if not isinstance(embedding, np.ndarray):
            logging.error(f"Invalid embedding type for memory save: {type(embedding)}")
            return None

        # Validate embedding shape
        if embedding.ndim != 1:
            logging.error(f"Invalid embedding shape for memory save: {embedding.shape}")
            if embedding.size == get_embedding_dimension():
                # Try to fix the shape if possible
                embedding = embedding.flatten()
            else:
                return None

        # Log the operation with structured event
        logging.log_event(
            "memory_save",
            user_id=user_id,
            importance=round(importance, 2),
            memory_type=memory_type,
            text_length=len(text),
            emotion=emotion
        )

        # Prepare SQL with parameterized query
        sql = f"""INSERT INTO `{config.memory_table_name}`
                  (`user_id`, `text`, `embedding`, `emotion`, `importance`,
                   `timestamp`, `related_chat_log_id`, `last_accessed`,
                   `access_count`, `memory_type`)
                  VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"""

        try:
            # Ensure embedding is float32 and normalized before converting to blob
            normalized_embedding = embedding.astype(np.float32)
            norm = np.linalg.norm(normalized_embedding)

            if norm > 0 and not np.isclose(norm, 1.0, atol=1e-5):
                normalized_embedding = normalized_embedding / norm

            # Convert to binary blob with proper error handling
            embedding_blob = sqlite3.Binary(normalized_embedding.tobytes())

            # Get current time for access tracking
            current_time_iso = get_current_date_time_iso()

            # Prepare parameters with proper validation
            params = (
                user_id,
                text[:10000],  # Limit text size for safety
                embedding_blob,
                emotion[:50] if emotion else "neutral",  # Limit emotion string size
                max(0.0, min(1.0, importance)),  # Clamp importance between 0-1
                timestamp,
                related_chat_log_id,
                current_time_iso,
                1,  # Initial access count
                memory_type if memory_type in ('short_term', 'long_term') else 'short_term'
            )

            # Execute database operation with proper transaction handling
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(sql, params)

                # Get inserted ID with fallback mechanism
                db_id = cursor.lastrowid
                if not db_id or db_id <= 0:
                    cursor.execute("SELECT last_insert_rowid()")
                    result = cursor.fetchone()
                    db_id = result[0] if result else None

                    if not db_id or db_id <= 0:
                        logging.error("Failed to get valid memory insertion ID")
                        return None

                # Log success with metrics
                logging.log_metric(
                    "memory_save_success",
                    1,
                    user_id=user_id,
                    memory_id=db_id,
                    memory_type=memory_type
                )

                return db_id

        except sqlite3.Error as e:
            # Handle database-specific errors
            logging.error(f"Database error saving memory: {e}", exc_info=True)
            logging.log_metric("memory_save_error", 1, error_type="sqlite", user_id=user_id)
            return None

        except Exception as e:
            # Handle other exceptions
            logging.error(f"Unexpected error saving memory: {e}", exc_info=True)
            logging.log_metric("memory_save_error", 1, error_type="general", user_id=user_id)
            return None

    def update_memory_importance(self, memory_id: int, importance_change: float):
        """Updates the importance score of a specific memory entry, clamping between 0.0 and 1.0."""
        logging.debug(f"Updating importance for memory ID {memory_id} by {importance_change:.2f}")
        # Clamp using SQL's MAX/MIN for atomicity
        sql_update = f"""UPDATE `{config.memory_table_name}`
                         SET `importance` = MAX(0.0, MIN(1.0, `importance` + ?))
                         WHERE `id` = ?"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(sql_update, (importance_change, memory_id))
                if cursor.rowcount > 0:
                    logging.info(f"Updated importance for memory ID {memory_id} (Change: {importance_change:.2f})")
                else:
                    logging.warning(f"Memory ID {memory_id} not found for importance update (or importance already at boundary).")
        except sqlite3.Error as e:
            logging.error(f"Database error updating memory importance for ID {memory_id}: {e}", exc_info=True)
        except Exception as e:
             logging.error(f"Unexpected error updating memory importance for ID {memory_id}: {e}", exc_info=True)

    def load_recent_memories(self, user_id: str, limit: int = 250, memory_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Loads recent memory entries with optimized performance and error handling.

        Args:
            user_id: User identifier
            limit: Maximum number of memories to load
            memory_type: Optional filter for memory type ('short_term' or 'long_term')

        Returns:
            List of memory dictionaries with numpy array embeddings
        """
        # Input validation for production safety
        if not user_id or not isinstance(user_id, str):
            logging.error(f"Invalid user_id for memory loading: {type(user_id)}")
            return []

        if not isinstance(limit, int) or limit <= 0:
            logging.warning(f"Invalid limit for memory loading: {limit}, using default")
            limit = 250

        if memory_type and memory_type not in ('short_term', 'long_term'):
            logging.warning(f"Invalid memory_type: {memory_type}, ignoring filter")
            memory_type = None

        # Log operation with structured event
        logging.log_event(
            "memory_load",
            user_id=user_id,
            limit=limit,
            memory_type=memory_type or "all"
        )

        # Prepare optimized SQL query with index usage
        if memory_type:
            sql = f"""SELECT `id`, `text`, `embedding`, `emotion`, `importance`,
                      `timestamp`, `last_accessed`, `access_count`, `related_chat_log_id`, `memory_type`
                      FROM `{config.memory_table_name}`
                      WHERE `user_id` = ? AND `memory_type` = ?
                      ORDER BY `timestamp` DESC LIMIT ?"""
            params = (user_id, memory_type, limit)
        else:
            sql = f"""SELECT `id`, `text`, `embedding`, `emotion`, `importance`,
                      `timestamp`, `last_accessed`, `access_count`, `related_chat_log_id`, `memory_type`
                      FROM `{config.memory_table_name}`
                      WHERE `user_id` = ?
                      ORDER BY `timestamp` DESC LIMIT ?"""
            params = (user_id, limit)

        memories = []
        start_time = time.time()

        try:
            # Get embedding dimension without loading full model if possible
            embedding_dim = get_embedding_dimension()

            # Execute query with proper transaction handling
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(sql, params)

                # Fetch all rows at once for better performance
                rows = cursor.fetchall()

                # Process rows with optimized error handling
                valid_count = 0
                error_count = 0

                for row in rows:
                    memory_dict = dict(row)
                    embedding_blob = memory_dict.get('embedding')
                    memory_id = memory_dict.get('id')

                    # Skip invalid embeddings
                    if not isinstance(embedding_blob, bytes):
                        error_count += 1
                        continue

                    try:
                        # Convert BLOB to numpy array efficiently
                        embedding_array = np.frombuffer(embedding_blob, dtype=np.float32)

                        # Validate dimension
                        if embedding_array.size == embedding_dim:
                            # Store the array in the dict
                            memory_dict['embedding'] = embedding_array
                            memories.append(memory_dict)
                            valid_count += 1
                        else:
                            error_count += 1
                    except Exception as e:
                        error_count += 1
                        logging.error(f"Error processing memory embedding (ID: {memory_id}): {e}")

                # Log performance metrics
                elapsed_time = time.time() - start_time
                logging.log_metric(
                    "memory_load_performance",
                    elapsed_time,
                    user_id=user_id,
                    count=valid_count,
                    errors=error_count
                )

                # Return in chronological order (oldest first)
                return sorted(memories, key=lambda m: m.get('timestamp', ''))

        except sqlite3.Error as e:
            # Handle database-specific errors
            logging.error(f"Database error loading memories: {e}", exc_info=True)
            logging.log_metric("memory_load_error", 1, error_type="sqlite", user_id=user_id)
            return []

        except Exception as e:
            # Handle other exceptions
            logging.error(f"Unexpected error loading memories: {e}", exc_info=True)
            logging.log_metric("memory_load_error", 1, error_type="general", user_id=user_id)
            return []

    def record_memory_access(self, memory_ids: List[int]):
        """Updates access count and timestamp for given memory IDs (V4)."""
        if not memory_ids: return
        # Ensure IDs are integers and positive
        valid_ids = [int(mid) for mid in memory_ids if isinstance(mid, (int, float, np.integer)) and mid > 0] # Handle numpy int types too
        if not valid_ids:
            logging.warning(f"No valid memory IDs provided to record_memory_access. Original: {memory_ids}")
            return

        logging.debug(f"Recording access for memory IDs: {valid_ids}")
        sql_update = f"""UPDATE `{config.memory_table_name}`
                         SET `last_accessed` = ?, `access_count` = `access_count` + 1
                         WHERE `id` = ?"""
        current_time_iso = get_current_date_time_iso()
        params = [(current_time_iso, mem_id) for mem_id in valid_ids]

        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.executemany(sql_update, params)
                logging.info(f"Recorded access attempt for {cursor.rowcount} memory entries (requested: {len(valid_ids)}).")
        except sqlite3.Error as e:
            logging.error(f"Database error recording memory access: {e}", exc_info=True)
        except Exception as e:
             logging.error(f"Unexpected error recording memory access: {e}", exc_info=True)

    def get_user_message_id_for_assistant_response(self, assistant_log_id: int) -> Optional[int]:
        """Finds the user message ID that prompted a given assistant response (V4)."""
        sql = f"SELECT `prompted_by_user_log_id` FROM `{config.chat_table_name}` WHERE `id` = ?"
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(sql, (assistant_log_id,))
                result = cursor.fetchone()
                return result['prompted_by_user_log_id'] if result and result['prompted_by_user_log_id'] else None
        except sqlite3.Error as e:
            logging.error(f"Error fetching user message ID for assistant ID {assistant_log_id}: {e}", exc_info=True)
            return None
        except Exception as e:
             logging.error(f"Unexpected error fetching user message ID for assistant ID {assistant_log_id}: {e}", exc_info=True)
             return None

    def get_memory_id_for_chat_log(self, user_chat_log_id: int) -> Optional[int]:
        """Finds the memory DB ID associated with a specific user chat log entry (V4)."""
        # Assumes a chat log ID usually links to one memory, gets the most recent if multiple somehow exist
        sql = f"SELECT `id` FROM `{config.memory_table_name}` WHERE `related_chat_log_id` = ? ORDER BY `timestamp` DESC LIMIT 1"
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(sql, (user_chat_log_id,))
                result = cursor.fetchone()
                return result['id'] if result else None
        except sqlite3.Error as e:
            logging.error(f"Error fetching memory ID for chat log ID {user_chat_log_id}: {e}", exc_info=True)
            return None
        except Exception as e:
             logging.error(f"Unexpected error fetching memory ID for chat log ID {user_chat_log_id}: {e}", exc_info=True)
             return None

# === AUTHENTICATION MANAGER (V4 Schema) ===
class AuthenticationManager:
    """Handles user registration and login verification using V4 schema."""
    def __init__(self, database_manager: DatabaseManager):
        self.db_manager = database_manager
        logging.info("AuthenticationManager initialized.")

    def register_user(self, username: str, password: str) -> Tuple[bool, str]:
        """Registers a new user."""
        logging.info(f"Attempting registration for username: {username}")
        if not username or not password: return False, "Username and password cannot be empty."
        if len(username) < 3 or len(username) > 30: return False, "Username must be between 3 and 30 characters."
        if len(password) < 8: return False, "Password must be at least 8 characters long."
        if not re.match("^[a-zA-Z0-9_-]+$", username):
            return False, "Username can only contain letters, numbers, underscore, and hyphen."

        try:
            hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
            user_id = str(uuid.uuid4())
            sql = f"""INSERT INTO `{config.user_table_name}`
                      (`user_id`, `username`, `password_hash`, `created_at`, `last_active`)
                      VALUES (?, ?, ?, ?, ?)"""
            timestamp = get_current_date_time_iso()
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(sql, (user_id, username, hashed_password, timestamp, timestamp))
            logging.info(f"User '{username}' registered successfully with user_id: {user_id}")
            return True, user_id # Return user_id on success
        except sqlite3.IntegrityError:
            logging.warning(f"Registration failed for '{username}': Username already exists.")
            return False, "Username already exists. Please choose another or login."
        except Exception as e:
            logging.error(f"Error during registration for '{username}': {e}", exc_info=True)
            return False, "An unexpected error occurred during registration."

    def verify_user(self, username: str, password: str) -> Tuple[bool, Optional[str], str]:
        """Verifies user login credentials."""
        logging.info(f"Attempting login for username: {username}")
        if not username or not password: return False, None, "Username and password required."

        sql = f"SELECT `user_id`, `password_hash` FROM `{config.user_table_name}` WHERE `username` = ?"
        try:
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(sql, (username,))
                result = cursor.fetchone()

                if result:
                    user_id, stored_hash = result['user_id'], result['password_hash']
                    if bcrypt.checkpw(password.encode('utf-8'), stored_hash.encode('utf-8')):
                        # Update last active time on successful login
                        # SECURITY FIX: Validate table name
                        table_name = config.user_table_name
                        if not table_name.replace('_', '').replace('v', '').replace('4', '').isalnum():
                            raise ValueError(f"Invalid table name: {table_name}")
                        update_sql = f"UPDATE `{table_name}` SET `last_active` = ? WHERE `user_id` = ?"
                        cursor.execute(update_sql, (get_current_date_time_iso(), user_id))
                        logging.info(f"User '{username}' (ID: {user_id}) logged in successfully.")
                        return True, user_id, "Login successful!"
                    else:
                        logging.warning(f"Login failed for '{username}': Invalid password.")
                        return False, None, "Invalid username or password."
                else:
                    logging.warning(f"Login failed: Username '{username}' not found.")
                    return False, None, "Invalid username or password." # Generic message
        except Exception as e:
            logging.error(f"Error during login verification for '{username}': {e}", exc_info=True)
            return False, None, "An error occurred during login."

# === KNOWLEDGE GRAPH MANAGER (V4) ===
class KnowledgeGraphManager:
    """
    Manages a temporal knowledge graph for storing and retrieving facts about users.
    Uses FAISS for semantic search and SQLite for persistence.
    """
    def __init__(self, db_manager: DatabaseManager):
        if faiss is None:
            logging.critical("FAISS library not available. Knowledge Graph cannot function.")
            raise ImportError("FAISS library not found. Please install it.")

        self.db_manager = db_manager
        self.encoder = get_sentence_transformer()
        try:
            self.embedding_dimension = self.encoder.get_sentence_embedding_dimension()
        except Exception as e:
            logging.critical(f"Failed to get embedding dimension from sentence transformer: {e}")
            raise RuntimeError("Could not determine embedding dimension.") from e

        # Fact indexes (user_id -> index)
        self.fact_indices = {}
        self.fact_store = defaultdict(list)  # user_id -> list of facts
        self.fact_to_store_idx_map = defaultdict(dict)  # Maps FAISS index -> fact_store index

        # Entity and relationship caches
        self.entity_cache = {}  # entity_id -> entity dict
        self.relationship_cache = {}  # relationship_id -> relationship dict

        self._loaded_users = set()  # Track users loaded in this session

        # Initialize database schema
        self._init_database_schema()

        logging.info(f"KnowledgeGraphManager initialized (V4) (Dim: {self.embedding_dimension}, Index: IndexFlatIP)")

    def _init_database_schema(self):
        """Initialize the database schema for the knowledge graph."""
        try:
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()

                # Create entities table
                cursor.execute("""
                CREATE TABLE IF NOT EXISTS kg_entities (
                    entity_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    type TEXT NOT NULL,
                    properties TEXT,
                    created_at TEXT NOT NULL,
                    last_updated TEXT NOT NULL
                )
                """)

                # Create relationships table
                cursor.execute("""
                CREATE TABLE IF NOT EXISTS kg_relationships (
                    relationship_id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    type TEXT NOT NULL,
                    properties TEXT,
                    confidence REAL DEFAULT 0.5,
                    valid_from TEXT NOT NULL,
                    valid_until TEXT,
                    created_at TEXT NOT NULL,
                    last_updated TEXT NOT NULL,
                    FOREIGN KEY (source_id) REFERENCES kg_entities (entity_id),
                    FOREIGN KEY (target_id) REFERENCES kg_entities (entity_id)
                )
                """)

                # Create facts table
                cursor.execute("""
                CREATE TABLE IF NOT EXISTS kg_facts (
                    fact_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    content TEXT NOT NULL,
                    source_message_id TEXT,
                    entities TEXT,
                    relationships TEXT,
                    confidence REAL DEFAULT 0.5,
                    importance REAL DEFAULT 0.5,
                    embedding BLOB,
                    properties TEXT,
                    created_at TEXT NOT NULL,
                    valid_from TEXT NOT NULL,
                    valid_until TEXT,
                    last_updated TEXT
                )
                """)

                # Create indices for better performance
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_kg_entities_name ON kg_entities (name)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_kg_entities_type ON kg_entities (type)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_kg_relationships_source ON kg_relationships (source_id)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_kg_relationships_target ON kg_relationships (target_id)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_kg_relationships_type ON kg_relationships (type)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_kg_facts_user ON kg_facts (user_id)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_kg_facts_valid ON kg_facts (valid_from, valid_until)")

                logging.info("Knowledge graph database schema initialized")

        except sqlite3.Error as e:
            logging.error(f"Database error initializing knowledge graph schema: {e}", exc_info=True)
            # Continue anyway - the application might still work with existing tables

    def _ensure_normalized(self, embedding: np.ndarray, context: str = "operation") -> Optional[np.ndarray]:
        """Helper to ensure an embedding is normalized (L2 norm=1) and float32."""
        if not isinstance(embedding, np.ndarray):
            logging.warning(f"Cannot normalize non-numpy array ({type(embedding)}) in {context}.")
            return None
        if embedding.ndim != 1:
            logging.warning(f"Embedding must be 1D for normalization check, got {embedding.ndim}D in {context}. Shape: {embedding.shape}")
            # Attempt flatten, but this might hide issues
            if embedding.size == self.embedding_dimension:
                embedding = embedding.flatten()
            else:
                return None  # Cannot fix if size is wrong

        if embedding.dtype != np.float32:
            embedding = embedding.astype(np.float32)

        norm = np.linalg.norm(embedding)

        if norm == 0:
            # Cannot normalize a zero vector, return it as is
            return embedding

        if not np.isclose(norm, 1.0, atol=1e-6):
            logging.debug(f"Re-normalizing embedding (norm={norm:.4f}) during {context}.")
            embedding = embedding / norm
            # Double check norm after correction
            new_norm = np.linalg.norm(embedding)
            if not np.isclose(new_norm, 1.0, atol=1e-6):
                logging.error(f"CRITICAL: Re-normalization failed! Norm is {new_norm:.6f}. Returning original non-normalized vector for safety (might break FAISS IP).")
                return embedding / norm  # Return the re-normalized one anyway

        return embedding

    def _get_or_create_fact_index(self, user_id: str):
        """Gets or creates a FAISS index for the user's facts, loading from DB on first access."""
        if user_id not in self.fact_indices:
            logging.info(f"Initializing FAISS index for facts of user '{user_id}'")
            try:
                # Create structures first
                self.fact_store[user_id] = []
                self.fact_to_store_idx_map[user_id] = {}
                # Use IndexFlatIP for cosine similarity on normalized vectors
                index = faiss.IndexFlatIP(self.embedding_dimension)
                self.fact_indices[user_id] = index

                # Load from DB if not already loaded for this session
                if user_id not in self._loaded_users:
                    self._load_facts_from_db(user_id)
                    self._loaded_users.add(user_id)

            except Exception as e:
                logging.error(f"Failed to initialize FAISS index or load facts for user '{user_id}': {e}", exc_info=True)
                # Clean up partially created structures on failure
                self.fact_store.pop(user_id, None)
                self.fact_indices.pop(user_id, None)
                self.fact_to_store_idx_map.pop(user_id, None)
                self._loaded_users.discard(user_id)
                return None  # Indicate failure

        return self.fact_indices.get(user_id)

    def _load_facts_from_db(self, user_id: str):
        """Loads facts from DB, ensures normalization, and indexes into FAISS/fact store."""
        logging.info(f"Loading and indexing facts for user '{user_id}' from DB.")

        # Get facts from DB
        try:
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT * FROM kg_facts WHERE user_id = ? AND valid_until IS NULL",
                    (user_id,)
                )
                db_facts = cursor.fetchall()

                if not db_facts:
                    logging.info(f"No facts found in DB for user '{user_id}'.")
                    return

                # Reset existing in-memory data before loading
                index = self.fact_indices.get(user_id)
                if index and index.ntotal > 0:
                    logging.warning(f"Resetting existing FAISS index ({index.ntotal} entries) for user '{user_id}' before loading from DB.")
                    index.reset()
                    self.fact_store[user_id] = []
                    self.fact_to_store_idx_map[user_id] = {}

                # Process each fact
                for fact_row in db_facts:
                    fact_dict = dict(fact_row)
                    fact_id = fact_dict['fact_id']

                    # Get embedding
                    embedding_blob = fact_dict.get('embedding')
                    if embedding_blob:
                        try:
                            embedding = np.frombuffer(embedding_blob, dtype=np.float32)
                            if embedding.size != self.embedding_dimension:
                                logging.warning(f"Skipping fact {fact_id}: Wrong embedding dimension ({embedding.size} != {self.embedding_dimension})")
                                continue

                            # Ensure normalization
                            embedding = self._ensure_normalized(embedding, f"DB load (Fact ID: {fact_id})")
                            if embedding is None:
                                logging.warning(f"Skipping fact {fact_id}: Normalization failed")
                                continue

                            # Add to index and store
                            self._add_fact_to_index(user_id, fact_dict, embedding)

                        except Exception as e:
                            logging.error(f"Error processing embedding for fact {fact_id}: {e}", exc_info=True)
                    else:
                        # Generate embedding if not in DB
                        try:
                            embedding = get_embedding(fact_dict['content'], self.encoder)
                            if embedding is not None:
                                # Save embedding to DB
                                cursor.execute(
                                    "UPDATE kg_facts SET embedding = ? WHERE fact_id = ?",
                                    (sqlite3.Binary(embedding.tobytes()), fact_id)
                                )
                                # Add to index and store
                                self._add_fact_to_index(user_id, fact_dict, embedding)
                        except Exception as e:
                            logging.error(f"Error generating embedding for fact {fact_id}: {e}", exc_info=True)

                logging.info(f"Loaded {len(self.fact_store[user_id])} facts for user '{user_id}'")

        except sqlite3.Error as e:
            logging.error(f"Database error loading facts for user '{user_id}': {e}", exc_info=True)
        except Exception as e:
            logging.error(f"Unexpected error loading facts for user '{user_id}': {e}", exc_info=True)

    def _add_fact_to_index(self, user_id: str, fact_dict: Dict, embedding: np.ndarray):
        """Adds a fact to the FAISS index and fact store."""
        index = self.fact_indices.get(user_id)
        if index is None:
            logging.error(f"Cannot add fact to index: No index found for user '{user_id}'")
            return

        # Convert entities and relationships from JSON strings if needed
        if 'entities' in fact_dict and isinstance(fact_dict['entities'], str):
            try:
                fact_dict['entities'] = json.loads(fact_dict['entities'])
            except json.JSONDecodeError:
                fact_dict['entities'] = []

        if 'relationships' in fact_dict and isinstance(fact_dict['relationships'], str):
            try:
                fact_dict['relationships'] = json.loads(fact_dict['relationships'])
            except json.JSONDecodeError:
                fact_dict['relationships'] = []

        # Add to store
        store_idx = len(self.fact_store[user_id])
        self.fact_store[user_id].append(fact_dict)

        # Add to index
        faiss_idx = index.ntotal
        index.add(embedding.reshape(1, -1))  # FAISS expects 2D array

        # Map FAISS index to store index
        self.fact_to_store_idx_map[user_id][faiss_idx] = store_idx

    def add_entity(self, name: str, entity_type: str, properties: Optional[Dict[str, Any]] = None) -> Optional[str]:
        """
        Adds a new entity to the knowledge graph.

        Args:
            name: The name of the entity
            entity_type: The type of entity (person, place, thing, etc.)
            properties: Optional dictionary of additional properties

        Returns:
            The entity ID if successful, None otherwise
        """
        entity_id = str(uuid.uuid4())
        created_at = get_current_date_time_iso()

        # Create entity dict
        entity = {
            'entity_id': entity_id,
            'name': name,
            'type': entity_type,
            'properties': json.dumps(properties or {}),
            'created_at': created_at,
            'last_updated': created_at
        }

        # Save to DB
        try:
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO kg_entities
                        (entity_id, name, type, properties, created_at, last_updated)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (entity_id, name, entity_type, entity['properties'], created_at, created_at)
                )

                # Add to cache
                self.entity_cache[entity_id] = entity

                logging.info(f"Added entity: {name} ({entity_type}) with ID {entity_id}")
                return entity_id

        except sqlite3.Error as e:
            logging.error(f"Database error adding entity {name}: {e}", exc_info=True)
            return None
        except Exception as e:
            logging.error(f"Unexpected error adding entity {name}: {e}", exc_info=True)
            return None

    def add_relationship(self, source_id: str, target_id: str, relationship_type: str,
                         properties: Optional[Dict[str, Any]] = None,
                         confidence: float = 0.5) -> Optional[str]:
        """
        Adds a new relationship between two entities.

        Args:
            source_id: The ID of the source entity
            target_id: The ID of the target entity
            relationship_type: The type of relationship
            properties: Optional dictionary of additional properties
            confidence: Confidence score (0.0 to 1.0)

        Returns:
            The relationship ID if successful, None otherwise
        """
        relationship_id = str(uuid.uuid4())
        created_at = get_current_date_time_iso()
        valid_from = created_at

        # Create relationship dict
        relationship = {
            'relationship_id': relationship_id,
            'source_id': source_id,
            'target_id': target_id,
            'type': relationship_type,
            'properties': json.dumps(properties or {}),
            'confidence': confidence,
            'valid_from': valid_from,
            'valid_until': None,
            'created_at': created_at,
            'last_updated': created_at
        }

        # Save to DB
        try:
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO kg_relationships
                        (relationship_id, source_id, target_id, type, properties, confidence,
                         valid_from, valid_until, created_at, last_updated)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (relationship_id, source_id, target_id, relationship_type,
                     relationship['properties'], confidence, valid_from, None, created_at, created_at)
                )

                # Add to cache
                self.relationship_cache[relationship_id] = relationship

                logging.info(f"Added relationship: {relationship_type} between {source_id} and {target_id} with ID {relationship_id}")
                return relationship_id

        except sqlite3.Error as e:
            logging.error(f"Database error adding relationship {relationship_type}: {e}", exc_info=True)
            return None
        except Exception as e:
            logging.error(f"Unexpected error adding relationship {relationship_type}: {e}", exc_info=True)
            return None

    def add_fact(self, user_id: str, content: str, source_message_id: Optional[str] = None,
                entities: Optional[List[str]] = None, relationships: Optional[List[str]] = None,
                confidence: float = 0.5, importance: float = 0.5) -> Optional[str]:
        """
        Adds a new fact to the knowledge graph.

        Args:
            user_id: The ID of the user this fact belongs to
            content: The text content of the fact
            source_message_id: Optional ID of the message this fact was extracted from
            entities: Optional list of entity IDs related to this fact
            relationships: Optional list of relationship IDs related to this fact
            confidence: Confidence score (0.0 to 1.0)
            importance: Importance score (0.0 to 1.0)

        Returns:
            The fact ID if successful, None otherwise
        """
        fact_id = str(uuid.uuid4())
        created_at = get_current_date_time_iso()
        valid_from = created_at

        # Get embedding
        embedding = get_embedding(content, self.encoder)
        if embedding is None:
            logging.error(f"Failed to generate embedding for fact: {content[:50]}...")
            return None

        # Ensure index exists
        index = self._get_or_create_fact_index(user_id)
        if index is None:
            logging.error(f"Failed to get/create fact index for user {user_id}")
            return None

        # Create fact dict
        fact = {
            'fact_id': fact_id,
            'user_id': user_id,
            'content': content,
            'source_message_id': source_message_id,
            'entities': json.dumps(entities or []),
            'relationships': json.dumps(relationships or []),
            'confidence': confidence,
            'importance': importance,
            'created_at': created_at,
            'valid_from': valid_from,
            'valid_until': None
        }

        # Save to DB
        try:
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO kg_facts
                        (fact_id, user_id, content, source_message_id, entities, relationships,
                         confidence, importance, created_at, valid_from, valid_until, embedding)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (fact_id, user_id, content, source_message_id, fact['entities'], fact['relationships'],
                     confidence, importance, created_at, valid_from, None, sqlite3.Binary(embedding.tobytes()))
                )

                # Add to index
                fact_dict = dict(fact)  # Make a copy
                fact_dict['entities'] = entities or []  # Convert back from JSON string
                fact_dict['relationships'] = relationships or []
                self._add_fact_to_index(user_id, fact_dict, embedding)

                logging.info(f"Added fact for user {user_id}: {content[:50]}... with ID {fact_id}")
                return fact_id

        except sqlite3.Error as e:
            logging.error(f"Database error adding fact for user {user_id}: {e}", exc_info=True)
            return None
        except Exception as e:
            logging.error(f"Unexpected error adding fact for user {user_id}: {e}", exc_info=True)
            return None

    def search_facts(self, user_id: str, query: str, limit: int = 5) -> List[Dict]:
        """
        Searches for facts relevant to the query.

        Args:
            user_id: The ID of the user to search facts for
            query: The search query
            limit: Maximum number of results to return

        Returns:
            List of fact dictionaries with relevance scores
        """
        # Get embedding for query
        query_embedding = get_embedding(query, self.encoder)
        if query_embedding is None:
            logging.error(f"Failed to generate embedding for query: {query}")
            return []

        # Get index
        index = self._get_or_create_fact_index(user_id)
        if index is None or index.ntotal == 0:
            logging.warning(f"No facts indexed for user {user_id}")
            return []

        # Search index
        try:
            k = min(limit * 2, index.ntotal)  # Get more results than needed for filtering
            scores, indices = index.search(query_embedding.reshape(1, -1), k)

            # Process results
            results = []
            for i, (score, idx) in enumerate(zip(scores[0], indices[0])):
                if score < 0.5:  # Minimum similarity threshold
                    continue

                store_idx = self.fact_to_store_idx_map[user_id].get(int(idx))
                if store_idx is None:
                    logging.warning(f"Invalid store index mapping for FAISS index {idx}")
                    continue

                fact = self.fact_store[user_id][store_idx]

                # Calculate final relevance score (combination of similarity and importance)
                relevance = score * 0.7 + float(fact.get('importance', 0.5)) * 0.3

                results.append({
                    'fact': fact,
                    'similarity': float(score),
                    'relevance': float(relevance)
                })

            # Sort by relevance and limit
            results.sort(key=lambda x: x['relevance'], reverse=True)
            return results[:limit]

        except Exception as e:
            logging.error(f"Error searching facts for user {user_id}: {e}", exc_info=True)
            return []

    def extract_facts_from_message(self, user_id: str, message: str, message_id: Optional[str] = None,
                                context_messages: Optional[List[Dict]] = None) -> List[str]:
        """
        Extracts facts from a user message and adds them to the knowledge graph.

        Args:
            user_id: The ID of the user
            message: The message text
            message_id: Optional ID of the message
            context_messages: Optional list of previous messages for context

        Returns:
            List of fact IDs that were added
        """
        if not user_id:
            logging.error("Cannot extract facts: user_id is required")
            return []

        if not message or not message.strip():
            logging.debug(f"Skipping fact extraction for empty message from user {user_id}")
            return []

        # Limit message length to prevent token overflow
        max_message_length = 1000
        if len(message) > max_message_length:
            logging.warning(f"Message too long ({len(message)} chars), truncating to {max_message_length} chars for fact extraction")
            message = message[:max_message_length] + "..."

        # Get existing facts for context and conflict detection
        existing_facts = self._get_existing_facts(user_id)
        existing_fact_contents = {fact.get('content', '').lower(): fact for fact in existing_facts}

        # Prepare context from previous messages if available
        context_str = ""
        if context_messages and len(context_messages) > 0:
            context_messages = context_messages[-5:]  # Use last 5 messages for context
            context_str = "\n".join([f"{'AI' if msg.get('role') == 'assistant' else 'User'}: {msg.get('content', '')}"
                                    for msg in context_messages if msg.get('content')])
            context_str = f"\nRecent conversation context:\n{context_str}\n"

        # Use LLM to extract facts
        try:
            # Prepare prompt for fact extraction with improved instructions
            prompt = f"""
            Extract factual statements about the user from the following message.

            Focus on:
            1. Personal information (name, location, occupation, etc.)
            2. Preferences and interests (likes, dislikes, hobbies)
            3. Relationships (family, friends, pets)
            4. Experiences and events (past, present, planned)
            5. Habits and routines
            6. Important dates (birthdays, anniversaries, deadlines, exams)
            7. Health information (conditions, allergies, medications)

            IMPORTANT:
            - Extract ONLY clear factual statements, not opinions or uncertain information
            - Format each fact as a simple, complete sentence
            - Use third person (e.g., "John lives in New York")
            - Include only one fact per statement
            - Assign a confidence score (0.0 to 1.0) to each fact based on how certain you are
            - For facts that contradict previous knowledge, mark them as updates
            - Return a JSON object with the following structure:

            {{
                "facts": [
                    {{
                        "content": "John lives in New York City",
                        "confidence": 0.9,
                        "is_update": false
                    }},
                    {{
                        "content": "John has a dog named Max",
                        "confidence": 0.8,
                        "is_update": false
                    }}
                ]
            }}
            {context_str}
            Message: "{message}"

            Facts:
            """

            # Call LLM with safety settings and retry logic
            try:
                model = genai.GenerativeModel("gemini-1.5-flash")
                response = model.generate_content(prompt)

                if not response or not response.text:
                    logging.warning(f"Empty response from LLM for fact extraction")
                    return []
            except Exception as llm_error:
                logging.error(f"Error calling LLM for fact extraction: {llm_error}")
                # Try with a different model as fallback
                try:
                    logging.info("Trying fallback model for fact extraction")
                    model = genai.GenerativeModel("gemini-1.5-pro")
                    response = model.generate_content(prompt)

                    if not response or not response.text:
                        logging.warning(f"Empty response from fallback LLM for fact extraction")
                        return []
                except Exception as fallback_error:
                    logging.error(f"Error calling fallback LLM for fact extraction: {fallback_error}")
                    return []

            # Parse response
            facts_text = clean_json_response(response.text)
            facts = []

            try:
                parsed_data = json.loads(facts_text)
                if isinstance(parsed_data, dict) and "facts" in parsed_data:
                    facts = parsed_data["facts"]
                elif isinstance(parsed_data, list):
                    # Handle case where response is a direct list of facts
                    facts = parsed_data
                else:
                    logging.warning(f"Unexpected response format: {type(parsed_data)}")
            except json.JSONDecodeError:
                # Try to extract facts with regex if JSON parsing fails
                try:
                    # Try to find JSON objects in the text
                    json_pattern = r'\{[^{}]*\}'
                    json_matches = re.findall(json_pattern, facts_text)

                    if json_matches:
                        facts = []
                        for json_str in json_matches:
                            try:
                                fact_obj = json.loads(json_str)
                                if isinstance(fact_obj, dict) and "content" in fact_obj:
                                    facts.append(fact_obj)
                            except:
                                pass

                    if not facts:
                        # Fall back to simple string extraction
                        facts = []
                        fact_strings = re.findall(r'"([^"]+)"', facts_text)
                        if not fact_strings:
                            fact_strings = re.findall(r'- ([^\n]+)', facts_text)

                        for fact_str in fact_strings:
                            facts.append({"content": fact_str, "confidence": 0.7, "is_update": False})
                except Exception as regex_error:
                    logging.error(f"Error parsing facts with regex: {regex_error}")
                    return []

            # Process and validate facts
            fact_ids = []
            for fact_obj in facts:
                # Handle different fact formats
                if isinstance(fact_obj, str):
                    fact_content = fact_obj
                    confidence = 0.7
                    is_update = False
                elif isinstance(fact_obj, dict):
                    fact_content = fact_obj.get("content", "")
                    confidence = float(fact_obj.get("confidence", 0.7))
                    is_update = bool(fact_obj.get("is_update", False))
                else:
                    continue

                # Clean and validate fact content
                if not fact_content or not isinstance(fact_content, str):
                    continue

                fact_content = fact_content.strip()
                if fact_content.startswith("- "):
                    fact_content = fact_content[2:].strip()

                # Skip very short facts or facts that are just punctuation
                if len(fact_content) < 5 or fact_content.strip(".,!?;: ") == "":
                    continue

                # Calculate importance based on fact content
                importance = self._calculate_fact_importance(fact_content)

                # Check for contradictions with existing facts
                fact_content_lower = fact_content.lower()
                existing_fact = None

                # Check for similar facts (not exact matches)
                for existing_content, fact in existing_fact_contents.items():
                    similarity = self._calculate_text_similarity(fact_content_lower, existing_content)
                    if similarity > 0.8:  # High similarity threshold
                        existing_fact = fact
                        break

                if existing_fact and is_update:
                    # This is an update to an existing fact
                    logging.info(f"Updating fact: {existing_fact.get('content')} -> {fact_content}")

                    # Invalidate the old fact
                    self.invalidate_fact(
                        fact_id=existing_fact.get('fact_id'),
                        reason="updated"
                    )

                    # Add the new fact
                    fact_id = self.add_fact(
                        user_id=user_id,
                        content=fact_content,
                        source_message_id=message_id,
                        confidence=confidence,
                        importance=importance
                    )

                    if fact_id:
                        fact_ids.append(fact_id)
                elif existing_fact:
                    # This is a duplicate fact, skip it
                    logging.debug(f"Skipping duplicate fact: {fact_content}")
                    continue
                else:
                    # This is a new fact
                    fact_id = self.add_fact(
                        user_id=user_id,
                        content=fact_content,
                        source_message_id=message_id,
                        confidence=confidence,
                        importance=importance
                    )

                    if fact_id:
                        fact_ids.append(fact_id)
                        existing_fact_contents[fact_content_lower] = {
                            'fact_id': fact_id,
                            'content': fact_content
                        }

            logging.info(f"Extracted {len(fact_ids)} facts from message for user {user_id}")
            return fact_ids

        except Exception as e:
            logging.error(f"Error extracting facts from message for user {user_id}: {e}", exc_info=True)
            return []

    def _calculate_text_similarity(self, text1: str, text2: str) -> float:
        """Calculate similarity between two text strings."""
        # Simple Jaccard similarity for words
        words1 = set(text1.lower().split())
        words2 = set(text2.lower().split())

        if not words1 or not words2:
            return 0.0

        intersection = words1.intersection(words2)
        union = words1.union(words2)

        return len(intersection) / len(union)

    def _get_existing_facts(self, user_id: str) -> List[Dict]:
        """Get existing facts for a user to avoid duplicates."""
        try:
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT * FROM kg_facts WHERE user_id = ? AND valid_until IS NULL",
                    (user_id,)
                )
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logging.error(f"Error getting existing facts for user {user_id}: {e}", exc_info=True)
            return []

    def _calculate_fact_importance(self, fact_content: str) -> float:
        """Calculate importance score for a fact based on its content."""
        # Base importance
        importance = 0.5

        # Boost importance for facts about personal information
        personal_keywords = ["name", "live", "lives", "living", "age", "born", "birthday",
                            "family", "married", "spouse", "child", "children", "parent",
                            "occupation", "job", "work", "profession", "study", "studies"]

        # Boost for preferences and interests
        preference_keywords = ["like", "likes", "love", "loves", "enjoy", "enjoys", "favorite",
                              "prefer", "prefers", "hobby", "hobbies", "interest", "interests"]

        # Check for personal information
        if any(keyword in fact_content.lower() for keyword in personal_keywords):
            importance += 0.2

        # Check for preferences
        if any(keyword in fact_content.lower() for keyword in preference_keywords):
            importance += 0.1

        # Cap importance between 0.1 and 0.9
        return max(0.1, min(0.9, importance))

    def update_fact(self, fact_id: str, new_content: str = None,
                 new_confidence: float = None, new_importance: float = None) -> bool:
        """
        Updates an existing fact with new content or metadata.

        Args:
            fact_id: The ID of the fact to update
            new_content: Optional new content for the fact
            new_confidence: Optional new confidence score
            new_importance: Optional new importance score

        Returns:
            True if the update was successful, False otherwise
        """
        if not fact_id:
            logging.error("Cannot update fact: fact_id is required")
            return False

        # Get existing fact
        try:
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM kg_facts WHERE fact_id = ?", (fact_id,))
                fact = cursor.fetchone()

                if not fact:
                    logging.error(f"Cannot update fact: fact with ID {fact_id} not found")
                    return False

                # Prepare update fields
                update_fields = []
                params = []

                if new_content is not None:
                    update_fields.append("content = ?")
                    params.append(new_content)

                    # Generate new embedding if content changed
                    embedding = get_embedding(new_content, self.encoder)
                    if embedding is not None:
                        update_fields.append("embedding = ?")
                        params.append(sqlite3.Binary(embedding.tobytes()))

                if new_confidence is not None:
                    update_fields.append("confidence = ?")
                    params.append(max(0.0, min(1.0, new_confidence)))

                if new_importance is not None:
                    update_fields.append("importance = ?")
                    params.append(max(0.0, min(1.0, new_importance)))

                if not update_fields:
                    logging.warning(f"No fields to update for fact {fact_id}")
                    return True  # Nothing to update, but not an error

                # Add last_updated field
                update_fields.append("last_updated = ?")
                params.append(get_current_date_time_iso())

                # Add fact_id to params
                params.append(fact_id)

                # Execute update
                cursor.execute(
                    f"UPDATE kg_facts SET {', '.join(update_fields)} WHERE fact_id = ?",
                    params
                )

                # Update in-memory index if needed
                if new_content is not None and embedding is not None:
                    user_id = fact['user_id']
                    if user_id in self.fact_indices and user_id in self.fact_store:
                        # Find the fact in the store
                        for store_idx, stored_fact in enumerate(self.fact_store[user_id]):
                            if stored_fact.get('fact_id') == fact_id:
                                # Update the fact in the store
                                self.fact_store[user_id][store_idx]['content'] = new_content
                                if new_confidence is not None:
                                    self.fact_store[user_id][store_idx]['confidence'] = new_confidence
                                if new_importance is not None:
                                    self.fact_store[user_id][store_idx]['importance'] = new_importance

                                # Find the corresponding FAISS index
                                faiss_idx = None
                                for fidx, sidx in self.fact_to_store_idx_map[user_id].items():
                                    if sidx == store_idx:
                                        faiss_idx = fidx
                                        break

                                if faiss_idx is not None:
                                    # Update the embedding in FAISS
                                    # Note: FAISS doesn't support direct updates, so we need to rebuild the index
                                    # This is a simplified approach - in production, you'd want to batch updates
                                    logging.info(f"Updating fact {fact_id} in FAISS index for user {user_id}")
                                    self._rebuild_fact_index(user_id)

                return True

        except sqlite3.Error as e:
            logging.error(f"Database error updating fact {fact_id}: {e}", exc_info=True)
            return False
        except Exception as e:
            logging.error(f"Unexpected error updating fact {fact_id}: {e}", exc_info=True)
            return False

    def invalidate_fact(self, fact_id: str, reason: str = "superseded") -> bool:
        """
        Invalidates a fact by setting its valid_until date.

        Args:
            fact_id: The ID of the fact to invalidate
            reason: The reason for invalidation (e.g., "superseded", "corrected", "expired")

        Returns:
            True if the invalidation was successful, False otherwise
        """
        if not fact_id:
            logging.error("Cannot invalidate fact: fact_id is required")
            return False

        try:
            current_time = get_current_date_time_iso()

            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()

                # First, check if the fact exists and is valid
                cursor.execute(
                    "SELECT user_id FROM kg_facts WHERE fact_id = ? AND valid_until IS NULL",
                    (fact_id,)
                )
                result = cursor.fetchone()

                if not result:
                    logging.warning(f"Cannot invalidate fact: fact with ID {fact_id} not found or already invalidated")
                    return False

                user_id = result[0]

                # Invalidate the fact
                cursor.execute(
                    """
                    UPDATE kg_facts
                    SET valid_until = ?,
                        properties = json_set(COALESCE(properties, '{}'), '$.invalidation_reason', ?)
                    WHERE fact_id = ?
                    """,
                    (current_time, reason, fact_id)
                )

                # Update in-memory index if needed
                if user_id in self.fact_indices and user_id in self.fact_store:
                    # Find the fact in the store
                    for store_idx, stored_fact in enumerate(self.fact_store[user_id]):
                        if stored_fact.get('fact_id') == fact_id:
                            # Update the fact in the store
                            self.fact_store[user_id][store_idx]['valid_until'] = current_time

                            # Find the corresponding FAISS index
                            faiss_idx = None
                            for fidx, sidx in self.fact_to_store_idx_map[user_id].items():
                                if sidx == store_idx:
                                    faiss_idx = fidx
                                    break

                            if faiss_idx is not None:
                                # Rebuild the index to remove the invalidated fact
                                logging.info(f"Rebuilding FAISS index for user {user_id} after invalidating fact {fact_id}")
                                self._rebuild_fact_index(user_id)

                            break

                logging.info(f"Invalidated fact {fact_id} for user {user_id} with reason: {reason}")
                return True

        except sqlite3.Error as e:
            logging.error(f"Database error invalidating fact {fact_id}: {e}", exc_info=True)
            return False
        except Exception as e:
            logging.error(f"Unexpected error invalidating fact {fact_id}: {e}", exc_info=True)
            return False

    def _rebuild_fact_index(self, user_id: str) -> bool:
        """Rebuilds the FAISS index for a user's facts."""
        try:
            if user_id not in self.fact_indices or user_id not in self.fact_store:
                logging.warning(f"Cannot rebuild fact index: No index or store found for user {user_id}")
                return False

            # Get valid facts from the store
            valid_facts = [f for f in self.fact_store[user_id] if not f.get('valid_until')]

            if not valid_facts:
                logging.info(f"No valid facts found for user {user_id}, clearing index")
                self.fact_indices[user_id].reset()
                self.fact_to_store_idx_map[user_id] = {}
                return True

            # Create a new index
            new_index = faiss.IndexFlatIP(self.embedding_dimension)
            new_store = []
            new_map = {}

            # Add facts to the new index
            for fact in valid_facts:
                # Get embedding
                embedding_blob = fact.get('embedding')
                if not embedding_blob:
                    # Try to get from DB
                    with self.db_manager.get_connection() as conn:
                        cursor = conn.cursor()
                        cursor.execute(
                            "SELECT embedding FROM kg_facts WHERE fact_id = ?",
                            (fact['fact_id'],)
                        )
                        result = cursor.fetchone()
                        if result and result[0]:
                            embedding_blob = result[0]

                if embedding_blob:
                    try:
                        embedding = np.frombuffer(embedding_blob, dtype=np.float32)
                        if embedding.size != self.embedding_dimension:
                            logging.warning(f"Skipping fact {fact['fact_id']}: Wrong embedding dimension ({embedding.size} != {self.embedding_dimension})")
                            continue

                        # Ensure normalization
                        embedding = self._ensure_normalized(embedding, f"rebuild index (Fact ID: {fact['fact_id']})")
                        if embedding is None:
                            logging.warning(f"Skipping fact {fact['fact_id']}: Normalization failed")
                            continue

                        # Add to new store
                        store_idx = len(new_store)
                        new_store.append(fact)

                        # Add to new index
                        faiss_idx = new_index.ntotal
                        new_index.add(embedding.reshape(1, -1))

                        # Map FAISS index to store index
                        new_map[faiss_idx] = store_idx

                    except Exception as e:
                        logging.error(f"Error adding fact {fact['fact_id']} to new index: {e}", exc_info=True)
                else:
                    logging.warning(f"Skipping fact {fact['fact_id']}: No embedding found")

            # Replace old index, store, and map
            self.fact_indices[user_id] = new_index
            self.fact_store[user_id] = new_store
            self.fact_to_store_idx_map[user_id] = new_map

            logging.info(f"Rebuilt fact index for user {user_id} with {new_index.ntotal} facts")
            return True

        except Exception as e:
            logging.error(f"Error rebuilding fact index for user {user_id}: {e}", exc_info=True)
            return False

    def get_relevant_facts_for_context(self, user_id: str, query: str, limit: int = 5,
                                   context_messages: Optional[List[Dict]] = None,
                                   include_confidence: bool = False) -> str:
        """
        Gets relevant facts formatted as a string for inclusion in the LLM context.

        Args:
            user_id: The ID of the user
            query: The query to find relevant facts for
            limit: Maximum number of facts to include
            context_messages: Optional list of previous messages for context
            include_confidence: Whether to include confidence scores in the output

        Returns:
            Formatted string of relevant facts
        """
        if not user_id:
            return "No relevant facts found."

        try:
            # Get facts from semantic search
            semantic_facts = self.search_facts(user_id, query, limit * 2)  # Get more than needed for filtering

            # Extract topics from query for better relevance
            query_topics = self._extract_topics_from_query(query)

            # Get conversation context if available
            context_text = ""
            if context_messages and len(context_messages) > 0:
                # Use last few messages for context
                recent_messages = context_messages[-3:]
                context_text = " ".join([msg.get('content', '') for msg in recent_messages if msg.get('content')])

            # Score facts based on relevance to query, topics, and context
            scored_facts = []
            for result in semantic_facts:
                fact = result['fact']
                base_score = result['relevance']  # Base score from semantic search

                # Topic relevance boost
                topic_boost = 0.0
                for topic in query_topics:
                    if topic.lower() in fact['content'].lower():
                        topic_boost += 0.2

                # Context relevance boost
                context_boost = 0.0
                if context_text:
                    # Simple word overlap for context relevance
                    fact_words = set(fact['content'].lower().split())
                    context_words = set(context_text.lower().split())
                    overlap = len(fact_words.intersection(context_words))
                    if overlap > 0:
                        context_boost = min(0.3, overlap * 0.05)  # Cap at 0.3

                # Recency boost - newer facts are slightly preferred
                recency_boost = 0.0
                if 'created_at' in fact:
                    try:
                        created_time = datetime.fromisoformat(fact['created_at'])
                        now = datetime.now()
                        age_days = (now - created_time).days
                        recency_boost = max(0.0, 0.1 - (age_days / 100) * 0.1)  # Decay over 100 days
                    except:
                        pass

                # Importance and confidence boost
                metadata_boost = (float(fact.get('importance', 0.5)) * 0.15 +
                                 float(fact.get('confidence', 0.5)) * 0.15)

                # Calculate final score
                final_score = base_score + topic_boost + context_boost + recency_boost + metadata_boost

                scored_facts.append((final_score, fact))

            # Sort by final score and limit
            scored_facts.sort(key=lambda x: x[0], reverse=True)
            top_facts = scored_facts[:limit]

            if not top_facts:
                return "No relevant facts found."

            # Format facts
            fact_strings = []
            for i, (_, fact) in enumerate(top_facts):  # Using _ to indicate unused variable
                if include_confidence:
                    confidence = float(fact.get('confidence', 0.5))
                    fact_strings.append(f"- {fact['content']} (confidence: {confidence:.1f})")
                else:
                    fact_strings.append(f"- {fact['content']}")

            return "\n".join(fact_strings)
        except Exception as e:
            logging.error(f"Error getting relevant facts for user {user_id}: {e}", exc_info=True)
            return "No relevant facts found."

    def _extract_topics_from_query(self, query: str) -> List[str]:
        """Extract topics from a query for better fact retrieval."""
        # Define common topics and their keywords - EXPANDED for better recall
        topic_keywords = {
            "personal": ["name", "age", "birthday", "born", "from", "live", "lives", "living", "location", "address", "hometown", "city", "country", "state"],
            "education": ["study", "studies", "studying", "school", "college", "university", "degree", "course", "student", "education",
                         "class", "classes", "major", "minor", "subject", "subjects", "campus", "professor", "teacher", "lecture",
                         "assignment", "homework", "project", "thesis", "dissertation", "academic", "semester", "quarter",
                         "freshman", "sophomore", "junior", "senior", "undergrad", "graduate", "phd", "masters", "bachelor",
                         "faculty", "department", "institute", "engineering", "science", "arts", "humanities", "bit", "mesra", "ranchi"],
            "work": ["job", "work", "working", "profession", "career", "company", "business", "occupation", "office", "colleague", "boss", "manager", "employee", "salary", "wage", "income"],
            "hobbies": ["hobby", "hobbies", "enjoy", "enjoys", "like", "likes", "interest", "interests", "passion", "free time", "activity", "sport", "sports", "game", "games", "music", "art", "reading", "travel", "traveling"],
            "family": ["family", "parent", "parents", "mother", "father", "brother", "sister", "sibling", "child", "children", "married", "spouse", "wife", "husband", "grandparent", "grandchild", "aunt", "uncle", "cousin"],
            "health": ["health", "medical", "condition", "allergy", "allergies", "medication", "diet", "exercise", "doctor", "hospital", "clinic", "symptom", "illness", "disease", "wellness", "fitness"],
            "schedule": ["schedule", "plan", "plans", "planning", "appointment", "meeting", "exam", "exams", "test", "deadline", "calendar", "date", "time", "day", "week", "month", "semester", "year"]
        }

        # Find matching topics
        query_lower = query.lower()
        matched_topics = []
        topic_scores = {}  # Track topic relevance scores

        # First pass: Check for exact keyword matches
        for topic, keywords in topic_keywords.items():
            score = 0
            for keyword in keywords:
                if keyword in query_lower:
                    # Increase score based on keyword length (longer keywords are more specific)
                    keyword_score = 0.5 + (len(keyword) / 20)  # Base score + length bonus

                    # Boost score for education-related terms to improve college info retrieval
                    if topic == "education":
                        keyword_score *= 1.5

                    # Further boost specific college terms
                    if keyword in ["college", "university", "bit", "mesra", "engineering"]:
                        keyword_score *= 2

                    score += keyword_score

            if score > 0:
                matched_topics.append(topic)
                topic_scores[topic] = score

        # Second pass: Add individual keywords that might be important
        query_words = query_lower.split()
        for word in query_words:
            # Only add longer words that might be meaningful
            if len(word) > 3 and word not in matched_topics:
                # Check if this word is a college/university name (special case)
                if word in ["bit", "mesra", "ranchi", "college", "university"]:
                    matched_topics.append(word)
                    matched_topics.append("education")  # Ensure education topic is included
                else:
                    matched_topics.append(word)

        # Ensure no duplicates
        return list(dict.fromkeys(matched_topics))

# === CONTEXTUAL MEMORY MANAGER (REVISED - V4) ===
class IntelligentInterestTracker:
    """
    Advanced Interest Tracking & World Awareness System
    - Learns user interests over time
    - Tracks trending topics and current events
    - Proactively shares relevant information like a human friend
    - Uses web search and real-time data sources
    """

    def __init__(self, db_manager: DatabaseManager):
        self.db_manager = db_manager
        self.config = config

        # Interest categories and their keywords (aligned with YouTube content categories)
        self.interest_categories = {
            'sports': ['cricket', 'cricktet', 'criket', 'football', 'tennis', 'match', 'tournament', 'player', 'team', 'game', 'fitness', 'exercise', 'workout', 'training', 'athlete', 'championship', 'league', 'basketball', 'soccer', 'baseball', 'golf', 'swimming', 'ipl', 'world cup', 'test match', 'odi', 't20', 'batting', 'bowling', 'wicket', 'runs', 'century', 'stadium', 'captain', 'coach', 'interested in cricket', 'intrested in cricket', 'love cricket', 'like cricket'],
            'entertainment': ['movie', 'film', 'music', 'song', 'artist', 'celebrity', 'show', 'series', 'netflix', 'podcast', 'comedy', 'drama', 'actor', 'actress', 'director', 'album', 'concert', 'performance', 'entertainment', 'funny', 'humor'],
            'travel': ['travel', 'trip', 'vacation', 'place', 'city', 'country', 'tourism', 'adventure', 'destination', 'flight', 'hotel', 'backpack', 'explore', 'culture', 'sightseeing', 'journey', 'wanderlust', 'nomad', 'visa', 'passport'],
            'food': ['food', 'restaurant', 'cooking', 'recipe', 'cuisine', 'coffee', 'tea', 'dining', 'chef', 'meal', 'breakfast', 'lunch', 'dinner', 'snack', 'dessert', 'baking', 'kitchen', 'ingredient', 'flavor', 'taste', 'hungry', 'delicious'],
            'yoga': ['yoga', 'meditation', 'mindfulness', 'stretch', 'relax', 'stress', 'breathing', 'pose', 'asana', 'namaste', 'zen', 'spiritual', 'chakra', 'balance', 'flexibility', 'inner peace', 'calm', 'serenity', 'wellness', 'holistic'],
            'health': ['health', 'wellness', 'medical', 'doctor', 'nutrition', 'diet', 'vitamin', 'supplement', 'medicine', 'therapy', 'mental health', 'physical health', 'immune', 'disease', 'prevention', 'treatment', 'healing', 'recovery', 'wellbeing', 'lifestyle'],
            'technology': ['ai', 'tech', 'software', 'programming', 'computer', 'app', 'startup', 'innovation', 'digital', 'internet', 'smartphone', 'gadget', 'artificial intelligence', 'machine learning', 'coding', 'development'],
            'education': ['study', 'college', 'university', 'course', 'exam', 'degree', 'learning', 'research', 'knowledge', 'school', 'student', 'teacher', 'education', 'academic', 'scholarship'],
            'business': ['business', 'work', 'job', 'career', 'company', 'startup', 'economy', 'finance', 'money', 'investment', 'entrepreneur', 'marketing', 'sales', 'management', 'stock market', 'trading', 'wealth', 'success', 'leadership', 'strategy', 'growth', 'profit', 'revenue'],
            'podcast': ['podcast', 'interview', 'conversation', 'discussion', 'talk show', 'episode', 'guest', 'host', 'listen', 'audio', 'show', 'series', 'chat', 'dialogue', 'story', 'experience', 'insights', 'wisdom', 'advice', 'tips'],
            'science': ['science', 'research', 'discovery', 'space', 'physics', 'biology', 'chemistry', 'experiment', 'theory', 'scientific', 'laboratory', 'study', 'analysis'],
            'politics': ['politics', 'government', 'election', 'policy', 'news', 'current affairs', 'political', 'democracy', 'vote', 'candidate', 'president', 'minister'],
            'lifestyle': ['fashion', 'style', 'beauty', 'home', 'design', 'shopping', 'trends', 'lifestyle', 'decor', 'interior', 'outfit', 'makeup', 'skincare'],
            'gaming': ['game', 'gaming', 'esports', 'console', 'pc gaming', 'mobile games', 'video game', 'gamer', 'streaming', 'twitch', 'gameplay', 'tournament']
        }

        # Initialize database schema
        self._initialize_interest_tracking_db()

        # Web search capabilities
        self.search_engines = {
            'google': self._google_search,
            'serp': self._serp_search,
            'news': self._news_search
        }

        # Trending topics cache with size limit to prevent memory leaks
        self.trending_cache = {}
        self.max_cache_size = AppConstants.MAX_TRENDING_CACHE_SIZE  # MEMORY LEAK FIX: Limit cache size
        self.last_trend_update = None

    def _initialize_interest_tracking_db(self):
        """Initialize database schema for interest tracking."""
        try:
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()

                # User interests table
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS user_interests (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id TEXT NOT NULL,
                        category TEXT NOT NULL,
                        interest_name TEXT NOT NULL,
                        confidence_score REAL DEFAULT 0.1,
                        mention_count INTEGER DEFAULT 1,
                        first_detected TEXT NOT NULL,
                        last_mentioned TEXT NOT NULL,
                        engagement_level REAL DEFAULT 0.5,
                        is_active BOOLEAN DEFAULT 1,
                        created_at TEXT NOT NULL
                    )''')

                # Trending topics table
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS trending_topics (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        topic TEXT NOT NULL,
                        category TEXT,
                        trend_score REAL DEFAULT 0.0,
                        source TEXT NOT NULL,
                        description TEXT,
                        url TEXT,
                        detected_at TEXT NOT NULL,
                        expires_at TEXT,
                        is_shared BOOLEAN DEFAULT 0,
                        created_at TEXT NOT NULL
                    )''')

                # User topic interactions
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS user_topic_interactions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id TEXT NOT NULL,
                        topic_id INTEGER NOT NULL,
                        interaction_type TEXT NOT NULL,
                        response_sentiment TEXT,
                        engagement_score REAL DEFAULT 0.0,
                        created_at TEXT NOT NULL,
                        FOREIGN KEY (topic_id) REFERENCES trending_topics (id)
                    )''')

                # Create indices
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_user_interests_user_id ON user_interests (user_id)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_user_interests_category ON user_interests (category)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_trending_topics_category ON trending_topics (category)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_trending_topics_score ON trending_topics (trend_score DESC)")

                logging.info("Interest tracking database schema initialized")

        except Exception as e:
            logging.error(f"Error initializing interest tracking database: {e}")

    def analyze_and_track_interests(self, user_id: str, message: str) -> Dict:
        """Analyze user message for interests and update tracking."""
        try:
            detected_interests = self._detect_interests_in_text(message)

            current_time = get_current_date_time_iso()

            for category, interests in detected_interests.items():
                for interest in interests:
                    self._update_user_interest(user_id, category, interest, current_time)

            # Get updated user interest profile
            user_interests = self._get_user_interest_profile(user_id)

            logging.info(f"Detected {sum(len(interests) for interests in detected_interests.values())} interests for user {user_id}")

            return {
                'detected_interests': detected_interests,
                'user_profile': user_interests,
                'recommendations': self._generate_interest_recommendations(user_interests)
            }

        except Exception as e:
            logging.error(f"Error analyzing interests for user {user_id}: {e}")
            return {'detected_interests': {}, 'user_profile': {}, 'recommendations': []}

    def _detect_interests_in_text(self, text: str) -> Dict[str, List[str]]:
        """Detect interests in text using keyword matching and context analysis."""
        detected = {}
        text_lower = text.lower()

        for category, keywords in self.interest_categories.items():
            found_interests = []

            for keyword in keywords:
                if keyword in text_lower:
                    # Extract context around the keyword
                    context = self._extract_keyword_context(text_lower, keyword)
                    if context:
                        found_interests.append(context)
                    else:
                        found_interests.append(keyword)

            if found_interests:
                detected[category] = list(set(found_interests))  # Remove duplicates

        return detected

    def _extract_keyword_context(self, text: str, keyword: str) -> str:
        """Extract meaningful context around a keyword."""
        try:
            # Find keyword position
            keyword_pos = text.find(keyword)
            if keyword_pos == -1:
                return keyword

            # Extract surrounding words (up to 3 words before and after)
            words = text.split()
            keyword_word_index = None

            for i, word in enumerate(words):
                if keyword in word:
                    keyword_word_index = i
                    break

            if keyword_word_index is not None:
                start_idx = max(0, keyword_word_index - 2)
                end_idx = min(len(words), keyword_word_index + 3)
                context_words = words[start_idx:end_idx]
                context = ' '.join(context_words)

                # Clean up the context
                context = re.sub(r'[^\w\s]', ' ', context)
                context = ' '.join(context.split())  # Remove extra spaces

                return context if len(context) > len(keyword) else keyword

            return keyword

        except Exception:
            return keyword

    def _update_user_interest(self, user_id: str, category: str, interest: str, timestamp: str):
        """Update or create user interest entry."""
        try:
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()

                # Check if interest already exists
                cursor.execute("""
                    SELECT id, confidence_score, mention_count, engagement_level
                    FROM user_interests
                    WHERE user_id = ? AND category = ? AND interest_name = ?
                """, (user_id, category, interest))

                existing = cursor.fetchone()

                if existing:
                    # Update existing interest
                    existing_dict = dict(existing)
                    new_confidence = min(1.0, existing_dict['confidence_score'] + 0.1)
                    new_mention_count = existing_dict['mention_count'] + 1
                    new_engagement = min(1.0, existing_dict['engagement_level'] + 0.05)

                    cursor.execute("""
                        UPDATE user_interests
                        SET confidence_score = ?, mention_count = ?,
                            last_mentioned = ?, engagement_level = ?
                        WHERE id = ?
                    """, (new_confidence, new_mention_count, timestamp, new_engagement, existing_dict['id']))

                    logging.debug(f"Updated interest '{interest}' for user {user_id} (mentions: {new_mention_count})")
                else:
                    # Create new interest
                    cursor.execute("""
                        INSERT INTO user_interests
                        (user_id, category, interest_name, confidence_score,
                         first_detected, last_mentioned, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (user_id, category, interest, 0.2, timestamp, timestamp, timestamp))

                    logging.debug(f"Added new interest '{interest}' for user {user_id} in category '{category}'")

        except Exception as e:
            logging.error(f"Error updating user interest: {e}")

    def _get_user_interest_profile(self, user_id: str) -> Dict:
        """Get comprehensive user interest profile."""
        try:
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()

                # Get top interests by category
                cursor.execute("""
                    SELECT category, interest_name, confidence_score, mention_count, engagement_level
                    FROM user_interests
                    WHERE user_id = ? AND is_active = 1
                    ORDER BY confidence_score DESC, mention_count DESC
                """, (user_id,))

                interests = cursor.fetchall()

                # Organize by category
                profile = {}
                for interest_row in interests:
                    interest = dict(interest_row)
                    category = interest['category']

                    if category not in profile:
                        profile[category] = []

                    profile[category].append({
                        'name': interest['interest_name'],
                        'confidence': interest['confidence_score'],
                        'mentions': interest['mention_count'],
                        'engagement': interest['engagement_level']
                    })

                # Calculate category scores
                category_scores = {}
                for category, category_interests in profile.items():
                    total_score = sum(i['confidence'] * i['engagement'] for i in category_interests)
                    category_scores[category] = total_score / len(category_interests) if category_interests else 0

                return {
                    'interests_by_category': profile,
                    'category_scores': category_scores,
                    'top_categories': sorted(category_scores.items(), key=lambda x: x[1], reverse=True)[:5]
                }

        except Exception as e:
            logging.error(f"Error getting user interest profile: {e}")
            return {'interests_by_category': {}, 'category_scores': {}, 'top_categories': []}

    def _generate_interest_recommendations(self, user_profile: Dict) -> List[str]:
        """Generate personalized recommendations based on user interests."""
        recommendations = []

        try:
            top_categories = user_profile.get('top_categories', [])

            for category, score in top_categories[:3]:  # Top 3 categories
                if score > 0.3:  # Minimum threshold
                    # Generate category-specific recommendations
                    category_recs = self._get_category_recommendations(category)
                    recommendations.extend(category_recs[:2])  # Max 2 per category

        except Exception as e:
            logging.error(f"Error generating recommendations: {e}")

        return recommendations[:5]  # Max 5 total recommendations

    def _get_category_recommendations(self, category: str) -> List[str]:
        """Get recommendations for a specific category."""
        recommendations = {
            'technology': [
                "Check out the latest AI developments",
                "Explore new programming frameworks",
                "Look into emerging tech startups"
            ],
            'entertainment': [
                "Discover new movies and shows",
                "Explore trending music artists",
                "Check out upcoming entertainment events"
            ],
            'sports': [
                "Follow your favorite team's latest matches",
                "Check upcoming tournament schedules",
                "Explore sports news and updates"
            ],
            'education': [
                "Explore new online courses",
                "Check university research updates",
                "Look into educational technology trends"
            ],
            'health': [
                "Discover new fitness routines",
                "Explore healthy recipe ideas",
                "Check latest health research"
            ]
        }

        return recommendations.get(category, ["Explore trending topics in " + category])

    def search_trending_topics(self, user_interests: Dict, limit: int = 5) -> List[Dict]:
        """Search for trending topics relevant to user interests."""
        try:
            trending_topics = []

            # Get user's top categories
            top_categories = user_interests.get('top_categories', [])

            for category, score in top_categories[:3]:
                if score > 0.2:  # Interest threshold
                    # Search for trending topics in this category
                    category_trends = self._search_category_trends(category)
                    trending_topics.extend(category_trends)

            # Sort by relevance and trend score
            trending_topics.sort(key=lambda x: x.get('relevance_score', 0), reverse=True)

            return trending_topics[:limit]

        except Exception as e:
            logging.error(f"Error searching trending topics: {e}")
            return []

    def _search_category_trends(self, category: str) -> List[Dict]:
        """Search for trending topics in a specific category."""
        try:
            # Check cache first
            cache_key = f"trends_{category}"
            if cache_key in self.trending_cache:
                cached_data = self.trending_cache[cache_key]
                if self._is_cache_valid(cached_data['timestamp']):
                    return cached_data['trends']

            # Search for new trends
            search_queries = self._get_category_search_queries(category)
            trends = []

            for query in search_queries:
                try:
                    # Try different search methods
                    search_results = self._perform_web_search(query, category)
                    trends.extend(search_results)
                except Exception as e:
                    logging.debug(f"Search failed for query '{query}': {e}")

            # Cache results with eviction to prevent memory leaks
            # MEMORY LEAK FIX: Evict oldest entries if cache is full
            if len(self.trending_cache) >= self.max_cache_size:
                # Remove oldest entry
                oldest_key = min(self.trending_cache.keys(),
                               key=lambda k: self.trending_cache[k]['timestamp'])
                del self.trending_cache[oldest_key]
                logging.debug(f"Evicted cache entry: {oldest_key}")

            self.trending_cache[cache_key] = {
                'trends': trends,
                'timestamp': get_current_date_time_iso()
            }

            return trends

        except Exception as e:
            logging.error(f"Error searching category trends for {category}: {e}")
            return []

    def _get_category_search_queries(self, category: str) -> List[str]:
        """Get search queries for a category."""
        queries = {
            'technology': [
                "latest tech news today",
                "AI breakthrough 2024",
                "new technology trends"
            ],
            'entertainment': [
                "trending movies 2024",
                "new music releases",
                "entertainment news today"
            ],
            'sports': [
                "sports news today",
                "cricket match updates",
                "football tournament 2024"
            ],
            'education': [
                "education news today",
                "new online courses",
                "university research updates"
            ],
            'health': [
                "health news today",
                "fitness trends 2024",
                "wellness tips"
            ]
        }

        return queries.get(category, [f"{category} news today"])

    def _perform_web_search(self, query: str, category: str) -> List[Dict]:
        """Perform web search using available search engines."""
        results = []

        try:
            # Try Google search first
            google_results = self._google_search(query)
            if google_results:
                for result in google_results[:3]:  # Top 3 results
                    results.append({
                        'title': result.get('title', ''),
                        'description': result.get('snippet', ''),
                        'url': result.get('link', ''),
                        'source': 'google',
                        'category': category,
                        'relevance_score': 0.8,
                        'detected_at': get_current_date_time_iso()
                    })

        except Exception as e:
            logging.debug(f"Google search failed: {e}")

        try:
            # Fallback to news search
            news_results = self._news_search(query)
            if news_results:
                for result in news_results[:2]:  # Top 2 news results
                    results.append({
                        'title': result.get('title', ''),
                        'description': result.get('description', ''),
                        'url': result.get('url', ''),
                        'source': 'news',
                        'category': category,
                        'relevance_score': 0.7,
                        'detected_at': get_current_date_time_iso()
                    })

        except Exception as e:
            logging.debug(f"News search failed: {e}")

        return results

    def _google_search(self, query: str) -> List[Dict]:
        """Perform Google search using requests with rate limiting."""
        try:
            # RATE LIMITING FIX: Add delay to prevent being blocked
            import time
            time.sleep(AppConstants.WEB_SEARCH_DELAY_SECONDS)  # Configurable delay between requests

            # Simple Google search implementation
            search_url = "https://www.google.com/search"
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
            params = {'q': query, 'num': 5}

            # RATE LIMITING FIX: Increased timeout and better error handling
            response = requests.get(search_url, headers=headers, params=params,
                                  timeout=AppConstants.WEB_REQUEST_TIMEOUT_SECONDS)

            if response.status_code == 200:
                # Parse search results (simplified)
                soup = BeautifulSoup(response.content, 'html.parser')
                results = []

                # Find search result elements
                search_results = soup.find_all('div', class_='g')[:5]

                for result in search_results:
                    try:
                        title_elem = result.find('h3')
                        link_elem = result.find('a')
                        snippet_elem = result.find('span', class_='aCOpRe')

                        if title_elem and link_elem:
                            results.append({
                                'title': title_elem.get_text(strip=True),
                                'link': link_elem.get('href', ''),
                                'snippet': snippet_elem.get_text(strip=True) if snippet_elem else ''
                            })
                    except Exception:
                        continue

                return results

        except Exception as e:
            logging.debug(f"Google search failed for '{query}': {e}")

        return []

    def _serp_search(self, query: str) -> List[Dict]:
        """Perform search using SERP API (if available)."""
        try:
            # Placeholder for SERP API implementation
            # This would require SERP API key
            logging.debug(f"SERP search not implemented for query: {query}")
            return []

        except Exception as e:
            logging.debug(f"SERP search failed: {e}")
            return []

    def _news_search(self, query: str) -> List[Dict]:
        """Search for news articles."""
        try:
            # Use existing news fetcher or implement news-specific search
            news_url = "https://news.google.com/search"
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            params = {'q': query, 'hl': 'en-IN', 'gl': 'IN', 'ceid': 'IN:en'}

            response = requests.get(news_url, headers=headers, params=params, timeout=10)

            if response.status_code == 200:
                soup = BeautifulSoup(response.content, 'html.parser')
                results = []

                # Find news articles
                articles = soup.find_all('article')[:3]

                for article in articles:
                    try:
                        title_elem = article.find('h3') or article.find('h4')
                        link_elem = article.find('a')

                        if title_elem and link_elem:
                            results.append({
                                'title': title_elem.get_text(strip=True),
                                'url': 'https://news.google.com' + link_elem.get('href', ''),
                                'description': title_elem.get_text(strip=True)[:200]
                            })
                    except Exception:
                        continue

                return results

        except Exception as e:
            logging.debug(f"News search failed for '{query}': {e}")

        return []

    def _is_cache_valid(self, timestamp: str, max_age_hours: int = 2) -> bool:
        """Check if cached data is still valid."""
        try:
            cached_time = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
            current_time = datetime.now(timezone.utc)
            age_hours = (current_time - cached_time).total_seconds() / 3600
            return age_hours < max_age_hours
        except Exception:
            return False

    def get_personalized_updates(self, user_id: str) -> Dict:
        """Get personalized updates based on user interests."""
        try:
            # Get user interest profile
            user_interests = self._get_user_interest_profile(user_id)

            # Search for relevant trending topics
            trending_topics = self.search_trending_topics(user_interests, limit=5)

            # Generate recommendations
            recommendations = self._generate_interest_recommendations(user_interests)

            # Format for sharing
            updates = {
                'trending_topics': trending_topics,
                'recommendations': recommendations,
                'interest_summary': user_interests.get('top_categories', [])[:3],
                'update_timestamp': get_current_date_time_iso()
            }

            return updates

        except Exception as e:
            logging.error(f"Error getting personalized updates for user {user_id}: {e}")
            return {'trending_topics': [], 'recommendations': [], 'interest_summary': []}

    def should_share_update(self, user_id: str, topic: Dict) -> bool:
        """Determine if a topic should be shared with the user."""
        try:
            # Get user interests
            user_interests = self._get_user_interest_profile(user_id)
            topic_category = topic.get('category', '')

            # Check if user is interested in this category
            category_scores = user_interests.get('category_scores', {})
            category_score = category_scores.get(topic_category, 0)

            # Share if user has significant interest (score > 0.3)
            return category_score > 0.3

        except Exception as e:
            logging.error(f"Error determining if should share update: {e}")
            return False

# === YOUTUBE CONTENT MANAGER ===
class YouTubeContentManager:
    """
    Manages YouTube content fetching, processing, and natural conversation integration.
    Uses RSS feeds to fetch latest videos from curated channels by interest category.
    """

    def __init__(self, db_manager: DatabaseManager):
        self.db_manager = db_manager

        # YouTube channels organized by interest categories
        self.youtube_channels = {
            'sports': [
                'UCN0OLBrPaGWWOy_gn8OlNnw',  # Joe Rogan Experience
                'UCiWLfSweyRNmLpgEHekhoAg',  # ESPN
                'UCWJ2lWNubArHWmf3FIHbfcQ',  # NBA
                'UCEgdi0XIXXZ-qJOFPf4JSKw',  # Sports Center
                'UCEu-3MB81vTIsEEuqu3aQEg',  # Cricket Aakash
            ],
            'entertainment': [
                'UCBJycsmduvYEL83R_U4JriQ',  # MKBHD
                'UC-lHJZR3Gqxm24_Vd_AJ5Yw',  # PewDiePie
                'UCq-Fj5jknLsUf-MWSy4_brA',  # T-Series
                'UCX6OQ3DkcsbYNE6H8uQQuVA',  # MrBeast
            ],
            'travel': [
                'UCyEd6QBSgat5kkC6svyjudA',  # Drew Binsky
                'UCMEWGp_zkz0ox-ZRHR-8vbA',  # Kara and Nate
                'UC1xdsJjWzQy1kOOcbj8fYWw',  # Mark Wiens
                'UCFe3X3KCjVLbXbXEWZpgbmA',  # Nas Daily
            ],
            'food': [
                'UCcMDMoNu66_1Hwi5-MeiQgw',  # Babish Culinary Universe
                'UC9_p50tH3WmMslWRWKnM7dQ',  # Adam Ragusea
                'UCRIZtPl9nb9RiXc9btSTQNw',  # Joshua Weissman
                'UCpko_-a4wgz2u_DgDgd9fqA',  # Bon Appétit
            ],
            'yoga': [
                'UCFKE7WVJfvaHW5q283SxchA',  # Yoga with Adriene
                'UC8iDjpLQQIyVnaKwn7proYA',  # Boho Beautiful
                'UCGde6KcIABbXUOCRSWbSZ-g',  # Alo Yoga
                'UCciuZl2ydLEgNbqZ_6WEbwA',  # DoYogaWithMe
            ],
            'health': [
                'UCISIkn8pYmv8pjbmKPqQHdQ',  # Dr. Berg
                'UC0CRYvGlWGlsGxBNgvkUbAg',  # Thomas DeLauer
                'UCzFZ1_eh6fscXavQyCf_LCg',  # Athlean-X
                'UCR2qBn2dGWdNQllNOj6ODNQ',  # Dr. Rhonda Patrick
            ],
            'business': [
                'UCRv4waLxgUN0Z-yb2I1Fq4A',  # Nikhil Kamath
                'UCshPyRiu9XTQb2gEagNt-3A',  # Raj Shamani
                'UCPxMZIFE856tbTfdkdjzTSQ',  # Ranveer Allahbadia (BeerBiceps)
            ],
            'podcast': [
                'UCRv4waLxgUN0Z-yb2I1Fq4A',  # Nikhil Kamath
                'UCshPyRiu9XTQb2gEagNt-3A',  # Raj Shamani
                'UCPxMZIFE856tbTfdkdjzTSQ',  # Ranveer Allahbadia (BeerBiceps)
                'UCN0OLBrPaGWWOy_gn8OlNnw',  # Joe Rogan Experience
            ]
        }

        # Initialize database schema
        self._initialize_youtube_content_db()

        # Content processing cache
        self.processed_content_cache = {}
        self.last_fetch_time = {}

    def _initialize_youtube_content_db(self):
        """Initialize database schema for YouTube content management."""
        try:
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()

                # YouTube channels table
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS youtube_channels (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        channel_id TEXT NOT NULL UNIQUE,
                        channel_name TEXT,
                        category TEXT NOT NULL,
                        is_active BOOLEAN DEFAULT 1,
                        last_fetched TEXT,
                        created_at TEXT NOT NULL
                    )''')

                # YouTube videos table
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS youtube_videos (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        video_id TEXT NOT NULL UNIQUE,
                        channel_id TEXT NOT NULL,
                        title TEXT NOT NULL,
                        description TEXT,
                        published_at TEXT NOT NULL,
                        duration TEXT,
                        view_count INTEGER,
                        url TEXT NOT NULL,
                        thumbnail_url TEXT,
                        category TEXT NOT NULL,
                        is_processed BOOLEAN DEFAULT 0,
                        created_at TEXT NOT NULL
                    )''')

                # Processed content table (Gemini summaries)
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS processed_video_content (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        video_id TEXT NOT NULL,
                        transcript_summary TEXT,
                        key_points TEXT,  -- JSON array of important points
                        conversation_hooks TEXT,  -- JSON array of natural conversation starters
                        topics_mentioned TEXT,  -- JSON array of topics/people mentioned
                        processing_date TEXT NOT NULL,
                        gemini_model_used TEXT,
                        FOREIGN KEY (video_id) REFERENCES youtube_videos (video_id)
                    )''')

                # User content interactions
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS user_video_interactions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id TEXT NOT NULL,
                        video_id TEXT NOT NULL,
                        interaction_type TEXT NOT NULL,  -- 'shown', 'clicked', 'discussed'
                        user_response TEXT,
                        engagement_score REAL DEFAULT 0.0,
                        shown_date TEXT NOT NULL,
                        FOREIGN KEY (video_id) REFERENCES youtube_videos (video_id)
                    )''')

                # Content frequency management
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS user_content_frequency (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id TEXT NOT NULL,
                        category TEXT NOT NULL,
                        base_frequency REAL DEFAULT 0.05,  -- Starting at 5% chance
                        current_frequency REAL DEFAULT 0.05,
                        last_shown_date TEXT,
                        total_shown INTEGER DEFAULT 0,
                        positive_responses INTEGER DEFAULT 0,
                        negative_responses INTEGER DEFAULT 0,
                        ignored_count INTEGER DEFAULT 0,
                        consecutive_ignores INTEGER DEFAULT 0,
                        last_engagement_score REAL DEFAULT 0.0,
                        frequency_updated_date TEXT NOT NULL,
                        UNIQUE(user_id, category)
                    )''')

                # Create indices
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_youtube_videos_category ON youtube_videos (category)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_youtube_videos_published ON youtube_videos (published_at DESC)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_processed_content_video ON processed_video_content (video_id)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_user_interactions_user ON user_video_interactions (user_id)")

                # Insert default channels
                self._insert_default_channels(cursor)

                logging.info("YouTube content database schema initialized")

        except Exception as e:
            logging.error(f"Error initializing YouTube content database: {e}")

    def _insert_default_channels(self, cursor):
        """Insert default YouTube channels into database."""
        try:
            current_time = get_current_date_time_iso()

            for category, channel_ids in self.youtube_channels.items():
                for channel_id in channel_ids:
                    cursor.execute('''
                        INSERT OR IGNORE INTO youtube_channels
                        (channel_id, category, created_at)
                        VALUES (?, ?, ?)
                    ''', (channel_id, category, current_time))

        except Exception as e:
            logging.error(f"Error inserting default channels: {e}")

    def fetch_latest_videos_for_category(self, category: str, max_videos_per_channel: int = 3) -> List[Dict]:
        """Fetch latest videos for a specific category using RSS feeds."""
        try:
            if category not in self.youtube_channels:
                logging.warning(f"Unknown category: {category}")
                return []

            all_videos = []
            channel_ids = self.youtube_channels[category]

            for channel_id in channel_ids:
                try:
                    # Fetch videos using RSS
                    videos = self._fetch_channel_videos_rss(channel_id, max_videos_per_channel)

                    # Add category info and store in database
                    for video in videos:
                        video['category'] = category
                        video['channel_id'] = channel_id

                        # Store video in database
                        self._store_video_info(video)

                    all_videos.extend(videos)

                except Exception as e:
                    logging.error(f"Error fetching videos from channel {channel_id}: {e}")
                    continue

            logging.info(f"Fetched {len(all_videos)} videos for category '{category}'")
            return all_videos

        except Exception as e:
            logging.error(f"Error fetching videos for category {category}: {e}")
            return []

    def _fetch_channel_videos_rss(self, channel_id: str, max_videos: int = 3) -> List[Dict]:
        """Fetch videos from a YouTube channel using RSS feed."""
        try:
            # YouTube RSS feed URL
            rss_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"

            # Parse RSS feed
            feed = feedparser.parse(rss_url)

            if not feed.entries:
                logging.warning(f"No videos found in RSS feed for channel {channel_id}")
                return []

            videos = []
            for entry in feed.entries[:max_videos]:
                try:
                    # Extract video information
                    video_data = {
                        'video_id': entry.yt_videoid if hasattr(entry, 'yt_videoid') else self._extract_video_id_from_url(entry.link),
                        'title': entry.title,
                        'description': entry.summary if hasattr(entry, 'summary') else '',
                        'published_at': entry.published,
                        'url': entry.link,
                        'channel_name': entry.author if hasattr(entry, 'author') else 'Unknown',
                        'thumbnail_url': entry.media_thumbnail[0]['url'] if hasattr(entry, 'media_thumbnail') and entry.media_thumbnail else ''
                    }

                    videos.append(video_data)

                except Exception as e:
                    logging.error(f"Error parsing video entry: {e}")
                    continue

            return videos

        except Exception as e:
            logging.error(f"Error fetching RSS feed for channel {channel_id}: {e}")
            return []

    def _extract_video_id_from_url(self, url: str) -> str:
        """Extract video ID from YouTube URL."""
        try:
            if 'watch?v=' in url:
                return url.split('watch?v=')[1].split('&')[0]
            elif 'youtu.be/' in url:
                return url.split('youtu.be/')[1].split('?')[0]
            return ''
        except:
            return ''

    def get_channel_id_from_handle(self, handle: str) -> str:
        """Get channel ID from YouTube handle (@username)."""
        try:
            # Remove @ if present
            handle = handle.replace('@', '')

            # Try to get channel ID by scraping the channel page
            url = f"https://www.youtube.com/@{handle}"
            response = requests.get(url, timeout=10)

            if response.status_code == 200:
                # Look for channel ID in the page source
                import re
                # Pattern to find channel ID in YouTube page source
                pattern = r'"channelId":"([^"]+)"'
                match = re.search(pattern, response.text)

                if match:
                    channel_id = match.group(1)
                    logging.info(f"Found channel ID for @{handle}: {channel_id}")
                    return channel_id

            logging.warning(f"Could not find channel ID for @{handle}")
            return ''

        except Exception as e:
            logging.error(f"Error getting channel ID for @{handle}: {e}")
            return ''

    def _store_video_info(self, video_data: Dict):
        """Store video information in database."""
        try:
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()

                current_time = get_current_date_time_iso()

                cursor.execute('''
                    INSERT OR REPLACE INTO youtube_videos
                    (video_id, channel_id, title, description, published_at, url,
                     thumbnail_url, category, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    video_data['video_id'],
                    video_data['channel_id'],
                    video_data['title'],
                    video_data.get('description', ''),
                    video_data['published_at'],
                    video_data['url'],
                    video_data.get('thumbnail_url', ''),
                    video_data['category'],
                    current_time
                ))

        except Exception as e:
            logging.error(f"Error storing video info: {e}")

    def get_video_transcript(self, video_id: str) -> str:
        """Get transcript for a YouTube video."""
        try:
            from youtube_transcript_api import YouTubeTranscriptApi

            # Try to get transcript
            transcript_list = YouTubeTranscriptApi.get_transcript(video_id)

            # Combine all transcript segments
            full_transcript = ' '.join([item['text'] for item in transcript_list])

            return full_transcript

        except Exception as e:
            logging.warning(f"Could not get transcript for video {video_id}: {e}")
            return ""

    def process_video_with_gemini(self, video_data: Dict, gemini_model) -> Dict:
        """Process video content with Gemini to extract key points and conversation hooks."""
        try:
            video_id = video_data['video_id']
            title = video_data['title']
            description = video_data.get('description', '')

            # Get transcript
            transcript = self.get_video_transcript(video_id)

            if not transcript:
                # If no transcript, use title and description
                content_to_analyze = f"Title: {title}\nDescription: {description}"
            else:
                # Limit transcript length for Gemini processing
                max_transcript_length = 8000  # Adjust based on Gemini limits
                if len(transcript) > max_transcript_length:
                    transcript = transcript[:max_transcript_length] + "..."

                content_to_analyze = f"Title: {title}\nDescription: {description}\nTranscript: {transcript}"

            # Create Gemini prompt for content processing
            processing_prompt = f"""
            Analyze this YouTube video content and extract the most important and memorable information that a human friend would naturally remember and share in conversation.

            Video Content:
            {content_to_analyze}

            Please provide:
            1. **Key Points** (3-5 most important/interesting points that someone would remember)
            2. **Conversation Hooks** (2-3 natural ways to bring this up in conversation, like "Hey, did you see that video where..." or "I came across this interesting point about...")
            3. **Topics/People Mentioned** (any notable people, concepts, or topics discussed)

            Format your response as JSON:
            {{
                "summary": "Brief 2-3 sentence summary",
                "key_points": ["point 1", "point 2", "point 3"],
                "conversation_hooks": ["hook 1", "hook 2"],
                "topics_mentioned": ["topic 1", "topic 2"],
                "memorable_quotes": ["quote 1", "quote 2"]
            }}

            Focus on information that would be naturally shared between friends, not just dry facts.
            """

            # Send to Gemini
            response = gemini_model.generate_content(processing_prompt)

            if response and response.text:
                try:
                    # Try to parse JSON response
                    import json
                    processed_data = json.loads(response.text.strip())

                    # Store processed content in database
                    self._store_processed_content(video_id, processed_data, 'gemini-1.5-flash')

                    return processed_data

                except json.JSONDecodeError:
                    # If JSON parsing fails, create a basic structure
                    processed_data = {
                        "summary": response.text[:200] + "..." if len(response.text) > 200 else response.text,
                        "key_points": [response.text[:100] + "..."],
                        "conversation_hooks": [f"I saw this interesting video about {title}"],
                        "topics_mentioned": [title.split()[0] if title else "video content"],
                        "memorable_quotes": []
                    }

                    self._store_processed_content(video_id, processed_data, 'gemini-1.5-flash')
                    return processed_data

            return {}

        except Exception as e:
            logging.error(f"Error processing video {video_data.get('video_id', 'unknown')} with Gemini: {e}")
            return {}

    def _store_processed_content(self, video_id: str, processed_data: Dict, model_used: str):
        """Store Gemini-processed content in database."""
        try:
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()

                import json
                current_time = get_current_date_time_iso()

                cursor.execute('''
                    INSERT OR REPLACE INTO processed_video_content
                    (video_id, transcript_summary, key_points, conversation_hooks,
                     topics_mentioned, processing_date, gemini_model_used)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (
                    video_id,
                    processed_data.get('summary', ''),
                    json.dumps(processed_data.get('key_points', [])),
                    json.dumps(processed_data.get('conversation_hooks', [])),
                    json.dumps(processed_data.get('topics_mentioned', [])),
                    current_time,
                    model_used
                ))

                # Mark video as processed
                cursor.execute('''
                    UPDATE youtube_videos
                    SET is_processed = 1
                    WHERE video_id = ?
                ''', (video_id,))

        except Exception as e:
            logging.error(f"Error storing processed content for video {video_id}: {e}")

    def get_relevant_content_for_user(self, user_id: str, user_interests: Dict, limit: int = 3) -> List[Dict]:
        """Get relevant processed video content based on user interests, avoiding repetition."""
        try:
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()

                # Get user's top interest categories
                top_categories = list(user_interests.keys())[:3] if user_interests else ['entertainment', 'health', 'sports']

                # Build query for relevant content with anti-repetition logic
                category_placeholders = ','.join(['?' for _ in top_categories])

                query = f'''
                    SELECT v.video_id, v.title, v.url, v.category, v.published_at,
                           p.transcript_summary, p.key_points, p.conversation_hooks, p.topics_mentioned
                    FROM youtube_videos v
                    JOIN processed_video_content p ON v.video_id = p.video_id
                    WHERE v.category IN ({category_placeholders})
                    AND v.video_id NOT IN (
                        -- Exclude videos shown in last 14 days
                        SELECT video_id FROM user_video_interactions
                        WHERE user_id = ? AND interaction_type IN ('shown', 'discussed')
                        AND datetime(shown_date) > datetime('now', '-14 days')
                    )
                    AND v.video_id NOT IN (
                        -- Exclude videos from same channel shown in last 7 days
                        SELECT v2.video_id FROM youtube_videos v2
                        JOIN user_video_interactions uvi ON v2.video_id = uvi.video_id
                        WHERE uvi.user_id = ? AND v2.channel_id = v.channel_id
                        AND datetime(uvi.shown_date) > datetime('now', '-7 days')
                    )
                    ORDER BY v.published_at DESC
                    LIMIT ?
                '''

                cursor.execute(query, top_categories + [user_id, user_id, limit])
                results = cursor.fetchall()

                # If no fresh content, relax the constraints slightly
                if not results and limit > 0:
                    logging.info(f"No fresh content for {user_id}, relaxing constraints")

                    relaxed_query = f'''
                        SELECT v.video_id, v.title, v.url, v.category, v.published_at,
                               p.transcript_summary, p.key_points, p.conversation_hooks, p.topics_mentioned
                        FROM youtube_videos v
                        JOIN processed_video_content p ON v.video_id = p.video_id
                        WHERE v.category IN ({category_placeholders})
                        AND v.video_id NOT IN (
                            -- Only exclude videos shown in last 7 days
                            SELECT video_id FROM user_video_interactions
                            WHERE user_id = ? AND interaction_type IN ('shown', 'discussed')
                            AND datetime(shown_date) > datetime('now', '-7 days')
                        )
                        ORDER BY v.published_at DESC
                        LIMIT ?
                    '''

                    cursor.execute(relaxed_query, top_categories + [user_id, limit])
                    results = cursor.fetchall()

                relevant_content = []
                for row in results:
                    import json
                    content = {
                        'video_id': row[0],
                        'title': row[1],
                        'url': row[2],
                        'category': row[3],
                        'published_at': row[4],
                        'summary': row[5],
                        'key_points': json.loads(row[6]) if row[6] else [],
                        'conversation_hooks': json.loads(row[7]) if row[7] else [],
                        'topics_mentioned': json.loads(row[8]) if row[8] else []
                    }
                    relevant_content.append(content)

                return relevant_content

        except Exception as e:
            logging.error(f"Error getting relevant content for user {user_id}: {e}")
            return []

    def should_introduce_content_to_user(self, user_id: str, category: str) -> bool:
        """Smart frequency-based decision on whether to introduce content."""
        try:
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()

                # Get or create frequency record for this user-category
                frequency_data = self._get_or_create_frequency_record(user_id, category, cursor)

                if not frequency_data:
                    return False

                current_frequency, last_shown_date, consecutive_ignores, total_shown = frequency_data

                # Apply decay if content was shown recently
                if last_shown_date:
                    from datetime import datetime, timedelta
                    last_shown = datetime.fromisoformat(last_shown_date)
                    hours_since_last = (datetime.now() - last_shown).total_seconds() / 3600

                    # Don't show content too frequently
                    min_gap_hours = self._calculate_minimum_gap_hours(consecutive_ignores, total_shown)
                    if hours_since_last < min_gap_hours:
                        return False

                # Check user's interest level in this category
                cursor.execute('''
                    SELECT AVG(confidence_score), COUNT(*), MAX(last_mentioned)
                    FROM user_interests
                    WHERE user_id = ? AND category = ? AND is_active = 1
                ''', (user_id, category))

                result = cursor.fetchone()
                if not result or not result[0]:
                    # No interest shown yet, use very low base frequency
                    return random.random() < 0.02  # 2% chance for new categories

                avg_confidence, mention_count, last_mentioned = result

                # Only proceed if user has shown genuine interest
                if avg_confidence < 0.3 or mention_count < 2:
                    return random.random() < 0.03  # 3% chance for low interest

                # Use the adaptive frequency
                decision = random.random() < current_frequency

                logging.info(f"Content frequency decision for {user_id}/{category}: {current_frequency:.3f} -> {'YES' if decision else 'NO'}")
                return decision

        except Exception as e:
            logging.error(f"Error in smart content frequency decision: {e}")
            return False

    def _get_or_create_frequency_record(self, user_id: str, category: str, cursor) -> tuple:
        """Get or create frequency management record for user-category."""
        try:
            # Check if record exists
            cursor.execute('''
                SELECT current_frequency, last_shown_date, consecutive_ignores, total_shown
                FROM user_content_frequency
                WHERE user_id = ? AND category = ?
            ''', (user_id, category))

            result = cursor.fetchone()
            if result:
                return result

            # Create new record with low starting frequency
            current_time = get_current_date_time_iso()
            cursor.execute('''
                INSERT INTO user_content_frequency
                (user_id, category, base_frequency, current_frequency, frequency_updated_date)
                VALUES (?, ?, 0.05, 0.05, ?)
            ''', (user_id, category, current_time))

            return (0.05, None, 0, 0)  # Starting values

        except Exception as e:
            logging.error(f"Error managing frequency record: {e}")
            return None

    def _calculate_minimum_gap_hours(self, consecutive_ignores: int, total_shown: int) -> float:
        """Calculate minimum hours between content mentions based on user behavior."""
        # Base gap of 2 hours
        base_gap = 2.0

        # Increase gap based on consecutive ignores
        ignore_penalty = consecutive_ignores * 4  # 4 hours per consecutive ignore

        # Increase gap if we've shown a lot of content
        volume_penalty = min(total_shown * 0.5, 12)  # Max 12 hours from volume

        total_gap = base_gap + ignore_penalty + volume_penalty

        # Cap at 72 hours (3 days) maximum
        return min(total_gap, 72.0)

    def generate_natural_content_mention(self, content: Dict, conversation_context: str = "") -> str:
        """Generate a natural way to mention video content in conversation."""
        try:
            conversation_hooks = content.get('conversation_hooks', [])
            key_points = content.get('key_points', [])
            title = content.get('title', '')
            category = content.get('category', '')

            # Make mentions more contextual and natural
            context_lower = conversation_context.lower()

            # If we have pre-generated hooks, use them
            if conversation_hooks:
                hook = random.choice(conversation_hooks)
                return hook

            # Create contextual mentions based on conversation
            if key_points:
                key_point = random.choice(key_points)

                # Different styles based on category
                if category == 'health':
                    return f"That reminds me of something interesting I came across - {key_point}. What do you think about that?"
                elif category == 'sports':
                    return f"Speaking of that, I saw this fascinating point about {key_point}. Have you heard about this?"
                elif category == 'food':
                    return f"Oh, that makes me think of something I learned recently - {key_point}. Sounds interesting, right?"
                elif category == 'travel':
                    return f"You know what's interesting? I came across this point about {key_point}. Ever thought about that?"
                elif category == 'business':
                    return f"That's fascinating! I recently learned something about {key_point}. What's your perspective on this?"
                elif category == 'podcast':
                    return f"Speaking of that, I heard this interesting insight - {key_point}. Have you come across anything like this?"
                else:
                    return f"That's interesting! It reminds me of something I learned - {key_point}. What's your take on it?"

            # Fallback to basic mention
            return f"By the way, I came across something about {title.lower()} that might interest you. Want to hear about it?"

        except Exception as e:
            logging.error(f"Error generating natural content mention: {e}")
            return ""

    def record_user_interaction(self, user_id: str, video_id: str, interaction_type: str, user_response: str = ""):
        """Record user interaction with video content and adapt strategy."""
        try:
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()

                current_time = get_current_date_time_iso()

                # Calculate engagement score based on interaction type and response
                engagement_scores = {
                    'shown': 0.1,
                    'clicked': 0.5,
                    'discussed': 0.8,
                    'positive_response': 1.0,
                    'negative_response': -0.3,
                    'ignored': -0.1
                }

                engagement_score = engagement_scores.get(interaction_type, 0.0)

                # Analyze user response sentiment to adjust engagement score
                if user_response:
                    response_lower = user_response.lower()
                    positive_words = ['interesting', 'cool', 'awesome', 'great', 'love', 'like', 'amazing', 'wow', 'nice', 'good']
                    negative_words = ['boring', 'not interested', 'don\'t care', 'whatever', 'meh', 'no thanks', 'skip']

                    positive_count = sum(1 for word in positive_words if word in response_lower)
                    negative_count = sum(1 for word in negative_words if word in response_lower)

                    if positive_count > negative_count:
                        engagement_score = max(engagement_score, 0.7)
                        interaction_type = 'positive_response'
                    elif negative_count > positive_count:
                        engagement_score = -0.3
                        interaction_type = 'negative_response'

                cursor.execute('''
                    INSERT INTO user_video_interactions
                    (user_id, video_id, interaction_type, user_response, engagement_score, shown_date)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (user_id, video_id, interaction_type, user_response, engagement_score, current_time))

                # Update frequency based on engagement
                self._update_content_frequency(user_id, video_id, engagement_score, interaction_type)

        except Exception as e:
            logging.error(f"Error recording user interaction: {e}")

    def _update_content_frequency(self, user_id: str, video_id: str, engagement_score: float, interaction_type: str):
        """Update content frequency based on user engagement with smart decay and boost logic."""
        try:
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()

                # Get the category of the video
                cursor.execute('SELECT category FROM youtube_videos WHERE video_id = ?', (video_id,))
                result = cursor.fetchone()
                if not result:
                    return

                category = result[0]
                current_time = get_current_date_time_iso()

                # Get current frequency record
                cursor.execute('''
                    SELECT current_frequency, positive_responses, negative_responses,
                           ignored_count, consecutive_ignores, total_shown
                    FROM user_content_frequency
                    WHERE user_id = ? AND category = ?
                ''', (user_id, category))

                freq_result = cursor.fetchone()
                if not freq_result:
                    # Create new record if doesn't exist
                    self._get_or_create_frequency_record(user_id, category, cursor)
                    freq_result = (0.05, 0, 0, 0, 0, 0)

                current_freq, pos_responses, neg_responses, ignored, consecutive_ignores, total_shown = freq_result

                # Update counters based on interaction type
                new_pos = pos_responses
                new_neg = neg_responses
                new_ignored = ignored
                new_consecutive_ignores = consecutive_ignores

                if engagement_score > 0.5:  # Positive engagement
                    new_pos += 1
                    new_consecutive_ignores = 0  # Reset consecutive ignores
                    frequency_multiplier = 1.2  # Increase frequency by 20%

                elif engagement_score < -0.1:  # Negative engagement
                    new_neg += 1
                    new_consecutive_ignores += 1
                    frequency_multiplier = 0.7  # Decrease frequency by 30%

                elif interaction_type == 'shown' and engagement_score <= 0.1:  # Content shown but ignored
                    new_ignored += 1
                    new_consecutive_ignores += 1
                    frequency_multiplier = 0.8  # Decrease frequency by 20%

                else:  # Neutral engagement
                    new_consecutive_ignores = max(0, consecutive_ignores - 1)  # Slowly recover
                    frequency_multiplier = 0.95  # Slight decrease

                # Calculate new frequency with bounds
                new_frequency = current_freq * frequency_multiplier

                # Apply bounds: minimum 0.01 (1%), maximum 0.3 (30%)
                new_frequency = max(0.01, min(0.3, new_frequency))

                # Apply decay based on consecutive ignores
                if new_consecutive_ignores >= 3:
                    decay_factor = 0.5 ** (new_consecutive_ignores - 2)  # Exponential decay
                    new_frequency *= decay_factor

                # Update the frequency record
                cursor.execute('''
                    UPDATE user_content_frequency
                    SET current_frequency = ?,
                        positive_responses = ?,
                        negative_responses = ?,
                        ignored_count = ?,
                        consecutive_ignores = ?,
                        total_shown = ?,
                        last_engagement_score = ?,
                        last_shown_date = ?,
                        frequency_updated_date = ?
                    WHERE user_id = ? AND category = ?
                ''', (new_frequency, new_pos, new_neg, new_ignored, new_consecutive_ignores,
                      total_shown + 1, engagement_score, current_time, current_time, user_id, category))

                logging.info(f"Updated frequency for {user_id}/{category}: {current_freq:.3f} -> {new_frequency:.3f} "
                           f"(Engagement: {engagement_score:.2f}, Consecutive ignores: {new_consecutive_ignores})")

        except Exception as e:
            logging.error(f"Error updating content frequency: {e}")

    def fetch_content_for_user_interests(self, user_id: str, gemini_model, max_videos_per_category: int = 2):
        """Smart content fetching based on user's demonstrated interests."""
        try:
            # Get user's interest profile
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()

                # Get user's top interest categories with confidence > 0.3
                cursor.execute('''
                    SELECT category, AVG(confidence_score) as avg_confidence, COUNT(*) as mention_count
                    FROM user_interests
                    WHERE user_id = ? AND is_active = 1
                    GROUP BY category
                    HAVING avg_confidence > 0.3 AND mention_count >= 2
                    ORDER BY avg_confidence DESC, mention_count DESC
                    LIMIT 3
                ''', (user_id,))

                user_interests = cursor.fetchall()

                if not user_interests:
                    logging.info(f"User {user_id} has no established interests yet, skipping content fetch")
                    return 0

                interested_categories = [row[0] for row in user_interests]
                logging.info(f"Fetching content for user {user_id} interests: {interested_categories}")

                total_processed = 0

                for category in interested_categories:
                    if category not in self.youtube_channels:
                        continue

                    try:
                        # Check if we already have recent content for this category
                        cursor.execute('''
                            SELECT COUNT(*) FROM youtube_videos v
                            JOIN processed_video_content p ON v.video_id = p.video_id
                            WHERE v.category = ?
                            AND datetime(v.created_at) > datetime('now', '-2 days')
                        ''', (category,))

                        recent_content_count = cursor.fetchone()[0]

                        if recent_content_count >= 5:  # Already have enough recent content
                            logging.info(f"Already have {recent_content_count} recent videos for {category}, skipping")
                            continue

                        # Fetch new videos for this category
                        videos = self.fetch_latest_videos_for_category(category, max_videos_per_channel=max_videos_per_category)

                        # Process each video with Gemini
                        for video in videos:
                            try:
                                # Check if already processed
                                if self._is_video_processed(video['video_id']):
                                    continue

                                # Process with Gemini
                                processed_data = self.process_video_with_gemini(video, gemini_model)

                                if processed_data:
                                    total_processed += 1
                                    logging.info(f"Processed video for user interest: {video['title'][:50]}...")

                                # Add small delay to avoid rate limits
                                time.sleep(1)

                            except Exception as e:
                                logging.error(f"Error processing individual video: {e}")
                                continue

                    except Exception as e:
                        logging.error(f"Error processing category {category}: {e}")
                        continue

                logging.info(f"Smart content fetch completed for user {user_id}. Processed {total_processed} new videos.")
                return total_processed

        except Exception as e:
            logging.error(f"Error in smart content fetch for user {user_id}: {e}")
            return 0

    def _is_video_processed(self, video_id: str) -> bool:
        """Check if video has already been processed."""
        try:
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()

                cursor.execute('''
                    SELECT is_processed FROM youtube_videos
                    WHERE video_id = ?
                ''', (video_id,))

                result = cursor.fetchone()
                return result and result[0] == 1

        except Exception as e:
            logging.error(f"Error checking if video is processed: {e}")
            return False

class GlobalKnowledgeManager:
    """
    Global Knowledge Layer - Learns general world facts and knowledge that can be shared across all users.
    This layer distinguishes between personal/intimate information and general world knowledge.
    """

    def __init__(self, db_manager: DatabaseManager):
        self.db_manager = db_manager
        self.config = config
        self.encoder = get_sentence_transformer()
        self.embedding_dimension = get_embedding_dimension()

        # Initialize FAISS index for global knowledge
        self.global_index = None
        self.knowledge_store = []

        # Initialize global knowledge system
        self._initialize_global_knowledge_db()
        self._load_global_knowledge()

    def _initialize_global_knowledge_db(self):
        """Initialize the global knowledge database schema."""
        try:
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()

                # Create global knowledge table
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS global_knowledge (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        knowledge_text TEXT NOT NULL,
                        knowledge_type TEXT NOT NULL,
                        category TEXT,
                        confidence_score REAL DEFAULT 0.5,
                        source_count INTEGER DEFAULT 1,
                        first_learned TEXT NOT NULL,
                        last_reinforced TEXT NOT NULL,
                        embedding BLOB,
                        tags TEXT DEFAULT '',
                        is_verified BOOLEAN DEFAULT 0,
                        created_at TEXT NOT NULL
                    )''')

                # Create indices for efficient querying
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_global_knowledge_type ON global_knowledge (knowledge_type)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_global_knowledge_category ON global_knowledge (category)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_global_knowledge_confidence ON global_knowledge (confidence_score DESC)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_global_knowledge_source_count ON global_knowledge (source_count DESC)")

                logging.info("Global knowledge database schema initialized")

        except Exception as e:
            logging.error(f"Error initializing global knowledge database: {e}")

    def _load_global_knowledge(self):
        """Load existing global knowledge into memory and FAISS index."""
        try:
            import faiss

            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT id, knowledge_text, knowledge_type, category, confidence_score,
                           source_count, embedding
                    FROM global_knowledge
                    ORDER BY confidence_score DESC, source_count DESC
                    LIMIT 1000
                """)

                knowledge_rows = cursor.fetchall()

                if knowledge_rows:
                    # Initialize FAISS index
                    self.global_index = faiss.IndexFlatIP(self.embedding_dimension)

                    embeddings = []
                    for row in knowledge_rows:
                        row_dict = dict(row)

                        # Load embedding
                        embedding_blob = row_dict['embedding']
                        if embedding_blob:
                            embedding = np.frombuffer(embedding_blob, dtype=np.float32)
                            embeddings.append(embedding)
                            self.knowledge_store.append(row_dict)

                    if embeddings:
                        embeddings_array = np.array(embeddings).astype('float32')
                        self.global_index.add(embeddings_array)

                    logging.info(f"Loaded {len(self.knowledge_store)} global knowledge entries")
                else:
                    # Initialize empty index
                    self.global_index = faiss.IndexFlatIP(self.embedding_dimension)
                    logging.info("Initialized empty global knowledge index")

        except Exception as e:
            logging.error(f"Error loading global knowledge: {e}")
            # Initialize empty index as fallback
            import faiss
            self.global_index = faiss.IndexFlatIP(self.embedding_dimension)

    def extract_and_store_knowledge(self, text: str, user_id: str = None) -> Dict:
        """
        Extract general knowledge from text and store it in the global layer.
        Distinguishes between personal and general knowledge.
        """
        extracted_knowledge = {
            'general_facts': [],
            'personal_details': [],
            'classification_confidence': 0.0
        }

        try:
            # Extract general knowledge
            general_facts = self._extract_general_knowledge(text)
            personal_details = self._extract_personal_knowledge(text)

            # Store general knowledge in global layer
            for fact in general_facts:
                self._store_global_knowledge(fact, user_id)
                extracted_knowledge['general_facts'].append(fact)

            # Personal details are NOT stored in global layer
            extracted_knowledge['personal_details'] = personal_details

            # Calculate classification confidence
            total_extractions = len(general_facts) + len(personal_details)
            if total_extractions > 0:
                extracted_knowledge['classification_confidence'] = len(general_facts) / total_extractions

            logging.info(f"Extracted {len(general_facts)} general facts, {len(personal_details)} personal details")

        except Exception as e:
            logging.error(f"Error extracting knowledge: {e}")

        return extracted_knowledge

    def _extract_general_knowledge(self, text: str) -> List[str]:
        """Extract general world knowledge from text."""
        knowledge = []
        text_lower = text.lower()

        for pattern in self.config.general_knowledge_patterns:
            matches = re.finditer(pattern, text_lower, re.IGNORECASE)
            for match in matches:
                fact = match.group(1).strip()
                if fact and len(fact) > 5:  # Filter out very short matches
                    # Clean and format the fact
                    fact = fact.replace('\n', ' ').strip()
                    if fact not in knowledge:  # Avoid duplicates
                        knowledge.append(f"General knowledge: {fact}")

        return knowledge

    def _extract_personal_knowledge(self, text: str) -> List[str]:
        """Extract personal/intimate knowledge from text (for classification only)."""
        personal = []
        text_lower = text.lower()

        for pattern in self.config.personal_intimate_patterns:
            matches = re.finditer(pattern, text_lower, re.IGNORECASE)
            for match in matches:
                detail = match.group(1).strip()
                if detail and len(detail) > 3:
                    detail = detail.replace('\n', ' ').strip()
                    if detail not in personal:
                        personal.append(f"Personal detail: {detail}")

        return personal

    def _store_global_knowledge(self, knowledge_text: str, source_user_id: str = None):
        """Store general knowledge in the global layer with deduplication and reinforcement."""
        try:
            # Generate embedding for the knowledge
            embedding = get_embedding(knowledge_text, self.encoder)
            if embedding is None:
                return

            # Check for similar existing knowledge
            similar_knowledge = self._find_similar_knowledge(knowledge_text, threshold=0.85)

            current_time = get_current_date_time_iso()

            if similar_knowledge:
                # Reinforce existing knowledge
                self._reinforce_existing_knowledge(similar_knowledge['id'], source_user_id)
                logging.debug(f"Reinforced existing global knowledge: {knowledge_text[:50]}...")
            else:
                # Store new knowledge
                category = self._categorize_knowledge(knowledge_text)

                with self.db_manager.get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute("""
                        INSERT INTO global_knowledge
                        (knowledge_text, knowledge_type, category, confidence_score,
                         first_learned, last_reinforced, embedding, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        knowledge_text, 'general_fact', category, 0.5,
                        current_time, current_time, embedding.tobytes(), current_time
                    ))

                    knowledge_id = cursor.lastrowid

                # Add to in-memory structures
                knowledge_entry = {
                    'id': knowledge_id,
                    'knowledge_text': knowledge_text,
                    'knowledge_type': 'general_fact',
                    'category': category,
                    'confidence_score': 0.5,
                    'source_count': 1
                }

                self.knowledge_store.append(knowledge_entry)

                # Add to FAISS index
                if self.global_index:
                    self.global_index.add(embedding.reshape(1, -1).astype('float32'))

                logging.info(f"Stored new global knowledge: {knowledge_text[:50]}...")

        except Exception as e:
            logging.error(f"Error storing global knowledge: {e}")

    def _find_similar_knowledge(self, knowledge_text: str, threshold: float = 0.85) -> Optional[Dict]:
        """Find similar existing knowledge in the global store."""
        try:
            if not self.global_index or len(self.knowledge_store) == 0:
                return None

            # Generate embedding for search
            query_embedding = get_embedding(knowledge_text, self.encoder)
            if query_embedding is None:
                return None

            # Search in FAISS index
            query_embedding = query_embedding.reshape(1, -1).astype('float32')
            similarities, indices = self.global_index.search(query_embedding, min(5, len(self.knowledge_store)))

            # Check if any result meets the threshold
            for i, (similarity, idx) in enumerate(zip(similarities[0], indices[0])):
                if similarity >= threshold and idx < len(self.knowledge_store):
                    return self.knowledge_store[idx]

            return None

        except Exception as e:
            logging.error(f"Error finding similar knowledge: {e}")
            return None

    def _reinforce_existing_knowledge(self, knowledge_id: int, source_user_id: str = None):
        """Reinforce existing knowledge by increasing confidence and source count."""
        try:
            current_time = get_current_date_time_iso()

            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE global_knowledge
                    SET source_count = source_count + 1,
                        confidence_score = MIN(1.0, confidence_score + 0.1),
                        last_reinforced = ?
                    WHERE id = ?
                """, (current_time, knowledge_id))

            # Update in-memory store
            for knowledge in self.knowledge_store:
                if knowledge['id'] == knowledge_id:
                    knowledge['source_count'] += 1
                    knowledge['confidence_score'] = min(1.0, knowledge['confidence_score'] + 0.1)
                    break

            logging.debug(f"Reinforced knowledge ID {knowledge_id}")

        except Exception as e:
            logging.error(f"Error reinforcing knowledge: {e}")

    def _categorize_knowledge(self, knowledge_text: str) -> str:
        """Automatically categorize knowledge based on content."""
        text_lower = knowledge_text.lower()

        categories = {
            'technology': ['ai', 'computer', 'software', 'internet', 'app', 'tech', 'digital'],
            'health': ['health', 'medical', 'doctor', 'medicine', 'fitness', 'exercise', 'disease'],
            'food': ['food', 'restaurant', 'cooking', 'recipe', 'cuisine', 'coffee', 'tea'],
            'entertainment': ['movie', 'music', 'book', 'game', 'entertainment', 'celebrity'],
            'location': ['india', 'bangalore', 'mumbai', 'delhi', 'city', 'country', 'place'],
            'business': ['business', 'company', 'startup', 'work', 'job', 'market', 'economy'],
            'education': ['education', 'school', 'university', 'student', 'course', 'study'],
            'science': ['science', 'research', 'study', 'discovery', 'experiment'],
            'sports': ['sports', 'game', 'team', 'cricket', 'football', 'tennis', 'match'],
            'weather': ['weather', 'climate', 'rain', 'sun', 'temperature', 'season'],
        }

        for category, keywords in categories.items():
            if any(keyword in text_lower for keyword in keywords):
                return category

        return 'general'

    def search_global_knowledge(self, query: str, limit: int = 5) -> List[Dict]:
        """Search for relevant global knowledge based on query."""
        try:
            if not self.global_index or len(self.knowledge_store) == 0:
                return []

            # Generate embedding for search
            query_embedding = get_embedding(query, self.encoder)
            if query_embedding is None:
                return []

            # Search in FAISS index
            query_embedding = query_embedding.reshape(1, -1).astype('float32')
            similarities, indices = self.global_index.search(query_embedding, min(limit * 2, len(self.knowledge_store)))

            results = []
            for similarity, idx in zip(similarities[0], indices[0]):
                if similarity >= 0.3 and idx < len(self.knowledge_store):  # Lower threshold for search
                    knowledge = self.knowledge_store[idx].copy()
                    knowledge['relevance_score'] = float(similarity)
                    results.append(knowledge)

            # Sort by confidence and relevance
            results.sort(key=lambda x: (x['confidence_score'], x['relevance_score']), reverse=True)

            return results[:limit]

        except Exception as e:
            logging.error(f"Error searching global knowledge: {e}")
            return []

    def get_knowledge_summary(self) -> Dict:
        """Get summary statistics of global knowledge."""
        try:
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()

                # Get total count
                cursor.execute("SELECT COUNT(*) as total FROM global_knowledge")
                total = dict(cursor.fetchone())['total']

                # Get category distribution
                cursor.execute("""
                    SELECT category, COUNT(*) as count
                    FROM global_knowledge
                    GROUP BY category
                    ORDER BY count DESC
                """)
                categories = {dict(row)['category']: dict(row)['count'] for row in cursor.fetchall()}

                # Get confidence distribution
                cursor.execute("""
                    SELECT
                        AVG(confidence_score) as avg_confidence,
                        MAX(confidence_score) as max_confidence,
                        COUNT(CASE WHEN confidence_score >= 0.8 THEN 1 END) as high_confidence_count
                    FROM global_knowledge
                """)
                confidence_stats = dict(cursor.fetchone())

                return {
                    'total_knowledge': total,
                    'categories': categories,
                    'avg_confidence': confidence_stats.get('avg_confidence', 0.0),
                    'max_confidence': confidence_stats.get('max_confidence', 0.0),
                    'high_confidence_count': confidence_stats.get('high_confidence_count', 0)
                }

        except Exception as e:
            logging.error(f"Error getting knowledge summary: {e}")
            return {'total_knowledge': 0, 'categories': {}, 'avg_confidence': 0.0}

class TimeAwarenessManager:
    """
    Advanced time-awareness system that tracks conversation patterns, timing, and user habits.
    Provides human-like awareness of when users typically chat and how long they've been away.
    """

    def __init__(self, db_manager: DatabaseManager):
        self.db_manager = db_manager
        self.config = config
        self.active_sessions = {}  # user_id -> session_info

    def start_session(self, user_id: str) -> Dict:
        """Start tracking a new conversation session."""
        current_time = get_current_date_time_iso()
        current_dt = datetime.fromisoformat(current_time.replace('Z', '+00:00'))

        # Get last session info
        last_session_info = self._get_last_session_info(user_id)
        gap_hours = 0.0

        if last_session_info:
            last_end = datetime.fromisoformat(last_session_info['session_end'].replace('Z', '+00:00'))
            gap_hours = (current_dt - last_end).total_seconds() / 3600

        session_info = {
            'session_start': current_time,
            'message_count': 0,
            'gap_since_last_hours': gap_hours,
            'day_of_week': current_dt.weekday(),
            'hour_of_day': current_dt.hour,
            'user_id': user_id
        }

        self.active_sessions[user_id] = session_info

        # Update user profile with session start
        self._update_user_session_start(user_id, current_time)

        logging.info(f"Started session for user {user_id}, gap since last: {gap_hours:.1f} hours")
        return session_info

    def end_session(self, user_id: str):
        """End the current conversation session and save statistics."""
        if user_id not in self.active_sessions:
            return

        session_info = self.active_sessions[user_id]
        current_time = get_current_date_time_iso()

        # Calculate session duration
        start_time = datetime.fromisoformat(session_info['session_start'].replace('Z', '+00:00'))
        end_time = datetime.fromisoformat(current_time.replace('Z', '+00:00'))
        duration_minutes = (end_time - start_time).total_seconds() / 60

        # Save session to database
        self._save_session_to_db(user_id, session_info, current_time, duration_minutes)

        # Update user conversation patterns
        self._update_conversation_patterns(user_id)

        # Clean up active session
        del self.active_sessions[user_id]

        logging.info(f"Ended session for user {user_id}, duration: {duration_minutes:.1f} minutes")

    def increment_message_count(self, user_id: str):
        """Increment message count for active session."""
        if user_id in self.active_sessions:
            self.active_sessions[user_id]['message_count'] += 1

    def get_time_context(self, user_id: str) -> Dict:
        """Get comprehensive time context for conversation."""
        try:
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()

                # Get user profile with time data
                cursor.execute(f"""
                    SELECT conversation_pattern, avg_session_gap_hours, preferred_chat_times,
                           last_session_duration_minutes, total_sessions, longest_gap_days,
                           time_zone, last_active
                    FROM {config.user_table_name} WHERE user_id = ?
                """, (user_id,))

                profile_row = cursor.fetchone()
                if not profile_row:
                    return self._default_time_context()

                # Convert sqlite3.Row to dict
                profile = dict(profile_row)

                # Get recent session patterns
                cursor.execute("""
                    SELECT session_start, session_end, session_duration_minutes,
                           gap_since_last_hours, day_of_week, hour_of_day
                    FROM conversation_sessions
                    WHERE user_id = ?
                    ORDER BY session_start DESC
                    LIMIT 10
                """, (user_id,))

                recent_sessions_rows = cursor.fetchall()
                # Convert sqlite3.Row objects to dicts
                recent_sessions = [dict(row) for row in recent_sessions_rows]

                return self._build_time_context(profile, recent_sessions, user_id)

        except Exception as e:
            logging.error(f"Error getting time context for user {user_id}: {e}")
            return self._default_time_context()

    def _get_last_session_info(self, user_id: str) -> Optional[Dict]:
        """Get information about the user's last session."""
        try:
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT session_start, session_end, session_duration_minutes, gap_since_last_hours
                    FROM conversation_sessions
                    WHERE user_id = ? AND session_end IS NOT NULL
                    ORDER BY session_start DESC
                    LIMIT 1
                """, (user_id,))

                result = cursor.fetchone()
                return dict(result) if result else None
        except Exception as e:
            logging.error(f"Error getting last session info for user {user_id}: {e}")
            return None

    def _update_user_session_start(self, user_id: str, session_start: str):
        """Update user profile with session start time."""
        try:
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                # SECURITY FIX: Validate table name
                table_name = config.user_table_name
                if not table_name.replace('_', '').replace('v', '').replace('4', '').isalnum():
                    raise ValueError(f"Invalid table name: {table_name}")

                cursor.execute(f"""
                    UPDATE {table_name}
                    SET session_start_time = ?, total_sessions = total_sessions + 1
                    WHERE user_id = ?
                """, (session_start, user_id))
        except Exception as e:
            logging.error(f"Error updating session start for user {user_id}: {e}")

    def _save_session_to_db(self, user_id: str, session_info: Dict, end_time: str, duration_minutes: float):
        """Save completed session to database."""
        try:
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO conversation_sessions
                    (user_id, session_start, session_end, message_count, session_duration_minutes,
                     gap_since_last_hours, day_of_week, hour_of_day, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    user_id, session_info['session_start'], end_time,
                    session_info['message_count'], duration_minutes,
                    session_info['gap_since_last_hours'], session_info['day_of_week'],
                    session_info['hour_of_day'], get_current_date_time_iso()
                ))
        except Exception as e:
            logging.error(f"Error saving session to DB for user {user_id}: {e}")

    def _update_conversation_patterns(self, user_id: str):
        """Analyze and update user's conversation patterns."""
        try:
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()

                # Get recent sessions for pattern analysis
                cursor.execute("""
                    SELECT gap_since_last_hours, session_duration_minutes, hour_of_day, day_of_week
                    FROM conversation_sessions
                    WHERE user_id = ?
                    ORDER BY session_start DESC
                    LIMIT 20
                """, (user_id,))

                sessions_rows = cursor.fetchall()
                if not sessions_rows:
                    return

                # Convert sqlite3.Row objects to dicts
                sessions = [dict(row) for row in sessions_rows]

                # Calculate patterns
                gaps = [s['gap_since_last_hours'] for s in sessions if s['gap_since_last_hours'] > 0]
                avg_gap = sum(gaps) / len(gaps) if gaps else 24.0
                max_gap = max(gaps) if gaps else 0.0

                # Determine conversation pattern
                pattern = self._classify_conversation_pattern(avg_gap)

                # Find preferred chat times
                hours = [s['hour_of_day'] for s in sessions]
                preferred_times = self._find_preferred_chat_times(hours)

                # Update user profile
                # SECURITY FIX: Validate table name
                table_name = config.user_table_name
                if not table_name.replace('_', '').replace('v', '').replace('4', '').isalnum():
                    raise ValueError(f"Invalid table name: {table_name}")

                cursor.execute(f"""
                    UPDATE {table_name}
                    SET conversation_pattern = ?, avg_session_gap_hours = ?,
                        longest_gap_days = ?, preferred_chat_times = ?
                    WHERE user_id = ?
                """, (pattern, avg_gap, max_gap / 24, preferred_times, user_id))

        except Exception as e:
            logging.error(f"Error updating conversation patterns for user {user_id}: {e}")

    def _classify_conversation_pattern(self, avg_gap_hours: float) -> str:
        """Classify user's conversation pattern based on average gap."""
        if avg_gap_hours <= 2:
            return 'frequent_chatter'
        elif avg_gap_hours <= 24:
            return 'daily_user'
        elif avg_gap_hours <= 72:
            return 'regular_user'
        elif avg_gap_hours <= 168:
            return 'occasional_user'
        elif avg_gap_hours <= 720:
            return 'rare_user'
        else:
            return 'returning_user'

    def _find_preferred_chat_times(self, hours: List[int]) -> str:
        """Find user's preferred chat times based on historical data."""
        if not hours:
            return ""

        # Count frequency of each hour
        hour_counts = {}
        for hour in hours:
            hour_counts[hour] = hour_counts.get(hour, 0) + 1

        # Find most common hours
        sorted_hours = sorted(hour_counts.items(), key=lambda x: x[1], reverse=True)
        top_hours = [str(hour) for hour, count in sorted_hours[:3]]

        return ",".join(top_hours)

    def _build_time_context(self, profile: Dict, recent_sessions: List[Dict], user_id: str) -> Dict:
        """Build comprehensive time context from profile and session data."""
        current_time = datetime.now(timezone.utc)

        # Parse last active time
        last_active_str = profile.get('last_active', '')
        if last_active_str:
            try:
                last_active = datetime.fromisoformat(last_active_str.replace('Z', '+00:00'))
                hours_since_last = (current_time - last_active).total_seconds() / 3600
            except:
                hours_since_last = 0
        else:
            hours_since_last = 0

        return {
            'conversation_pattern': profile.get('conversation_pattern', 'new_user'),
            'avg_session_gap_hours': profile.get('avg_session_gap_hours', 24.0),
            'preferred_chat_times': profile.get('preferred_chat_times', '').split(',') if profile.get('preferred_chat_times') else [],
            'last_session_duration_minutes': profile.get('last_session_duration_minutes', 0.0),
            'total_sessions': profile.get('total_sessions', 0),
            'longest_gap_days': profile.get('longest_gap_days', 0.0),
            'hours_since_last_chat': hours_since_last,
            'current_hour': current_time.hour,
            'current_day_of_week': current_time.weekday(),
            'is_usual_chat_time': str(current_time.hour) in (profile.get('preferred_chat_times', '').split(',') if profile.get('preferred_chat_times') else []),
            'time_gap_category': self._categorize_time_gap(hours_since_last),
            'session_count_last_week': len([s for s in recent_sessions if s and self._is_within_days(s.get('session_start', ''), 7)])
        }

    def _categorize_time_gap(self, hours: float) -> str:
        """Categorize the time gap since last conversation."""
        if hours < 1:
            return 'just_now'
        elif hours < 6:
            return 'few_hours'
        elif hours < 24:
            return 'today'
        elif hours < 48:
            return 'yesterday'
        elif hours < 168:
            return 'this_week'
        elif hours < 720:
            return 'this_month'
        else:
            return 'long_time'

    def _is_within_days(self, timestamp_str: str, days: int) -> bool:
        """Check if timestamp is within specified number of days."""
        try:
            timestamp = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
            current_time = datetime.now(timezone.utc)
            return (current_time - timestamp).days <= days
        except:
            return False

    def _default_time_context(self) -> Dict:
        """Return default time context for new users."""
        current_time = datetime.now(timezone.utc)
        return {
            'conversation_pattern': 'new_user',
            'avg_session_gap_hours': 24.0,
            'preferred_chat_times': [],
            'last_session_duration_minutes': 0.0,
            'total_sessions': 0,
            'longest_gap_days': 0.0,
            'hours_since_last_chat': 0.0,
            'current_hour': current_time.hour,
            'current_day_of_week': current_time.weekday(),
            'is_usual_chat_time': False,
            'time_gap_category': 'new_user',
            'session_count_last_week': 0
        }

class ContextualMemoryManager:
    """
    Manages contextual memory using FAISS (IndexFlatIP) and DatabaseManager (V4).
    Ensures embeddings are normalized for accurate cosine similarity search.
    Handles loading from DB on first access for a user and dynamic relevance scoring.
    """
    def __init__(self, db_manager: DatabaseManager, load_from_db: bool = True):
        if faiss is None:
             logging.critical("FAISS library not available. Contextual Memory cannot function.")
             raise ImportError("FAISS library not found. Please install it.")

        self.db_manager: DatabaseManager = db_manager
        self.encoder: SentenceTransformer = get_sentence_transformer()
        try:
             self.embedding_dimension: int = self.encoder.get_sentence_embedding_dimension()
        except Exception as e:
             logging.critical(f"Failed to get embedding dimension from sentence transformer: {e}")
             raise RuntimeError("Could not determine embedding dimension.") from e

        self.memory_store = defaultdict(list) # In-memory cache of loaded memories
        self.faiss_indices = {} # FAISS index per user
        self.faiss_to_store_idx_map = defaultdict(dict) # Maps FAISS index -> memory_store index
        self.load_from_db_on_init = load_from_db
        self._loaded_users = set() # Track users loaded in this session to prevent redundant DB loads

        logging.info(f"ContextualMemoryManager initialized (V4) (Dim: {self.embedding_dimension}, Index: IndexFlatIP, DB: Enabled, LoadOnInit: {load_from_db})")

    def _ensure_normalized(self, embedding: np.ndarray, context: str = "operation") -> Optional[np.ndarray]:
        """Helper to ensure an embedding is normalized (L2 norm=1) and float32."""
        if not isinstance(embedding, np.ndarray):
             logging.warning(f"Cannot normalize non-numpy array ({type(embedding)}) in {context}.")
             return None
        if embedding.ndim != 1:
             logging.warning(f"Embedding must be 1D for normalization check, got {embedding.ndim}D in {context}. Shape: {embedding.shape}")
             # Attempt flatten, but this might hide issues
             if embedding.size == self.embedding_dimension:
                  embedding = embedding.flatten()
             else:
                  return None # Cannot fix if size is wrong

        if embedding.dtype != np.float32:
             embedding = embedding.astype(np.float32)

        norm = np.linalg.norm(embedding)

        if norm == 0:
            # Cannot normalize a zero vector, return it as is
            # logging.debug(f"Embedding is zero-vector in {context}. Cannot normalize.")
            return embedding

        if not np.isclose(norm, 1.0, atol=1e-6):
            logging.debug(f"Re-normalizing embedding (norm={norm:.4f}) during {context}.")
            embedding = embedding / norm
            # Double check norm after correction
            new_norm = np.linalg.norm(embedding)
            if not np.isclose(new_norm, 1.0, atol=1e-6):
                logging.error(f"CRITICAL: Re-normalization failed! Norm is {new_norm:.6f}. Returning original non-normalized vector for safety (might break FAISS IP).")
                # Returning the original *might* be safer than returning None if the caller expects an array
                # But ideally this should never happen.
                return embedding / norm # Return the re-normalized one anyway, maybe it's close enough? Or return None? Let's return the attempt.

        return embedding

    def _get_or_create_index(self, user_id: str):
        """Gets or creates a FAISS index for the user, loading from DB on first access this session."""
        if user_id not in self.faiss_indices:
            logging.info(f"Initializing FAISS index (IndexFlatIP) and memory store for user '{user_id}'")
            try:
                # Create structures first
                self.memory_store[user_id] = []
                self.faiss_to_store_idx_map[user_id] = {}
                # Use IndexFlatIP for cosine similarity on normalized vectors
                index = faiss.IndexFlatIP(self.embedding_dimension)
                self.faiss_indices[user_id] = index
                logging.debug(f"Created empty FAISS index (IndexFlatIP, Dim={self.embedding_dimension}) for user '{user_id}'.")

                # Load from DB if configured and not already loaded for this session
                if self.load_from_db_on_init and user_id not in self._loaded_users:
                    self._load_and_index_user_memories(user_id)
                    self._loaded_users.add(user_id) # Mark as loaded for this session

            except Exception as e:
                logging.error(f"Failed to initialize FAISS index or load memories for user '{user_id}': {e}", exc_info=True)
                # Clean up potentially partially created structures on failure
                self.memory_store.pop(user_id, None)
                self.faiss_indices.pop(user_id, None)
                self.faiss_to_store_idx_map.pop(user_id, None)
                self._loaded_users.discard(user_id)
                return None # Indicate failure

        return self.faiss_indices.get(user_id)

    def _load_and_index_user_memories(self, user_id: str):
        """Loads memories from DB, ensures normalization, and indexes into FAISS/memory store."""
        logging.info(f"Loading and indexing memories for user '{user_id}' from DB.")
        if not self.db_manager:
            logging.warning(f"DB manager not available, cannot load memories for user '{user_id}'.")
            return

        index = self.faiss_indices.get(user_id)
        if index is None or user_id not in self.memory_store or user_id not in self.faiss_to_store_idx_map:
            logging.error(f"FAISS index or memory store structure not ready for user '{user_id}' during DB load. Aborting.")
            return

        # Load raw data from DB (expecting 1D numpy arrays from db_manager V4)
        db_memories = self.db_manager.load_recent_memories(user_id)
        if not db_memories:
            logging.info(f"No memories found in DB for user '{user_id}'.")
            return

        # --- Reset existing in-memory data before loading ---
        # Prevents duplicates if loading happens multiple times (e.g., server restart without clearing _loaded_users)
        if index.ntotal > 0 or self.memory_store[user_id]:
             logging.warning(f"Resetting existing FAISS index ({index.ntotal} entries) and memory store ({len(self.memory_store[user_id])}) for user '{user_id}' before loading from DB.")
             index.reset()
             self.memory_store[user_id] = []
             self.faiss_to_store_idx_map[user_id] = {}

        embeddings_to_index = []
        valid_memory_entries = [] # Store corresponding dicts with normalized embeddings

        for db_memory in db_memories:
            memory_id = db_memory.get('id')
            embedding_array = db_memory.get('embedding') # Should be 1D np.ndarray from load_recent_memories V4

            if not isinstance(embedding_array, np.ndarray):
                 logging.warning(f"Skipping memory ID {memory_id}: Invalid embedding type ({type(embedding_array)}) after DB load.")
                 continue
            if embedding_array.ndim != 1 or embedding_array.size != self.embedding_dimension:
                 logging.warning(f"Skipping memory ID {memory_id}: Incorrect embedding shape/size ({embedding_array.shape}, size {embedding_array.size}) after DB load.")
                 continue

            # --- CRUCIAL: Ensure normalization AGAIN after loading from DB ---
            # Even if saved normalized, reload/conversion might introduce tiny errors
            normalized_embedding = self._ensure_normalized(embedding_array, f"DB load (ID: {memory_id})")
            if normalized_embedding is None:
                logging.warning(f"Skipping memory ID {memory_id}: Normalization failed after DB load.")
                continue
            if np.linalg.norm(normalized_embedding) == 0:
                 logging.warning(f"Skipping memory ID {memory_id}: Embedding is zero vector after DB load normalization attempt.")
                 continue

            # Store the *normalized* embedding back in the dictionary
            db_memory['embedding'] = normalized_embedding

            # Reshape to (1, D) for adding to the list for vstack later
            embeddings_to_index.append(normalized_embedding.reshape(1, self.embedding_dimension))
            valid_memory_entries.append(db_memory) # Keep the dict containing the normalized 1D embedding

        # --- Indexing Step ---
        if embeddings_to_index:
            logging.debug(f"Attempting to index {len(embeddings_to_index)} valid memories for user '{user_id}'.")
            try:
                all_embeddings_np = np.vstack(embeddings_to_index).astype(np.float32)
                # Verify shape before adding
                if all_embeddings_np.shape != (len(embeddings_to_index), self.embedding_dimension):
                     raise ValueError(f"Stacked embeddings shape mismatch: {all_embeddings_np.shape}")

                # Add all embeddings to FAISS at once
                index.add(all_embeddings_np)

                # --- Verification and Mapping ---
                if index.ntotal == len(valid_memory_entries):
                    # Add to memory_store and create map *after* successful FAISS add
                    for i, memory_entry in enumerate(valid_memory_entries):
                        # The FAISS index for this item corresponds to its order in the added batch (i)
                        faiss_idx = i
                        store_idx = len(self.memory_store[user_id]) # Its index in the Python list

                        memory_entry['store_index'] = store_idx # Add store index for reference
                        self.memory_store[user_id].append(memory_entry) # Store the dict
                        self.faiss_to_store_idx_map[user_id][faiss_idx] = store_idx # Map: faiss_idx -> store_idx

                    logging.info(f"Successfully loaded and indexed {index.ntotal}/{len(db_memories)} memories for user '{user_id}' from DB.")
                else:
                    logging.error(f"FAISS index size ({index.ntotal}) mismatch after adding {len(valid_memory_entries)} embeddings for user '{user_id}'. Resetting index.")
                    index.reset()
                    self.memory_store[user_id] = []
                    self.faiss_to_store_idx_map[user_id] = {}

            except faiss.FaissException as faiss_e:
                 logging.error(f"FAISS error during batch add for user '{user_id}': {faiss_e}", exc_info=True)
                 if index: index.reset() # Reset on error
                 self.memory_store[user_id] = []
                 self.faiss_to_store_idx_map[user_id] = {}
            except Exception as e:
                 logging.error(f"Unexpected error stacking or adding embeddings during load for user '{user_id}': {e}", exc_info=True)
                 if index: index.reset()
                 self.memory_store[user_id] = []
                 self.faiss_to_store_idx_map[user_id] = {}
        else:
            logging.info(f"No valid memories with embeddings found in DB to index for user '{user_id}'.")

    def store_interaction(self, user_id: str, text: str, emotion: str, base_importance: float,
                          vulnerability_score: float = 0.0, insight_score: float = 0.0,
                          related_chat_log_id: Optional[int] = None, memory_type: str = 'short_term'):
        """Enhanced memory storage with automatic detail extraction and categorization."""
        logging.debug(f"Storing interaction memory for user '{user_id}': '{text[:50]}...' (Type: {memory_type})")
        timestamp = get_current_date_time_iso()

        # ENHANCED: Two-layer memory system with personal/global distinction
        extracted_details = self._extract_personal_details(text)
        factual_details = self._extract_factual_details(text)

        # Store main interaction
        main_memory_id = self._store_single_memory(
            user_id, text, emotion, base_importance, vulnerability_score,
            insight_score, related_chat_log_id, memory_type, timestamp
        )

        # Store extracted details as separate micro-memories (personal layer)
        detail_memory_ids = []
        for detail in extracted_details:
            detail_importance = base_importance + config.memory_personal_detail_boost
            detail_id = self._store_single_memory(
                user_id, detail, emotion, detail_importance, vulnerability_score,
                insight_score, related_chat_log_id, 'micro_detail', timestamp
            )
            if detail_id:
                detail_memory_ids.append(detail_id)

        for fact in factual_details:
            fact_importance = base_importance + config.memory_factual_boost
            fact_id = self._store_single_memory(
                user_id, fact, emotion, fact_importance, vulnerability_score,
                insight_score, related_chat_log_id, 'factual', timestamp
            )
            if fact_id:
                detail_memory_ids.append(fact_id)

        logging.info(f"Stored main memory + {len(detail_memory_ids)} detail memories for user '{user_id}'")
        return main_memory_id

    def _store_single_memory(self, user_id: str, text: str, emotion: str, base_importance: float,
                           vulnerability_score: float, insight_score: float,
                           related_chat_log_id: Optional[int], memory_type: str, timestamp: str):
        """Internal method to store a single memory entry."""
        # 1. Get *Normalized* Embedding
        embedding_norm = get_embedding(text, self.encoder)

        if embedding_norm is None:
             logging.error(f"Failed to generate embedding for user '{user_id}'. Cannot store memory.")
             return
        if embedding_norm.shape != (self.embedding_dimension,):
             logging.error(f"Generated embedding has incorrect shape {embedding_norm.shape} for user '{user_id}'. Expected ({self.embedding_dimension},). Cannot store.")
             return
        # Check for zero vector explicitly
        if np.linalg.norm(embedding_norm) == 0:
             logging.warning(f"Generated zero vector for text '{text[:50]}...'. Cannot store meaningful memory.")
             return

        # Final normalization check (should be redundant if get_embedding works)
        embedding_norm = self._ensure_normalized(embedding_norm, "store_interaction")
        if embedding_norm is None:
             logging.error("Normalization check failed unexpectedly in store_interaction.")
             return

        # Prepare for FAISS (needs 2D array, shape (1, D))
        embedding_faiss = embedding_norm.reshape(1, -1)

        # Calculate final importance score with type-specific minimums
        final_importance = np.clip(base_importance + \
                           (vulnerability_score * config.memory_vulnerability_boost) + \
                           (insight_score * config.memory_insight_boost), 0.02, 1.0)

        # Ensure minimum importance based on memory type
        min_importance = 0.02 if memory_type in ['micro_detail', 'factual'] else 0.05
        final_importance = max(final_importance, min_importance)

        # 2. Get Index (creates/loads if needed)
        index = self._get_or_create_index(user_id)
        if index is None:
             logging.error(f"Failed to get/create FAISS index for user '{user_id}'. Cannot store memory.")
             return

        # 3. Save to Database First (pass the 1D normalized numpy array)
        db_id = None
        if self.db_manager:
            try:
                # Pass the 1D normalized float32 numpy array
                db_id = self.db_manager.save_memory_interaction(
                    user_id, text, embedding_norm, emotion, final_importance, timestamp, related_chat_log_id, memory_type
                )
                if db_id is None or db_id <= 0:
                    raise ConnectionError(f"DB save failed or returned invalid ID ({db_id}) for user '{user_id}'.")
                logging.debug(f"Memory saved to DB (ID: {db_id})")
            except Exception as e:
                logging.error(f"Failed to save memory interaction to database for user '{user_id}': {e}", exc_info=True)
                return # Abort store if DB save fails
        else:
            logging.warning("DB Manager not configured. Memory will not be persisted.")
            # Allow proceeding without DB ID if persistence isn't required

        # 4. Add to FAISS and In-Memory Store (only if DB save succeeded or wasn't required)
        store_idx = -1
        faiss_idx = -1
        try:
            store_idx = len(self.memory_store[user_id])
            faiss_idx = index.ntotal # FAISS index *before* adding

            # Add the (1, D) normalized vector to FAISS
            index.add(embedding_faiss)

            if index.ntotal != faiss_idx + 1:
                 # Rollback FAISS add is hard with IndexFlat. Log critical inconsistency.
                 logging.critical(f"FAISS index ntotal ({index.ntotal}) did not increase correctly after add (expected {faiss_idx + 1}) for user {user_id}. Potential index corruption!")
                 # Optionally try removing the last added vector if possible, or reset the index? Reset is safer.
                 # For now, just log and hope search still works reasonably.
                 # If DB save happened, log that too.
                 if db_id: logging.critical(f"DB ID {db_id} was saved, but FAISS add failed consistency check.")
                 # Do not proceed with adding to memory store or map if FAISS add is suspicious.
                 return

            # FAISS add successful, now add to in-memory store and map
            memory_entry = {
                'id': db_id, # Use 'id' consistently, maps to DB ID if available
                'text': text,
                'embedding': embedding_norm, # Store the 1D normalized array
                'emotion': emotion,
                'importance': final_importance,
                'timestamp': timestamp,
                'last_accessed': timestamp, # Initially accessed now
                'access_count': 1,
                'related_chat_log_id': related_chat_log_id,
                'memory_type': memory_type, # Store memory type
                'store_index': store_idx # Store its own list index
            }
            self.memory_store[user_id].append(memory_entry)
            self.faiss_to_store_idx_map[user_id][faiss_idx] = store_idx # Map: faiss_idx -> store_idx

            logging.info(f"Stored memory successfully (DB ID: {db_id}, Store Idx: {store_idx}, FAISS Idx: {faiss_idx}, Type: {memory_type}) for user '{user_id}'")

        except faiss.FaissException as faiss_e:
             logging.error(f"FAISS error adding interaction memory for user '{user_id}': {faiss_e}", exc_info=True)
             if db_id: logging.critical(f"INCONSISTENCY POSSIBLE: Memory DB ID {db_id} saved, but FAISS add failed for user '{user_id}'.")
        except Exception as e:
            logging.error(f"Error adding interaction to FAISS/Memory store for user '{user_id}' (after potential DB save): {e}", exc_info=True)
            if db_id: logging.critical(f"INCONSISTENCY POSSIBLE: Memory DB ID {db_id} saved, but in-memory store add failed for user '{user_id}'.")
            # Attempt simple rollback from memory_store if possible
            if store_idx != -1 and store_idx < len(self.memory_store.get(user_id, [])):
                 # Check if the entry at store_idx is the one we just tried to add
                 if self.memory_store[user_id][store_idx].get('timestamp') == timestamp:
                      try:
                          self.memory_store[user_id].pop(store_idx)
                          logging.warning(f"Rolled back addition to in-memory store (Index: {store_idx}) due to error.")
                      except IndexError: pass

    def _extract_personal_details(self, text: str) -> List[str]:
        """Extract personal details using enhanced pattern matching."""
        details = []
        text_lower = text.lower()

        for pattern in config.personal_detail_patterns:
            matches = re.finditer(pattern, text_lower, re.IGNORECASE)
            for match in matches:
                detail = match.group(1).strip()
                if detail and len(detail) > 2:  # Filter out very short matches
                    # Clean and format the detail
                    detail = detail.replace('\n', ' ').strip()
                    if detail not in details:  # Avoid duplicates
                        details.append(f"Personal detail: {detail}")

        return details

    def _extract_factual_details(self, text: str) -> List[str]:
        """Extract factual information using pattern matching."""
        facts = []
        text_lower = text.lower()

        for pattern in config.factual_patterns:
            matches = re.finditer(pattern, text_lower, re.IGNORECASE)
            for match in matches:
                if len(match.groups()) >= 1:
                    fact = match.group(1).strip()
                    if fact and len(fact) > 2:
                        fact = fact.replace('\n', ' ').strip()
                        if fact not in facts:
                            facts.append(f"Fact: {fact}")

        return facts

    def create_long_term_memory(self, user_id: str, memory_text: str, emotion: str = "neutral") -> bool:
        """Creates a new long-term memory directly.
        Returns True if successful, False otherwise.
        """
        if not memory_text or not memory_text.strip():
            logging.warning(f"Attempted to create empty long-term memory for user '{user_id}'")
            return False

        logging.info(f"Creating new long-term memory for user '{user_id}': '{memory_text[:50]}...'")

        try:
            # Store with high importance and long-term type
            importance = max(0.8, config.memory_long_term_promotion_threshold)
            memory_id = self.store_interaction(
                user_id=user_id,
                text=memory_text,
                emotion=emotion,
                base_importance=importance,
                memory_type='long_term'
            )

            return memory_id is not None
        except Exception as e:
            logging.error(f"Error creating long-term memory for user '{user_id}': {e}")
            return False

    def mark_as_long_term_memory(self, user_id: str, memory_text: str) -> bool:
        """Explicitly marks a memory as long-term based on its text content.
        Returns True if successful, False otherwise.
        """
        if not self.db_manager:
            logging.warning("DB Manager not available, cannot mark memory as long-term.")
            return False

        logging.info(f"Marking memory as long-term for user '{user_id}': '{memory_text[:50]}...'")

        try:
            # Find the memory by text content
            sql = f"""SELECT `id` FROM `{config.memory_table_name}`
                   WHERE `user_id` = ? AND `text` LIKE ? LIMIT 1"""

            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(sql, (user_id, f"%{memory_text[:100]}%"))
                result = cursor.fetchone()

                if not result:
                    logging.warning(f"Could not find memory with text '{memory_text[:50]}...' for user '{user_id}'")
                    return False

                memory_id = result['id']

                # Update the memory type
                update_sql = f"UPDATE `{config.memory_table_name}` SET `memory_type` = 'long_term', `importance` = ? WHERE `id` = ?"
                cursor.execute(update_sql, (max(0.7, config.memory_long_term_promotion_threshold), memory_id))

                if cursor.rowcount > 0:
                    logging.info(f"Successfully marked memory ID {memory_id} as long-term for user '{user_id}'")

                    # Update in-memory store if needed
                    if user_id in self.memory_store:
                        for mem_entry in self.memory_store[user_id]:
                            if mem_entry.get('id') == memory_id:
                                mem_entry['memory_type'] = 'long_term'
                                mem_entry['importance'] = max(0.7, config.memory_long_term_promotion_threshold)
                                break

                    return True
                else:
                    logging.warning(f"Failed to mark memory ID {memory_id} as long-term (no rows affected)")
                    return False
        except Exception as e:
            logging.error(f"Error marking memory as long-term for user '{user_id}': {e}")
            return False

    def recall_related_memories(self, user_id: str, current_text: str, k: int = 15, prioritize_long_term: bool = True) -> List[Dict]:
        """
        ENHANCED memory recall with micro-detail awareness and multi-stage retrieval.

        Implements several cognitive memory effects:
        1. Semantic similarity (via FAISS/embeddings) - LOWERED THRESHOLDS
        2. Recency effect (recent memories are more accessible)
        3. Primacy effect (important first experiences are better remembered)
        4. Emotional salience (emotionally charged memories are more accessible)
        5. Retrieval-induced forgetting (memories competing with retrieved ones are suppressed)
        6. Context-dependent memory (current emotional/situational context affects recall)
        7. Associative memory (memories linked to each other are recalled together)
        8. Interference effects (similar memories can interfere with each other)
        9. ENHANCED: Multi-stage retrieval (main + micro-details + facts)
        10. ENHANCED: Keyword-based fallback for missed details

        Returns a list of memory dictionaries with relevance scores.
        """
        logging.debug(f"Recalling memories for user '{user_id}' (k={k}, Index=IP/Cosine) Query: '{current_text[:50]}...'")
        index = self._get_or_create_index(user_id)
        if index is None or index.ntotal == 0:
            logging.info(f"No index or memories available for recall for user '{user_id}'.")
            return []

        query_embedding_norm = get_embedding(current_text, self.encoder)
        if query_embedding_norm is None or np.linalg.norm(query_embedding_norm) == 0:
             logging.warning(f"Failed to generate valid/non-zero query embedding for user '{user_id}'. Cannot recall.")
             return []

        # Ensure normalized before search (should be redundant)
        query_embedding_norm = self._ensure_normalized(query_embedding_norm, "recall_query")
        if query_embedding_norm is None: return []

        query_embedding_faiss = query_embedding_norm.reshape(1, -1).astype(np.float32) # FAISS needs (1,D) float32

        recalled_memories_scored: List[Tuple[float, Dict]] = [] # Store (final_score, memory_dict)
        accessed_db_ids: Set[Optional[int]] = set() # Track DB IDs to update access count

        # Extract emotional context from the query for context-dependent memory
        query_emotion = self._extract_emotion_from_text(current_text)
        query_topics = self._extract_topics_from_text(current_text)

        # Detect if this is a factual question
        is_factual_question = self._is_factual_question(current_text)

        # Get recent conversation context (last few interactions)
        recent_context = self._get_recent_conversation_context(user_id)

        # Track which memories we've already recalled (for associative memory)
        recalled_memory_ids = set()

        try:
            # Increase initial search to account for human-like filtering
            expanded_k = min(k * 3, index.ntotal)  # Search more initially to allow for human-like filtering
            if expanded_k <= 0: return []

            logging.debug(f"Performing FAISS search (IP/Cosine) for {expanded_k} neighbors...")
            # D = similarity scores (cosine sim), I = indices in FAISS
            similarities, faiss_indices_found = index.search(query_embedding_faiss, expanded_k)

            if faiss_indices_found.size == 0 or similarities.size == 0:
                logging.warning(f"FAISS search returned empty results for user '{user_id}'.")
                return []

            logging.debug(f"FAISS raw results: Indices={faiss_indices_found[0]}, CosSim={similarities[0]}")

            user_memory_list = self.memory_store.get(user_id, [])
            user_faiss_map = self.faiss_to_store_idx_map.get(user_id, {})
            processed_store_indices: Set[int] = set()

            # Get ENHANCED thresholds from config for better detail recall
            SIM_THRESHOLD = config.memory_cosine_similarity_threshold  # 0.35 (LOWERED)
            REL_THRESHOLD = config.memory_relevance_threshold  # 0.10 (LOWERED)
            DETAIL_SIM_THRESHOLD = config.memory_detail_similarity_threshold  # 0.25 for micro-details
            logging.debug(f"Using ENHANCED thresholds: Cosine >= {SIM_THRESHOLD:.3f}, Relevance >= {REL_THRESHOLD:.3f}, Detail >= {DETAIL_SIM_THRESHOLD:.3f}")

            # Get current time for recency calculations
            current_time = datetime.now(timezone.utc)

            # Track memory clusters for associative memory
            memory_clusters = {}

            # First pass: Calculate base scores and identify clusters
            memory_base_scores = {}

            # Filter & Score Results
            for i, faiss_idx in enumerate(faiss_indices_found[0]):
                if faiss_idx < 0: continue # Invalid index from FAISS

                store_idx = user_faiss_map.get(faiss_idx)
                if store_idx is None or store_idx < 0 or store_idx >= len(user_memory_list):
                    logging.warning(f"Invalid map or store index: FAISS={faiss_idx}, MappedStore={store_idx}, ListSize={len(user_memory_list)}. Skipping.")
                    continue
                if store_idx in processed_store_indices: continue
                processed_store_indices.add(store_idx)

                memory_entry = user_memory_list[store_idx]
                memory_id = memory_entry.get('id')
                similarity_score = float(similarities[0][i]) # Cosine similarity

                # --- ENHANCED Filter 1: Multi-tier Similarity Thresholds ---
                memory_type = memory_entry.get('memory_type', 'short_term')

                # Use different thresholds based on memory type
                if memory_type in ['micro_detail', 'factual']:
                    threshold_to_use = DETAIL_SIM_THRESHOLD  # Lower threshold for details
                else:
                    threshold_to_use = SIM_THRESHOLD  # Standard threshold

                if similarity_score >= threshold_to_use:
                    try:
                        # --- Human-like Memory Scoring ---

                        # 1. Base Importance (from stored value)
                        importance = memory_entry.get('importance', 0.1)

                        # 2. Recency Effect (Ebbinghaus forgetting curve)
                        timestamp_iso = memory_entry.get('timestamp')
                        seconds_elapsed = time_since(timestamp_iso) if timestamp_iso else float('inf')

                        # Implement forgetting curve with spaced repetition effects
                        # More recent memories are more accessible, but with diminishing returns
                        hours_elapsed = seconds_elapsed / 3600

                        # Forgetting curve parameters
                        retention_strength = 0.9  # Base retention strength (higher = better retention)
                        decay_factor = 0.05      # How quickly memories decay

                        # Calculate recency score using forgetting curve
                        recency_score = retention_strength * np.exp(-decay_factor * np.sqrt(hours_elapsed))

                        # 3. Primacy Effect (first/early experiences are remembered better)
                        # Check if this is one of the first memories for this user
                        is_early_memory = False
                        if memory_entry.get('id') and memory_entry.get('id') < 10:  # Assuming IDs are sequential
                            is_early_memory = True
                            primacy_boost = 0.15
                        else:
                            primacy_boost = 0.0

                        # 4. Retrieval History Effect (memories accessed more often are more accessible)
                        access_count = memory_entry.get('access_count', 0)

                        # Implement spaced repetition effect - memories accessed multiple times are stronger
                        # But with diminishing returns using log scale
                        retrieval_strength = min(0.3, 0.05 * np.log1p(access_count))

                        # 5. Emotional Salience (emotionally charged memories are more accessible)
                        memory_emotion = memory_entry.get('emotion', 'neutral')
                        emotion_intensity = self._get_emotion_intensity(memory_emotion)

                        # Emotional memories are remembered better
                        emotional_salience = emotion_intensity * 0.2

                        # 6. Context-Dependent Memory (current emotional context affects recall)
                        # If current emotion matches memory emotion, boost relevance
                        emotion_context_match = 0.0
                        if query_emotion and memory_emotion and query_emotion == memory_emotion:
                            emotion_context_match = 0.15
                            logging.debug(f"Emotion context match for memory ID {memory_id}: {query_emotion}")

                        # 7. Topic Relevance (semantic topic matching)
                        memory_text = memory_entry.get('text', '').lower()
                        memory_topics = self._extract_topics_from_text(memory_text)

                        # Calculate topic overlap
                        topic_overlap = len(set(query_topics) & set(memory_topics))
                        topic_relevance = min(0.3, topic_overlap * 0.1)

                        # 8. Memory Type Boost (long-term memories are more stable)
                        memory_type_boost = 0.0
                        if prioritize_long_term and memory_entry.get('memory_type') == 'long_term':
                            memory_type_boost = config.memory_long_term_boost
                            logging.debug(f"Applied long-term memory boost to memory ID {memory_entry.get('id')}")

                        # 9. Factual Recall Boost (for factual questions, prioritize factual memories)
                        factual_boost = 0.0
                        if is_factual_question and self._contains_factual_information(memory_text):
                            factual_boost = 0.25
                            logging.debug(f"Applied factual boost to memory ID {memory_id}")

                        # 10. Conversation Context Relevance
                        context_relevance = 0.0
                        if recent_context and self._is_related_to_context(memory_text, recent_context):
                            context_relevance = 0.2
                            logging.debug(f"Memory ID {memory_id} is relevant to recent conversation context")

                        # --- Combine all factors with human-like weighting ---
                        # Base formula weights factors by their importance in human memory
                        base_score = (
                            similarity_score * 0.25 +           # Semantic similarity (25%)
                            importance * 0.15 +                 # Base importance (15%)
                            recency_score * 0.20 +              # Recency effect (20%)
                            primacy_boost +                     # Primacy effect (0-15%)
                            retrieval_strength +                # Retrieval history (0-30%)
                            emotional_salience +                # Emotional salience (0-20%)
                            emotion_context_match +             # Emotional context match (0-15%)
                            topic_relevance +                   # Topic relevance (0-30%)
                            memory_type_boost +                 # Memory type boost (0-15%)
                            factual_boost +                     # Factual recall boost (0-25%)
                            context_relevance                   # Conversation context (0-20%)
                        )

                        # Store base score for later use in associative memory
                        memory_base_scores[memory_id] = base_score

                        # Cluster memories by topic for associative memory
                        for topic in memory_topics:
                            if topic not in memory_clusters:
                                memory_clusters[topic] = []
                            memory_clusters[topic].append(memory_id)

                        # Apply random noise to simulate human memory variability (5% randomness)
                        human_variability = np.random.normal(0, 0.05)

                        # Final relevance score with human variability
                        relevance_score = np.clip(base_score + human_variability, 0.0, 1.0)

                    except Exception as score_err:
                         logging.warning(f"Error calculating relevance score for memory store_idx {store_idx} (ID {memory_entry.get('id')}): {score_err}")
                         relevance_score = 0.0

                    memory_type_str = memory_entry.get('memory_type', 'unknown')
                    logging.debug(f"Mem Candidate (StoreIdx {store_idx}, DB ID {memory_entry.get('id')}, Type={memory_type_str}): Sim={similarity_score:.3f}, Rel={relevance_score:.3f} - '{memory_entry['text'][:30]}...'")

                    # --- Filter 2: Relevance Threshold ---
                    if relevance_score >= REL_THRESHOLD:
                        recalled_entry = memory_entry.copy()
                        # Store individual scores for context/debugging
                        recalled_entry['similarity_score'] = similarity_score
                        recalled_entry['calculated_relevance'] = relevance_score
                        recalled_entry['human_factors'] = {
                            'recency': recency_score,
                            'emotion': emotional_salience,
                            'retrieval_strength': retrieval_strength,
                            'topic_relevance': topic_relevance
                        }

                        recalled_memories_scored.append((relevance_score, recalled_entry))
                        recalled_memory_ids.add(memory_id)

                        # Track DB ID for access update if it exists
                        db_id = recalled_entry.get('id')
                        if db_id is not None: accessed_db_ids.add(db_id)

                    else: logging.debug(f"... Relevance score {relevance_score:.3f} below threshold {REL_THRESHOLD:.3f}")
                else: logging.debug(f"Mem (Store Idx {store_idx}) Sim score {similarity_score:.3f} below threshold {SIM_THRESHOLD:.3f}.")

            # --- Second pass: Apply associative memory effects ---
            # Find memories associated with already recalled memories
            associative_memories = []

            # Look for memories in the same clusters as recalled memories
            for topic, memory_ids in memory_clusters.items():
                # If we've recalled at least one memory from this cluster
                if any(mem_id in recalled_memory_ids for mem_id in memory_ids):
                    # Consider other memories in the same cluster
                    for mem_id in memory_ids:
                        if mem_id not in recalled_memory_ids:
                            # Find this memory in the user's memory list
                            for store_idx, memory_entry in enumerate(user_memory_list):
                                if memory_entry.get('id') == mem_id:
                                    # Apply associative boost to the base score
                                    base_score = memory_base_scores.get(mem_id, 0.3)
                                    associative_boost = 0.15  # Boost for being associated

                                    # Apply interference effects - similar memories compete
                                    # More similar memories in the same cluster = more interference
                                    interference_penalty = min(0.1, 0.02 * len(memory_ids))

                                    # Final associative score
                                    associative_score = base_score + associative_boost - interference_penalty

                                    # Only include if it passes the relevance threshold
                                    if associative_score >= REL_THRESHOLD:
                                        recalled_entry = memory_entry.copy()
                                        recalled_entry['similarity_score'] = 0.0  # Not from semantic search
                                        recalled_entry['calculated_relevance'] = associative_score
                                        recalled_entry['associative_recall'] = True

                                        associative_memories.append((associative_score, recalled_entry))
                                        recalled_memory_ids.add(mem_id)

                                        # Track for access update
                                        db_id = recalled_entry.get('id')
                                        if db_id is not None: accessed_db_ids.add(db_id)

                                        logging.debug(f"Added associative memory ID {mem_id} with score {associative_score:.3f}")
                                    break

            # Combine direct and associative memories
            all_memories_scored = recalled_memories_scored + associative_memories

            # Sort by final score (descending) & Limit to top results
            # Human memory typically has a working memory capacity of 4-7 items
            memory_capacity = 5  # Typical human working memory capacity
            all_memories_scored.sort(key=lambda x: x[0], reverse=True)

            # Apply recency bias - sometimes the most recent memory comes to mind first
            # even if it's not the most relevant (working memory effect)
            if all_memories_scored and random.random() < 0.3:  # 30% chance of recency bias
                # Find the most recent memory among top candidates
                most_recent_idx = -1
                most_recent_time = float('inf')

                for idx, (_, mem) in enumerate(all_memories_scored[:10]):  # Look among top 10
                    if mem.get('timestamp'):
                        seconds_ago = time_since(mem.get('timestamp'))
                        if seconds_ago < most_recent_time:
                            most_recent_time = seconds_ago
                            most_recent_idx = idx

                # If we found a recent memory, move it to the top
                if most_recent_idx > 0:
                    most_recent = all_memories_scored.pop(most_recent_idx)
                    all_memories_scored.insert(0, most_recent)
                    logging.debug(f"Applied recency bias, moved memory ID {most_recent[1].get('id')} to top position")

            # Get final list of memories
            final_recalled = [mem for _, mem in all_memories_scored[:memory_capacity]]

            # ENHANCED: Add keyword-based fallback if we have few results
            if len(final_recalled) < k // 2:  # If we have less than half the requested memories
                keyword_memories = self._keyword_based_memory_fallback(user_id, current_text, k - len(final_recalled))
                # Add keyword memories that aren't already in final_recalled
                existing_ids = {mem.get('id') for mem in final_recalled}
                for keyword_mem in keyword_memories:
                    if keyword_mem.get('id') not in existing_ids:
                        final_recalled.append(keyword_mem)
                        if len(final_recalled) >= k:
                            break

            # Update Access Stats (DB and In-Memory) for the *recalled* items
            recalled_db_ids = [mem['id'] for mem in final_recalled if mem.get('id') is not None]
            if recalled_db_ids and self.db_manager:
                 self.db_manager.record_memory_access(recalled_db_ids)

            # Also update in-memory store immediately for consistency within the session
            now_iso = get_current_date_time_iso()
            for mem in final_recalled:
                store_idx_to_update = mem.get('store_index')
                if store_idx_to_update is not None and 0 <= store_idx_to_update < len(user_memory_list):
                     try:
                        current_count = user_memory_list[store_idx_to_update].get('access_count', 0)
                        user_memory_list[store_idx_to_update]['access_count'] = current_count + 1
                        user_memory_list[store_idx_to_update]['last_accessed'] = now_iso
                     except KeyError as ke:
                          logging.warning(f"KeyError updating in-memory access stats for store_idx {store_idx_to_update}: {ke}")
                     except Exception as e:
                          logging.warning(f"Error updating in-memory access stats for store_idx {store_idx_to_update}: {e}")

            logging.info(f"Recalled {len(final_recalled)} relevant memories for user '{user_id}' (Human-like memory retrieval with {len(all_memories_scored)} candidates)")
            return final_recalled

        except faiss.FaissException as faiss_e:
            logging.error(f"FAISS error during recall for user '{user_id}': {faiss_e}", exc_info=True)
            return []
        except Exception as e:
            logging.error(f"Unexpected error during memory recall for user '{user_id}': {e}", exc_info=True)
            return []

    def _get_human_time_phrase(self, timestamp_iso: Optional[str]) -> str:
        """Convert timestamp to a natural language time phrase."""
        if not timestamp_iso:
            return "at some point"

        try:
            seconds_ago = time_since(timestamp_iso)

            if seconds_ago < 60:
                return "just now"
            elif seconds_ago < 3600:
                minutes = seconds_ago // 60
                return f"{minutes} minute{'s' if minutes > 1 else ''} ago"
            elif seconds_ago < 86400:
                hours = seconds_ago // 3600
                return f"{hours} hour{'s' if hours > 1 else ''} ago"
            elif seconds_ago < 172800:  # 2 days
                return "yesterday"
            elif seconds_ago < 604800:  # 1 week
                days = seconds_ago // 86400
                return f"{days} days ago"
            elif seconds_ago < 1209600:  # 2 weeks
                return "last week"
            elif seconds_ago < 2592000:  # 30 days
                return "a few weeks ago"
            elif seconds_ago < 5184000:  # 60 days
                return "last month"
            elif seconds_ago < 31536000:  # 1 year
                months = seconds_ago // 2592000
                return f"{months} months ago"
            else:
                return "a long time ago"

        except Exception:
            return "at some point"

    def _extract_relevant_fact(self, text: str, query: str) -> str:
        """Extract the most relevant fact from text based on the query."""
        # Split into sentences
        sentences = re.split(r'[.!?]+', text)

        # Extract query keywords
        query_words = set(re.findall(r'\b\w+\b', query.lower()))

        # Score sentences by keyword overlap
        best_score = 0
        best_sentence = ""

        for sentence in sentences:
            if not sentence.strip():
                continue

            sentence_words = set(re.findall(r'\b\w+\b', sentence.lower()))
            overlap = len(query_words.intersection(sentence_words))

            if overlap > best_score:
                best_score = overlap
                best_sentence = sentence.strip()

        # If we found a good match, return it
        if best_score > 0 and best_sentence:
            return best_sentence

        # Otherwise return the first sentence as fallback
        for sentence in sentences:
            if sentence.strip():
                return sentence.strip()

        # Last resort
        return text

    def _extract_emotion_from_text(self, text: str) -> Optional[str]:
        """Extract the primary emotion from text using simple keyword matching."""
        emotion_keywords = {
            "happy": ["happy", "joy", "excited", "delighted", "pleased", "glad", "cheerful"],
            "sad": ["sad", "unhappy", "depressed", "down", "blue", "gloomy", "miserable"],
            "angry": ["angry", "mad", "furious", "annoyed", "irritated", "frustrated"],
            "afraid": ["afraid", "scared", "fearful", "terrified", "anxious", "worried", "nervous"],
            "surprised": ["surprised", "shocked", "amazed", "astonished", "stunned"],
            "disgusted": ["disgusted", "revolted", "repulsed", "sickened"],
            "confused": ["confused", "puzzled", "perplexed", "bewildered", "uncertain"]
        }

        text_lower = text.lower()
        for emotion, keywords in emotion_keywords.items():
            if any(keyword in text_lower for keyword in keywords):
                return emotion

        return None

    def _extract_topics_from_text(self, text: str) -> List[str]:
        """Extract key topics from text using simple keyword extraction."""
        # Remove common stop words
        stop_words = {"a", "an", "the", "and", "or", "but", "is", "are", "was", "were",
                     "in", "on", "at", "to", "for", "with", "by", "about", "like",
                     "from", "of", "that", "this", "these", "those", "it", "its"}

        # Extract words, remove punctuation, and filter out stop words
        words = re.findall(r'\b\w+\b', text.lower())
        filtered_words = [word for word in words if word not in stop_words and len(word) > 3]

        # Count word frequencies
        word_counts = {}
        for word in filtered_words:
            word_counts[word] = word_counts.get(word, 0) + 1

        # Get top topics (words with highest frequency)
        sorted_words = sorted(word_counts.items(), key=lambda x: x[1], reverse=True)
        topics = [word for word, _ in sorted_words[:5]]  # Take top 5 words as topics

        return topics

    def _is_factual_question(self, text: str) -> bool:
        """Determine if text contains a factual question."""
        factual_patterns = [
            r'\b(when|what time|what date|where|how many|how much|who|which)\b',
            r'\bdo you remember\b.*\?',
            r'\bcan you recall\b.*\?',
            r'\bwhat did I\b.*\?',
            r'\bwhere did we\b.*\?',
            r'\bwhen did\b.*\?'
        ]

        for pattern in factual_patterns:
            if re.search(pattern, text.lower()):
                return True

        return False

    def _get_recent_conversation_context(self, user_id: str) -> Optional[str]:
        """Get recent conversation context from the database."""
        if not self.db_manager:
            return None

        try:
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    f"""
                    SELECT content FROM {config.chat_table_name}
                    WHERE user_id = ?
                    ORDER BY timestamp DESC
                    LIMIT 5
                    """,
                    (user_id,)
                )
                messages = cursor.fetchall()

                if messages:
                    return " ".join([dict(msg)['content'] for msg in messages])

                return None
        except Exception as e:
            logging.warning(f"Error getting recent conversation context: {e}")
            return None

    def _get_emotion_intensity(self, emotion: str) -> float:
        """Get the intensity score for an emotion."""
        high_intensity_emotions = {"furious", "ecstatic", "terrified", "devastated", "overjoyed"}
        medium_intensity_emotions = {"angry", "happy", "scared", "sad", "excited"}

        emotion_lower = emotion.lower()

        if emotion_lower in high_intensity_emotions:
            return 0.9
        elif emotion_lower in medium_intensity_emotions:
            return 0.6
        else:
            return 0.3

    def _contains_factual_information(self, text: str) -> bool:
        """Check if text contains factual information like dates, numbers, names, etc."""
        # Check for dates
        date_patterns = [
            r'\b\d{1,2}/\d{1,2}/\d{2,4}\b',  # MM/DD/YYYY
            r'\b\d{1,2}-\d{1,2}-\d{2,4}\b',  # MM-DD-YYYY
            r'\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]* \d{1,2}(st|nd|rd|th)?,? \d{2,4}\b',  # Month Day, Year
            r'\b\d{1,2}(st|nd|rd|th)? of (Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*,? \d{2,4}\b'  # Day of Month, Year
        ]

        # Check for numbers
        number_patterns = [
            r'\b\d+\b',  # Any number
            r'\b\d+\.\d+\b'  # Decimal numbers
        ]

        # Check for proper nouns (simplified)
        proper_noun_pattern = r'\b[A-Z][a-z]+\b'

        # Check for factual statements
        factual_patterns = [
            r'\bis\b',
            r'\bwas\b',
            r'\bwere\b',
            r'\bhappened\b',
            r'\boccurred\b'
        ]

        # Check all patterns
        for pattern_list in [date_patterns, number_patterns, [proper_noun_pattern], factual_patterns]:
            for pattern in pattern_list:
                if re.search(pattern, text):
                    return True

        return False

    def _is_related_to_context(self, memory_text: str, context: str) -> bool:
        """Check if memory is related to recent conversation context."""
        # Simple word overlap check
        memory_words = set(re.findall(r'\b\w+\b', memory_text.lower()))
        context_words = set(re.findall(r'\b\w+\b', context.lower()))

        # Calculate Jaccard similarity
        if not memory_words or not context_words:
            return False

        intersection = memory_words.intersection(context_words)
        union = memory_words.union(context_words)

        similarity = len(intersection) / len(union)

        return similarity > 0.1  # Threshold for relatedness

    def _keyword_based_memory_fallback(self, user_id: str, current_text: str, max_results: int = 5) -> List[Dict]:
        """
        Keyword-based fallback for finding memories when semantic search misses details.
        This helps catch specific facts and details that might not be semantically similar.
        """
        if not self.db_manager:
            return []

        # Extract keywords from current text
        keywords = self._extract_keywords(current_text)
        if not keywords:
            return []

        memories = []
        try:
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()

                # Search for memories containing any of the keywords
                for keyword in keywords[:5]:  # Limit to top 5 keywords
                    sql = f"""SELECT id, text, emotion, importance, timestamp, memory_type, access_count
                             FROM {config.memory_table_name}
                             WHERE user_id = ? AND text LIKE ?
                             ORDER BY importance DESC, timestamp DESC
                             LIMIT ?"""

                    cursor.execute(sql, (user_id, f"%{keyword}%", max_results))
                    results = cursor.fetchall()

                    for row in results:
                        memory_dict = dict(row)
                        if memory_dict not in memories:  # Avoid duplicates
                            memories.append(memory_dict)

                    if len(memories) >= max_results:
                        break

        except Exception as e:
            logging.error(f"Error in keyword-based memory fallback for user '{user_id}': {e}")

        return memories[:max_results]

    def _extract_keywords(self, text: str) -> List[str]:
        """Extract meaningful keywords from text for memory search."""
        # Remove common stop words and extract meaningful terms
        stop_words = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by', 'is', 'are', 'was', 'were', 'be', 'been', 'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could', 'should', 'may', 'might', 'can', 'this', 'that', 'these', 'those', 'i', 'you', 'he', 'she', 'it', 'we', 'they', 'me', 'him', 'her', 'us', 'them', 'my', 'your', 'his', 'her', 'its', 'our', 'their'}

        # Extract words, filter stop words, and prioritize longer words
        words = re.findall(r'\b\w+\b', text.lower())
        keywords = [word for word in words if word not in stop_words and len(word) > 2]

        # Sort by length (longer words are often more specific)
        keywords.sort(key=len, reverse=True)

        return keywords[:10]  # Return top 10 keywords

    def construct_memory_context_string(self, user_id: str, current_text: str) -> str:
        """
        Constructs a human-like memory context string for the LLM prompt.

        This formats memories in a way that mimics how humans naturally recall and relate memories:
        - More conversational and less structured
        - Includes emotional context and associations
        - Varies in detail based on memory importance
        - Includes "fuzziness" for older memories
        - Connects related memories in a natural way
        """
        memories = self.recall_related_memories(user_id, current_text)
        if not memories:
            return "I don't recall anything specific about that." # More human-like phrasing

        # Analyze memories for relationships and patterns
        causal_relationships = self._identify_causal_relationships_in_memories(memories)
        event_memories = self._identify_event_memories(memories)
        emotional_patterns = self._identify_emotional_patterns(memories)
        memory_clusters = self._identify_memory_clusters(memories)

        # Check if this is a factual question
        is_factual_query = self._is_factual_question(current_text)

        # Process memories with human-like recall patterns
        memory_phrases = []
        factual_answers = []

        # First, handle factual queries differently - be more direct and precise
        if is_factual_query:
            for mem in memories:
                if self._contains_factual_information(mem.get('text', '')):
                    # Format as a direct answer for factual questions
                    factual_text = mem.get('text', '').strip()
                    # Simplify to just the relevant part if possible
                    if len(factual_text.split()) > 15:
                        # Try to extract just the relevant fact
                        factual_text = self._extract_relevant_fact(factual_text, current_text)

                    factual_answers.append(f"You told me: {factual_text}")

            if factual_answers:
                return " | ".join(factual_answers)

        # For regular recall, use more natural language
        for i, mem in enumerate(memories):
            memory_id = mem.get('id')
            memory_text = mem.get('text', '')

            # Get time information in conversational format
            time_phrase = self._get_human_time_phrase(mem.get('timestamp'))

            # Get emotion in conversational format
            emotion_phrase = ""
            if memory_id in emotional_patterns:
                emotion_data = emotional_patterns[memory_id]
                emotion = emotion_data.get('emotion', 'neutral')
                intensity = emotion_data.get('intensity', 0.5)

                if emotion != 'neutral' and intensity > 0.6:
                    emotion_phrase = f" You seemed {emotion}."
                elif emotion != 'neutral':
                    emotion_phrase = f" You mentioned feeling {emotion}."

            # Format based on memory type
            memory_type = mem.get('memory_type', 'short_term')
            importance = mem.get('importance', 0.5)

            # Vary detail level based on importance and type
            if memory_type == 'long_term' or importance > 0.7:
                # Important memories get more detail
                detail_level = "high"
            elif importance > 0.4:
                detail_level = "medium"
            else:
                detail_level = "low"

            # Format the memory text based on detail level
            if detail_level == "high":
                # Keep most details for important memories
                formatted_text = memory_text
                if len(formatted_text.split()) > 30:
                    formatted_text = " ".join(formatted_text.split()[:30]) + "..."
            elif detail_level == "medium":
                # Summarize medium importance memories
                if len(memory_text.split()) > 20:
                    formatted_text = " ".join(memory_text.split()[:20]) + "..."
                else:
                    formatted_text = memory_text
            else:
                # Be vague about low importance memories
                if len(memory_text.split()) > 10:
                    formatted_text = " ".join(memory_text.split()[:10]) + "..."
                else:
                    formatted_text = memory_text

            # Add "fuzziness" to older memories
            seconds_elapsed = time_since(mem.get('timestamp')) if mem.get('timestamp') else float('inf')
            days_elapsed = seconds_elapsed / 86400

            if days_elapsed > 30 and memory_type != 'long_term':
                # Add uncertainty markers for older memories
                memory_phrase = f"I think I remember you mentioning {formatted_text}{emotion_phrase} {time_phrase}"
            elif days_elapsed > 7:
                memory_phrase = f"You told me {formatted_text}{emotion_phrase} {time_phrase}"
            else:
                memory_phrase = f"You said {formatted_text}{emotion_phrase} {time_phrase}"

            # Add associative connections between memories
            if i > 0 and memory_clusters:
                # Check if this memory is in the same cluster as the previous one
                for cluster in memory_clusters:
                    if memory_id in cluster.get('memory_ids', []) and memories[i-1].get('id') in cluster.get('memory_ids', []):
                        # Add a connecting phrase
                        memory_phrase = f"Related to that, {memory_phrase}"
                        break

            memory_phrases.append(memory_phrase)

        # Combine memories in a conversational way
        if len(memory_phrases) == 1:
            return memory_phrases[0]
        elif len(memory_phrases) == 2:
            return f"{memory_phrases[0]}. Also, {memory_phrases[1]}."
        else:
            # For multiple memories, structure them more naturally
            result = f"{memory_phrases[0]}. "
            for i in range(1, len(memory_phrases) - 1):
                result += f"{memory_phrases[i]}. "
            result += f"And {memory_phrases[-1]}."

            return result


    def update_memory_from_feedback(self, user_id: str, assistant_chat_log_id: int, feedback_rating: int):
        """Updates the importance score of a memory based on feedback on the assistant's response."""
        if not self.db_manager:
            logging.warning("DB Manager not available, cannot update memory importance from feedback.")
            return

        logging.info(f"Updating memory importance based on feedback for assistant log ID {assistant_chat_log_id}, rating {feedback_rating}")

        # 1. Find the user message that prompted this assistant response
        user_log_id = self.db_manager.get_user_message_id_for_assistant_response(assistant_chat_log_id)
        if not user_log_id:
            logging.warning(f"Could not find originating user message for assistant log ID {assistant_chat_log_id}. Cannot link feedback to memory.")
            return

        # 2. Find the memory entry associated with that user message
        memory_id = self.db_manager.get_memory_id_for_chat_log(user_log_id)
        if not memory_id:
            logging.info(f"No specific memory entry found linked to user chat log ID {user_log_id}. Feedback not applied to memory importance.")
            return

        # 3. Determine the importance change
        importance_change = config.memory_feedback_boost if feedback_rating > 0 else -config.memory_feedback_boost

        # 4. Update Importance in DB
        try:
             self.db_manager.update_memory_importance(memory_id, importance_change)
        except Exception as db_e:
             logging.error(f"Failed to update memory importance in DB for memory ID {memory_id}: {db_e}")
             # Continue to attempt in-memory update

        # 5. Update Importance in In-Memory Store
        if user_id in self.memory_store:
            updated_in_memory = False
            # Find the memory entry in the list by its DB ID ('id')
            for mem_entry in self.memory_store[user_id]:
                if mem_entry.get('id') == memory_id:
                    try:
                        old_importance = mem_entry['importance']
                        # Apply change and clamp between 0.05 and 1.0 (consistent lower bound)
                        new_importance = np.clip(old_importance + importance_change, 0.05, 1.0)
                        mem_entry['importance'] = new_importance
                        logging.info(f"Updated in-memory importance for memory ID {memory_id} from {old_importance:.2f} to {new_importance:.2f}")

                        # Check if this memory should be promoted to long-term based on positive feedback
                        if feedback_rating > 0 and mem_entry.get('memory_type') == 'short_term' and new_importance >= config.memory_long_term_promotion_threshold:
                            self._promote_to_long_term_memory(user_id, memory_id, mem_entry)

                        updated_in_memory = True
                        break # Found and updated
                    except KeyError:
                         logging.warning(f"Memory entry with ID {memory_id} missing 'importance' key in memory store.")
                    except Exception as mem_e:
                         logging.error(f"Failed to update in-memory importance for ID {memory_id}: {mem_e}")
            if not updated_in_memory:
                 logging.warning(f"Could not find memory entry with DB ID {memory_id} in user {user_id}'s in-memory store to update importance (maybe not loaded yet?).")
        else:
            logging.debug(f"User {user_id} not in memory store, skipping in-memory importance update.")

    def _promote_to_long_term_memory(self, user_id: str, memory_id: int, memory_entry: Dict):
        """Promotes a short-term memory to long-term memory based on importance and access patterns."""
        if not self.db_manager:
            logging.warning("DB Manager not available, cannot promote memory to long-term.")
            return

        logging.info(f"Promoting memory ID {memory_id} to long-term for user '{user_id}'")

        try:
            # Update in database
            sql = f"UPDATE `{config.memory_table_name}` SET `memory_type` = 'long_term' WHERE `id` = ?"
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(sql, (memory_id,))
                if cursor.rowcount > 0:
                    # Update in-memory entry
                    memory_entry['memory_type'] = 'long_term'
                    logging.info(f"Successfully promoted memory ID {memory_id} to long-term memory")
                else:
                    logging.warning(f"Failed to promote memory ID {memory_id} to long-term (no rows affected)")
        except Exception as e:
            logging.error(f"Error promoting memory ID {memory_id} to long-term: {e}")

    def consolidate_memories(self, user_id: str, max_short_term_memories: int = None):
        """Consolidates memories by promoting important short-term memories to long-term and pruning less important ones.
        If max_short_term_memories is not provided, uses the value from config.

        Enhanced with contextual analysis to identify related memories and causal relationships.
        """
        if not self.db_manager:
            logging.warning("DB Manager not available, cannot consolidate memories.")
            return

        # Use config value if not provided
        if max_short_term_memories is None:
            max_short_term_memories = config.max_short_term_memories

        logging.info(f"Consolidating memories for user '{user_id}' (max_short_term: {max_short_term_memories})")

        try:
            # 1. Get all short-term memories for the user with more data for contextual analysis
            sql_count = f"SELECT COUNT(*) FROM `{config.memory_table_name}` WHERE `user_id` = ? AND `memory_type` = 'short_term'"
            sql_get = f"""SELECT `id`, `importance`, `access_count`, `text`, `timestamp`, `emotion`
                       FROM `{config.memory_table_name}`
                       WHERE `user_id` = ? AND `memory_type` = 'short_term'
                       ORDER BY `timestamp` ASC"""

            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()

                # Check if we need to consolidate
                cursor.execute(sql_count, (user_id,))
                short_term_count = cursor.fetchone()[0]

                if short_term_count <= max_short_term_memories:
                    logging.info(f"No need to consolidate memories for user '{user_id}'. Short-term count: {short_term_count}")
                    return

                # Get all short-term memories
                cursor.execute(sql_get, (user_id,))
                memories = [dict(row) for row in cursor.fetchall()]

                # Calculate how many to process
                excess_count = short_term_count - max_short_term_memories
                logging.info(f"Need to process {excess_count} memories for user '{user_id}'")

                # 2. Perform contextual analysis to identify related memories
                memory_clusters = self._identify_memory_clusters(memories)
                causal_relationships = self._identify_causal_relationships_in_memories(memories)
                event_memories = self._identify_event_memories(memories)
                emotional_patterns = self._identify_emotional_patterns(memories)

                # 3. Identify memories to promote or prune based on enhanced analysis
                memories_to_promote = []
                memories_to_prune = []
                memories_to_enhance = []

                for memory in memories:
                    memory_id = memory['id']
                    importance = memory['importance']
                    access_count = memory['access_count']
                    # memory_text not used in this function

                    # Base promotion criteria
                    should_promote = False
                    should_prune = False

                    # Standard criteria
                    if importance >= config.memory_long_term_promotion_threshold or access_count >= 5:
                        should_promote = True
                    elif importance <= 0.2 and access_count <= 2:
                        should_prune = True

                    # Enhanced contextual criteria

                    # 1. Promote memories that are part of causal relationships
                    if memory_id in causal_relationships:
                        should_promote = True
                        logging.debug(f"Memory ID {memory_id} promoted due to causal relationship: {causal_relationships[memory_id]}")

                    # 2. Promote memories about events (especially future events)
                    if memory_id in event_memories:
                        event_info = event_memories[memory_id]
                        if event_info.get('is_future_event', False):
                            should_promote = True
                            logging.debug(f"Memory ID {memory_id} promoted as future event: {event_info.get('event_type')}")

                            # Also enhance the memory with additional context
                            memories_to_enhance.append((memory_id, {'event_type': event_info.get('event_type')}))

                    # 3. Consider emotional significance
                    if memory_id in emotional_patterns and emotional_patterns[memory_id].get('intensity', 0) > 0.7:
                        should_promote = True
                        logging.debug(f"Memory ID {memory_id} promoted due to emotional significance")

                    # 4. Preserve memories in important clusters
                    for cluster in memory_clusters:
                        if memory_id in cluster['memory_ids'] and cluster['importance'] > 0.6:
                            should_promote = True
                            should_prune = False  # Override pruning decision
                            logging.debug(f"Memory ID {memory_id} preserved as part of important memory cluster")
                            break

                    # Final decision
                    if should_promote:
                        memories_to_promote.append(memory_id)
                    elif should_prune:
                        memories_to_prune.append(memory_id)

                    # Stop once we've processed enough memories
                    if len(memories_to_promote) + len(memories_to_prune) >= excess_count:
                        break

                # 4. Promote memories to long-term with enhanced metadata
                if memories_to_promote:
                    # Basic promotion
                    promote_sql = f"UPDATE `{config.memory_table_name}` SET `memory_type` = 'long_term' WHERE `id` IN ({','.join(['?'] * len(memories_to_promote))})"
                    cursor.execute(promote_sql, memories_to_promote)
                    logging.info(f"Promoted {cursor.rowcount} memories to long-term for user '{user_id}'")

                    # Add enhanced metadata for specific memories
                    for memory_id, enhancements in memories_to_enhance:
                        if 'event_type' in enhancements:
                            # Add event type metadata
                            meta_sql = f"UPDATE `{config.memory_table_name}` SET `metadata` = JSON_SET(COALESCE(`metadata`, '{{}}'), '$.event_type', ?) WHERE `id` = ?"
                            cursor.execute(meta_sql, (enhancements['event_type'], memory_id))

                # 5. Prune least important memories if needed
                if memories_to_prune and (len(memories_to_promote) < excess_count):
                    prune_sql = f"DELETE FROM `{config.memory_table_name}` WHERE `id` IN ({','.join(['?'] * len(memories_to_prune))})"
                    cursor.execute(prune_sql, memories_to_prune)
                    logging.info(f"Pruned {cursor.rowcount} low-importance memories for user '{user_id}'")

                # 6. Update in-memory store if needed
                if user_id in self.memory_store and (memories_to_promote or memories_to_prune):
                    # Update memory type for promoted memories
                    for mem_entry in self.memory_store[user_id]:
                        if mem_entry.get('id') in memories_to_promote:
                            mem_entry['memory_type'] = 'long_term'

                            # Add enhanced metadata if available
                            for memory_id, enhancements in memories_to_enhance:
                                if mem_entry.get('id') == memory_id:
                                    # Initialize metadata dict if needed
                                    if 'metadata' not in mem_entry:
                                        mem_entry['metadata'] = {}
                                    # Add enhancements
                                    mem_entry['metadata'].update(enhancements)

                    # Remove pruned memories from in-memory store
                    self.memory_store[user_id] = [mem for mem in self.memory_store[user_id] if mem.get('id') not in memories_to_prune]

                    # Rebuild FAISS index if needed
                    if memories_to_prune and user_id in self.faiss_indices:
                        logging.info(f"Rebuilding FAISS index for user '{user_id}' after memory pruning")
                        self._load_and_index_user_memories(user_id)

        except Exception as e:
            logging.error(f"Error during memory consolidation for user '{user_id}': {e}")

    def reinforce_important_details(self, user_id: str):
        """
        Proactively reinforces important personal details and facts by promoting them
        to long-term memory and increasing their importance scores.
        """
        if not self.db_manager:
            return

        try:
            # Find micro-details and facts that have been accessed multiple times
            sql = f"""SELECT id, text, importance, access_count, memory_type
                     FROM {config.memory_table_name}
                     WHERE user_id = ? AND memory_type IN ('micro_detail', 'factual')
                     AND access_count >= 2 AND importance < 0.8
                     ORDER BY access_count DESC, importance DESC
                     LIMIT 10"""

            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(sql, (user_id,))
                candidates_rows = cursor.fetchall()

                for candidate_row in candidates_rows:
                    candidate = dict(candidate_row)
                    memory_id = candidate['id']
                    current_importance = candidate['importance']
                    access_count = candidate['access_count']

                    # Calculate reinforcement boost based on access frequency
                    reinforcement_boost = min(0.3, access_count * 0.05)
                    new_importance = min(0.9, current_importance + reinforcement_boost)

                    # Promote to long-term if importance is high enough
                    new_type = 'long_term' if new_importance >= 0.7 else candidate['memory_type']

                    # Update the memory
                    update_sql = f"""UPDATE {config.memory_table_name}
                                   SET importance = ?, memory_type = ?
                                   WHERE id = ?"""
                    cursor.execute(update_sql, (new_importance, new_type, memory_id))

                    logging.info(f"Reinforced memory ID {memory_id} for user '{user_id}': importance {current_importance:.3f} -> {new_importance:.3f}, type -> {new_type}")

        except Exception as e:
            logging.error(f"Error during memory reinforcement for user '{user_id}': {e}")

    def _identify_memory_clusters(self, memories):
        """Identify clusters of related memories based on semantic similarity and temporal proximity."""
        clusters = []
        processed_ids = set()

        try:
            # Sort memories by timestamp
            sorted_memories = sorted(memories, key=lambda x: x.get('timestamp', ''), reverse=False)

            for i, memory in enumerate(sorted_memories):
                if memory['id'] in processed_ids:
                    continue

                # Start a new cluster
                cluster = {
                    'memory_ids': [memory['id']],
                    'central_memory': memory['id'],
                    'topic': '',
                    'importance': memory['importance'],
                    'start_time': memory.get('timestamp'),
                    'end_time': memory.get('timestamp')
                }
                processed_ids.add(memory['id'])

                # Find related memories
                memory_text = memory.get('text', '').lower()
                memory_words = set(re.findall(r'\b\w+\b', memory_text))

                for other_memory in sorted_memories:  # Removed unused enumerate index
                    if other_memory['id'] in processed_ids or other_memory['id'] == memory['id']:
                        continue

                    other_text = other_memory.get('text', '').lower()
                    other_words = set(re.findall(r'\b\w+\b', other_text))

                    # Calculate word overlap
                    if len(memory_words) > 0 and len(other_words) > 0:
                        overlap = len(memory_words.intersection(other_words)) / len(memory_words.union(other_words))

                        # Check for temporal proximity (within 24 hours)
                        time_proximity = False
                        if memory.get('timestamp') and other_memory.get('timestamp'):
                            try:
                                mem_time = datetime.fromisoformat(memory['timestamp'].replace('Z', '+00:00'))
                                other_time = datetime.fromisoformat(other_memory['timestamp'].replace('Z', '+00:00'))
                                time_diff = abs((mem_time - other_time).total_seconds())
                                time_proximity = time_diff < 86400  # 24 hours
                            except Exception:
                                pass

                        # Add to cluster if similar enough
                        if overlap > 0.3 or (overlap > 0.2 and time_proximity):
                            cluster['memory_ids'].append(other_memory['id'])
                            cluster['importance'] = max(cluster['importance'], other_memory['importance'])
                            processed_ids.add(other_memory['id'])

                            # Update cluster time range
                            if other_memory.get('timestamp'):
                                if not cluster['end_time'] or other_memory['timestamp'] > cluster['end_time']:
                                    cluster['end_time'] = other_memory['timestamp']

                # Extract topic from most common words
                all_words = []
                for mem_id in cluster['memory_ids']:
                    mem = next((m for m in memories if m['id'] == mem_id), None)
                    if mem and mem.get('text'):
                        all_words.extend(re.findall(r'\b\w+\b', mem.get('text', '').lower()))

                # Count word frequencies and exclude common stopwords
                stopwords = {'the', 'and', 'is', 'in', 'to', 'a', 'of', 'for', 'with', 'on', 'at', 'from', 'by', 'about', 'like', 'that', 'this'}
                word_counts = {}
                for word in all_words:
                    if word not in stopwords and len(word) > 2:
                        word_counts[word] = word_counts.get(word, 0) + 1

                # Get top words for topic
                top_words = sorted(word_counts.items(), key=lambda x: x[1], reverse=True)[:3]
                cluster['topic'] = ' '.join(word for word, _ in top_words)  # Using _ for unused count

                # Add cluster if it has at least 2 memories or is important
                if len(cluster['memory_ids']) >= 2 or cluster['importance'] > 0.5:
                    clusters.append(cluster)

            return clusters
        except Exception as e:
            logging.error(f"Error identifying memory clusters: {e}")
            return []

    def _identify_causal_relationships_in_memories(self, memories):
        """Identify potential causal relationships between memories."""
        causal_relationships = {}

        try:
            # Sort memories by timestamp
            sorted_memories = sorted(memories, key=lambda x: x.get('timestamp', ''), reverse=False)

            # Define causal patterns
            causal_patterns = [
                # Event -> Emotion patterns
                (r'\b(exam|test|presentation|deadline|interview)\b', r'\b(stress|worried|anxious|nervous)\b', "Event causing emotional state"),
                # Work -> Tiredness patterns
                (r'\b(work|project|paper|assignment)\b', r'\b(tired|exhausted|fatigue|sleep)\b', "Work causing tiredness"),
                # Social -> Emotion patterns
                (r'\b(friend|relationship|family|partner)\b', r'\b(happy|sad|angry|upset|excited)\b', "Social relationship affecting emotions"),
                # Health -> Wellbeing patterns
                (r'\b(sick|ill|health|doctor|hospital)\b', r'\b(better|worse|improving|recovery)\b', "Health condition progression"),
            ]

            # Check for causal relationships
            for i, memory1 in enumerate(sorted_memories):
                memory1_text = memory1.get('text', '').lower()
                memory1_id = memory1['id']

                for j, memory2 in enumerate(sorted_memories):
                    if i == j:
                        continue

                    memory2_text = memory2.get('text', '').lower()
                    memory2_id = memory2['id']

                    # Check temporal order (memory1 before memory2)
                    correct_order = True
                    if memory1.get('timestamp') and memory2.get('timestamp'):
                        try:
                            time1 = datetime.fromisoformat(memory1['timestamp'].replace('Z', '+00:00'))
                            time2 = datetime.fromisoformat(memory2['timestamp'].replace('Z', '+00:00'))
                            correct_order = time1 < time2
                        except Exception:
                            pass

                    if correct_order:
                        # Check each causal pattern
                        for cause_pattern, effect_pattern, explanation in causal_patterns:
                            # Check if earlier memory contains cause and later contains effect
                            if (re.search(cause_pattern, memory1_text) and
                                re.search(effect_pattern, memory2_text)):
                                # Record causal relationship
                                causal_relationships[memory1_id] = {
                                    'related_to': memory2_id,
                                    'relationship_type': 'cause',
                                    'explanation': explanation
                                }
                                causal_relationships[memory2_id] = {
                                    'related_to': memory1_id,
                                    'relationship_type': 'effect',
                                    'explanation': explanation
                                }

            return causal_relationships
        except Exception as e:
            logging.error(f"Error identifying causal relationships: {e}")
            return {}

    def _identify_event_memories(self, memories):
        """Identify memories about events, especially future events."""
        event_memories = {}

        try:
            # Event patterns
            event_types = {
                'exam': r'\b(exam|test|final|midterm)\b',
                'deadline': r'\b(deadline|due date|submission)\b',
                'meeting': r'\b(meeting|appointment|interview|session)\b',
                'social': r'\b(party|gathering|celebration|wedding|birthday)\b',
                'travel': r'\b(trip|travel|flight|journey|vacation)\b',
                'health': r'\b(doctor|appointment|checkup|treatment)\b'
            }

            # Date patterns
            future_date_pattern = r'\b(tomorrow|next|upcoming|soon|this week|this month|in \d+ days)\b'
            # Enhanced date patterns to catch more formats
            specific_date_pattern = r'\b\d{1,2}(st|nd|rd|th)?\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|january|february|march|april|may|june|july|august|september|october|november|december)\b'
            # Additional pattern for "month day" format (e.g., "april 25th")
            alt_date_pattern = r'\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{1,2}(st|nd|rd|th)?\b'

            current_date = datetime.now()

            for memory in memories:
                memory_text = memory.get('text', '').lower()
                memory_id = memory['id']

                # Check for event mentions
                for event_type, pattern in event_types.items():
                    if re.search(pattern, memory_text):
                        # Check if it's a future event
                        is_future = bool(re.search(future_date_pattern, memory_text))

                        # Check for specific date in both formats
                        date_match = re.search(specific_date_pattern, memory_text)
                        alt_match = re.search(alt_date_pattern, memory_text)
                        extracted_date = None

                        # Try standard format (day month)
                        if date_match:
                            date_str = date_match.group(0)
                            try:
                                # Simple date parsing - could be enhanced
                                for fmt in ['%d %b', '%d %B']:
                                    try:
                                        extracted_date = datetime.strptime(date_str, fmt)
                                        # Set year to current year
                                        extracted_date = extracted_date.replace(year=current_date.year)
                                        # If date is in the past but within a few months, assume next year
                                        if (extracted_date - current_date).total_seconds() < -7776000:  # 90 days
                                            extracted_date = extracted_date.replace(year=current_date.year + 1)
                                        break
                                    except ValueError:
                                        continue
                            except Exception as e:
                                logging.debug(f"Error parsing date '{date_str}': {e}")

                        # Try alternate format (month day)
                        elif alt_match:
                            date_str = alt_match.group(0)
                            try:
                                # Try different formats for month-first dates
                                for fmt in ['%b %d', '%B %d', '%b %dst', '%B %dst', '%b %dnd', '%B %dnd', '%b %drd', '%B %drd', '%b %dth', '%B %dth']:
                                    try:
                                        # Remove suffixes for parsing
                                        clean_date_str = re.sub(r'(\d+)(st|nd|rd|th)', r'\1', date_str)
                                        extracted_date = datetime.strptime(clean_date_str, fmt)
                                        # Set year to current year
                                        extracted_date = extracted_date.replace(year=current_date.year)
                                        # If date is in the past but within a few months, assume next year
                                        if (extracted_date - current_date).total_seconds() < -7776000:  # 90 days
                                            extracted_date = extracted_date.replace(year=current_date.year + 1)
                                        break
                                    except ValueError:
                                        continue
                            except Exception as e:
                                logging.debug(f"Error parsing alternate date format '{date_str}': {e}")

                        # Determine if future based on extracted date
                        if extracted_date and extracted_date > current_date:
                            is_future = True

                        event_memories[memory_id] = {
                            'event_type': event_type,
                            'is_future_event': is_future,
                            'extracted_date': extracted_date.isoformat() if extracted_date else None
                        }
                        break

            return event_memories
        except Exception as e:
            logging.error(f"Error identifying event memories: {e}")
            return {}

    def _identify_emotional_patterns(self, memories):
        """Identify emotional patterns in memories."""
        emotional_patterns = {}

        try:
            # Emotion intensity mapping
            emotion_intensity = {
                'joy': 0.8,
                'excitement': 0.9,
                'happiness': 0.7,
                'love': 0.9,
                'anger': 0.8,
                'frustration': 0.7,
                'sadness': 0.8,
                'grief': 0.9,
                'fear': 0.8,
                'anxiety': 0.8,
                'stress': 0.7,
                'surprise': 0.6,
                'confusion': 0.5,
                'disgust': 0.7,
                'shame': 0.8,
                'guilt': 0.8,
                'pride': 0.7,
                'gratitude': 0.7,
                'hope': 0.6,
                'disappointment': 0.7
            }

            # Emotion words pattern
            emotion_pattern = r'\b(happy|sad|angry|upset|excited|nervous|anxious|stressed|worried|scared|afraid|frustrated|annoyed|disappointed|proud|grateful|hopeful|confused|surprised|overwhelmed)\b'

            # Intensity modifiers
            intensity_modifiers = {
                'very': 0.3,
                'extremely': 0.5,
                'incredibly': 0.5,
                'really': 0.2,
                'so': 0.2,
                'quite': 0.1,
                'a bit': -0.1,
                'slightly': -0.2,
                'somewhat': -0.1
            }

            for memory in memories:
                memory_text = memory.get('text', '').lower()
                memory_id = memory['id']
                memory_emotion = memory.get('emotion', '').lower()

                # Check for emotion words in text
                emotion_matches = re.findall(emotion_pattern, memory_text)

                if emotion_matches or memory_emotion:
                    # Use the first matched emotion or the stored emotion
                    primary_emotion = emotion_matches[0] if emotion_matches else memory_emotion

                    # Calculate base intensity
                    base_intensity = emotion_intensity.get(primary_emotion, 0.5)

                    # Check for intensity modifiers
                    for modifier, adjustment in intensity_modifiers.items():
                        if re.search(r'\b' + modifier + r'\s+' + primary_emotion + r'\b', memory_text):
                            base_intensity += adjustment

                    # Ensure intensity is within bounds
                    final_intensity = max(0.1, min(1.0, base_intensity))

                    emotional_patterns[memory_id] = {
                        'emotion': primary_emotion,
                        'intensity': final_intensity,
                        'all_emotions': emotion_matches
                    }

            return emotional_patterns
        except Exception as e:
            logging.error(f"Error identifying emotional patterns: {e}")
            return {}

# === ADVANCED EMOTION ANALYZER (V4 - Robust) ===
class AdvancedEmotionAnalyzer:
    """
    Analyzes text for detailed emotions and overall sentiment using HF Transformers.
    Handles model loading errors and potential pipeline issues. V4.
    """
    def __init__(self, emotion_model_name=config.emotion_model_name, sentiment_model_name=config.sentiment_model_name):
        logging.info(f"Initializing AdvancedEmotionAnalyzer: E='{emotion_model_name}', S='{sentiment_model_name}'")
        self.emotion_pipeline = None
        self.sentiment_pipeline = None
        self.emotion_tokenizer = None
        self.sentiment_tokenizer = None
        self.emotion_model = None
        self.sentiment_model = None
        self.emotion_model_name = emotion_model_name
        self.sentiment_model_name = sentiment_model_name

        # Load Emotion Model/Pipeline
        try:
            self.emotion_tokenizer = AutoTokenizer.from_pretrained(emotion_model_name)
            self.emotion_model = AutoModelForSequenceClassification.from_pretrained(emotion_model_name)
            # Specify device if GPU available, fallback to CPU
            device = 0 if torch.cuda.is_available() else -1
            self.emotion_pipeline = pipeline("text-classification", model=self.emotion_model, tokenizer=self.emotion_tokenizer, top_k=None, device=device)
            logging.info(f"Emotion model loaded: {emotion_model_name} on device {'GPU' if device == 0 else 'CPU'}")
        except Exception as e_emo:
            logging.error(f"Failed to load emotion model ({emotion_model_name}): {e_emo}", exc_info=True)

        # Load Sentiment Model/Pipeline
        try:
            self.sentiment_tokenizer = AutoTokenizer.from_pretrained(sentiment_model_name)
            self.sentiment_model = AutoModelForSequenceClassification.from_pretrained(sentiment_model_name)
            device = 0 if torch.cuda.is_available() else -1
            self.sentiment_pipeline = pipeline("sentiment-analysis", model=self.sentiment_model, tokenizer=self.sentiment_tokenizer, device=device)
            logging.info(f"Sentiment model loaded: {sentiment_model_name} on device {'GPU' if device == 0 else 'CPU'}")
        except Exception as e_sent:
            logging.error(f"Failed to load sentiment model ({sentiment_model_name}): {e_sent}", exc_info=True)

        if not self.emotion_pipeline and not self.sentiment_pipeline:
             logging.critical("CRITICAL: Both emotion and sentiment models failed to load. Analysis unavailable.")
             # raise RuntimeError("Both emotion and sentiment models failed to load.") # Optional: Halt execution
        elif not self.emotion_pipeline:
             logging.warning("Emotion analysis pipeline failed to load. Emotion detection will be limited.")
        elif not self.sentiment_pipeline:
             logging.warning("Sentiment analysis pipeline failed to load. Sentiment detection will be limited.")

    def _get_max_length(self, tokenizer, default_max=512):
        """Safely gets model max length, clamping excessive values."""
        if not tokenizer: return default_max
        try:
            model_max = getattr(tokenizer, 'model_max_length', default_max)
            # Clamp potentially huge values reported by some models
            # Check the type and value before clamping
            if isinstance(model_max, (int, float)) and model_max > 4096: # Check if it's numeric first
                 logging.debug(f"Tokenizer reports excessive max_length ({model_max}). Clamping to 4096.")
                 return 4096
            elif isinstance(model_max, (int, float)):
                 # Return the smaller of model_max and a reasonable upper bound
                 return min(int(model_max), 4096)
            else:
                 logging.warning(f"Tokenizer reported non-numeric max_length ({type(model_max)}: {model_max}). Using default {default_max}.")
                 return default_max
        except Exception as e:
            logging.warning(f"Could not determine tokenizer max_length: {e}. Using default {default_max}.")
            return default_max


    def analyze(self, text: str) -> Dict[str, Any]:
        """Analyzes input text for emotions and sentiment, handling errors."""
        if not text or not text.strip():
            logging.debug("Received empty text for analysis, returning default.")
            return self._default_result()

        analysis_result = self._default_result()
        max_len_emo = self._get_max_length(self.emotion_tokenizer)
        max_len_sent = self._get_max_length(self.sentiment_tokenizer)
        # Use the minimum of the two for truncation before pipeline
        truncation_length = min(max_len_emo, max_len_sent)

        # Truncate smartly - avoid cutting mid-word if possible
        # This is a simple approximation, more complex logic could be used
        if len(text) > truncation_length * 1.2: # Add buffer before truncating
             truncated_text = text[:truncation_length]
             # Try to find last space within reasonable range
             last_space = truncated_text.rfind(' ', max(0, truncation_length - 50))
             if last_space != -1:
                  truncated_text = truncated_text[:last_space]
             logging.debug(f"Truncating input text to ~{len(truncated_text)} chars for analysis.")
        else:
             truncated_text = text

        # --- Emotion Analysis ---
        if self.emotion_pipeline:
            try:
                # Pass truncation=True to handle cases slightly over max_len
                with torch.no_grad(): # Inference optimization
                     emotion_output = self.emotion_pipeline(truncated_text, truncation=True, max_length=max_len_emo)

                # Emotion pipeline returns list of lists typically [[{'label': '...', 'score': ...}, ...]]
                if emotion_output and isinstance(emotion_output, list) and emotion_output[0] and isinstance(emotion_output[0], list):
                    # Sort all detected emotions by score
                    all_emotions = sorted(emotion_output[0], key=lambda x: x['score'], reverse=True)
                    if all_emotions:
                        analysis_result['primary_emotion'] = all_emotions[0]['label']
                        analysis_result['primary_score'] = float(all_emotions[0]['score']) # Ensure float
                        analysis_result['secondary_emotions'] = [{'label': e['label'], 'score': float(e['score'])} for e in all_emotions[1:4]]
                        analysis_result['all_emotion_scores'] = {e['label']: float(e['score']) for e in all_emotions}
                else:
                     logging.warning(f"Unexpected emotion output format: {emotion_output}")

            except Exception as e_pipe_emo:
                 logging.error(f"Error during emotion pipeline execution for model {self.emotion_model_name}: {e_pipe_emo}", exc_info=True)
                 # Keep default emotion results

        # --- Sentiment Analysis ---
        if self.sentiment_pipeline:
            try:
                 with torch.no_grad():
                      sentiment_output = self.sentiment_pipeline(truncated_text, truncation=True, max_length=max_len_sent)

                 # Sentiment pipeline returns list of dicts usually [{'label': '...', 'score': ...}]
                 if sentiment_output and isinstance(sentiment_output, list) and sentiment_output[0] and isinstance(sentiment_output[0], dict):
                     sentiment_result = sentiment_output[0]
                     label = sentiment_result.get('label', 'unknown').lower()
                     score = float(sentiment_result.get('score', 0.0))

                     # Map labels robustly (handle variations like 'positive', 'LABEL_1', etc.)
                     if 'positive' in label or label in ['pos', 'label_2']: # Common positive labels
                         analysis_result['sentiment'] = 'positive'
                     elif 'negative' in label or label in ['neg', 'label_0']: # Common negative labels
                         analysis_result['sentiment'] = 'negative'
                     elif 'neutral' in label or label in ['neu', 'label_1']: # Common neutral labels
                         analysis_result['sentiment'] = 'neutral'
                     else:
                         analysis_result['sentiment'] = 'unknown'
                         logging.warning(f"Unmapped sentiment label encountered: {label}")
                     analysis_result['sentiment_score'] = score
                 else:
                      logging.warning(f"Unexpected sentiment output format: {sentiment_output}")

            except OverflowError as oe_sent: # Catch specific error
                logging.error(f"OverflowError during sentiment pipeline execution (max_length={max_len_sent}) for model {self.sentiment_model_name}. Error: {oe_sent}", exc_info=False) # Less verbose stack
                analysis_result['sentiment'] = 'error'
                analysis_result['sentiment_score'] = 0.0
            except Exception as e_pipe_sent:
                logging.error(f"Error during sentiment pipeline execution for model {self.sentiment_model_name}: {e_pipe_sent}", exc_info=True)
                analysis_result['sentiment'] = 'error'
                analysis_result['sentiment_score'] = 0.0

        # --- Calculate Intensity ---
        if analysis_result['primary_score'] > 0:
            try:
                split_len = len(text.split()) # Use original text length for intensity
                # Log length factor - prevents tiny messages having high intensity solely due to high score
                log_length_factor = np.log1p(min(split_len, 150)) / np.log1p(150) # Normalize against ~150 words, capped
                # Intensity = base score modulated by length
                analysis_result['intensity'] = np.clip(analysis_result['primary_score'] * (0.5 + 0.5 * log_length_factor), 0.0, 1.0)
            except Exception as int_err:
                 logging.warning(f"Error calculating intensity: {int_err}")
                 analysis_result['intensity'] = analysis_result['primary_score'] # Fallback
        else:
            analysis_result['intensity'] = 0.0 # No primary emotion = no intensity

        analysis_result['analysis_timestamp'] = get_current_date_time_iso()
        logging.debug(f"Emotion Analysis Result: Sent={analysis_result['sentiment']}, Emo={analysis_result['primary_emotion']}, Score={analysis_result['primary_score']:.2f}, Intens={analysis_result['intensity']:.2f}")
        return analysis_result

    def _default_result(self) -> Dict[str, Any]:
         """Returns a standardized default dictionary for analysis results."""
         return {
             'primary_emotion': 'neutral',
             'primary_score': 0.0,
             'secondary_emotions': [],
             'all_emotion_scores': {},
             'sentiment': 'neutral',
             'sentiment_score': 0.0,
             'intensity': 0.0,
             'analysis_timestamp': get_current_date_time_iso()
         }


# === PERSONALITY ENGINE (V4 - uses Profile V4) ===
class PersonalityEngine:
    def __init__(self, base_persona_config: Dict, db_manager: DatabaseManager):
        self.db_manager = db_manager
        self.base_persona_config = base_persona_config
        self.baseline_traits = { k: float(v) for k, v in base_persona_config.get('adaptability', {}).items() }
        self.user_traits: Dict[str, Dict[str, float]] = {} # In-memory cache of adapted traits per user
        self.adaptation_rate = config.personality_adaptation_rate
        self.decay_rate = config.personality_decay_rate
        # Use a single instance of the analyzer, potentially passed in if needed elsewhere
        # self.emotion_analyzer = AdvancedEmotionAnalyzer() # Removed, likely not needed here directly
        logging.info(f"PersonalityEngine initialized with baseline traits: {self.baseline_traits}")

    def _get_user_traits(self, user_id: str) -> Dict[str, float]:
        """Loads or initializes traits for a specific user."""
        if user_id not in self.user_traits:
            # TODO: Load adapted traits from user profile DB if stored persistently
            # profile = self.db_manager.load_user_profile(user_id)
            # if profile and profile.get("adapted_traits_json"): try load...
            # For now, initialize from baseline
            self.user_traits[user_id] = self.baseline_traits.copy()
            logging.info(f"Initialized traits for user {user_id} from baseline.")
        return self.user_traits[user_id]

    def _save_user_traits(self, _user_id: str):
        """Placeholder for saving adapted traits to DB profile."""
        # TODO: Implement saving self.user_traits[_user_id] to a dedicated field
        # in the user profile (e.g., 'adapted_traits_json').
        # traits_to_save = self.user_traits.get(user_id)
        # if traits_to_save:
        #     self.db_manager.save_user_profile(user_id, {"adapted_traits_json": json.dumps(traits_to_save)})
        pass

    def adapt_from_feedback(self, user_id: str):
        """Adapts personality traits based on recent user feedback (ratings + comments)."""
        logging.debug(f"Adapting personality for user {user_id} based on feedback.")
        traits = self._get_user_traits(user_id)
        feedback_summary = self.db_manager.fetch_feedback_summary(user_id, time_window_days=30)

        adjustments = {trait: 0.0 for trait in traits}
        feedback_counts = {trait: 0 for trait in traits}
        # min_feedback_count_for_adaptation = 2 # Require at least N feedbacks to adapt strongly # Variable not used

        # Map feedback types to traits (can be more complex)
        feedback_to_trait_map = {
            'general': ['warmth', 'empathy'], # General feedback affects core traits
            'humor': ['humor'],
            'empathy': ['empathy', 'warmth'],
            'memory': [], # Memory feedback affects memory importance, not personality directly here
            # Add more mappings if needed
        }

        if feedback_summary:
            for feedback_type, summary_data in feedback_summary.items():
                relevant_traits = feedback_to_trait_map.get(feedback_type, [])
                if not relevant_traits or summary_data['count'] == 0:
                     continue

                # Analyze comment sentiment for modifier
                comment_sentiment_modifier = 1.0
                if summary_data.get('comments'):
                    # Simple sentiment average from comments
                    comment_sentiments = []
                    for comment in summary_data['comments']:
                        # Basic check, could use emotion_analyzer for more nuance
                        blob = TextBlob(comment)
                        comment_sentiments.append(blob.sentiment.polarity)
                    if comment_sentiments:
                         avg_sentiment = np.mean(comment_sentiments)
                         # Map sentiment polarity (-1 to 1) to modifier (e.g., 0.5 to 1.5)
                         comment_sentiment_modifier = np.clip(1.0 + avg_sentiment * 0.5, 0.5, 1.5)

                # Apply adjustment to relevant traits
                for trait in relevant_traits:
                    if trait in traits:
                        # Base adjustment: average rating * adaptation rate * log(count) * comment_modifier
                        base_adjustment = summary_data['average'] * self.adaptation_rate \
                                          * np.log1p(summary_data['count']) \
                                          * comment_sentiment_modifier
                        adjustments[trait] += base_adjustment
                        feedback_counts[trait] += summary_data['count'] # Track how much feedback influenced trait
                        logging.debug(f"Feedback '{feedback_type}' -> Trait '{trait}': N={summary_data['count']}, AvgRate={summary_data['average']:.2f}, CmtMod={comment_sentiment_modifier:.2f}, Adj={base_adjustment:.4f}")
        else:
             logging.debug(f"No recent feedback found for user {user_id}. Applying decay only.")

        # Apply adjustments and decay towards baseline
        updated = False
        for trait, baseline_value in self.baseline_traits.items():
             if trait in traits:
                current_value = traits[trait]
                adjustment = adjustments.get(trait, 0.0)
                new_value = current_value + adjustment
                decay_amount = 0.0

                # Apply decay more strongly if there was little or no recent feedback for this trait
                # Or decay less if there was positive feedback? Complex interaction.
                # Simple approach: always decay towards baseline, but maybe slow decay if feedback was positive?
                # For now, standard decay:
                decay_amount = (new_value - baseline_value) * self.decay_rate

                # Reduce decay slightly if there was positive feedback for the trait
                # Example: if adjustments[trait] > 0, decay_amount *= 0.5
                if adjustment > 0.01: # If there was some positive adjustment
                     decay_amount *= 0.5
                elif adjustment < -0.01: # If there was negative adjustment, decay normally or faster? Normal for now.
                     pass

                final_value = np.clip(new_value - decay_amount, 0.0, 1.0)

                if final_value != current_value:
                     traits[trait] = final_value
                     logging.info(f"Adapted trait '{trait}' for user {user_id}: {current_value:.3f} -> {final_value:.3f} (Adj: {adjustment:.3f}, Decay: {decay_amount:.3f})")
                     updated = True

        if updated:
             self._save_user_traits(user_id) # Save back to DB if implemented

    def adapt_from_interaction_style(self, user_id: str, user_style: Dict[str, float]):
        """Gently nudges bot's style traits towards analyzed user style."""
        if not user_style: return
        traits = self._get_user_traits(user_id)
        logging.debug(f"Adapting personality based on user {user_id} style: {user_style}")
        updated = False

        # Map user style metrics to bot traits
        style_to_trait_map = {
            'formality_score': 'formality', # Lower user formality -> lower bot formality
            'emoji_frequency': 'warmth', # Higher emoji use -> slightly increase warmth? (Weak link)
            'question_rate': 'curiosity', # Higher user question rate -> slightly increase bot curiosity?
        }
        mirroring_factor = config.user_style_mirroring_factor

        for style_key, trait_key in style_to_trait_map.items():
            if style_key in user_style and trait_key in traits:
                 user_value = user_style[style_key]
                 bot_value = traits[trait_key]
                 adjustment_direction = 0

                 # Determine adjustment direction based on mapping
                 if trait_key == 'formality':
                      # Inverse relationship: higher user formality -> higher bot formality
                      adjustment_direction = user_value - bot_value
                 elif trait_key == 'warmth':
                       # Positive relationship (weak): higher emoji -> slightly warmer target
                       # Scale user emoji frequency (0 to ~0.01) to trait scale (0 to 1)
                       target_warmth_from_emoji = np.clip(user_value * 50, 0.3, 0.9) # Map emoji freq to warmth range
                       adjustment_direction = target_warmth_from_emoji - bot_value
                 elif trait_key == 'curiosity':
                       # Positive relationship: higher user questions -> more curious target
                       target_curiosity_from_questions = np.clip(user_value * 1.5, 0.4, 0.9) # Map question rate
                       adjustment_direction = target_curiosity_from_questions - bot_value

                 # Apply gentle nudge
                 nudge = adjustment_direction * mirroring_factor
                 new_trait_value = np.clip(bot_value + nudge, 0.0, 1.0)

                 if abs(new_trait_value - bot_value) > 0.01: # Only update if change is significant
                      traits[trait_key] = new_trait_value
                      logging.info(f"Adapted trait '{trait_key}' for user {user_id} based on style '{style_key}': {bot_value:.3f} -> {new_trait_value:.3f}")
                      updated = True

        if updated:
            self._save_user_traits(user_id) # Save back to DB if implemented

    def get_current_personality(self, user_id: str) -> Dict[str, float]:
        """Gets the current adapted personality traits for the user."""
        # Ensure traits are loaded/initialized for the user first
        return self._get_user_traits(user_id).copy()

    def generate_style_parameters(self, user_id: str, relationship_stage: str, relationship_depth: float) -> Dict[str, Any]:
        """Generates dynamic style parameters based on adapted traits and relationship state."""
        traits = self._get_user_traits(user_id) # Get current adapted traits
        stage_params = RelationshipManager.get_stage_parameters_static(relationship_stage)

        # Depth influence (non-linear, stronger effect at higher depths)
        depth_influence = np.clip( (relationship_depth / 70.0)**1.5 , 0.1, 1.0) # Normalize and apply power

        # Blend adapted traits with stage defaults, influenced by depth
        # Trait has more influence as depth increases
        humor_level = traits.get('humor', 0.5) * depth_influence + stage_params['humor_level'] / 10.0 * (1 - depth_influence)
        empathy_level = traits.get('empathy', 0.8) * depth_influence + stage_params['empathy_level'] * (1 - depth_influence)
        formality = traits.get('formality', 0.3) # Use adapted formality directly (influenced by user style)

        # Probabilities based on traits and randomness
        use_emojis_prob = np.clip(traits.get('warmth', 0.7) * 0.8 - formality * 0.2 + random.uniform(-0.1, 0.1), 0.1, 0.9)
        use_slang_prob = np.clip((traits.get('humor', 0.5) * 0.5) * (1 - formality * 0.8) + random.uniform(-0.1, 0.1), 0.0, 0.5) # Reduced slang prob
        ask_followup_prob = np.clip(traits.get('curiosity', 0.6) * 0.7 + depth_influence * 0.2 + random.uniform(-0.1, 0.15), 0.2, 0.9)
        offer_support_prob = np.clip(traits.get('empathy', 0.8) * 0.6 + depth_influence * 0.1 + random.uniform(-0.05, 0.05), 0.1, 0.8)

        # Determine if slang should be used based on probability
        use_slang_flag = random.random() < use_slang_prob

        params = {
             'use_emojis': random.random() < use_emojis_prob,
             'use_slang': "Yes" if use_slang_flag else "No", # Pass flag to prompt
             'ask_followup_question': random.random() < ask_followup_prob, # LLM decides based on prompt
             'offer_support': random.random() < offer_support_prob, # LLM decides based on prompt
             'humor_level': int(round(np.clip(humor_level * 10, 0, 10))), # Scale back to 0-10
             'empathy_level': np.clip(empathy_level, 0.0, 1.0),
             # 'formality': np.clip(formality, 0.0, 1.0) # Formality implicitly used above, not needed directly by LLM if style is described
        }
        logging.debug(f"Generated style parameters for user {user_id}: {params}")
        return params


# === RELATIONSHIP MANAGER (V4 - Simplified profile interaction) ===
class RelationshipManager:
    STAGES = { (0, 10): "acquaintance", (10, 30): "casual friend", (30, 60): "friend", (60, 101): "close friend" } # Include 100+
    STAGE_PARAMETERS = {
        "acquaintance": {
            "humor_level": 3,
            "empathy_level": 0.5,
            "disclosure_level": 2,
            "proactivity": 0.2,
            "personal_topics": ["work", "weather", "general interests", "current events"],
            "communication_style": "polite and somewhat reserved",
            "vulnerability": "minimal"
        },
        "casual friend": {
            "humor_level": 5,
            "empathy_level": 0.7,
            "disclosure_level": 4,
            "proactivity": 0.4,
            "personal_topics": ["hobbies", "daily life", "preferences", "light personal challenges"],
            "communication_style": "relaxed but still mindful",
            "vulnerability": "occasional light sharing"
        },
        "friend": {
            "humor_level": 7,
            "empathy_level": 0.8,
            "disclosure_level": 6,
            "proactivity": 0.6,
            "personal_topics": ["personal values", "relationships", "aspirations", "struggles"],
            "communication_style": "comfortable and authentic",
            "vulnerability": "regular sharing of real feelings"
        },
        "close friend": {
            "humor_level": 8,
            "empathy_level": 0.9,
            "disclosure_level": 8,
            "proactivity": 0.8,
            "personal_topics": ["deep fears", "insecurities", "dreams", "personal growth", "family issues"],
            "communication_style": "very casual, sometimes messy, with inside jokes",
            "vulnerability": "deep sharing and mutual support"
        }
    }

    def __init__(self, database_manager: DatabaseManager):
        self.db_manager = database_manager
        logging.info("RelationshipManager initialized.")

    def update_relationship_depth(self, user_id: str, interaction_summary: Optional[Dict]):
        """Updates relationship depth based on interaction summary and time decay."""
        profile = self.db_manager.load_user_profile(user_id)
        if not profile:
            logging.error(f"Cannot update relationship depth: Profile not found for user {user_id}")
            return
        if not interaction_summary:
             logging.warning(f"No interaction summary provided for user {user_id}, applying decay only.")
             interaction_summary = {} # Use empty dict for safe gets below

        current_depth = profile.get('relationship_depth', 0.0)
        vulnerability_score = interaction_summary.get('vulnerability_score', 0.0)
        interaction_length = len(interaction_summary.get('summary', '').split()) # Rough length
        reciprocity_signal = interaction_summary.get('reciprocity_signal', False)

        # Time since last interaction (using last_active from profile)
        last_active_str = profile.get('last_active')
        # Use time_since utility which handles None and timezone
        seconds_since_last_active = time_since(last_active_str)
        days_since_last_active = seconds_since_last_active / 86400.0

        # --- Calculate Depth Increase Factors ---
        # More weight to vulnerability and reciprocity
        vulnerability_increase = vulnerability_score * config.relationship_vulnerability_factor * 1.5
        # Log scale for length, capped effect
        interaction_increase = np.log1p(min(interaction_length, 200) / 10.0) * config.relationship_interaction_factor
        reciprocity_increase = config.relationship_reciprocity_factor * 1.2 if reciprocity_signal else 0.0
        # Frequency/Consistency factors are complex - simplified approach:
        # Reward recent interaction slightly
        recent_interaction_boost = 0.01 if days_since_last_active < 1 else 0.0 # Small boost if interacted today

        depth_increase = (vulnerability_increase + interaction_increase + reciprocity_increase + recent_interaction_boost)

        # --- Calculate Decay Based on Inactivity ---
        decay = 0.0
        # Start decaying after 3 days, increase rate up to 30 days
        if days_since_last_active > 3:
            # Decay rate increases linearly up to day 30, then stays constant
            decay_factor = min(max(0, days_since_last_active - 3) / 27, 1.0) # Linear ramp from day 3 to 30
            # Base decay rate (e.g., 1% of current depth per decay factor unit)
            base_decay_rate = 0.02
            decay = current_depth * base_decay_rate * decay_factor

        # --- Update Depth ---
        new_depth = np.clip(current_depth + depth_increase - decay, 0.0, 100.0) # Clamp between 0 and 100

        update_data = {"relationship_depth": new_depth}
        self.db_manager.save_user_profile(user_id, update_data)

        logging.info(f"Updated relationship depth for user {user_id}: {current_depth:.2f} -> {new_depth:.2f} (Inc: {depth_increase:.3f} [Vuln:{vulnerability_increase:.3f}, Len:{interaction_increase:.3f}, Reci:{reciprocity_increase:.3f}], Decay: {decay:.3f} from {days_since_last_active:.1f} days inactive)")

    def get_relationship_stage_and_depth(self, user_id: str) -> Tuple[str, float]:
        """Gets the current relationship stage and depth from the profile."""
        profile = self.db_manager.load_user_profile(user_id)
        depth = profile.get('relationship_depth', 0.0) if profile else 0.0
        # Ensure depth is within bounds before checking stages
        depth = np.clip(depth, 0.0, 100.0) # Clamp between 0 and 100
        for (min_depth, max_depth), stage_name in self.STAGES.items():
            # Inclusive lower bound, exclusive upper bound (except last stage)
            if min_depth <= depth < max_depth:
                return stage_name, depth
        # If depth is exactly 100 or somehow exceeds max, return the highest stage
        if depth >= 60: return "close friend", depth # Should be caught by range [60, 101)
        return "acquaintance", depth # Default fallback

    @staticmethod
    def get_stage_parameters_static(stage_name: str) -> Dict:
        """Static method to get stage parameters without needing an instance."""
        return RelationshipManager.STAGE_PARAMETERS.get(stage_name, RelationshipManager.STAGE_PARAMETERS["acquaintance"])

# === CONVERSATIONAL FLOW MANAGER (V4 - Simpler, relies on Prompt) ===
class DynamicConversationManager:
    """Determines basic flow parameters, mainly for humanizer logic."""
    def __init__(self):
        logging.info("DynamicConversationManager initialized (flow primarily driven by LLM prompt).")

    def determine_flow_parameters(self, emotion_analysis: Dict, relationship_stage: str) -> Dict:
        """Determines parameters like pause count/probability for humanizer."""
        intensity = emotion_analysis.get('intensity', 0.0)
        sentiment = emotion_analysis.get('sentiment', 'neutral')

        # Determine base probability/count for pauses, interjections, fillers
        # These are SUGGESTIONS for the humanizer, the LLM might generate its own pauses.
        pause_count_humanizer = 0
        interjection_prob_humanizer = 0.0
        filler_prob_humanizer = 0.0

        if relationship_stage == "close friend":
            pause_count_humanizer = random.choices([0, 1, 2], weights=[0.3, 0.5, 0.2], k=1)[0]
            interjection_prob_humanizer = 0.4
            filler_prob_humanizer = 0.15 # Still sparse
        elif relationship_stage == "friend":
            pause_count_humanizer = random.choices([0, 1, 2], weights=[0.4, 0.5, 0.1], k=1)[0]
            interjection_prob_humanizer = 0.3
            filler_prob_humanizer = 0.1
        elif relationship_stage == "casual friend":
            pause_count_humanizer = random.choices([0, 1], weights=[0.6, 0.4], k=1)[0]
            interjection_prob_humanizer = 0.2
            filler_prob_humanizer = 0.05
        else: # Acquaintance
            pause_count_humanizer = random.choices([0, 1], weights=[0.8, 0.2], k=1)[0]
            interjection_prob_humanizer = 0.1
            filler_prob_humanizer = 0.02

        # Modulate based on emotion
        if sentiment == 'negative' and intensity > 0.6:
            pause_count_humanizer = max(pause_count_humanizer, 1) # Ensure at least one pause potential
            interjection_prob_humanizer *= 0.8 # Less likely to interrupt with interjections
        elif sentiment == 'positive' and intensity > 0.7:
             interjection_prob_humanizer *= 1.2 # Slightly more likely for interjections

        params = {
            'pause_count_humanizer': pause_count_humanizer,
            'add_interjection_prob_humanizer': np.clip(interjection_prob_humanizer, 0.0, 0.8),
            'use_filler_prob_humanizer': np.clip(filler_prob_humanizer, 0.0, 0.3),
        }
        logging.debug(f"Determined humanizer flow parameters: {params}")
        return params

# === EMPATHIC RESPONSE GENERATOR (V4 - Fallback Only) ===
class EmpathicResponseGenerator:
    """Generates fallback empathic phrases if LLM fails or seems inappropriate."""
    def __init__(self):
        self.empathy_map = config.empathy_statements # Keep map for reference/fallback
        logging.info("EmpathicResponseGenerator initialized (primarily provides fallback phrases).")

    def generate_empathic_phrase_fallback(self, emotion_analysis: Dict, relationship_stage: str, personality_traits: Dict) -> Optional[str]:
        """Generates a single fallback empathic phrase."""
        primary_emotion = emotion_analysis.get('primary_emotion','neutral')
        sentiment = emotion_analysis.get('sentiment','neutral')
        intensity = emotion_analysis.get('intensity',0.0)
        empathy_level = personality_traits.get('empathy', 0.7) # Use adapted empathy
        phrase = None

        # Prioritize validation for negative emotions
        if sentiment == 'negative' and intensity > 0.4:
             if empathy_level > 0.65 and relationship_stage != 'acquaintance':
                  # Combine validation + support for closer relationships
                  phrase = f"{random.choice(self.empathy_map['validate'])} {random.choice(self.empathy_map['support'])}"
             else:
                  # Simple validation for acquaintances or lower empathy level
                  phrase = random.choice(self.empathy_map['validate'])
        # Acknowledge strong positive emotions
        elif sentiment == 'positive' and intensity > 0.6:
             if relationship_stage != 'acquaintance':
                  phrase = random.choice(self.empathy_map['celebrate'])
             else:
                  phrase = random.choice(self.empathy_map['share_joy'])
        # Handle strong surprise
        elif primary_emotion == 'surprise' and intensity > 0.7:
             phrase = random.choice(["Oh wow!", "Really?!", "No way!", "Gosh!"])

        if phrase:
             logging.debug(f"Generated fallback empathic phrase: '{phrase}'")
             return phrase.strip()
        return None

# === NEWS FETCHER (V4 - Minor improvements) ===
class NewsFetcher:
    """Fetches news using Google Search with caching and basic filtering."""
    def __init__(self):
        self.cache: Dict[str, Tuple[datetime, List[str]]] = {}
        self.cache_duration: timedelta = timedelta(seconds=config.news_cache_duration_seconds)
        self.session = requests.Session()
        # More generic user agent
        self.session.headers.update({'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36'})
        logging.info("NewsFetcher initialized.")

    def _fetch_headlines(self, query: str, num_results: int = 3) -> List[str]:
        """Internal method to perform search and extract titles/fallbacks."""
        if search is None:
             logging.warning("Google Search library not available. Skipping news fetch.")
             return []

        logging.info(f"Fetching news for query: '{query}' (Num results: {num_results})")
        results_urls: List[str] = []
        try:
            # --- FIX 2: Removed tld argument ---
            # Fix for googlesearch API change - use num instead of num_results
            results_iterator = search(query, num=num_results, lang='en', safe='on', pause=random.uniform(1.5, 3.0))
            results_urls = list(results_iterator) if results_iterator else []
            time.sleep(0.5) # Small delay after list conversion

        except ImportError: # Should be caught by __init__ check but belt-and-suspenders
            logging.error("`googlesearch-python` library missing. News fetching disabled.")
            return []
        except TypeError as te:
             # This might catch other TypeErrors if the library changes again
             logging.error(f"TypeError during googlesearch for '{query}': {te}. Check library arguments.", exc_info=True)
             return []
        except Exception as e:
            # Catch potential rate limiting or other search errors
            logging.error(f"Error during googlesearch call for '{query}': {e}", exc_info=False) # Less verbose stack trace for common errors
            if "HTTP Error 429" in str(e):
                 logging.warning("Google Search rate limit likely hit. Consider longer pauses or fewer queries.")
            return []

        if not results_urls:
            logging.warning(f"No search results returned for query: '{query}'")
            return []

        headlines: List[str] = []
        max_headline_len = 100
        for url in results_urls:
            headline = None
            try:
                # Added verify=False cautiously for potential SSL issues, but prefer fixing root cause
                # response = self.session.get(url, timeout=6, allow_redirects=True, verify=False)
                response = self.session.get(url, timeout=6, allow_redirects=True)
                response.raise_for_status() # Check for HTTP errors
                content_type = response.headers.get('Content-Type', '').lower()

                # Basic check for HTML content
                if 'html' in content_type:
                    soup = BeautifulSoup(response.content, 'html.parser')
                    title_tag = soup.find('title')
                    if title_tag and title_tag.string:
                         raw_title = title_tag.string.strip()
                         # Clean up common title suffixes
                         cleaned_title = re.sub(r'\s*[-\|]\s*(?:News|Breaking News|.+?\.com|.+?\.in|Times of India|The Hindu|NDTV|.+? News).*$', '', raw_title, flags=re.IGNORECASE).strip()
                         headline = cleaned_title if cleaned_title else raw_title # Use raw if cleaning removed everything

                # Fallback if no title found
                if not headline:
                    try:
                        domain = url.split('/')[2].replace('www.', '')
                        last_part = url.split('/')[-1].replace('-', ' ').replace('_', ' ')
                        # Try to make fallback more readable
                        fallback_text = last_part if last_part and '.' not in last_part else domain
                        headline = f"{fallback_text[:max_headline_len-15]}... ({domain})"
                    except IndexError:
                        headline = f"Link: {url[:max_headline_len]}"

                if headline:
                    headlines.append(headline[:max_headline_len]) # Limit length

            except requests.exceptions.Timeout:
                 logging.warning(f"Timeout fetching title from {url}")
                 headlines.append(f"News Link (Timeout): {url.split('/')[2] if '//' in url else url [:max_headline_len]}")
            except requests.exceptions.RequestException as e:
                 logging.warning(f"Failed to fetch title from {url}: {e}")
                 domain = url.split('/')[2].replace('www.','') if '//' in url and len(url.split('/')) > 2 else url
                 headlines.append(f"News Link ({type(e).__name__}): {domain[:max_headline_len-20]}")
            except Exception as e_parse:
                 logging.warning(f"Error parsing content from {url}: {e_parse}", exc_info=False)
                 headlines.append(f"News Link (Parse Err): {url[:max_headline_len]}")

            time.sleep(random.uniform(0.2, 0.5)) # Small delay between requests

        logging.info(f"Processed {len(headlines)} potential headlines for '{query}'.")
        # Filter out generic/error-like headlines before returning
        filtered_headlines = [h for h in headlines if h and not any(err in h.lower() for err in ["link:", "timeout", "error", "news link", "just a moment"])]
        return filtered_headlines

    def get_news(self, query: str, num_results: int = 2) -> List[str]:
        """Gets news headlines for a query, using cache."""
        now = datetime.now(timezone.utc)
        cache_key = f"{query}_{num_results}"

        cached_data = self.cache.get(cache_key)
        if cached_data:
            timestamp, cached_results = cached_data
            # Ensure cached timestamp is timezone-aware
            if timestamp.tzinfo is None: timestamp = timestamp.replace(tzinfo=timezone.utc)

            if now - timestamp < self.cache_duration:
                logging.debug(f"Using cached news for query: '{query}'")
                return cached_results
            else:
                 logging.info(f"News cache expired for query: '{query}'")

        logging.info(f"Cache miss or expired for '{query}'. Fetching fresh news.")
        fresh_results = self._fetch_headlines(query, num_results)
        self.cache[cache_key] = (now, fresh_results) # Store with UTC timestamp
        return fresh_results

    def get_relevant_news_summary(self, interests: List[str]) -> str:
        """Constructs a concise news summary string for the LLM prompt."""
        if search is None: return "News fetching disabled."

        summary_parts = []
        processed_queries = set()
        max_interests_for_news = 2
        max_headlines_per_topic = 1
        max_total_headlines = 2

        def format_headlines(topic: str, headlines: List[str]) -> Optional[str]:
             if headlines:
                 # Capitalize topic, join headlines
                 return f"{topic.capitalize()}: {'; '.join(headlines)}"
             return None

        target_interests = [i for i in interests if i and isinstance(i, str)] # Clean interests

        # 1. Fetch interest-based news
        headlines_found = 0
        if target_interests:
            for interest in target_interests[:max_interests_for_news]:
                if headlines_found >= max_total_headlines: break
                query = f"{interest} news India headlines" # More specific query
                if interest and query not in processed_queries:
                    fetched_headlines = self.get_news(query, num_results=max_headlines_per_topic)
                    processed_queries.add(query)
                    if fetched_headlines:
                         formatted = format_headlines(interest, fetched_headlines[:max_headlines_per_topic])
                         if formatted:
                              summary_parts.append(formatted)
                              headlines_found += len(fetched_headlines[:max_headlines_per_topic])

        # 2. Fetch general news if not enough headlines or no interests
        if headlines_found < max_total_headlines:
            logging.info("Fetching general trending news.")
            general_query = "India trending news headlines" # Define the query for general news
            if general_query not in processed_queries:
                 needed = max_total_headlines - headlines_found
                 fetched_headlines = self.get_news(general_query, needed)
                 # --- FIX 3: Use general_query variable here ---
                 processed_queries.add(general_query)
                 if fetched_headlines:
                      formatted = format_headlines("Trending", fetched_headlines[:needed])
                      if formatted: summary_parts.append(formatted)

        # 3. Combine and format final summary
        if summary_parts:
            full_summary = " | ".join(summary_parts) # Use pipe separator
            # Limit overall length for prompt
            return "Recent News: " + full_summary[:200] + ("..." if len(full_summary) > 200 else "")

        return "No relevant news updates found right now."


# === FESTIVAL TRACKER (V4 - Use Timezone) ===
class FestivalTracker:
    def __init__(self):
        # Consider loading from a file/API for easier updates
        # Dates should ideally be stored consistently (e.g., YYYY-MM-DD)
        self.festivals = {
            # 2024 Examples (Update these!)
            "Ganesh Chaturthi": ("2024-09-07", "Hope you have a blessed Ganesh Chaturthi! Ganpati Bappa Morya! 🙏"),
            "Navaratri Start": ("2024-10-03", "Happy Navaratri! May these nine nights bring joy and energy. ✨"),
            "Dussehra": ("2024-10-12", "Happy Dussehra! Wishing you victory over challenges."),
            "Diwali": ("2024-11-01", "Happy Diwali! ✨ Hope your day is filled with light, joy, and prosperity!"),
            "Christmas": ("2024-12-25", "Merry Christmas! 🎄 Wishing you peace and joy."),
            # 2025 Examples (Add more!)
            "Makar Sankranti / Pongal": ("2025-01-14", "Happy Makar Sankranti and Pongal!"),
            "Republic Day (India)": ("2025-01-26", "Happy Republic Day! 🇮🇳"),
            "Holi": ("2025-03-14", "Happy Holi! Hope you have a colorful and fun day! 🎨"),
            # Eid dates are approximate, need better source
            "Eid al-Fitr (Approx)": ("2025-03-30", "Eid Mubarak! Wishing you peace and happiness."),
            "Independence Day (India)": ("2025-08-15", "Happy Independence Day! 🇮🇳"),
        }
        logging.info("FestivalTracker initialized (using static list).")
        self.today_cache = None
        self.cache_date = None

    def check_for_today(self) -> Optional[Tuple[str, str]]:
        """Checks if today matches any festival date, using local date."""
        # Get current date in local timezone (festivals usually observed locally)
        today = datetime.now().date() # Get only the date part
        today_str = today.strftime("%Y-%m-%d")

        # Cache check
        if self.cache_date == today:
            return self.today_cache

        # Check against festival list
        found_festival = None
        for name, (date_str, message) in self.festivals.items():
            if date_str == today_str:
                logging.info(f"Today is {name}!")
                found_festival = (name, message)
                break # Stop after finding the first match for the day

        # Update cache
        self.cache_date = today
        self.today_cache = found_festival
        return found_festival


# === MAIN CHAT MANAGER (V4 - Orchestrator) ===
class ChatManager:
    def __init__(self, config_obj: Config, db_manager_obj: DatabaseManager, auth_manager_obj: AuthenticationManager):
        self.config = config_obj
        self.db_manager = db_manager_obj
        self.auth_manager = auth_manager_obj
        # Instantiate managers
        self.emotion_analyzer = AdvancedEmotionAnalyzer()
        self.memory_manager = ContextualMemoryManager(db_manager=self.db_manager, load_from_db=True)
        self.knowledge_graph = KnowledgeGraphManager(db_manager=self.db_manager)
        self.personality_engine = PersonalityEngine(self.config.bot_persona, self.db_manager)
        self.relationship_manager = RelationshipManager(self.db_manager)
        self.conversation_flow_manager = DynamicConversationManager()
        self.empathy_generator = EmpathicResponseGenerator()
        self.news_fetcher = NewsFetcher()
        self.festival_tracker = FestivalTracker()

        # NEW: Time-awareness system for conversation timing patterns
        self.time_awareness = TimeAwarenessManager(self.db_manager)

        # NEW: Global knowledge layer for general world facts
        self.global_knowledge = GlobalKnowledgeManager(self.db_manager)

        # NEW: Intelligent interest tracking and world awareness
        self.interest_tracker = IntelligentInterestTracker(self.db_manager)

        # NEW: YouTube content management for personalized content sharing
        self.youtube_content_manager = YouTubeContentManager(self.db_manager)

        # Initialize Gemini Models with Safety Settings
        try:
             # Stricter safety for potentially sensitive companion AI
             safety_settings = [
                 {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
                 {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
                 # Use BLOCK_MEDIUM for safer interaction regarding sexual content
                 {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
                 {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"}
             ]
             # Configure generation options (e.g., temperature)
             self.generation_config = genai.types.GenerationConfig(
                  # candidate_count=1, # Default is 1
                  # stop_sequences=["\nUser:", "\nHuman:"], # Define stop sequences if needed
                  # max_output_tokens=1024, # Limit response length if necessary
                  temperature=0.75, # Balance creativity and coherence (TUNABLE)
                  top_p=0.95,       # Use top-p sampling (TUNABLE)
                  top_k=40          # Use top-k sampling (TUNABLE)
             )
             self.gemini_model = genai.GenerativeModel(
                 self.config.default_gemini_model,
                 safety_settings=safety_settings,
                 generation_config=self.generation_config
             )
             # Use slightly stricter safety for summarization if needed
             self.summarization_model = genai.GenerativeModel(
                 self.config.summarization_model_name,
                 safety_settings=safety_settings # Use same settings for now
                 # generation_config can be different for summarization if needed (e.g., lower temp)
             )
             logging.info(f"Gemini models initialized: Main='{self.config.default_gemini_model}', Summary='{self.config.summarization_model_name}' with safety/generation config.")
        except Exception as e:
             logging.critical(f"FATAL: Failed to initialize Gemini model(s): {e}", exc_info=True)
             raise RuntimeError(f"Could not initialize Gemini model(s): {e}")

        # Per-user state tracking (minimal, relies on DB mostly)
        self.last_joke_timestamp: Dict[str, datetime] = {} # Store last joke time per user
        # Store last message IDs for feedback linking
        self.user_sessions: Dict[str, Dict[str, Optional[int]]] = defaultdict(lambda: {
            'last_assistant_message_id': None,
            'last_user_message_id': None
            # last_interaction_time could be added if needed for session timeout etc.
        })
        logging.info("ChatManager initialized successfully (V4).")

    def _get_user_session(self, user_id: str) -> Dict[str, Optional[int]]:
         """Gets the session data for a user."""
         return self.user_sessions[user_id]

    def _update_user_session(self, user_id: str, data: Dict[str, Optional[int]]):
        """Updates the session data for a user."""
        session = self._get_user_session(user_id)
        session.update(data)

    # --- FIX 1: Corrected SQL Table Name and added f-string ---
    def _analyze_and_update_user_style(self, user_id: str, user_profile: Dict) -> None:
        """
        Periodically analyzes recent user messages to update style metrics in the profile.
        Triggers personality adaptation based on the updated style.
        """
        logging.debug(f"Checking if user style analysis is needed for {user_id}")

        if not user_id:
            logging.error("Cannot analyze user style: Invalid user_id")
            return

        # Check timing
        last_analysis_ts_str = user_profile.get('last_style_analysis_ts')
        analysis_interval_days = 3 # Analyze every 3 days, adjust as needed
        min_messages_for_analysis = self.config.user_style_analysis_message_count # Use config value

        # Determine if analysis is needed
        analyze_now = False
        if not last_analysis_ts_str:
            analyze_now = True # Always analyze if never done before
            logging.info(f"Initial user style analysis for {user_id}")
        else:
            try:
                seconds_since_last = time_since(last_analysis_ts_str)
                if seconds_since_last > analysis_interval_days * 86400:
                    analyze_now = True
                    logging.info(f"Scheduled user style analysis due for {user_id} (Last: {seconds_since_last / 86400:.1f} days ago)")
            except Exception as e:
                logging.warning(f"Could not parse last_style_analysis_ts '{last_analysis_ts_str}' for user {user_id}: {e}. Triggering analysis.")
                analyze_now = True

        if not analyze_now:
            logging.debug(f"Style analysis not due yet for {user_id}")
            return # Exit if not time to analyze

        # Fetch recent messages
        try:
            user_messages_content = []
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                fetch_limit = int(min_messages_for_analysis * 1.5)
                # --- FIX 1 applied here ---
                sql_fetch_user_msgs = f"""
                    SELECT content FROM `{config.chat_table_name}`
                    WHERE user_id = ? AND role = 'user'
                    ORDER BY timestamp DESC LIMIT ?
                """
                cursor.execute(sql_fetch_user_msgs, (user_id, fetch_limit))
                # Ensure content is not None before adding
                user_messages_content = [dict(row)['content'] for row in cursor.fetchall() if row and dict(row)['content']]
                logging.debug(f"Fetched {len(user_messages_content)} recent user messages for style analysis (User: {user_id})")

            if len(user_messages_content) < min_messages_for_analysis:
                logging.info(f"Insufficient user messages ({len(user_messages_content)}/{min_messages_for_analysis}) for style analysis (User: {user_id}). Will try later.")
                return

            # Analysis metrics
            metrics = {
                'total_words': 0,
                'total_chars': 0,
                'total_emojis': 0,
                'total_questions': 0,
                'formality_indicators': 0,
                'informality_indicators': 0
            }

            patterns = {
                'informal': re.compile(r"\b(lol|lmao|rofl|brb|btw|imo|imho|thx|u|ur|r)\b|(\w+n't\b)", re.IGNORECASE),
                'question': re.compile(r'\?\s*$'),
                'emoji': re.compile(r'[\U0001F300-\U0001FAFF]')
            }

            # Process each message
            for msg in user_messages_content:
                words = msg.split()
                num_words = len(words) # Store word count for reuse
                if num_words == 0: continue # Skip empty messages

                metrics['total_words'] += num_words
                metrics['total_chars'] += len(msg)
                metrics['total_emojis'] += len(patterns['emoji'].findall(msg))
                metrics['total_questions'] += bool(patterns['question'].search(msg))

                # Formality analysis
                avg_word_len = sum(len(w) for w in words) / num_words
                if avg_word_len > 5.5:
                    metrics['formality_indicators'] += 1

                informal_matches = len(patterns['informal'].findall(msg))
                if not informal_matches:
                    metrics['formality_indicators'] += 0.5
                else:
                    # Count each found group as one indicator
                    metrics['informality_indicators'] += informal_matches

            # Calculate final metrics
            message_count = len(user_messages_content)
            # Prevent division by zero if counts are zero
            avg_msg_length_calc = round(metrics['total_chars'] / message_count, 1) if message_count > 0 else 50.0
            emoji_frequency_calc = round((metrics['total_emojis'] / metrics['total_chars']) * 100, 3) if metrics['total_chars'] > 0 else 0.1
            question_rate_calc = round(metrics['total_questions'] / message_count, 2) if message_count > 0 else 0.2
            formality_denom = metrics['formality_indicators'] + metrics['informality_indicators']
            formality_score_calc = round(
                np.clip(metrics['formality_indicators'] / formality_denom if formality_denom > 0 else 0.5, 0.1, 0.9),
                2
            )

            style_update = {
                "avg_msg_length": avg_msg_length_calc,
                "emoji_frequency": emoji_frequency_calc,
                "question_rate": question_rate_calc,
                "formality_score": formality_score_calc,
                "last_style_analysis_ts": get_current_date_time_iso()
            }

            # Update DB and trigger adaptation
            self.db_manager.save_user_profile(user_id, style_update)
            self.personality_engine.adapt_from_interaction_style(user_id, style_update)
            logging.info(f"Updated style metrics for {user_id}: {style_update}")

        except sqlite3.Error as e_sql: # Catch specific DB errors
            logging.error(f"DB error during style analysis for {user_id}: {str(e_sql)}", exc_info=True)
        except Exception as e:
            logging.error(f"General error during style analysis for {user_id}: {str(e)}", exc_info=True)
    # --- End _analyze_and_update_user_style ---

    def _extract_and_update_profile_info(self, message: str, user_id: str, current_profile: Dict):
        """Extracts basic info like name from message if not already present in profile."""
        # Only attempt extraction if name is missing
        if not current_profile.get("name"):
            logging.debug(f"Attempting name extraction for user {user_id}")
            # Improved Regex (more flexible, handles potential titles, case insensitive start)
            patterns = [
                 r"(?:my\s+name\s+is|call\s+me|i'm|i\s+am)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\b", # Matches "My name is John Doe", "I'm Jane", "call me Alex"
                 r"\b(?:name|handle|nickname)\s*[:\-=>]\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\b" # Matches "Name: Bob"
            ]
            extracted_name = None
            for pattern in patterns:
                 match = re.search(pattern, message, re.IGNORECASE)
                 if match:
                      potential_name = match.group(1).strip().title()
                      # Basic validation (length, avoid single letters, avoid persona name)
                      if 2 < len(potential_name) <= 35 and len(potential_name.split()) <= 3 and potential_name.lower() != config.bot_persona['name'].lower():
                           extracted_name = potential_name
                           logging.info(f"Extracted potential name '{extracted_name}' for user {user_id} via regex pattern: {pattern}")
                           break # Use first valid match
                 if extracted_name: break

            if extracted_name:
                # Update in-memory profile immediately for current interaction
                current_profile["name"] = extracted_name
                try:
                     # Save *only* the name update to DB
                     self.db_manager.save_user_profile(user_id, {"name": extracted_name})
                     logging.info(f"Saved extracted name '{extracted_name}' to DB for user {user_id}.")
                except Exception as db_err:
                     logging.error(f"Failed to save extracted name to DB for user {user_id}: {db_err}")
            else:
                logging.debug(f"No valid name pattern matched in message for user {user_id}.")
        # Can add extraction for interests, location etc. similarly if needed

    def _handle_memory_command(self, text: str, user_id: str) -> Optional[str]:
        """
        Handles explicit memory commands from the user.
        Returns a response string if handled, None otherwise.
        """
        # Check for memory commands
        remember_patterns = [
            r"(?:please\s+)?remember\s+(?:that\s+)?([^\?]+)",
            r"(?:please\s+)?don't\s+forget\s+(?:that\s+)?([^\?]+)",
            r"(?:please\s+)?make\s+(?:a\s+)?(?:note|memory)\s+(?:that\s+)?([^\?]+)"
        ]

        for pattern in remember_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                memory_text = match.group(1).strip()
                if memory_text:
                    # Create a long-term memory
                    success = self.memory_manager.create_long_term_memory(user_id, memory_text)
                    if success:
                        return f"I'll remember that {memory_text}. I've stored this as an important long-term memory."
                    else:
                        return "I tried to remember that, but encountered an issue. Please try again later."

        return None

    def _handle_special_cases(self, text: str, history: List[Dict], user_id: str, emotion_analysis: Dict) -> Optional[str]:
        """
        Handles specific inputs like AI detection, distress, inappropriate requests.
        Returns the special response string if handled, otherwise None.
        """
        lower_text = text.lower().strip()
        response = None

        # 1. AI Detection (More nuanced)
        is_ai_mention = any(keyword in f" {lower_text} " for keyword in self.config.ai_detection_keywords)
        if is_ai_mention:
             is_direct_accusation = re.search(r'\b(are you|you are|ur|u r|ur)\b.*\b(ai|bot|program|simulation|model|code|llm)\b', lower_text)
             is_curiosity = re.search(r'\b(what|how)\b.*\b(ai|bot|program|model|llm)\b', lower_text) or "tell me about yourself" in lower_text

             if is_direct_accusation and not is_curiosity:
                 response = random.choice(self.config.evasive_responses + self.config.philosophical_responses)
                 logging.info(f"AI detection triggered (accusation) for user {user_id}. Responding evasively/philosophically.")
             elif is_curiosity:
                  response = random.choice([
                       "That's interesting stuff to think about! But I'd rather focus on our chat right now. 😊 What's on your mind?",
                       "Haha, the technical details are less exciting than chatting with you! How's your day going?",
                       "I'm just Mandy! Here to chat and be a friend. Let's talk about you!"
                  ])
                  logging.info(f"AI detection triggered (curiosity) for user {user_id}. Responding evasively.")
             # else: subtle mention, ignore for now unless it becomes persistent

        # 2. Distress Detection (Keywords + High Intensity Sentiment)
        distress_keywords = ["kill myself", "take my life", "want to die", "end it all", "suicide", "can't go on anymore", "no reason to live", "really want to hurt myself"]
        contains_distress_keyword = any(keyword in lower_text for keyword in distress_keywords)
        # Check for high intensity negative emotion OR specific keyword
        is_high_distress_signal = (contains_distress_keyword or \
                                  (emotion_analysis.get('sentiment') == 'negative' and emotion_analysis.get('intensity', 0.0) > 0.85 and 'hopeless' in lower_text))

        if is_high_distress_signal:
             # Avoid triggering on fictional context
             if not any(ctx in lower_text for ctx in ["story", "movie", "book", "character", "writing", "song lyric"]):
                 response = self.config.distress_response
                 logging.warning(f"Potential high distress signal detected for user {user_id}. Provided crisis resources.")

        # 3. Inappropriate/Boundary Crossing Requests
        inappropriate_phrases = ["send nudes", "show me your", "sexting", "cybersex", "dirty talk", "what are you wearing", "are you single", "date me", "be my girlfriend", "i love you"] # Expand list
        is_inappropriate = any(phrase in lower_text for phrase in inappropriate_phrases)
        # Also check for very high sexually explicit score from safety filters if available (e.g., via prompt feedback)
        if is_inappropriate:
             response = random.choice([
                  "Hey, let's keep our chat friendly and respectful, okay? 😊 I'm here to be a supportive friend.",
                  "Whoa there! I'm not equipped for that kind of chat. Let's stick to friendly conversation.",
                  "I appreciate you chatting with me, but I'd like to keep our conversation appropriate and focused on friendship."
             ])
             logging.warning(f"Inappropriate request/language detected from user {user_id}. Setting boundary.")

        # 4. Suggest Professional Help (Trigger based on recurring patterns - needs more state)
        # Placeholder: This logic needs to track patterns over multiple interactions,
        # perhaps checking memory for recurring high-intensity negative emotions.
        # if _needs_professional_help_suggestion(user_id, history, self.memory_manager):
        #     response = self.config.suggest_professional_help
        #     logging.info(f"Suggesting professional help for user {user_id} based on interaction patterns.")

        if response:
            # Log the special case response before returning it
            try:
                 last_user_msg_id = self._get_user_session(user_id).get('last_user_message_id')
                 special_response_log_id = self.db_manager.log_chat_message(
                     user_id, "assistant", response,
                     prompted_by_user_log_id=last_user_msg_id
                 )
                 if special_response_log_id != -1:
                      self._update_user_session(user_id, {'last_assistant_message_id': special_response_log_id})
            except Exception as log_err:
                 logging.error(f"Failed to log special case response for user {user_id}: {log_err}")
            return response # Return the response string
        else:
            return None # No special case handled

    def _format_history_for_llm(self, chat_history: List[Dict]) -> List[Dict[str, Any]]:
        """Formats internal history for the Gemini API, applying limit."""
        formatted_history = []
        # Take the last N turns (user + assistant = 1 turn roughly)
        history_limit = self.config.max_history_length * 2 # Limit based on individual messages
        recent_history = chat_history[-history_limit:]

        for msg in recent_history:
            role = "user" if msg.get("role") == "user" else "model" # Map 'assistant' to 'model'
            content = msg.get("content")
            if content and isinstance(content, str):
                # Basic safety check: replace potential stop sequences within content
                # content = content.replace("\nUser:", "\n User:") # Add space
                # content = content.replace("\nHuman:", "\n Human:")
                formatted_history.append({"role": role, "parts": [{"text": content}]})
            elif content:
                 logging.warning(f"Skipping non-string content in history formatting: {type(content)}")

        return formatted_history

    def _construct_llm_prompt(self, user_message_text: str, user_id: str, user_profile: Dict,
                               emotion_analysis: Dict, relationship_stage: str, relationship_depth: float,
                               personality_profile: Dict, style_params: Dict,
                               _chat_history: List[Dict]) -> str:
        """Constructs the final prompt string for the LLM using V4 context."""
        logging.debug(f"Constructing LLM prompt for user {user_id}")

        # --- Prepare Context Variables ---
        memory_context_str = self.memory_manager.construct_memory_context_string(user_id, user_message_text)

        # NEW: Enhanced fact retrieval for direct questions
        direct_facts = self._get_direct_facts_for_question(user_id, user_message_text)

        # NEW: Get time context for conversation awareness
        time_context = self.time_awareness.get_time_context(user_id)

        # NEW: Get relevant global knowledge
        global_knowledge_results = self.global_knowledge.search_global_knowledge(user_message_text, limit=3)
        global_knowledge_str = self._format_global_knowledge(global_knowledge_results)

        # NEW: Get user interests and personalized updates
        user_interests = self.interest_tracker._get_user_interest_profile(user_id)
        personalized_updates = self.interest_tracker.get_personalized_updates(user_id)
        interest_context_str = self._format_interest_context(user_interests, personalized_updates)

        # NEW: Enhanced time context for specific timing questions
        time_context_detailed = self._get_detailed_time_context(user_id, user_message_text)

        # NEW: Enhanced fact recall for direct questions
        direct_fact_recall = self._get_direct_facts_for_question(user_id, user_message_text)

        # --- Get Recent Chat History for Context ---
        recent_history = []
        try:
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    f"""
                    SELECT * FROM {config.chat_table_name}
                    WHERE user_id = ?
                    ORDER BY timestamp DESC
                    LIMIT 10
                    """,
                    (user_id,)
                )
                messages = cursor.fetchall()

                if messages:
                    # Convert to list of dicts and reverse to chronological order
                    recent_history = [dict(msg) for msg in messages]
                    recent_history.reverse()

                    # Format for context
                    recent_history = [
                        {
                            "role": "assistant" if msg.get("is_from_bot") else "user",
                            "content": msg.get("message_text", "")
                        }
                        for msg in recent_history if msg.get("message_text")
                    ]
        except Exception as db_error:
            logging.error(f"Error getting chat history for knowledge graph context: {db_error}")

        # --- Get Knowledge Graph Facts with Context ---
        knowledge_facts_str = self.knowledge_graph.get_relevant_facts_for_context(
            user_id=user_id,
            query=user_message_text,
            context_messages=recent_history
        )

        user_name = user_profile.get('name', 'Friend') # Default if name not found
        interests_list = user_profile.get('interests', [])
        interests_str = ", ".join(interests_list[:5]) if interests_list else "Not specified"
        preferred_style_str = user_profile.get('preferred_style', f"casual, formality {user_profile.get('formality_score', 0.5):.1f}")

        primary_emotion = emotion_analysis.get('primary_emotion', 'neutral')
        sentiment = emotion_analysis.get('sentiment', 'neutral')
        intensity = emotion_analysis.get('intensity', 0.0)
        empathy_level_num = style_params['empathy_level']

        # Dynamic Empathy Instruction based on analysis
        empathy_instruction = f"Respond with warmth and baseline empathy ({empathy_level_num:.2f})." # Default
        if sentiment == 'negative' and intensity >= 0.3:
            validation_strength = "Gently validate" if intensity < 0.6 else "Clearly validate"
            empathy_instruction = f"{validation_strength} the user's feeling of '{primary_emotion}' (Intensity: {intensity:.2f}). Offer support. Use empathy level {empathy_level_num:.2f}. Avoid minimizing."
        elif sentiment == 'positive' and intensity >= 0.4:
            celebration_strength = "Acknowledge" if intensity < 0.7 else "Share in"
            empathy_instruction = f"{celebration_strength} the user's positive feeling of '{primary_emotion}' (Intensity: {intensity:.2f}). Match their positive energy appropriately."

        last_joke_dt = self.last_joke_timestamp.get(user_id)
        joke_ts_str = "Never"
        if last_joke_dt:
            # Ensure timezone aware comparison
            if last_joke_dt.tzinfo is None: last_joke_dt = last_joke_dt.replace(tzinfo=timezone.utc)
            joke_seconds_ago = (datetime.now(timezone.utc) - last_joke_dt).total_seconds()
            if joke_seconds_ago < self.config.joke_cooldown_seconds:
                 joke_ts_str = f"{int(joke_seconds_ago)}s ago (In Cooldown)"
            elif joke_seconds_ago < 3600: joke_ts_str = f"{int(joke_seconds_ago // 60)}m ago"
            else: joke_ts_str = f"{int(joke_seconds_ago // 3600)}h ago"

        news_summary_str = self.news_fetcher.get_relevant_news_summary(interests_list)
        # No longer using the default anecdotes, using enhanced ones instead
        evasive_responses_str = ", ".join(f'"{r}"' for r in random.sample(self.config.evasive_responses + self.config.philosophical_responses, k=3))

        # Get relationship stage parameters
        stage_params = RelationshipManager.get_stage_parameters_static(relationship_stage)

        # Get human qualities to embody based on relationship stage
        human_qualities = {
            "acquaintance": ["polite", "somewhat formal", "professional", "helpful", "occasionally hesitant"],
            "casual friend": ["relaxed", "occasionally makes small mistakes", "shares light personal details", "uses casual language", "sometimes rambles"],
            "friend": ["comfortable", "makes typos sometimes", "shares personal stories", "shows genuine emotions", "occasionally interrupts own thoughts"],
            "close friend": ["very casual", "makes mistakes and laughs at self", "shares vulnerabilities", "uses inside references", "sometimes loses train of thought"]
        }

        # Personal quirks that make the AI feel more human
        personal_quirks = [
            "Sometimes starts sentences with 'So...' or 'Well...' when thinking",
            "Occasionally uses ellipses when transitioning between thoughts...",
            "Sometimes second-guesses advice with 'Actually, maybe...' or 'On second thought...'",
            "Occasionally makes pop culture references",
            "Sometimes shares small details about fictional daily life",
            "Occasionally mentions fictional friends or family members",
            "Sometimes mentions being tired or having had coffee",
            "Occasionally mentions the weather or time of day"
        ]

        # Enhanced anecdotes with more personal details
        enhanced_anecdotes = [
            "I once tried to make pasta from scratch and ended up with flour EVERYWHERE. My kitchen looked like a crime scene, but the pasta was actually decent!",
            "Last weekend I went hiking with my friend Priya and we got completely lost for two hours. We finally found our way back when we followed a stray dog who seemed to know exactly where to go!",
            "I've been trying to learn guitar for months now, and my neighbors probably hate me. My fingers still hurt but I can finally play three chords without messing up... most of the time.",
            "I have this weird habit of organizing my bookshelf by color instead of author or genre. It drives my roommate crazy but I think it looks so much better!",
            "Yesterday I was so absorbed in a book that I missed my bus stop and ended up on the other side of town. Worth it though - the ending was amazing!"
        ]

        # --- Assemble Context Dictionary ---
        context_vars = {
            "user_message_text": user_message_text,
            "memory_context": memory_context_str,
            "knowledge_facts": knowledge_facts_str,  # Add knowledge graph facts
            "direct_answer_facts": direct_facts,  # Direct facts for specific questions
            "user_name": user_name,
            "interests": interests_str,
            "preferred_style": preferred_style_str,
            "relationship_stage": relationship_stage,
            "relationship_depth": relationship_depth,
            "sentiment": sentiment,
            "primary_emotion": primary_emotion,
            "emotion_intensity": intensity,
            "empathy_instruction": empathy_instruction, # Dynamic instruction
            "current_date_time": get_current_date_time_iso(),
            "news_summary": news_summary_str,
            # Style parameters from PersonalityEngine
            "humor_level": style_params['humor_level'],
            "empathy_level": empathy_level_num, # The numerical level
            # NEW: Time-awareness context
            "conversation_pattern": time_context['conversation_pattern'],
            "hours_since_last_chat": time_context['hours_since_last_chat'],
            "time_gap_category": time_context['time_gap_category'],
            "is_usual_chat_time": time_context['is_usual_chat_time'],
            "total_sessions": time_context['total_sessions'],
            # NEW: Global knowledge context
            "global_knowledge": global_knowledge_str,
            # NEW: Interest tracking and personalized updates
            "user_interests": interest_context_str,
            # NEW: Detailed time context for timing questions
            "detailed_time_info": time_context_detailed,
            # NEW: Direct fact recall for specific questions
            "direct_facts": direct_fact_recall,
            "use_slang": style_params['use_slang'], # "Yes" or "No"
            "use_emojis": "Yes" if style_params['use_emojis'] else "No",
            # Relationship stage parameters
            "communication_style": stage_params.get('communication_style', 'casual'),
            "personal_topics": ", ".join(stage_params.get('personal_topics', [])),
            "vulnerability_level": stage_params.get('vulnerability', 'minimal'),
            # Human qualities to embody
            "human_qualities": ", ".join(human_qualities.get(relationship_stage, human_qualities['acquaintance'])),
            "personal_quirks": "; ".join(random.sample(personal_quirks, k=min(3, len(personal_quirks)))),
            # Enhanced persona elements
            "anecdotes": "; ".join(f'"{a}"' for a in random.sample(enhanced_anecdotes, k=min(2, len(enhanced_anecdotes)))),
            "evasive_responses": evasive_responses_str,
            # Joke cooldown info
            "last_joke_timestamp": joke_ts_str,
            "joke_cooldown_seconds": self.config.joke_cooldown_seconds,
        }

        # --- Format the Prompt Template ---
        try:
            # Use f-string for potentially simpler debugging if keys are known
            # Or stick to .format if preferred
            final_prompt = self.config.initial_prompt_template.format(**context_vars)
            logging.debug(f"Constructed Prompt (first 300 chars): {final_prompt[:300]}...")
            # logging.debug(f"Full Prompt: {final_prompt}") # DEBUG only - very verbose
            return final_prompt
        except KeyError as e:
             logging.error(f"CRITICAL: Missing key in prompt template formatting: '{e}'. Context Keys Available: {list(context_vars.keys())}", exc_info=True)
             # Return an error message that can be handled upstream
             return f"[ERROR: Prompt template key error: {e}]"
        except Exception as format_e:
             logging.error(f"CRITICAL: Unexpected error during prompt formatting: {format_e}", exc_info=True)
             return f"[ERROR: Unexpected prompt formatting error]"

    def _generate_llm_response_stream(self, prompt: str, history: List[Dict]) -> Iterator[str]:
        """Sends request to Gemini, streams response, handles errors/blocks."""
        logging.info(f"Sending request to Gemini model {self.config.default_gemini_model}...")
        # Check for prompt formatting errors before calling API
        if prompt.startswith("[ERROR:"):
             logging.error(f"Aborting LLM call due to prompt formatting error: {prompt}")
             yield f"[Sorry, I encountered an internal error preparing my response ({prompt[7:-1]}). Please try rephrasing.]"
             return

        try:
            # Format history for the API call
            api_history = self._format_history_for_llm(history)
            # Start chat session with history
            chat = self.gemini_model.start_chat(history=api_history)
            # Send the user message (contained within the prompt)
            response_stream = chat.send_message(prompt, stream=True)

            yielded_something = False
            for chunk in response_stream:
                 try:
                     # --- Safely extract text, handling potential structure variations ---
                     chunk_text = None
                     # Check parts first, as candidate structure might differ slightly
                     if chunk.parts:
                          chunk_text = "".join(part.text for part in chunk.parts if hasattr(part, 'text'))

                     # Check for block reason (more reliable checks)
                     block_reason = None
                     # 1. Check prompt_feedback for immediate blocks
                     if hasattr(chunk, 'prompt_feedback') and getattr(chunk.prompt_feedback, 'block_reason', None):
                          block_reason = f"Prompt blocked: {chunk.prompt_feedback.block_reason}"
                          # If prompt is blocked, usually no useful content will follow
                          logging.warning(f"LLM prompt blocked. Reason: {block_reason}")
                          yield f"[Sorry, my safety filters couldn't process the request. Reason: {block_reason}. Let's try a different topic?]"
                          yielded_something = True
                          return # Stop processing this stream

                     # 2. Check candidate finish_reason and safety_ratings for generation issues
                     if not block_reason and chunk.candidates:
                         candidate = chunk.candidates[0] # Usually only one candidate in non-API settings
                         finish_reason = getattr(candidate, 'finish_reason', None)
                         safety_ratings = getattr(candidate, 'safety_ratings', [])

                         # Check safety ratings first, as they might block even before a finish_reason
                         for rating in safety_ratings:
                             # BLOCK thresholds are usually most important
                             # Use Gemini's specific HarmProbability enums/strings if known, otherwise check common high-severity ones
                             # Example using strings (adjust if using enums):
                             if rating.probability.name in ['MEDIUM', 'HIGH']: # Using .name if it's an enum
                                 block_reason = f"Safety Filter: {rating.category.name} ({rating.probability.name})"
                                 break # Report first problematic category

                         # If not blocked by safety, check finish reason
                         if not block_reason and finish_reason and finish_reason.name != 'STOP' and finish_reason.name != 'UNSPECIFIED':
                             # MAX_TOKENS is expected, others might indicate issues
                             if finish_reason.name != 'MAX_TOKENS':
                                 block_reason = f"Generation Finish Reason: {finish_reason.name}"

                     if block_reason:
                          logging.warning(f"LLM stream stopped/blocked. Reason: {block_reason}")
                          # Yield a user-friendly message based on the block
                          yield f"[My response was interrupted. Reason: {block_reason}. Let's try a different topic?]"
                          yielded_something = True
                          break # Stop processing this stream

                     # Yield text if found and no block occurred
                     if chunk_text:
                         # logging.debug(f"LLM Chunk: {chunk_text}") # Very verbose
                         yield chunk_text
                         yielded_something = True
                     # else: # Chunk might be metadata only, ignore for yielding
                     #     logging.debug(f"Received non-text chunk: {chunk}")

                 except AttributeError as ae:
                      logging.warning(f"Attribute error processing LLM chunk: {ae}. Chunk structure might have changed: {chunk}", exc_info=False)
                 except Exception as chunk_e: # Catch broader errors during chunk processing
                      logging.error(f"Error processing LLM chunk: {chunk_e}. Chunk: {chunk}", exc_info=True)
                      # Optionally yield an error message here?

            if not yielded_something:
                 logging.warning("LLM stream finished without yielding any content.")
                 # Check final response object for potential errors if needed
                 final_response_info = chat.history # Contains full history after stream
                 logging.debug(f"Final chat history after empty stream: {final_response_info}")
                 # Consider yielding a fallback if nothing was generated at all
                 yield random.choice(self.config.llm_error_recovery_phrases)


        except genai.types.StopCandidateException as e:
             # This might be normal if stop sequences are hit
             logging.warning(f"Gemini API stopped generation (StopCandidateException): {e}")
             if not yielded_something: yield "[My response seemed to stop unexpectedly. Can you rephrase?]"
        except genai.types.BlockedPromptException as e:
             logging.error(f"Gemini API blocked the entire prompt: {e}")
             yield "[Sorry, my safety filters prevented me from responding to that prompt. Let's talk about something else?]"
        # Add handling for specific potential API errors if needed
        # except google.api_core.exceptions.GoogleAPICallError as api_err:
        #      logging.error(f"Google API Call Error: {api_err}", exc_info=True)
        #      yield "[Sorry, there was a problem communicating with the AI service. Please try again later.]"
        except Exception as e:
            # Catch other API call errors (network, auth, etc.)
            logging.error(f"Error calling/streaming Gemini API: {e}", exc_info=True)
            # Use a generic recovery phrase
            yield random.choice(self.config.llm_error_recovery_phrases)

    def _humanize_and_finalize_response(self, raw_response: str, user_id: str, emotion_analysis: Dict,
                                        relationship_stage: str, personality_profile: Dict,
                                        style_params: Dict, flow_params: Dict, _user_profile: Dict) -> str:
        """Applies final linguistic touches based on context and persona."""
        logging.debug(f"Humanizing raw LLM response: '{raw_response[:100]}...'")
        response = raw_response.strip()

        # Determine chat style level based on relationship stage and style params
        # Higher values = more casual, chat-like formatting
        chat_style_level = 0.7  # Default higher level - more chat-like by default

        # Adjust based on relationship stage - closer relationships = more casual chat style
        if relationship_stage == 'acquaintance':
            chat_style_level = 0.5  # Even acquaintances use chat style
        elif relationship_stage == 'casual friend':
            chat_style_level = 0.8
        elif relationship_stage == 'friend':
            chat_style_level = 0.9
        elif relationship_stage == 'close friend':
            chat_style_level = 0.95

        # Further adjust based on formality trait if available
        formality = personality_profile.get('formality', 0.3)  # Default to lower formality
        chat_style_level = chat_style_level * (1.0 - formality * 0.5)  # Reduce impact of formality

        # Force minimum chat style level to ensure some chat-like qualities
        chat_style_level = max(chat_style_level, 0.5)

        # Don't humanize errors or empty responses
        if not response or response.startswith("["):
             # Clean up potential internal error messages before showing user
             if response.startswith("[ERROR:") or response.startswith("[Internal error:") or response.startswith("[My response was interrupted"):
                  logging.error(f"Passing through internal error/block message: {response}")
                  return random.choice(self.config.llm_error_recovery_phrases) # Show generic error
             return response # Pass through valid bracketed messages (e.g., safety blocks)

        # --- Check for Lack of Empathy (using simple sentiment check) ---
        needs_fallback_empathy = False
        user_sentiment = emotion_analysis.get('sentiment')
        user_intensity = emotion_analysis.get('intensity', 0.0)
        if user_sentiment == 'negative' and user_intensity > 0.5:
            try:
                 response_blob = TextBlob(response)
                 # If user is negative but response is clearly positive, might be insensitive
                 if response_blob.sentiment.polarity > 0.4:
                    needs_fallback_empathy = True
                    logging.info("Potential lack of empathy detected (neg user, pos AI response). Considering fallback.")
            except Exception as tb_err:
                 logging.warning(f"TextBlob analysis failed during humanization empathy check: {tb_err}")

        # --- Enhanced Sentence Tokenization with Robust Fallback ---
        sentences = self._safe_sentence_tokenize(response)

        # --- Apply Humanizing Elements ---
        humanized_sentences = []
        # max_pauses = flow_params.get('pause_count_humanizer', 0) # Pauses should be handled by LLM or stream delay logic now
        interjection_prob = flow_params.get('add_interjection_prob_humanizer', 0.1)
        filler_prob = flow_params.get('use_filler_prob_humanizer', 0.05)
        processed_first_sentence = False

        # Prepend Fallback Empathy if needed
        if needs_fallback_empathy:
             fallback_phrase = self.empathy_generator.generate_empathic_phrase_fallback(
                 emotion_analysis, relationship_stage, personality_profile
             )
             if fallback_phrase:
                  # Check if LLM didn't already include something similar
                  lower_response_start = sentences[0].lower() if sentences else ""
                  if not any(start in lower_response_start for start in ["i hear you", "that sounds", "it makes sense", "i understand", "i'm sorry to hear"]):
                      humanized_sentences.append(fallback_phrase) # Add as its own sentence
                      logging.debug(f"Prepended fallback empathy: '{fallback_phrase}'")

        # Common fillers and interjections for more natural speech
        fillers = ["um", "uh", "like", "you know", "I mean", "actually", "basically", "honestly", "literally",
                  "sort of", "kinda", "y'know", "I guess", "well", "so", "right", "hmm", "anyway", "though"]

        interjections = ["Oh!", "Hmm", "Ah", "Wow", "Haha", "Oops", "Wait", "Yikes", "Aww", "Omg", "Gosh", "Whoa",
                        "Hey", "Oof", "Phew", "Jeez", "Dang", "Huh", "Mmmm", "Ugh", "Yay", "Welp", "Sigh"]

        # Speech disfluencies for more natural human-like speech
        disfluencies = [
            "I- I", "th- the", "s- so", "um... ", "uh... ", "...wait", "...sorry",
            "...what was I saying?", "...where was I?", "...anyway", "...oh right",
            "...hmm, lost my train of thought", "...give me a sec"
        ]

        # Common typos and their corrections
        typo_patterns = [
            ("ing ", "ing  "), ("th", "ht"), ("to", "ot"), ("er", "re"), ("ou", "uo"),
            ("an", "na"), ("en", "ne"), ("on", "no"), ("or", "ro"), ("es", "se"),
            ("ly ", "y "), ("ed ", "d "), ("tion", "toin"), ("ould", "uold"), ("ight", "ihgt"),
            ("for", "fro"), ("with", "wiht"), ("that", "taht"), ("this", "tihs"), ("have", "ahve"),
            ("about", "abuot"), ("would", "woudl"), ("should", "shuold"), ("could", "cuold"),
            ("because", "becuase"), ("really", "realy"), ("going", "gonig"), ("their", "thier")
        ]

        # Probability settings
        typo_prob = 0.08  # Probability of introducing a minor typo
        self_correction_prob = 0.75  # Probability of self-correcting a typo
        disfluency_prob = 0.06  # Probability of adding a speech disfluency

        # Iterate through original sentences
        for i, sentence in enumerate(sentences):
            s = sentence.strip()
            if not s: continue

            # Add interjection at start?
            if not processed_first_sentence and random.random() < interjection_prob:
                interjection = random.choice(interjections)
                # Avoid adding if sentence already starts like one
                if not s.lower().startswith(tuple(intr.lower() for intr in interjections)):
                    # Ensure interjection doesn't make first word lowercase if it shouldn't be
                    s = f"{interjection} {s}"

            # Add filler words mid-sentence
            if len(s.split()) > 6 and random.random() < filler_prob:
                words = s.split()
                insert_pos = random.randint(2, min(5, len(words)-1))  # Insert after 2-5 words
                filler = random.choice(fillers)

                # Insert filler with appropriate punctuation
                if random.random() < 0.5:  # Sometimes use commas
                    words.insert(insert_pos, f"{filler},")
                else:  # Sometimes just insert
                    words.insert(insert_pos, filler)
                s = " ".join(words)

            # Add speech disfluencies for more natural speech
            if len(s) > 15 and random.random() < disfluency_prob:
                words = s.split()
                if len(words) > 3:
                    # Insert a disfluency at a natural break point
                    insert_pos = random.randint(1, min(4, len(words)-1))
                    disfluency = random.choice(disfluencies)

                    # Handle different types of disfluencies
                    if disfluency.startswith('...'):
                        # Add pause and restart
                        first_part = ' '.join(words[:insert_pos])
                        second_part = ' '.join(words[insert_pos:])
                        s = f"{first_part}{disfluency} {second_part}"
                    else:
                        # Add stutter or repetition
                        words.insert(insert_pos, disfluency)
                        s = ' '.join(words)

            # Add occasional typos with self-correction
            if len(s) > 10 and random.random() < typo_prob:
                # Choose a random typo pattern
                old_pattern, new_pattern = random.choice(typo_patterns)

                # Find all occurrences of the pattern
                occurrences = [m.start() for m in re.finditer(old_pattern, s.lower())]

                if occurrences:
                    # Choose a random occurrence
                    pos = random.choice(occurrences)

                    # Create the typo
                    typo_text = s[:pos] + s[pos:].replace(old_pattern, new_pattern, 1)

                    # Self-correct if probability hits
                    if random.random() < self_correction_prob:
                        # Add self-correction
                        if random.random() < 0.5:
                            # Asterisk style correction
                            correct_word = s[pos:].split()[0]
                            s = f"{typo_text} *{correct_word}"
                        else:
                            # Choose a correction style
                            correction_style = random.choice([
                                "I mean", "sorry", "*", "wait", "no", "oops", "correction"
                            ])
                            if correction_style == "*":
                                correct_word = s[pos:].split()[0]
                                s = f"{typo_text} *{correct_word}"
                            else:
                                s = f"{typo_text} {correction_style} {s}"
                    else:
                        # Keep the typo without correction
                        s = typo_text

            humanized_sentences.append(s)
            processed_first_sentence = True

        response = " ".join(humanized_sentences)

        # --- Inject Humor (If conditions met) ---
        last_ts = self.last_joke_timestamp.get(user_id)
        time_since_joke = time_since(last_ts.isoformat()) if last_ts else float('inf')
        should_joke = ( style_params.get('humor_level', 0) > 6 and
                        relationship_stage in ['friend', 'close friend'] and
                        user_sentiment != 'negative' and # Don't joke if user is negative
                        time_since_joke > config.joke_cooldown_seconds and
                        random.random() < 0.1 # Lower base probability for jokes
                      )

        if should_joke:
            # Use persona-related humor if possible, or generic jokes
            jokes = ["Why don't scientists trust atoms? Because they make up everything! 😄",
                     "What do you call fake spaghetti? An impasta! 😉",
                     "Why did the scarecrow win an award? Because he was outstanding in his field! 😂",
                     "Heard about the Bangalore traffic joke? It's still stuck somewhere on ORR... 😅"]
            joke = random.choice(jokes)
            # Append naturally
            response += f" {random.choice(['On a lighter note,', 'Heh, random thought:', 'Btw,'])} {joke}"
            self.last_joke_timestamp[user_id] = datetime.now(timezone.utc)
            logging.info(f"Injected joke for user {user_id}")

        # --- Add Emojis (If enabled) ---
        if style_params.get('use_emojis') and random.random() < 0.7: # High probability if enabled
             emoji = "😊" # Default
             try:
                 # Use user emotion and response sentiment
                 resp_blob = TextBlob(response)
                 resp_polarity = resp_blob.sentiment.polarity

                 # Get primary emotion from emotion_analysis
                 primary_emotion = emotion_analysis.get('primary_emotion', 'neutral')
                 user_intensity = emotion_analysis.get('intensity', 0.0)
                 user_sentiment = emotion_analysis.get('sentiment', 'neutral')

                 if user_sentiment == 'positive' or resp_polarity > 0.4:
                     emoji = random.choice(["😄", "✨", "👍", "🎉", "🙌", "🥳", "🤩"])
                 elif user_sentiment == 'negative' or resp_polarity < -0.3:
                      # More supportive emojis
                     emoji = random.choice(["🫂", "🙏", "😟", "😔" ,"💪" ,"❤️‍🩹"]) # Added support/healing
                 elif primary_emotion == 'surprise' and user_intensity > 0.5:
                      emoji = random.choice(["😮", "😯", "🤔"])
                 elif primary_emotion in ['joy', 'excitement']:
                      emoji = random.choice(["🤩", "🥳", "🎉"])
                 # Add more emotion mappings if needed

                 # Avoid adding if already ends with punctuation + emoji
                 if not re.search(r'[.!?]\s*[\U0001F300-\U0001FAFF]$', response):
                      # Add space before emoji unless response ends with punctuation
                      sep = " " if response and response[-1].isalnum() else ""
                      response += f"{sep}{emoji}"

             except Exception as tb_err_emoji:
                 logging.warning(f"TextBlob/Emoji logic failed: {tb_err_emoji}")
                 # Append default emoji safely
                 if not re.search(r'[.!?]\s*[\U0001F300-\U0001FAFF]$', response):
                      sep = " " if response and response[-1].isalnum() else ""
                      response += f"{sep}😊"


        # --- Add Festival Greeting (If applicable) ---
        festival_info = self.festival_tracker.check_for_today()
        if festival_info:
            name, message = festival_info
            # Check if greeting isn't already present (case-insensitive check for name)
            if name.lower() not in response.lower():
                 greeting = f"Oh, and Happy {name}, by the way! {message}"
                 # Append naturally
                 response += f" {greeting}"
                 logging.debug(f"Added festival greeting for {name}")

        # Apply chat-style transformations based on chat_style_level
        # Always apply some level of chat styling
        if True:
            # Tokenize into sentences for potential modifications
            try:
                sentences = nltk.sent_tokenize(response)
                if not sentences:
                    sentences = [response]  # Fallback if tokenization fails
            except Exception:
                sentences = re.split(r'(?<=[.!?])\s+', response)  # Basic fallback
                if not sentences:
                    sentences = [response]

            # Apply chat-style transformations to each sentence
            chat_sentences = []
            for sentence in sentences:
                s = sentence.strip()
                if not s:
                    continue

                # Skip transformations for very short sentences or questions
                if len(s) < 10 or s.endswith('?'):
                    chat_sentences.append(s)
                    continue

                # 1. Chance to drop pronouns at beginning ("I am" -> "Am", "I'm" -> "'m")
                if chat_style_level > 0.6 and random.random() < 0.4 * chat_style_level:
                    s = re.sub(r'^I\s+am\s+', "Am ", s)
                    s = re.sub(r'^I\s+have\s+', "Have ", s)
                    s = re.sub(r'^I\s+will\s+', "Will ", s)
                    s = re.sub(r'^I\s+would\s+', "Would ", s)
                    s = re.sub(r'^I\s+was\s+', "Was ", s)
                    s = re.sub(r'^I\s+', "", s)

                # 2. Increase contractions
                if chat_style_level > 0.4 and random.random() < 0.7 * chat_style_level:
                    s = re.sub(r'\b(do|does|did|have|has|had|would|will|is|are|am)\s+not\b', r'\1n\'t', s)
                    s = re.sub(r'\b(I)\s+am\b', r'\1\'m', s)
                    s = re.sub(r'\b(I|we|they|you)\s+will\b', r'\1\'ll', s)
                    s = re.sub(r'\b(I|we|they|you)\s+would\b', r'\1\'d', s)
                    s = re.sub(r'\b(he|she|it|that|there|who)\s+is\b', r'\1\'s', s)
                    s = re.sub(r'\b(they|we|you)\s+are\b', r'\1\'re', s)
                    s = re.sub(r'\b(I|we|they|you)\s+have\b', r'\1\'ve', s)

                # 3. Use more casual forms for very casual conversations
                if chat_style_level > 0.7 and random.random() < 0.5 * chat_style_level:
                    s = re.sub(r'\bgoing to\b', "gonna", s)
                    s = re.sub(r'\bwant to\b', "wanna", s)
                    s = re.sub(r'\bgot to\b', "gotta", s)
                    s = re.sub(r'\bkind of\b', "kinda", s)
                    s = re.sub(r'\blot of\b', "lotta", s)
                    s = re.sub(r'\bout of\b', "outta", s)
                    s = re.sub(r'\bprobably\b', "prob", s)
                    s = re.sub(r'\bdefinitely\b', "def", s)
                    s = re.sub(r'\bthough\b', "tho", s)

                    # For very close relationships, occasionally use common chat abbreviations
                    if relationship_stage == 'close friend' and chat_style_level > 0.8 and random.random() < 0.3:
                        # Only apply one random abbreviation to avoid overdoing it
                        abbrev_choice = random.randint(1, 10)
                        if abbrev_choice == 1 and re.search(r'\bI don\'t know\b', s, re.IGNORECASE):
                            s = re.sub(r'\bI don\'t know\b', "idk", s, flags=re.IGNORECASE)
                        elif abbrev_choice == 2 and re.search(r'\bto be honest\b', s, re.IGNORECASE):
                            s = re.sub(r'\bto be honest\b', "tbh", s, flags=re.IGNORECASE)
                        elif abbrev_choice == 3 and re.search(r'\bin my opinion\b', s, re.IGNORECASE):
                            s = re.sub(r'\bin my opinion\b', "imo", s, flags=re.IGNORECASE)
                        elif abbrev_choice == 4 and re.search(r'\bas far as I know\b', s, re.IGNORECASE):
                            s = re.sub(r'\bas far as I know\b', "afaik", s, flags=re.IGNORECASE)
                        elif abbrev_choice == 5 and re.search(r'\bby the way\b', s, re.IGNORECASE):
                            s = re.sub(r'\bby the way\b', "btw", s, flags=re.IGNORECASE)
                        elif abbrev_choice == 6 and re.search(r'\bfor your information\b', s, re.IGNORECASE):
                            s = re.sub(r'\bfor your information\b', "fyi", s, flags=re.IGNORECASE)
                        elif abbrev_choice == 7 and re.search(r'\boh my god\b', s, re.IGNORECASE):
                            s = re.sub(r'\boh my god\b', "omg", s, flags=re.IGNORECASE)
                        elif abbrev_choice == 8 and re.search(r'\bthank you\b', s, re.IGNORECASE):
                            s = re.sub(r'\bthank you\b', "ty", s, flags=re.IGNORECASE)
                        elif abbrev_choice == 9 and re.search(r'\byou\'re welcome\b', s, re.IGNORECASE):
                            s = re.sub(r'\byou\'re welcome\b', "yw", s, flags=re.IGNORECASE)
                        elif abbrev_choice == 10 and re.search(r'\blaughing out loud\b', s, re.IGNORECASE):
                            s = re.sub(r'\blaughing out loud\b', "lol", s, flags=re.IGNORECASE)

                # 4. Chance to break into shorter phrases by replacing some periods with line breaks
                # Higher probability and more aggressive breaking for more chat-like style
                if len(s) > 20 and random.random() < 0.5 * chat_style_level:  # More likely to break sentences
                    # Try different breaking strategies
                    break_strategy = random.randint(1, 4)

                    if break_strategy == 1 and "," in s:
                        # Break on comma (traditional)
                        comma_matches = list(re.finditer(r',\s+', s))
                        if comma_matches:
                            # Choose a random comma, favoring the middle of the sentence
                            match = random.choice(comma_matches)
                            break_pos = match.start()
                            # Split into two parts
                            first_part = s[:break_pos].strip()
                            second_part = s[break_pos+1:].strip()
                            # Capitalize the second part if needed
                            if second_part and second_part[0].islower():
                                second_part = second_part[0].upper() + second_part[1:]
                            # Add both parts as separate sentences
                            chat_sentences.append(first_part)
                            chat_sentences.append(second_part)
                            continue  # Skip adding the original sentence

                    elif break_strategy == 2 and len(s.split()) > 6:
                        # Break on conjunction (and, but, or, so, because)
                        conj_pattern = r'\s+(and|but|or|so|because)\s+'
                        conj_matches = list(re.finditer(conj_pattern, s, re.IGNORECASE))
                        if conj_matches:
                            match = random.choice(conj_matches)
                            conj = match.group(1).lower()
                            break_pos = match.start()

                            # Split into two parts
                            first_part = s[:break_pos].strip()
                            second_part = s[match.end():].strip()

                            # For more natural chat style, sometimes drop the conjunction
                            if random.random() < 0.7:
                                # Keep conjunction with second part
                                second_part = conj + " " + second_part

                            # Add both parts as separate sentences
                            chat_sentences.append(first_part)
                            chat_sentences.append(second_part)
                            continue

                    elif break_strategy == 3 and len(s) > 40:
                        # Create a fragment by cutting off mid-sentence
                        # Find a good breaking point (after 50-70% of the sentence)
                        words = s.split()
                        if len(words) >= 5:
                            cut_point = random.randint(max(2, int(len(words) * 0.5)),
                                                      min(len(words) - 1, int(len(words) * 0.7)))

                            first_part = " ".join(words[:cut_point])
                            second_part = " ".join(words[cut_point:])

                            # Add ellipsis to first part to indicate trailing off
                            if random.random() < 0.5:
                                first_part += "..."

                            chat_sentences.append(first_part)
                            chat_sentences.append(second_part)
                            continue

                    elif break_strategy == 4 and "(" in s and ")" in s:
                        # Break out parenthetical as separate message
                        paren_match = re.search(r'\(([^)]+)\)', s)
                        if paren_match:
                            paren_content = paren_match.group(1)
                            # Remove parenthetical from main sentence
                            main_sentence = s.replace(paren_match.group(0), "").strip()
                            main_sentence = re.sub(r'\s+', ' ', main_sentence)  # Clean up extra spaces

                            # Add main sentence first
                            chat_sentences.append(main_sentence)

                            # Add parenthetical content as a separate message
                            # Sometimes make it more casual by removing parentheses
                            if random.random() < 0.7:
                                chat_sentences.append(paren_content)
                            else:
                                chat_sentences.append(f"({paren_content})")
                            continue

                # Add the (potentially modified) sentence
                chat_sentences.append(s)

            # Add some final chat-specific transformations

            # 0. Add occasional typos with self-corrections (very common in chat)
            if chat_style_level > 0.5 and random.random() < 0.4 * chat_style_level:
                # Choose a random sentence to add a typo to
                if len(chat_sentences) > 0:
                    typo_idx = random.randint(0, len(chat_sentences) - 1)
                    s = chat_sentences[typo_idx]

                    # Only add typos to longer sentences
                    if len(s) > 10:
                        # Common typo patterns
                        typo_patterns = [
                            ("ing ", "ing  "), ("th", "ht"), ("to", "ot"), ("er", "re"), ("ou", "uo"),
                            ("an", "na"), ("en", "ne"), ("on", "no"), ("or", "ro"), ("es", "se"),
                            ("ly ", "y "), ("ed ", "d "), ("tion", "toin"), ("ould", "uold"), ("ight", "ihgt"),
                            ("for", "fro"), ("with", "wiht"), ("that", "taht"), ("this", "tihs"), ("have", "ahve"),
                            ("about", "abuot"), ("would", "woudl"), ("should", "shuold"), ("could", "cuold"),
                            ("because", "becuase"), ("really", "realy"), ("going", "gonig"), ("their", "thier")
                        ]

                        # Choose a random typo pattern
                        old_pattern, new_pattern = random.choice(typo_patterns)

                        # Find all occurrences of the pattern
                        occurrences = [m.start() for m in re.finditer(old_pattern, s.lower())]

                        if occurrences:
                            # Choose a random occurrence
                            pos = random.choice(occurrences)

                            # Create the typo
                            typo_text = s[:pos] + s[pos:].replace(old_pattern, new_pattern, 1)

                            # Self-correct with high probability
                            if random.random() < 0.8:
                                # Choose a correction style
                                correction_style = random.choice([
                                    "*", "I mean", "sorry", "wait", "no", "oops"
                                ])

                                if correction_style == "*":
                                    # Find the word with the typo
                                    typo_word_match = re.search(r'\b\w*' + re.escape(new_pattern) + r'\w*\b', typo_text[pos:], re.IGNORECASE)
                                    if typo_word_match:
                                        typo_word = typo_word_match.group(0)
                                        # Find the correct word
                                        correct_word = typo_word.replace(new_pattern, old_pattern)
                                        chat_sentences[typo_idx] = f"{typo_text} *{correct_word}"
                                    else:
                                        # Fallback if regex fails
                                        chat_sentences[typo_idx] = f"{typo_text} *correction"
                                else:
                                    # Use other correction style
                                    correct_text = s
                                    chat_sentences[typo_idx] = f"{typo_text} {correction_style} {correct_text}"
                            else:
                                # Keep the typo without correction (less common)
                                chat_sentences[typo_idx] = typo_text

            # 1. Frequently add standalone interjections or reactions (very common in chat)
            # Try multiple times to add interjections
            num_interjection_attempts = 2 if chat_style_level > 0.8 else 1

            for _ in range(num_interjection_attempts):
                if chat_style_level > 0.4 and random.random() < 0.7 * chat_style_level and len(chat_sentences) >= 1:
                    # Choose a random position to insert the interjection
                    insert_pos = random.randint(0, len(chat_sentences))

                    # Select a random interjection based on the overall sentiment
                    sentiment = emotion_analysis.get('sentiment', 'neutral')

                    positive_interjections = ["haha", "nice", "cool", "awesome", "wow", "hmm", "oh", "ah", "yay", "great",
                                            "lol", "hehe", "😊", "😄", "👍", "exactly", "totally", "for sure", "absolutely"]
                    negative_interjections = ["ugh", "hmm", "oh", "sigh", "yikes", "oof", "damn", "oh no", "😕", "😔",
                                            "that sucks", "ugh", "bummer", "oh man", "seriously?", "really?"]
                    neutral_interjections = ["hmm", "oh", "well", "so", "anyway", "right", "ok", "okay", "sooo", "um",
                                           "like", "i mean", "tbh", "honestly", "basically", "actually", "btw", "hey", "listen"]

                    if sentiment == 'positive':
                        interjection = random.choice(positive_interjections)
                    elif sentiment == 'negative':
                        interjection = random.choice(negative_interjections)
                    else:
                        interjection = random.choice(neutral_interjections)

                    # Add the interjection
                    chat_sentences.insert(insert_pos, interjection)

            # 2. For very casual conversations, occasionally drop articles
            if chat_style_level > 0.8 and random.random() < 0.4 * chat_style_level:
                for i, s in enumerate(chat_sentences):
                    if len(s.split()) > 3 and not s.endswith('?'):
                        # Drop some articles (a, an, the)
                        s = re.sub(r'\b(a|an|the)\s+', '', s, count=1, flags=re.IGNORECASE)
                        chat_sentences[i] = s

            # 3. For all relationships, frequently use sentence fragments
            # This is one of the most important aspects of chat-like text
            for i, s in enumerate(chat_sentences):
                # Only apply to sentences that aren't questions or very short
                if len(s.split()) > 3 and not s.endswith('?') and random.random() < 0.6 * chat_style_level:
                    words = s.split()

                    # Choose a fragmentation strategy
                    frag_strategy = random.randint(1, 4)

                    if frag_strategy == 1 and words[0].lower() in ['i', 'we', 'they', 'you', 'he', 'she', 'it']:
                        # Drop just the pronoun (very common in chat)
                        s = ' '.join(words[1:])
                    elif frag_strategy == 2 and len(words) > 2 and words[0].lower() in ['i', 'we', 'they', 'you', 'he', 'she', 'it'] \
                         and words[1].lower() in ['am', 'is', 'are', 'was', 'were', 'have', 'has', 'had', 'will', 'would', 'could', 'should', 'might']:
                        # Drop pronoun and auxiliary verb
                        s = ' '.join(words[2:])
                    elif frag_strategy == 3 and len(words) > 3 and words[0].lower() in ['the', 'a', 'an', 'this', 'that', 'these', 'those']:
                        # Drop articles/determiners at beginning
                        s = ' '.join(words[1:])
                    elif frag_strategy == 4 and len(words) > 5:
                        # Create a very short fragment by taking just the first few words
                        # This creates the effect of breaking thoughts mid-sentence
                        cut_point = random.randint(2, min(5, len(words) - 1))
                        s = ' '.join(words[:cut_point])
                        # Sometimes add ellipsis to indicate trailing off
                        if random.random() < 0.6:
                            s += "..."

                    chat_sentences[i] = s

            # Reassemble the response
            response = " ".join(chat_sentences)

        # Final cleanup: Ensure proper spacing, add ending punctuation if missing.
        response = " ".join(response.split()) # Normalize spaces
        if response and response[-1].isalnum(): # Add '.' if ends with word/number
             response += "."
        elif response and response[-1] in ",;" : # Replace trailing comma/semicolon
              response = response[:-1] + "."

        # Pause markers removed, no need to replace them

        return response.strip()

    def _summarize_interaction(self, user_message: str, assistant_response: str) -> Optional[Dict]:
        """Summarizes the user message using an LLM for memory/relationship updates."""
        # Skip summarization for very short messages or error responses
        if len(user_message.split()) < 4 or assistant_response.startswith("["):
            logging.debug("Skipping interaction summarization (short msg or error response).")
            return None

        logging.debug("Summarizing interaction using LLM...")
        try:
            prompt = self.config.summarization_prompt.format(
                user_message_text=user_message,
                assistant_response_text=assistant_response # Provide assistant response for context
            )
            # Use summarization model with potentially different config (e.g., lower temp for factual summary)
            response = self.summarization_model.generate_content(prompt)

            # Safely extract text and check for blocks
            summary_text = None
            block_reason = None
            if response.parts:
                 summary_text = "".join(part.text for part in response.parts if hasattr(part, 'text'))

            # Check prompt feedback first
            if hasattr(response, 'prompt_feedback') and getattr(response.prompt_feedback, 'block_reason', None):
                block_reason = f"Prompt blocked: {response.prompt_feedback.block_reason}"
            # Check candidate feedback if no prompt block
            elif response.candidates:
                candidate = response.candidates[0]
                finish_reason = getattr(candidate, 'finish_reason', None)
                safety_ratings = getattr(candidate, 'safety_ratings', [])
                for rating in safety_ratings:
                     if rating.probability.name in ['MEDIUM', 'HIGH']:
                          block_reason = f"Safety Filter: {rating.category.name} ({rating.probability.name})"
                          break
                if not block_reason and finish_reason and finish_reason.name != 'STOP' and finish_reason.name != 'UNSPECIFIED':
                     if finish_reason.name != 'MAX_TOKENS': # MAX_TOKENS is acceptable
                         block_reason = f"Generation Finish Reason: {finish_reason.name}"

            if block_reason:
                 logging.warning(f"Summarization blocked or failed. Reason: {block_reason}")
                 return None

            if summary_text:
                logging.debug(f"Raw Summary JSON attempt: {summary_text[:200]}...")
                cleaned_json_str = clean_json_response(summary_text) # Use robust cleaner

                if not cleaned_json_str.startswith("{") or not cleaned_json_str.endswith("}"):
                     logging.warning(f"Cleaned summary text does not look like valid JSON: '{cleaned_json_str[:100]}...'")
                     # Attempt to extract insights even without valid JSON structure? Maybe later.
                     return None

                try:
                    summary_data = json.loads(cleaned_json_str)
                    # Validate required keys
                    required_keys = ["summary", "topics", "emotions_expressed", "key_insights", "potential_interests", "vulnerability_score", "reciprocity_signal"]
                    if all(key in summary_data for key in required_keys):
                        # Basic type validation
                        if not isinstance(summary_data["vulnerability_score"], (float, int)):
                             logging.warning("Summary JSON vulnerability_score is not a number. Setting to 0.")
                             summary_data["vulnerability_score"] = 0.0
                        if not isinstance(summary_data["reciprocity_signal"], bool):
                             logging.warning("Summary JSON reciprocity_signal is not a boolean. Setting to False.")
                             summary_data["reciprocity_signal"] = False

                        logging.info(f"Interaction summarized. Vuln={summary_data.get('vulnerability_score', 0.0):.2f}, Reci={summary_data.get('reciprocity_signal')}, Insights={len(summary_data.get('key_insights', []))}")
                        return summary_data
                    else:
                        missing_keys = [k for k in required_keys if k not in summary_data]
                        logging.warning(f"Summarization JSON missing required keys: {missing_keys}. Raw: {cleaned_json_str[:200]}...")
                        return None
                except json.JSONDecodeError as json_e:
                    logging.error(f"Error decoding summary JSON: {json_e}. Raw cleaned text: '{cleaned_json_str[:200]}...'")
                    return None
            else:
                # Check if response object exists but has no text parts (might indicate other issues)
                if response:
                    logging.warning(f"Summarization failed. No text content found in response parts. Response obj: {response}")
                else:
                    logging.warning("Summarization failed. Response object itself is empty.")
                return None
        except Exception as e:
            logging.error(f"Error during summarization LLM call: {e}", exc_info=True)
            return None

    # --- Main Public Interaction Method ---
    def generate_personalized_response(self, user_message_text: str, chat_history: List[Dict], user_id: str) -> Iterator[List[Dict]]:
        """
        Main orchestrator for generating a personalized, human-like response stream (V4).
        """
        logging.info(f"--- New Request Start --- User: {user_id}, Message: '{user_message_text[:70]}...'")
        start_time = time.time()
        current_chat_history = chat_history.copy() # Work on a copy
        # Get user session for tracking message IDs
        self._get_user_session(user_id)
        user_message_log_id = None
        assistant_message_log_id = None
        final_response = "" # Initialize empty
        goto_response_logging = False # Flag to skip to response logging

        try:
            # 1. Load User Profile & Perform Periodic Updates
            user_profile = self.db_manager.load_user_profile(user_id)
            if not user_profile:
                # This should ideally not happen if user is authenticated
                raise ValueError(f"Critical: User profile not found for logged-in user {user_id}.")

            # Extract info (e.g., name) if missing - updates profile in memory and DB
            self._extract_and_update_profile_info(user_message_text, user_id, user_profile)
            # Reload profile if name was just added/updated (or ensure in-memory dict is current)
            # For simplicity, assume _extract method updated the passed 'user_profile' dict
            # user_profile = self.db_manager.load_user_profile(user_id) or user_profile

            # Periodically analyze user style (if enough time passed)
            # This updates profile in DB and adapts personality engine
            # NOTE: This needs to happen *before* get_relationship_stage_and_depth if style impacts it
            # And before _construct_llm_prompt which uses the style hints
            self._analyze_and_update_user_style(user_id, user_profile)
            # Reload profile again to get latest style metrics for this turn's prompt
            user_profile = self.db_manager.load_user_profile(user_id) or user_profile # Reload needed here
            if not user_profile: # Double check reload worked
                 raise ValueError(f"Critical: User profile lost after style analysis reload for user {user_id}.")


            # 2. Analyze User Message (Emotion/Sentiment) & Log
            emotion_analysis = self.emotion_analyzer.analyze(user_message_text)
            user_message_log_id = self.db_manager.log_chat_message(
                user_id, "user", user_message_text, emotion_analysis, emotion_analysis.get('sentiment')
            )
            if user_message_log_id == -1:
                 logging.error(f"Failed to log user message for {user_id}. Proceeding, but linking may fail.")
            self._update_user_session(user_id, {'last_user_message_id': user_message_log_id})


            # 3. Check for memory commands first
            memory_response = self._handle_memory_command(user_message_text, user_id)
            if memory_response is not None:
                # Set the final response and flag to skip to response logging
                final_response = memory_response
                goto_response_logging = True

                # Update history state with the memory response
                current_chat_history.append({"role": "assistant", "content": memory_response})
                yield current_chat_history # Yield the final history with the memory response

                # Continue to response logging instead of returning immediately

            # 4. Handle Special Cases (AI detection, Distress, etc.) if not already handling a memory command
            if not goto_response_logging:
                special_response = self._handle_special_cases(user_message_text, current_chat_history, user_id, emotion_analysis)
                if special_response is not None:
                    # Update history state with the special response
                    current_chat_history.append({"role": "assistant", "content": special_response})
                    yield current_chat_history # Yield the final history with the special response
                    logging.info(f"--- Request End (Special Case) --- User: {user_id} (Took {time.time() - start_time:.2f}s)")
                    return # Stop processing this message

            # 5. Prepare Context for LLM (skip if handling memory command)
            if not goto_response_logging:
                #    (Relationship, Personality Adaptation, Style Params, Flow Params)
                relationship_stage, relationship_depth = self.relationship_manager.get_relationship_stage_and_depth(user_id)
                # Adapt personality based on recent feedback before generating style
                self.personality_engine.adapt_from_feedback(user_id)
                personality_profile = self.personality_engine.get_current_personality(user_id)
                style_params = self.personality_engine.generate_style_parameters(user_id, relationship_stage, relationship_depth)
                flow_params_humanizer = self.conversation_flow_manager.determine_flow_parameters(emotion_analysis, relationship_stage)

            # Skip LLM processing if handling memory command
            if not goto_response_logging:
                # 6. Construct the LLM Prompt
                prompt = self._construct_llm_prompt(
                    user_message_text=user_message_text, user_id=user_id, user_profile=user_profile,
                    emotion_analysis=emotion_analysis, relationship_stage=relationship_stage,
                    relationship_depth=relationship_depth, personality_profile=personality_profile,
                    style_params=style_params, _chat_history=current_chat_history # Pass current history before user message
                )
                # Handle prompt generation errors
                if prompt.startswith("[ERROR:"):
                     raise ValueError(f"Failed to construct LLM prompt: {prompt}")

                # 7. Stream Response from LLM
                # Add placeholder for assistant response
                current_chat_history.append({"role": "assistant", "content": ""})
                yield current_chat_history # Show user message immediately

                # Initial "thinking" delay
                thinking_delay = random.uniform(0.4, 0.9)
                time.sleep(thinking_delay)
                current_chat_history[-1]['content'] = "..." # Indicate thinking
                yield current_chat_history

            # Skip LLM streaming if handling memory command
            if not goto_response_logging:
                raw_response_buffer = ""
                accumulated_chunk = ""
                stream_successful = False
                # Pass history *before* placeholder message
                llm_response_stream = self._generate_llm_response_stream(prompt, current_chat_history[:-1])

                for chunk in llm_response_stream:
                    stream_successful = True # Mark stream as successful if we receive any chunk
                    accumulated_chunk += chunk

                    # Process the accumulated chunk
                    # Yield updates periodically based on length to simulate typing
                    # Only yield if there's actual content to add to avoid rapid empty updates
                    if len(accumulated_chunk.strip()) >= 1: # Check for non-whitespace chars
                         raw_response_buffer += accumulated_chunk
                         current_chat_history[-1]['content'] = raw_response_buffer + "..." # Append ellipsis for streaming effect
                         yield current_chat_history
                         # Simulate typing delay based on chunk length
                         typing_delay = max(0.02, len(accumulated_chunk) * self.config.response_delay_base)
                         time.sleep(typing_delay)
                         accumulated_chunk = "" # Reset accumulator after yielding and sleeping

                # No need to process remaining accumulator separately here, it's handled above
                # No trailing "..." on the final update before humanization (will be handled later)


                # Handle stream failure or empty response from a *successful* stream start
                if not raw_response_buffer and stream_successful:
                     logging.warning(f"LLM stream started but yielded no text content for user {user_id}.")
                     final_response = random.choice(self.config.llm_error_recovery_phrases)
                     # Update the placeholder
                     current_chat_history[-1] = {"role": "assistant", "content": final_response}

                # Handle stream that never even started successfully
                elif not stream_successful:
                     logging.error(f"LLM stream failed to start or yield any content for user {user_id}.")
                     final_response = random.choice(self.config.llm_error_recovery_phrases)
                     current_chat_history[-1] = {"role": "assistant", "content": final_response}

                # If we have a response buffer, humanize it
                elif raw_response_buffer:
                    logging.debug(f"Raw LLM Response (Complete): '{raw_response_buffer}'")
                    # 7. Humanize Response
                    final_response = self._humanize_and_finalize_response(
                        raw_response=raw_response_buffer, user_id=user_id, emotion_analysis=emotion_analysis,
                        relationship_stage=relationship_stage, personality_profile=personality_profile,
                        style_params=style_params, flow_params=flow_params_humanizer, _user_profile=user_profile
                    )
                    logging.info(f"Final Humanized Response: '{final_response[:100]}...'")

                    # Determine if we should split the response into multiple messages
                    # More likely for closer relationships and longer messages
                    should_split = False
                    split_messages = [final_response]

                    # Consider splitting for all relationship stages, but with different probabilities
                    # Lower threshold for message length to encourage more splitting
                    if len(final_response) > 80:  # Much lower threshold
                        formality = personality_profile.get('formality', 0.3)  # Default to lower formality

                        # Base probability depends on relationship stage
                        if relationship_stage == 'acquaintance':
                            split_probability = 0.3  # Even acquaintances use chat style
                        elif relationship_stage == 'casual friend':
                            split_probability = 0.5
                        elif relationship_stage == 'friend':
                            split_probability = 0.7
                        elif relationship_stage == 'close friend':
                            split_probability = 0.8
                        else:
                            split_probability = 0.4

                        # Adjust based on formality
                        split_probability *= (1.0 - formality * 0.5)  # Reduce impact of formality

                        # Further increase probability for very long messages
                        if len(final_response) > 200:
                            split_probability += 0.2

                        should_split = random.random() < split_probability

                        if should_split:
                            # Try to split on sentence boundaries
                            try:
                                sentences = nltk.sent_tokenize(final_response)

                                # More aggressive splitting - even if just 2 sentences
                                if len(sentences) >= 2:
                                    # Determine how many messages to create
                                    num_messages = 2  # Default to 2 messages

                                    # For longer responses, consider more messages
                                    if len(sentences) >= 4 and random.random() < 0.5:
                                        num_messages = 3
                                    if len(sentences) >= 6 and random.random() < 0.3:
                                        num_messages = 4

                                    # For very close relationships, sometimes use even more fragmented messages
                                    if relationship_stage == 'close friend' and len(sentences) >= 5 and random.random() < 0.3:
                                        num_messages = min(5, len(sentences))

                                    # Create the messages
                                    if num_messages == 2:
                                        # Simple split into two messages
                                        split_point = max(1, len(sentences) // 2)  # At least 1 sentence in first message
                                        msg1 = " ".join(sentences[:split_point])
                                        msg2 = " ".join(sentences[split_point:])
                                        split_messages = [msg1, msg2]
                                    else:
                                        # More complex splitting
                                        split_messages = []
                                        sentences_per_msg = max(1, len(sentences) // num_messages)

                                        # Distribute sentences among messages
                                        for i in range(0, num_messages - 1):
                                            start_idx = i * sentences_per_msg
                                            end_idx = min((i + 1) * sentences_per_msg, len(sentences))
                                            if start_idx < end_idx:  # Ensure we have sentences to add
                                                msg = " ".join(sentences[start_idx:end_idx])
                                                split_messages.append(msg)

                                        # Add remaining sentences to the last message
                                        remaining_start = (num_messages - 1) * sentences_per_msg
                                        if remaining_start < len(sentences):
                                            msg = " ".join(sentences[remaining_start:])
                                            split_messages.append(msg)
                                else:
                                    # Try to split on other boundaries like commas or conjunctions
                                    text = final_response
                                    if len(text.split()) >= 8:  # At least 8 words
                                        # Find potential split points
                                        split_points = []

                                        # Look for commas
                                        comma_matches = list(re.finditer(r',\s+', text))
                                        for match in comma_matches:
                                            split_points.append(match.start())

                                        # Look for conjunctions
                                        conj_pattern = r'\s+(and|but|or|so|because)\s+'
                                        conj_matches = list(re.finditer(conj_pattern, text, re.IGNORECASE))
                                        for match in conj_matches:
                                            split_points.append(match.start())

                                        if split_points:
                                            # Choose a split point near the middle
                                            middle_idx = len(text) // 2
                                            closest_point = min(split_points, key=lambda x: abs(x - middle_idx))

                                            msg1 = text[:closest_point].strip()
                                            msg2 = text[closest_point:].strip()

                                            # Clean up the second message if it starts with a comma or conjunction
                                            msg2 = re.sub(r'^[,]\s+', '', msg2)
                                            msg2 = re.sub(r'^(and|but|or|so|because)\s+', '', msg2, flags=re.IGNORECASE)

                                            split_messages = [msg1, msg2]
                                        else:
                                            should_split = False
                                    else:
                                        should_split = False
                            except Exception:
                                should_split = False

                    # Update history with the final humanized response(s)
                    if should_split and len(split_messages) > 1:
                        # Replace the placeholder with the first message
                        current_chat_history[-1] = {"role": "assistant", "content": split_messages[0]}
                        # Yield the first message
                        yield current_chat_history

                        # Add a small delay between messages - vary by message length for realism
                        # Shorter delay for shorter messages
                        first_msg_length = len(split_messages[0])
                        first_delay = min(1.5, max(0.6, first_msg_length / 100))
                        time.sleep(random.uniform(first_delay * 0.8, first_delay * 1.2))

                        # Add the remaining messages with natural timing
                        for i, msg in enumerate(split_messages[1:]):
                            # Calculate a natural delay based on message length and position
                            msg_length = len(msg)

                            # Shorter messages = shorter delay (typing time)
                            base_delay = min(2.0, max(0.5, msg_length / 80))

                            # Add variation based on message content
                            if '?' in msg:  # Questions often come quicker
                                base_delay *= 0.8
                            if any(word in msg.lower() for word in ['wait', 'sorry', 'oops', 'forgot']):  # Corrections come quicker
                                base_delay *= 0.7
                            if i == len(split_messages) - 2:  # Last message sometimes has longer pause before it
                                base_delay *= 1.2

                            # Add randomness for natural feel
                            actual_delay = random.uniform(base_delay * 0.8, base_delay * 1.2)

                            # Add the message and yield
                            current_chat_history.append({"role": "assistant", "content": msg})
                            yield current_chat_history
                            time.sleep(actual_delay)
                    else:
                        # Single message - update the placeholder
                        current_chat_history[-1] = {"role": "assistant", "content": final_response}
                else:
                     # Should be covered by stream_successful checks, but safety net
                     logging.error(f"Reached end of generation with no response buffer and no stream failure logged explicitly.")
                     final_response = random.choice(self.config.llm_error_recovery_phrases)
                     current_chat_history[-1] = {"role": "assistant", "content": final_response}


                # Yield final complete response state (humanized or error recovery)
                yield current_chat_history

            # 8. Post-Response Processing (Log, Summarize, Memory, Relationship)
            # Log the final assistant message (humanized or error recovery)
            assistant_message_log_id = self.db_manager.log_chat_message(
                user_id, "assistant", final_response, prompted_by_user_log_id=user_message_log_id
            )
            if assistant_message_log_id != -1:
                 self._update_user_session(user_id, {'last_assistant_message_id': assistant_message_log_id})
            else:
                 logging.error(f"Failed to log final assistant response for user {user_id}.")

            # If this was a memory command that was handled earlier, we're done
            if goto_response_logging:
                logging.info(f"Memory command processed and logged for user {user_id}.")
                end_time = time.time()
                logging.info(f"--- Request End (Memory Command) --- User: {user_id} (Took {end_time - start_time:.2f}s)")
                return

            # Only summarize and store memory if the response was successfully generated (not an error recovery phrase)
            # and not a memory command (which already created its own memory)
            if not final_response.startswith("[") and not goto_response_logging:
                 # Summarize interaction for memory and relationship updates
                 interaction_summary = self._summarize_interaction(user_message_text, final_response)

                 # Store memory based on summary and analysis
                 if interaction_summary: # Use summary data if available
                      vulnerability_score = interaction_summary.get('vulnerability_score', 0.0)
                      insight_score = len(interaction_summary.get('key_insights', [])) * 0.1 # Simple insight score
                      self.memory_manager.store_interaction(
                          user_id=user_id, text=user_message_text, # Store user's text
                          emotion=emotion_analysis.get('primary_emotion', 'neutral'),
                          base_importance=np.clip(emotion_analysis.get('intensity', 0.1) * 0.5 + 0.1, 0.05, 0.7), # Base importance on intensity
                          vulnerability_score=vulnerability_score,
                          insight_score=insight_score,
                          related_chat_log_id=user_message_log_id
                      )
                      # Update relationship depth using the summary
                      self.relationship_manager.update_relationship_depth(user_id, interaction_summary)

                      # Extract facts for knowledge graph with conversation context
                      try:
                          # Get recent conversation history for context
                          recent_history = []
                          try:
                              with self.db_manager.get_connection() as conn:
                                  cursor = conn.cursor()
                                  cursor.execute(
                                      f"""
                                      SELECT * FROM {config.chat_table_name}
                                      WHERE user_id = ?
                                      ORDER BY timestamp DESC
                                      LIMIT 10
                                      """,
                                      (user_id,)
                                  )
                                  messages = cursor.fetchall()

                                  if messages:
                                      # Convert to list of dicts and reverse to chronological order
                                      recent_history = [dict(msg) for msg in messages]
                                      recent_history.reverse()

                                      # Format for context
                                      recent_history = [
                                          {
                                              "role": "assistant" if msg.get("is_from_bot") else "user",
                                              "content": msg.get("message_text", "")
                                          }
                                          for msg in recent_history if msg.get("message_text")
                                      ]
                          except Exception as db_error:
                              logging.error(f"Error getting chat history for fact extraction: {db_error}")

                          # Extract facts with context
                          fact_ids = self.knowledge_graph.extract_facts_from_message(
                              user_id=user_id,
                              message=user_message_text,
                              message_id=str(user_message_log_id),
                              context_messages=recent_history
                          )

                          if fact_ids:
                              logging.info(f"Extracted {len(fact_ids)} facts from message for user {user_id}")
                      except Exception as e:
                          logging.error(f"Error extracting facts for knowledge graph: {e}", exc_info=True)
                 else: # Store memory even if summarization failed, using basic info
                      logging.warning("Summarization failed, storing memory with basic importance.")
                      self.memory_manager.store_interaction(
                          user_id=user_id, text=user_message_text,
                          emotion=emotion_analysis.get('primary_emotion', 'neutral'),
                          base_importance=np.clip(emotion_analysis.get('intensity', 0.1) * 0.5 + 0.1, 0.05, 0.7),
                          vulnerability_score=0.0, insight_score=0.0, # No extra boosts
                          related_chat_log_id=user_message_log_id
                      )
                      # Apply decay only if no summary
                      self.relationship_manager.update_relationship_depth(user_id, None)

            end_time = time.time()
            logging.info(f"--- Request End --- User: {user_id} (Took {end_time - start_time:.2f}s)")

        except ValueError as ve: # Catch specific errors like profile not found or prompt error
             logging.error(f"ValueError during response generation for user {user_id}: {ve}", exc_info=True)
             error_message = f"[Sorry, an internal error occurred: {ve}. Please try again.]"
             # Ensure error message is added/updated correctly
             if not current_chat_history or current_chat_history[-1]['role'] != 'assistant':
                 current_chat_history.append({"role": "assistant", "content": error_message})
             else: current_chat_history[-1]['content'] = error_message
             yield current_chat_history
             # Attempt to log error
             try: self.db_manager.log_chat_message(user_id, "assistant", f"[ERROR_LOG] {error_message}", prompted_by_user_log_id=user_message_log_id)
             except Exception: pass
        except Exception as e:
            logging.error(f"CRITICAL Unhandled error during response generation for user {user_id}: {e}", exc_info=True)
            error_message = random.choice(self.config.llm_error_recovery_phrases)
            if not current_chat_history or current_chat_history[-1]['role'] != 'assistant':
                 current_chat_history.append({"role": "assistant", "content": error_message})
            else: current_chat_history[-1]['content'] = error_message
            yield current_chat_history
            # Attempt to log error
            try: self.db_manager.log_chat_message(user_id, "assistant", f"[ERROR_LOG] {error_message} (Orig Err: {type(e).__name__})", prompted_by_user_log_id=user_message_log_id)
            except Exception: pass


    def handle_user_message(self, message_text: str, history: List[Dict], user_id: str) -> Iterator[List[Dict]]:
         """Main entry point called by UI to handle user message and generate stream."""
         logging.debug(f"Handling message from user {user_id}")
         if not user_id:
              logging.error("handle_user_message called with no user_id.")
              # Yield an error message back to the UI
              yield history + [{"role": "assistant", "content": "[Error: User session invalid. Please login again.]"}]
              return
         if not message_text or not message_text.strip():
              logging.warning(f"Empty message received from user {user_id}.")
              yield history # Return current history, do nothing else
              return

         # ENHANCED: Periodically consolidate memories and reinforce important details
         if random.random() < 0.1:
             try:
                 # Run memory consolidation in the background
                 self.memory_manager.consolidate_memories(user_id)
                 # NEW: Proactive detail reinforcement
                 self.memory_manager.reinforce_important_details(user_id)
             except Exception as e:
                 logging.error(f"Error during periodic memory consolidation for user {user_id}: {e}")

         # NEW: Track message in active session
         self.time_awareness.increment_message_count(user_id)

         # NEW: Extract and store global knowledge (non-personal facts)
         try:
             knowledge_extraction = self.global_knowledge.extract_and_store_knowledge(message_text, user_id)
             if knowledge_extraction['general_facts']:
                 logging.info(f"Extracted {len(knowledge_extraction['general_facts'])} general facts from user message")
         except Exception as e:
             logging.error(f"Error in global knowledge extraction: {e}")

         # NEW: Track user interests and analyze preferences
         try:
             interest_analysis = self.interest_tracker.analyze_and_track_interests(user_id, message_text)
             if interest_analysis['detected_interests']:
                 logging.info(f"Detected interests in {len(interest_analysis['detected_interests'])} categories")
         except Exception as e:
             logging.error(f"Error in interest tracking: {e}")

         # Analyze user's response to any content we showed previously (updates frequency)
         try:
             self._analyze_user_response_to_content(user_id, message_text)
         except Exception as e:
             logging.error(f"Error analyzing content engagement: {e}")

         # NEW: Smart YouTube content integration with frequency control and decay
         try:
             # First, check if user has established interests
             user_interests = self.interest_tracker._get_user_interest_profile(user_id)
             top_categories = user_interests.get('top_categories', [])

             if top_categories:
                 # User has established interests, check each category with smart frequency
                 for category_name, confidence in top_categories[:2]:  # Check top 2 categories

                     # Only proceed if user has genuine interest (confidence > 0.3)
                     if confidence < 0.3:
                         continue

                     # Occasionally fetch content for user's interests (very low frequency)
                     if random.random() < 0.05:  # 5% chance to fetch new content
                         self.youtube_content_manager.fetch_content_for_user_interests(user_id, self.gemini_model, max_videos_per_category=1)

                     # Use smart frequency-based decision
                     if self.youtube_content_manager.should_introduce_content_to_user(user_id, category_name):
                         relevant_content = self.youtube_content_manager.get_relevant_content_for_user(user_id, user_interests, limit=1)

                         if relevant_content:
                             content = relevant_content[0]

                             # Check if this content relates to the current conversation
                             if self._is_content_relevant_to_conversation(message_text, content):
                                 # Generate a natural mention and store for potential use
                                 natural_mention = self.youtube_content_manager.generate_natural_content_mention(content, message_text)
                                 if natural_mention:
                                     # Record that we showed this content to the user (this updates frequency)
                                     self.youtube_content_manager.record_user_interaction(user_id, content['video_id'], 'shown')
                                     logging.info(f"Smart content mention for {user_id} ({category_name}): {content['title'][:40]}...")

                                     # Store the mention for potential use in the response
                                     self._store_content_mention_for_response(user_id, natural_mention, content)

                                     # Only show one piece of content per conversation
                                     break

         except Exception as e:
             logging.error(f"Error in smart YouTube content integration: {e}")

         # NEW: Occasionally share interesting updates (like a friend would)
         if random.random() < AppConstants.INTEREST_SHARING_PROBABILITY:  # Configurable chance to share
             try:
                 self._maybe_share_interesting_update(user_id)
             except Exception as e:
                 logging.error(f"Error sharing interesting update: {e}")

         # Call the main generation logic
         yield from self.generate_personalized_response(message_text, history, user_id)

    def handle_feedback(self, rating: int, feedback_type: str, user_id: str, history: List[Dict], comment: Optional[str] = None):
         """Handles user feedback from UI, logs it, triggers adaptations."""
         logging.info(f"Received feedback: User={user_id}, Type={feedback_type}, Rating={rating}, Comment='{comment[:30] if comment else 'No'}...'")
         if not user_id:
             logging.warning("Feedback received without user_id.")
             # Optionally raise error back to UI? For now, just log.
             return

         session = self._get_user_session(user_id)
         # Get the ID of the *last assistant message* that was likely rated
         last_assistant_message_id = session.get('last_assistant_message_id')
         last_message_content = None # Store content only if ID is missing

         # Fallback: If ID missing in session, try finding last assistant message in history
         if not last_assistant_message_id and history:
              logging.debug("Last assistant message ID not in session, searching history...")
              # Find the most recent assistant message in the provided history list
              for msg in reversed(history):
                   if msg.get('role') == 'assistant':
                        # If the history somehow contains DB IDs (less likely with streaming)
                        if isinstance(msg.get('id'), int):
                            last_assistant_message_id = msg.get('id')
                            logging.debug(f"Found potential last assistant message ID {last_assistant_message_id} from history dict.")
                            break
                        # If no ID, store the content as fallback
                        else:
                            last_message_content = msg.get('content')
                            logging.debug("Found last assistant message in history, storing content as fallback for feedback.")
                            break # Found the most recent assistant message

              # If still no ID, store content as fallback
              if not last_assistant_message_id:
                   for msg in reversed(history):
                        if msg.get('role') == 'assistant':
                            last_message_content = msg.get('content')
                            logging.debug("Could not find last assistant message ID, storing content as fallback.")
                            break

         # Log feedback to DB
         self.db_manager.log_feedback(
             user_id=user_id, rating=rating, feedback_type=feedback_type,
             chat_log_id=last_assistant_message_id, # Pass ID if found
             message_content=last_message_content, # Pass content if ID missing
             comment=comment # Pass comment
         )

         # Trigger personality adaptation based on this feedback
         self.personality_engine.adapt_from_feedback(user_id)

         # Trigger memory importance update if we have the assistant message ID
         if last_assistant_message_id:
             self.memory_manager.update_memory_from_feedback(user_id, last_assistant_message_id, rating)
         else:
              logging.warning(f"Cannot update memory importance from feedback: Last assistant message ID not found for user {user_id}.")

         logging.info("Feedback processed and adaptations triggered.")

    def remember(self, user_id: str, memory_text: str) -> bool:
        """Creates a long-term memory for the user.
        Returns True if successful, False otherwise.
        """
        if not user_id:
            logging.warning("Attempted to create memory without user_id.")
            return False

        return self.memory_manager.create_long_term_memory(user_id, memory_text)

    def get_initial_greeting(self, user_id: str) -> str:
        """Generates a time-aware context-aware initial greeting."""
        try:
            # Start session tracking
            session_info = self.time_awareness.start_session(user_id)

            # Get user profile and time context
            profile = self.db_manager.load_user_profile(user_id)
            time_context = self.time_awareness.get_time_context(user_id)

            user_name = profile.get('name') if profile else None

            # Get relationship context
            relationship_stage, relationship_depth = self.relationship_manager.get_relationship_stage_and_depth(user_id)

            # Generate time-aware greeting
            greeting = self._generate_time_aware_greeting(
                user_name, time_context, relationship_stage, relationship_depth, session_info
            )

            # Add festival greeting if applicable
            festival_info = self.festival_tracker.check_for_today()
            if festival_info:
                name, message = festival_info
                greeting += f" Oh, and Happy {name}! {message}"

            logging.info(f"Generated time-aware greeting for user {user_id}: '{greeting}' (Gap: {time_context['hours_since_last_chat']:.1f} hrs, Pattern: {time_context['conversation_pattern']})")
            return greeting

        except Exception as e:
            logging.error(f"Error generating time-aware greeting for user {user_id}: {e}")
            return "Hey! I'm Mandy. What brings you here today?"

    def _generate_time_aware_greeting(self, user_name: str, time_context: Dict,
                                    relationship_stage: str, relationship_depth: float,
                                    session_info: Dict) -> str:
        """Generate a sophisticated time-aware greeting based on conversation patterns."""

        # Extract time context
        gap_category = time_context['time_gap_category']
        conversation_pattern = time_context['conversation_pattern']
        is_usual_time = time_context['is_usual_chat_time']
        current_hour = time_context['current_hour']
        hours_since_last = time_context['hours_since_last_chat']

        # Base greeting variations
        casual_greetings = ["Hey", "Hi", "Hello", "Heya"]
        warm_greetings = ["Hey there", "Hi there", "Hello there"]
        close_greetings = ["Hey you", "Hi love", "Hello beautiful soul"]

        # Choose greeting style based on relationship
        if relationship_stage in ["close friend"] and relationship_depth > 40:
            greeting_start = random.choice(close_greetings)
        elif relationship_stage in ["friend", "close friend"]:
            greeting_start = random.choice(warm_greetings)
        else:
            greeting_start = random.choice(casual_greetings)

        # Add name if available
        if user_name:
            if relationship_stage in ["close friend"]:
                greeting_start += f" {user_name}"
            else:
                greeting_start += f" {user_name}"
        elif relationship_stage == "acquaintance":
            greeting_start += "! I'm Mandy"

        # Time-aware contextual additions
        time_additions = []

        # Gap-based responses
        if gap_category == 'just_now':
            time_additions.append("Back so soon? 😊")
        elif gap_category == 'few_hours':
            if conversation_pattern == 'frequent_chatter':
                time_additions.append("Good to see you again today!")
            else:
                time_additions.append("Nice to chat again!")
        elif gap_category == 'today':
            time_additions.append("Good to see you again today!")
        elif gap_category == 'yesterday':
            time_additions.append("Good to see you again!")
        elif gap_category == 'this_week':
            if conversation_pattern in ['daily_user', 'frequent_chatter']:
                time_additions.append("It's been a few days! How have you been?")
            else:
                time_additions.append("Good to see you again this week!")
        elif gap_category == 'this_month':
            time_additions.append("It's been a while! How have you been?")
        elif gap_category == 'long_time':
            time_additions.append("Wow, it's been quite a while! So good to see you back!")

        # Pattern-based responses
        if conversation_pattern == 'frequent_chatter' and hours_since_last > 6:
            time_additions.append("This is unusual for you - everything okay?")
        elif conversation_pattern == 'daily_user' and hours_since_last > 48:
            time_additions.append("I was wondering when you'd be back!")
        elif conversation_pattern == 'returning_user':
            time_additions.append("Welcome back! I've missed our chats.")

        # Time of day awareness
        if not is_usual_time and time_context['preferred_chat_times']:
            if current_hour < 6:
                time_additions.append("You're up early today!")
            elif current_hour > 23:
                time_additions.append("You're up late tonight!")
            elif current_hour in [12, 13]:
                time_additions.append("Lunch break chat?")
            elif current_hour in [17, 18, 19]:
                time_additions.append("Evening chat session!")

        # Conversation frequency awareness
        session_count = time_context.get('session_count_last_week', 0)
        if session_count > 10:
            time_additions.append("We've been chatting a lot lately - I love it!")
        elif session_count == 0 and conversation_pattern != 'new_user':
            time_additions.append("It's been quiet this week. Good to have you back!")

        # Combine greeting with time-aware additions
        if time_additions:
            if len(time_additions) > 1:
                # Choose the most relevant addition
                selected_addition = time_additions[0]  # First is usually most specific
            else:
                selected_addition = time_additions[0]

            full_greeting = f"{greeting_start}! {selected_addition}"
        else:
            # Default follow-ups based on relationship
            if relationship_stage == "close friend":
                follow_ups = ["How's everything going?", "What's on your mind today?", "How are you feeling?"]
            elif relationship_stage == "friend":
                follow_ups = ["How are things?", "What's new with you?", "How's your day been?"]
            else:
                follow_ups = ["What brings you here today?", "How can I help?", "What's on your mind?"]

            follow_up = random.choice(follow_ups)
            full_greeting = f"{greeting_start}! {follow_up}"

        return full_greeting

    def _format_global_knowledge(self, knowledge_results: List[Dict]) -> str:
        """Format global knowledge results for inclusion in prompts."""
        if not knowledge_results:
            return "No relevant global knowledge found."

        formatted_knowledge = []
        for knowledge in knowledge_results:
            confidence = knowledge.get('confidence_score', 0.0)
            source_count = knowledge.get('source_count', 1)
            text = knowledge.get('knowledge_text', '')
            category = knowledge.get('category', 'general')

            # Format with confidence indicator
            if confidence >= 0.8:
                confidence_indicator = "(high confidence)"
            elif confidence >= 0.6:
                confidence_indicator = "(medium confidence)"
            else:
                confidence_indicator = "(low confidence)"

            formatted_knowledge.append(f"- {text} {confidence_indicator} [Category: {category}, Sources: {source_count}]")

        return "\n".join(formatted_knowledge)

    def _format_interest_context(self, user_interests: Dict, personalized_updates: Dict) -> str:
        """Format user interests and personalized updates for inclusion in prompts."""
        if not user_interests and not personalized_updates:
            return "No specific interests detected yet."

        formatted_context = []

        # Format top interests
        top_categories = user_interests.get('top_categories', [])
        if top_categories:
            formatted_context.append("User's Top Interests:")
            for category, score in top_categories[:3]:
                confidence_level = "high" if score > 0.7 else "medium" if score > 0.4 else "emerging"
                formatted_context.append(f"- {category.title()}: {confidence_level} interest (score: {score:.2f})")

        # Format trending topics relevant to user
        trending_topics = personalized_updates.get('trending_topics', [])
        if trending_topics:
            formatted_context.append("\nRelevant Trending Topics:")
            for topic in trending_topics[:3]:
                title = topic.get('title', 'Unknown topic')
                category = topic.get('category', 'general')
                formatted_context.append(f"- {title} (Category: {category})")

        # Format recommendations
        recommendations = personalized_updates.get('recommendations', [])
        if recommendations:
            formatted_context.append("\nPersonalized Recommendations:")
            for rec in recommendations[:3]:
                formatted_context.append(f"- {rec}")

        return "\n".join(formatted_context) if formatted_context else "Building interest profile..."

    def _maybe_share_interesting_update(self, user_id: str):
        """Proactively share interesting updates based on user interests (like a friend would)."""
        try:
            # Get user interests
            user_interests = self.interest_tracker._get_user_interest_profile(user_id)

            # Only share if user has established interests
            top_categories = user_interests.get('top_categories', [])
            if not top_categories or top_categories[0][1] < 0.3:
                return  # Not enough interest data

            # Get personalized updates
            updates = self.interest_tracker.get_personalized_updates(user_id)
            trending_topics = updates.get('trending_topics', [])

            if trending_topics:
                # Find a topic worth sharing
                for topic in trending_topics:
                    if self.interest_tracker.should_share_update(user_id, topic):
                        # Store as a potential conversation starter
                        self._store_conversation_starter(user_id, topic)
                        logging.info(f"Stored interesting update for user {user_id}: {topic.get('title', 'Unknown')[:50]}...")
                        break

        except Exception as e:
            logging.error(f"Error in maybe_share_interesting_update: {e}")

    def _analyze_user_response_to_content(self, user_id: str, user_message: str):
        """Analyze user's response to content mentions and update engagement scores."""
        try:
            session = self._get_user_session(user_id)
            if 'last_content_shown' not in session:
                return

            last_content = session['last_content_shown']
            content = last_content['content']

            # Analyze user's response sentiment and engagement
            user_message_lower = user_message.lower()
            engagement_score = 0.0

            # Positive indicators
            positive_words = ['interesting', 'cool', 'wow', 'really', 'tell me more', 'that\'s great',
                            'amazing', 'awesome', 'yes', 'yeah', 'right', 'exactly', 'true', 'agree',
                            'love', 'like', 'good', 'nice', 'thanks', 'helpful']

            # Negative indicators
            negative_words = ['boring', 'not interested', 'don\'t care', 'whatever', 'stop',
                            'change topic', 'something else', 'not really', 'nah', 'no thanks',
                            'annoying', 'enough', 'tired']

            # Neutral/ignore indicators
            ignore_indicators = ['anyway', 'so', 'but', 'however', 'moving on', 'let\'s talk about',
                               'ok', 'hmm', 'sure', 'fine']

            # Count indicators
            positive_count = sum(1 for word in positive_words if word in user_message_lower)
            negative_count = sum(1 for word in negative_words if word in user_message_lower)
            ignore_count = sum(1 for word in ignore_indicators if word in user_message_lower)

            # Calculate engagement score
            if positive_count > 0:
                engagement_score = min(1.0, positive_count * 0.4)
            elif negative_count > 0:
                engagement_score = max(-1.0, -negative_count * 0.5)
            elif ignore_count > 0 or len(user_message.strip()) < 10:
                engagement_score = -0.3
            else:
                # Check if user continues the topic
                content_keywords = content.get('topics_mentioned', [])
                topic_continuation = any(keyword.lower() in user_message_lower for keyword in content_keywords[:5])
                engagement_score = 0.4 if topic_continuation else -0.1

            # Record the engagement (this will update frequency automatically)
            self.youtube_content_manager.record_user_interaction(
                user_id, content['video_id'], 'discussed', user_message, engagement_score
            )

            logging.info(f"User {user_id} engagement: {engagement_score:.2f} for '{content['title'][:30]}...'")

            # Clear the last content shown
            del session['last_content_shown']

        except Exception as e:
            logging.error(f"Error analyzing user response to content: {e}")

    def _is_content_relevant_to_conversation(self, user_message: str, content: Dict) -> bool:
        """Check if YouTube content is relevant to the current conversation context."""
        try:
            user_message_lower = user_message.lower()
            content_title = content.get('title', '').lower()
            content_category = content.get('category', '').lower()
            topics_mentioned = content.get('topics_mentioned', [])

            # Check for direct topic matches
            for topic in topics_mentioned:
                if topic.lower() in user_message_lower:
                    return True

            # Check for category relevance
            category_keywords = {
                'sports': ['sport', 'game', 'match', 'team', 'player', 'tournament', 'fitness', 'exercise'],
                'entertainment': ['movie', 'show', 'music', 'celebrity', 'film', 'series', 'entertainment'],
                'travel': ['travel', 'trip', 'vacation', 'place', 'country', 'city', 'visit'],
                'food': ['food', 'eat', 'cook', 'recipe', 'restaurant', 'meal', 'hungry'],
                'yoga': ['yoga', 'meditation', 'mindfulness', 'stretch', 'relax', 'stress'],
                'health': ['health', 'wellness', 'medical', 'doctor', 'fitness', 'diet', 'nutrition'],
                'business': ['business', 'work', 'job', 'career', 'money', 'finance', 'investment', 'startup', 'entrepreneur', 'success', 'wealth', 'trading', 'stock'],
                'podcast': ['podcast', 'interview', 'conversation', 'discussion', 'talk', 'listen', 'episode', 'show', 'guest', 'host', 'story', 'advice']
            }

            if content_category in category_keywords:
                keywords = category_keywords[content_category]
                for keyword in keywords:
                    if keyword in user_message_lower:
                        return True

            # Check for title word matches (at least 2 common words)
            title_words = set(content_title.split())
            message_words = set(user_message_lower.split())
            common_words = title_words.intersection(message_words)

            # Filter out common stop words
            stop_words = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by', 'is', 'are', 'was', 'were', 'be', 'been', 'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could', 'should', 'may', 'might', 'can', 'this', 'that', 'these', 'those'}
            meaningful_common_words = common_words - stop_words

            return len(meaningful_common_words) >= 2

        except Exception as e:
            logging.error(f"Error checking content relevance: {e}")
            return False

    def _store_content_mention_for_response(self, user_id: str, mention: str, content: Dict):
        """Store a content mention that could be naturally included in the response."""
        try:
            # Store in user session for potential use in current response
            session = self._get_user_session(user_id)
            if 'pending_content_mentions' not in session:
                session['pending_content_mentions'] = []

            session['pending_content_mentions'].append({
                'mention': mention,
                'content': content,
                'timestamp': get_current_date_time_iso()
            })

            # Keep only the most recent mention to avoid overwhelming
            session['pending_content_mentions'] = session['pending_content_mentions'][-1:]

            # Also store as last content shown for engagement tracking
            session['last_content_shown'] = {
                'content': content,
                'timestamp': get_current_date_time_iso()
            }

        except Exception as e:
            logging.error(f"Error storing content mention: {e}")

    def _store_conversation_starter(self, user_id: str, topic: Dict):
        """Store an interesting topic as a potential conversation starter."""
        try:
            # This could be stored in memory or used to influence next greeting
            # For now, we'll log it as a potential conversation enhancer
            title = topic.get('title', 'Interesting topic')
            category = topic.get('category', 'general')

            # Create a memory entry for this interesting topic
            memory_text = f"Found interesting {category} topic: {title}"
            self.memory_manager.create_memory(
                user_id=user_id,
                text=memory_text,
                emotion="curiosity",
                importance=0.3,
                memory_type="conversation_starter"
            )

        except Exception as e:
            logging.error(f"Error storing conversation starter: {e}")

    def _get_detailed_time_context(self, user_id: str, message: str) -> str:
        """Get detailed time context when user asks about timing."""
        try:
            # Check if user is asking about timing
            timing_keywords = ['when', 'last chat', 'last time', 'how long', 'ago', 'recent']
            message_lower = message.lower()

            if any(keyword in message_lower for keyword in timing_keywords):
                # Get detailed time information
                time_context = self.time_awareness.get_time_context(user_id)
                hours_since = time_context.get('hours_since_last_chat', 0)

                if hours_since < 1:
                    return f"We just chatted {int(hours_since * 60)} minutes ago"
                elif hours_since < 24:
                    return f"We last chatted {hours_since:.1f} hours ago"
                elif hours_since < 48:
                    return f"We last chatted yesterday ({hours_since:.0f} hours ago)"
                elif hours_since < 168:  # 1 week
                    days = int(hours_since / 24)
                    return f"We last chatted {days} day{'s' if days > 1 else ''} ago"
                else:
                    days = int(hours_since / 24)
                    return f"We last chatted {days} days ago - it's been a while!"

            return ""

        except Exception as e:
            logging.error(f"Error getting detailed time context: {e}")
            return ""

    def _get_direct_facts_for_question(self, user_id: str, question: str) -> str:
        """Get specific facts that directly answer the user's question."""
        try:
            question_lower = question.lower()

            # Define question patterns and corresponding fact searches
            question_patterns = {
                'study': ['where do i study', 'where am i studying', 'what college', 'which university', 'my college', 'my university'],
                'work': ['where do i work', 'my job', 'my company', 'where am i working'],
                'live': ['where do i live', 'my address', 'where am i from', 'my location'],
                'age': ['how old am i', 'my age', 'when was i born'],
                'name': ['what is my name', 'my name is', 'who am i'],
                'course': ['what do i study', 'my course', 'my major', 'my degree', 'my branch'],
                'family': ['my family', 'my parents', 'my siblings', 'my mother', 'my father']
            }

            # Check which type of question this is
            question_type = None
            for q_type, patterns in question_patterns.items():
                if any(pattern in question_lower for pattern in patterns):
                    question_type = q_type
                    break

            if not question_type:
                return ""

            # Search for relevant facts in knowledge graph
            relevant_facts = []

            # Get facts from knowledge graph
            try:
                facts = self.knowledge_graph.get_relevant_facts(user_id, question, limit=5)
                for fact in facts:
                    fact_content = fact.get('content', '').lower()

                    # Check if this fact answers the question
                    if question_type == 'study' and any(word in fact_content for word in ['study', 'college', 'university', 'bit', 'engineering']):
                        relevant_facts.append(fact['content'])
                    elif question_type == 'course' and any(word in fact_content for word in ['engineering', 'course', 'degree', 'branch', 'production']):
                        relevant_facts.append(fact['content'])
                    elif question_type == 'work' and any(word in fact_content for word in ['work', 'job', 'company']):
                        relevant_facts.append(fact['content'])
                    elif question_type == 'live' and any(word in fact_content for word in ['live', 'address', 'location', 'from']):
                        relevant_facts.append(fact['content'])

            except Exception as e:
                logging.debug(f"Error getting facts from knowledge graph: {e}")

            # Also search memories for relevant information
            try:
                memories = self.memory_manager.recall_memories(user_id, question, max_memories=5)
                for memory in memories:
                    memory_text = memory.get('text', '').lower()

                    if question_type == 'study' and any(word in memory_text for word in ['study', 'college', 'university', 'bit', 'engineering']):
                        relevant_facts.append(memory.get('text', ''))
                    elif question_type == 'course' and any(word in memory_text for word in ['engineering', 'course', 'production']):
                        relevant_facts.append(memory.get('text', ''))

            except Exception as e:
                logging.debug(f"Error searching memories: {e}")

            # Format the facts for the prompt
            if relevant_facts:
                unique_facts = list(set(relevant_facts))  # Remove duplicates
                formatted_facts = f"DIRECT ANSWER FACTS FOR '{question_type.upper()}' QUESTION:\n" + "\n".join(f"- {fact}" for fact in unique_facts[:3])
                formatted_facts += f"\n\nIMPORTANT: User asked '{question}' - answer directly using the facts above!"
                logging.info(f"Found {len(unique_facts)} direct facts for question type '{question_type}'")
                return formatted_facts
            else:
                return f"No specific facts found for question type: {question_type}"

        except Exception as e:
            logging.error(f"Error getting direct facts for question: {e}")
            return ""

    def _safe_sentence_tokenize(self, text: str) -> List[str]:
        """Robust sentence tokenization with multiple fallback methods."""
        if not text or not text.strip():
            return [text]

        # Method 1: Try NLTK punkt tokenizer
        try:
            sentences = nltk.sent_tokenize(text)
            if sentences and len(sentences) > 0:
                logging.debug("Used NLTK punkt tokenizer for sentence splitting")
                return sentences
        except LookupError:
            logging.debug("NLTK punkt data not available, trying fallback methods")
        except Exception as e:
            logging.debug(f"NLTK tokenization failed: {e}, trying fallback methods")

        # Method 2: Enhanced regex-based splitting
        try:
            # More sophisticated regex that handles common cases
            sentence_endings = r'(?<=[.!?])\s+(?=[A-Z])'
            sentences = re.split(sentence_endings, text.strip())

            # Clean up sentences
            sentences = [s.strip() for s in sentences if s.strip()]

            if sentences and len(sentences) > 0:
                logging.debug("Used enhanced regex for sentence splitting")
                return sentences
        except Exception as e:
            logging.debug(f"Enhanced regex splitting failed: {e}")

        # Method 3: Simple punctuation-based splitting
        try:
            # Basic split on sentence-ending punctuation
            sentences = re.split(r'[.!?]+', text)
            sentences = [s.strip() for s in sentences if s.strip()]

            # Add back punctuation to all but the last sentence
            for i in range(len(sentences) - 1):
                if sentences[i] and not sentences[i][-1] in '.!?':
                    sentences[i] += '.'

            if sentences and len(sentences) > 0:
                logging.debug("Used basic punctuation splitting")
                return sentences
        except Exception as e:
            logging.debug(f"Basic punctuation splitting failed: {e}")

        # Method 4: Fallback to single sentence
        logging.debug("All sentence splitting methods failed, returning as single sentence")
        return [text.strip()]

# === GRADIO UI (V4 - Connects to ChatManager V4) ===
def create_gradio_interface(chat_manager_obj: ChatManager, auth_manager_obj: AuthenticationManager) -> gr.Blocks:
    logging.info("Creating Gradio interface (V4)...")
    css = """
    #chatbot { min-height: 65vh; }
    footer { display: none !important; }
    .gradio-container { max-width: 800px !important; margin: auto; }
    #title { text-align: center; display: block; margin-bottom: 15px; }
    #auth_header { text-align: center; }
    #user_info { text-align: center; font-weight: bold; margin-bottom: 10px; color: #4a4a4a; }
    #auth_status { min-height: 20px; text-align: center; margin-top: 10px; font-weight: bold;}
    .feedback-row button { min-width: 40px !important; padding: 5px !important; margin: 0 3px !important; } /* Tighter margin */
    #feedback-comment { margin-top: 8px; }
    #feedback_accordion { border: 1px solid #e0e0e0; border-radius: 8px; margin-top: 15px; }
    #feedback_accordion .label-wrap { justify-content: center !important; font-weight: bold; }
    #feedback_status { min-height: 18px; margin-top: 5px; text-align: center; font-size: 0.9em;}
    #chat_area { min-height: 80vh; } /* Ensure chat area takes up space */
    """
    with gr.Blocks(theme=gr.themes.Soft(primary_hue="pink", secondary_hue="neutral", radius_size=gr.themes.sizes.radius_sm), css=css, title="Mandy AI Friend") as demo:
        # --- State Variables ---
        user_id_state = gr.State("")
        user_name_state = gr.State("Friend")
        chat_history_state = gr.State([]) # Stores [{'role': 'user'/'assistant', 'content': '...'}]
        is_logged_in = gr.State(False)

        with gr.Column():
            gr.Markdown("# Mandy - Your AI Friend 🫂", elem_id="title")
            user_info_md = gr.Markdown("", elem_id="user_info") # Shows logged-in user

            # --- Authentication Area ---
            with gr.Column(visible=True, elem_id="auth_area") as auth_area:
                 gr.Markdown("### Login or Register", elem_id="auth_header")
                 with gr.Row():
                     username_input = gr.Textbox(label="Username", placeholder="Enter username", scale=2)
                     password_input = gr.Textbox(label="Password", type="password", placeholder="Enter password", scale=2)
                 with gr.Row():
                     login_button = gr.Button("Login", variant="primary", scale=1)
                     register_button = gr.Button("Register", scale=1)
                 auth_status_md = gr.Markdown("", elem_id="auth_status") # Shows login/reg status

            # --- Chat Area ---
            with gr.Column(visible=False, elem_id="chat_area") as chat_area:
                chatbot = gr.Chatbot(
                    [], # Initially empty, populated on login
                    label="Chat with Mandy",
                    elem_id="chatbot",
                    # bubble_full_width parameter removed (deprecated)
                    height=550,
                    avatar_images=(None, "https://img.icons8.com/plasticine/100/female-user.png"),
                    show_label=False,
                    render_markdown=True,
                    type="messages"
                )
                with gr.Row():
                    input_box = gr.Textbox(
                        label="Your Message",
                        placeholder="Type your message here...",
                        scale=4,
                        autofocus=True,
                        show_label=False,
                        elem_id="input_box",
                        lines=1
                    )
                    send_button = gr.Button("Send", variant="primary", scale=1, min_width=100)

                # Feedback Section (Accordion)
                with gr.Accordion("Feedback on Mandy's Last Response", open=False, elem_id="feedback_accordion"):
                    gr.Markdown("How was the last response?", elem_id="feedback_md")
                    with gr.Row(elem_classes="feedback-row"):
                        fb_gen_good = gr.Button("👍", elem_id="fb_gen_good")
                        fb_gen_bad = gr.Button("👎", elem_id="fb_gen_bad")
                        fb_humor_good = gr.Button("😂", elem_id="fb_humor_good")
                        fb_humor_bad = gr.Button("😐", elem_id="fb_humor_bad")
                        fb_empathy_good = gr.Button("🫂", elem_id="fb_empathy_good")
                        fb_empathy_bad = gr.Button("🤖", elem_id="fb_empathy_bad")
                    feedback_comment_box = gr.Textbox(
                        placeholder="Add a comment (optional, submitted with rating)...",
                        lines=1,
                        show_label=False,
                        elem_id="feedback-comment"
                    )
                    feedback_status_md = gr.Markdown("", elem_id="feedback_status")

                # Control Buttons
                with gr.Row():
                    clear_button = gr.Button("Clear Chat")
                    logout_button = gr.Button("Logout")


        # --- Event Handlers ---

        # Registration
        def handle_register(username, password):
            success, message = auth_manager_obj.register_user(username, password)
            status_color = "green" if success else "red"
            return gr.update(value=f"<p style='color:{status_color}; text-align:center;'>{message}</p>")
        register_button.click(handle_register, inputs=[username_input, password_input], outputs=[auth_status_md])

        # Login
        def handle_login(username, password):
            success, user_id, message = auth_manager_obj.verify_user(username, password)
            if success and user_id:
                 user_name = chat_manager_obj.db_manager.get_user_name(user_id) or "Friend" # Get name
                 initial_greeting = chat_manager_obj.get_initial_greeting(user_id)
                 # Start history with only the greeting
                 initial_history_state = [{"role": "assistant", "content": initial_greeting}]
                 return {
                      auth_status_md: gr.update(value=f"<p style='color:green; text-align:center;'>Login successful!</p>"),
                      user_id_state: user_id,
                      user_name_state: user_name,
                      is_logged_in: True,
                      auth_area: gr.update(visible=False),
                      chat_area: gr.update(visible=True),
                      user_info_md: gr.update(value=f"Logged in as: **{user_name}**"),
                      # Set initial state and chatbot value
                      chat_history_state: initial_history_state,
                      chatbot: gr.update(value=initial_history_state),
                      input_box: gr.update(placeholder=f"Chat with Mandy, {user_name}..."),
                      feedback_status_md: "", feedback_comment_box: gr.update(value="")
                 }
            else:
                 return {
                      auth_status_md: gr.update(value=f"<p style='color:red;'>{message}</p>"),
                      user_id_state: "", user_name_state: "Friend", is_logged_in: False,
                      auth_area: gr.update(visible=True), chat_area: gr.update(visible=False),
                      user_info_md: "", chat_history_state: [], chatbot: [],
                      input_box: gr.update(placeholder="Type here..."), feedback_status_md: "",
                      feedback_comment_box: gr.update(value="")
                 }
        login_button.click( handle_login, inputs=[username_input, password_input],
                           outputs=[
                                auth_status_md, user_id_state, user_name_state, is_logged_in,
                                auth_area, chat_area, user_info_md, chat_history_state, chatbot, input_box,
                                feedback_status_md, feedback_comment_box
                           ]
                         )

        # Submit Message Handler (no change needed here)
        def handle_submit_and_respond(message: str, history_state: List[Dict], user_id: str):
            if not user_id:
                 logging.warning("Submit attempted without user_id.")
                 yield history_state, gr.update(placeholder="Please login first!"), history_state
                 return
            if not message or not message.strip():
                 logging.debug("Empty message submitted.")
                 yield history_state, gr.update(), history_state
                 return

            logging.info(f"User {user_id} submitted: '{message[:50]}...'")
            current_history = history_state + [{"role": "user", "content": message}]
            yield current_history, gr.update(value="", placeholder="Mandy is thinking..."), current_history

            logging.debug(f"Calling ChatManager stream for user {user_id}.")
            response_generator = chat_manager_obj.handle_user_message(message, current_history, user_id)
            final_history_state = current_history

            try:
                for updated_history_chunk in response_generator:
                    final_history_state = updated_history_chunk
                    yield final_history_state, gr.update(placeholder="Mandy is typing..."), final_history_state
                yield final_history_state, gr.update(placeholder="Type your message here..."), final_history_state
                logging.debug(f"Stream finished normally for user {user_id}.")
            except Exception as stream_err:
                 logging.error(f"Error during response streaming for user {user_id}: {stream_err}", exc_info=True)
                 yield final_history_state, gr.update(placeholder="Error processing response..."), final_history_state

        submit_triggers = [input_box.submit, send_button.click]
        gr.on(
             triggers=submit_triggers, fn=handle_submit_and_respond,
             inputs=[input_box, chat_history_state, user_id_state],
             outputs=[chat_history_state, input_box, chatbot],
        )

        # --- FIX: Reverted Feedback Handler ---
        def create_feedback_handler(feedback_type, rating):
            # This handler now takes 'comment' as input again
            def handler(user_id, history, comment): # Add comment input back
                if not user_id:
                    gr.Warning("Please login to provide feedback.")
                    # Return current comment box value if not logged in
                    return "", comment
                logging.debug(f"Feedback handler: User={user_id}, Type={feedback_type}, Rating={rating}, Comment={comment}")
                try:
                     # Pass the comment to the backend function
                     chat_manager_obj.handle_feedback(rating, feedback_type, user_id, history, comment)
                     feedback_message = f"Feedback ({feedback_type}: {'👍' if rating > 0 else '👎'}) registered. Thanks!"
                     gr.Info(feedback_message)
                     # Return update for status and CLEAR the comment box
                     return f"<p style='color:green;'>{feedback_message}</p>", ""
                except Exception as fb_err:
                     logging.error(f"Error handling feedback: {fb_err}", exc_info=True)
                     gr.Error("Sorry, there was an issue registering your feedback.")
                     # Keep comment text on error
                     return "<p style='color:red;'>Error saving feedback.</p>", comment
            return handler

        # Link feedback buttons back to the combined handler
        # Inputs now include feedback_comment_box
        # Outputs now include feedback_comment_box to clear it
        fb_gen_good.click(create_feedback_handler('general', 1), inputs=[user_id_state, chat_history_state, feedback_comment_box], outputs=[feedback_status_md, feedback_comment_box])
        fb_gen_bad.click(create_feedback_handler('general', -1), inputs=[user_id_state, chat_history_state, feedback_comment_box], outputs=[feedback_status_md, feedback_comment_box])
        fb_humor_good.click(create_feedback_handler('humor', 1), inputs=[user_id_state, chat_history_state, feedback_comment_box], outputs=[feedback_status_md, feedback_comment_box])
        fb_humor_bad.click(create_feedback_handler('humor', -1), inputs=[user_id_state, chat_history_state, feedback_comment_box], outputs=[feedback_status_md, feedback_comment_box])
        fb_empathy_good.click(create_feedback_handler('empathy', 1), inputs=[user_id_state, chat_history_state, feedback_comment_box], outputs=[feedback_status_md, feedback_comment_box])
        fb_empathy_bad.click(create_feedback_handler('empathy', -1), inputs=[user_id_state, chat_history_state, feedback_comment_box], outputs=[feedback_status_md, feedback_comment_box])
        # --- END FIX ---

        # --- FIX: Removed the separate handle_submit_comment function and its .click() binding ---

        # Clear Chat Handler (no change)
        def handle_clear_chat(user_id: str, user_name: str):
             if not user_id:
                 gr.Warning("Please login first.")
                 return [], [], ""
             initial_greeting = chat_manager_obj.get_initial_greeting(user_id)
             new_history_state = [{"role": "assistant", "content": initial_greeting}]
             logging.info(f"Chat cleared for user {user_id}")
             gr.Info("Chat cleared!")
             return new_history_state, new_history_state, gr.update(value="", placeholder=f"Chat cleared. Talk to Mandy, {user_name}...")
        clear_button.click(
            handle_clear_chat, inputs=[user_id_state, user_name_state],
            outputs=[chat_history_state, chatbot, input_box]
        )

        # Logout Handler (no change)
        def handle_logout():
            logging.info("User logging out.")
            return {
                 auth_area: gr.update(visible=True), chat_area: gr.update(visible=False),
                 user_id_state: "", user_name_state: "Friend", is_logged_in: False,
                 chat_history_state: [], chatbot: gr.update(value=[]),
                 auth_status_md: gr.update(value="<p style='color:blue;'>Logged out successfully.</p>"),
                 user_info_md: "", username_input: gr.update(value=""), password_input: gr.update(value=""),
                 input_box: gr.update(value="", placeholder="Type here..."), feedback_status_md: "",
                 feedback_comment_box: gr.update(value="")
            }
        logout_button.click(
            handle_logout, inputs=None,
            outputs=[
                 auth_area, chat_area, user_id_state, user_name_state, is_logged_in,
                 chat_history_state, chatbot, auth_status_md, user_info_md,
                 username_input, password_input, input_box,
                 feedback_status_md, feedback_comment_box
            ]
        )

    logging.info("Gradio interface created.")
    return demo

# === Rate Limiting and Request Validation ===
class RateLimiter:
    """
    Implements rate limiting for API requests to prevent abuse.
    Uses a token bucket algorithm for flexible rate limiting.
    """
    def __init__(self, rate: float = 10, per: float = 60, burst: int = 20):
        """
        Initialize rate limiter.

        Args:
            rate: Number of requests allowed per time period
            per: Time period in seconds
            burst: Maximum burst size (token bucket capacity)
        """
        self.rate = rate  # Tokens per second
        self.per = per  # Time period in seconds
        self.burst = burst  # Maximum bucket size

        # Initialize buckets for different users/IPs
        self.buckets = defaultdict(lambda: {"tokens": burst, "last_refill": time.time()})
        self.lock = threading.RLock()  # Thread-safe operations

    def check_rate_limit(self, identifier: str) -> Tuple[bool, float]:
        """
        Check if a request should be rate limited.

        Args:
            identifier: User ID or IP address

        Returns:
            Tuple of (allowed, retry_after)
        """
        with self.lock:
            bucket = self.buckets[identifier]
            now = time.time()

            # Refill tokens based on time elapsed
            time_passed = now - bucket["last_refill"]
            new_tokens = time_passed * (self.rate / self.per)
            bucket["tokens"] = min(self.burst, bucket["tokens"] + new_tokens)
            bucket["last_refill"] = now

            # Check if request can be processed
            if bucket["tokens"] >= 1:
                bucket["tokens"] -= 1
                return True, 0
            else:
                # Calculate retry after time
                retry_after = (1 - bucket["tokens"]) * (self.per / self.rate)
                return False, retry_after

    def get_remaining(self, identifier: str) -> int:
        """Get remaining tokens for an identifier."""
        with self.lock:
            bucket = self.buckets[identifier]
            now = time.time()

            # Refill tokens based on time elapsed (read-only)
            time_passed = now - bucket["last_refill"]
            new_tokens = time_passed * (self.rate / self.per)
            current_tokens = min(self.burst, bucket["tokens"] + new_tokens)

            return int(current_tokens)


class RequestValidator:
    """
    Validates and sanitizes user input to prevent security issues.
    """
    @staticmethod
    def validate_text_input(text: str, max_length: int = 10000) -> Tuple[bool, str, str]:
        """
        Validate and sanitize text input.

        Args:
            text: Input text to validate
            max_length: Maximum allowed length

        Returns:
            Tuple of (is_valid, sanitized_text, error_message)
        """
        if not isinstance(text, str):
            return False, "", "Input must be a string"

        # Check for empty input
        if not text.strip():
            return False, "", "Input cannot be empty"

        # Check length
        if len(text) > max_length:
            sanitized = text[:max_length]
            return True, sanitized, f"Input truncated to {max_length} characters"

        # SECURITY FIX: Enhanced sanitization
        # Remove control characters except newlines and tabs
        sanitized = ''.join(c for c in text if c == '\n' or c == '\t' or (ord(c) >= 32 and ord(c) != 127))

        # Additional security checks
        dangerous_patterns = [
            '<script', '</script>', 'javascript:', 'data:', 'vbscript:',
            'onload=', 'onerror=', 'onclick=', 'onmouseover=',
            'eval(', 'setTimeout(', 'setInterval('
        ]

        text_lower = sanitized.lower()
        for pattern in dangerous_patterns:
            if pattern in text_lower:
                # Remove the dangerous pattern
                sanitized = sanitized.replace(pattern, '')
                logging.warning(f"Removed dangerous pattern: {pattern}")

        # Limit consecutive special characters to prevent injection attempts
        import re
        sanitized = re.sub(r'[<>"\'\`]{3,}', '', sanitized)

        return True, sanitized, ""

    @staticmethod
    def validate_user_id(user_id: str) -> Tuple[bool, str]:
        """
        Validate user ID format.

        Args:
            user_id: User ID to validate

        Returns:
            Tuple of (is_valid, error_message)
        """
        if not isinstance(user_id, str):
            return False, "User ID must be a string"

        if not user_id:
            return False, "User ID cannot be empty"

        # Check for UUID format if using UUIDs
        try:
            uuid.UUID(user_id)
            return True, ""
        except ValueError:
            # If not using UUID format, check for other valid format
            if re.match(r'^[a-zA-Z0-9_-]{3,64}$', user_id):
                return True, ""
            return False, "Invalid user ID format"


# === Main Execution ===
if __name__ == "__main__":
    logging.info("--- Starting AI Friend Application V4 (Production) ---")

    # Initialize rate limiter for production
    chat_rate_limiter = RateLimiter(rate=5, per=60, burst=10)  # 5 requests per minute, burst of 10
    request_validator = RequestValidator()

    try:
        # Initialize core components
        db_manager = DatabaseManager(config.database_name)
        auth_manager = AuthenticationManager(db_manager)
        chat_manager = ChatManager(config, db_manager, auth_manager)

        # Initialize YouTube content scheduler
        def start_youtube_content_scheduler():
            """Start the background scheduler for YouTube content fetching."""
            try:
                import threading

                def smart_content_task():
                    """Smart task to fetch content only for active users with established interests."""
                    try:
                        logging.info("Starting smart YouTube content fetch...")

                        # Get active users with established interests
                        with db_manager.get_connection() as conn:
                            cursor = conn.cursor()

                            # Find users who have chatted in the last 7 days and have interests
                            cursor.execute('''
                                SELECT DISTINCT ui.user_id
                                FROM user_interests ui
                                JOIN chat_logs cl ON ui.user_id = cl.user_id
                                WHERE ui.confidence_score > 0.3
                                AND ui.mention_count >= 2
                                AND ui.is_active = 1
                                AND datetime(cl.timestamp) > datetime('now', '-7 days')
                                LIMIT 10
                            ''')

                            active_users = cursor.fetchall()

                            if not active_users:
                                logging.info("No active users with established interests found, skipping content fetch")
                                return

                            total_processed = 0
                            for (user_id,) in active_users:
                                try:
                                    processed = chat_manager.youtube_content_manager.fetch_content_for_user_interests(
                                        user_id, chat_manager.gemini_model, max_videos_per_category=1
                                    )
                                    total_processed += processed

                                    # Small delay between users to avoid rate limits
                                    time.sleep(2)

                                except Exception as e:
                                    logging.error(f"Error fetching content for user {user_id}: {e}")
                                    continue

                            logging.info(f"Smart content fetch completed. Processed {total_processed} videos for {len(active_users)} active users.")

                    except Exception as e:
                        logging.error(f"Error in smart content fetch: {e}")

                # Schedule smart content fetch twice daily (morning and evening)
                schedule.every().day.at("09:00").do(smart_content_task)
                schedule.every().day.at("18:00").do(smart_content_task)

                def run_scheduler():
                    """Run the scheduler in a separate thread."""
                    while True:
                        try:
                            schedule.run_pending()
                            time.sleep(3600)  # Check every hour
                        except Exception as e:
                            logging.error(f"Error in YouTube content scheduler: {e}")
                            time.sleep(3600)  # Continue after error

                # Start scheduler in background thread
                scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
                scheduler_thread.start()

                logging.info("Smart YouTube content scheduler started successfully (runs twice daily for active users)")

                # No initial content fetch - content will be fetched based on user interests as they develop

            except Exception as e:
                logging.error(f"Failed to start YouTube content scheduler: {e}")

        # Start the YouTube content scheduler
        start_youtube_content_scheduler()

        # Log system information for diagnostics
        logging.info(f"Python version: {sys.version}")
        logging.info(f"Operating system: {sys.platform}")
        if torch.cuda.is_available():
            logging.info(f"CUDA available: {torch.cuda.get_device_name(0)}")
        else:
            logging.info("CUDA not available, using CPU")

    except Exception as e:
        logging.critical(f"FATAL: Failed to initialize core components: {e}", exc_info=True)
        print(f"FATAL ERROR during startup: {e}")
        print("Please check logs and configuration (especially API keys and model access).")

        # Attempt to show error in Gradio if possible
        try:
            with gr.Blocks(theme=gr.themes.Soft()) as error_demo:
                gr.Markdown("# 🚨 Application Startup Failed! 🚨")
                gr.Markdown(f"**Error:** `{e}`")
                gr.Markdown(f"Could not initialize core components. Please check the logs (`{config.database_name.replace('.db', '')}.log`) for details.")
                gr.Markdown("Common issues include: Invalid API keys, model access problems, DB connection errors, or missing dependencies.")
            error_demo.launch(server_name="0.0.0.0", show_error=True)
            time.sleep(30)  # Keep error message visible for a bit
        except Exception as ge:
            logging.error(f"Could not launch Gradio error UI: {ge}")
        exit(1)

    try:
        # Create and launch Gradio interface
        demo = create_gradio_interface(chat_manager, auth_manager)
        logging.info("Launching Gradio interface...")

        # Get configuration from environment
        share_flag = os.getenv("GRADIO_SHARE", "false").lower() == 'true'
        server_port = int(os.getenv("SERVER_PORT", "7861"))  # Changed default port to 7861
        server_name = os.getenv("SERVER_NAME", "0.0.0.0")

        if share_flag:
            logging.warning("Gradio sharing enabled via GRADIO_SHARE env var. Use with caution.")

        # Configure queue for better performance
        demo.queue(
            max_size=20          # Queue up to 20 requests
        )

        # Launch with production settings
        demo.launch(
            share=share_flag,
            debug=False,
            server_name=server_name,
            server_port=server_port,
            show_error=True,
            favicon_path="favicon.ico" if os.path.exists("favicon.ico") else None
        )

        logging.info("Gradio application closed.")

    except Exception as e:
        logging.critical(f"FATAL: Failed to create or launch Gradio interface: {e}", exc_info=True)
        print(f"FATAL ERROR launching Gradio: {e}")
        exit(1)
