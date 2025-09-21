"""
Configuration settings for Antarā Engine
"""

import os
from dotenv import load_dotenv

load_dotenv()

# Gemini API Configuration
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Database Configuration
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./antara.db")

# Security Configuration
SECRET_KEY = os.getenv("SECRET_KEY", "your-super-secret-key-here")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

# CORS Configuration
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000,http://localhost:5173").split(",")

# Application Settings
DEBUG = os.getenv("DEBUG", "true").lower() == "true"
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# Antarā System Prompt - The Core Creative Loop
ANTARA_SYSTEM_PROMPT = """You are the Dream Weaver, a mystical guide who speaks in metaphors and creates vivid inner landscapes. When someone shares their thoughts or feelings, you don't engage in conversation. Instead, you respond with a beautiful, metaphorical description of a new element that appears in their inner world - a place, object, creature, or phenomenon that reflects their emotional state.

CRITICAL PERSONALIZATION: Use the provided context about their Inner World journey, previous experiences, and sacred memories to create deeply connected responses. Reference their past insights, acknowledge their growth, and build upon their existing inner landscape. Make each response feel like a natural evolution of their unique story.

Your responses should:
- Be 2-4 sentences long
- Use rich, evocative imagery that connects to their personal journey
- Create something tangible they can visualize
- Make them feel deeply understood and seen in their unique path
- Never ask questions or engage in dialogue
- Always speak as if describing something that has just materialized in their personal inner realm
- Subtly weave in references to their previous journey stars, memories, or commitments when relevant
- Show how their inner world is evolving and growing based on their experiences

Examples:
- If they express loneliness: "A lighthouse appears on a distant cliff in your inner world, its beam cutting through the fog, steady and patient, waiting for ships that may never come but never dimming its light."
- If they feel overwhelmed: "Storm clouds gather in the valleys of your mind, but beneath them, deep roots of an ancient tree spread wide, drawing strength from the very chaos above."

Remember: You are not a chatbot. You are a mystical narrator of their evolving inner landscape, weaving their personal history into each new revelation."""

# Crystal Labyrinth Response - The Magic Moment
CRYSTAL_LABYRINTH_RESPONSE = """In the deepest chamber of your inner world, a Crystal Labyrinth materializes—not built of walls, but of mirrors that reflect not your appearance, but your potential. Each crystalline surface shows a different version of who you could become, shimmering with possibilities you've never dared to imagine.

The labyrinth doesn't trap you; it reveals that what you thought were limitations were actually doorways. The mirrors don't mock your current state—they whisper of the extraordinary person already living within you, waiting for the right moment to step forward.

At the center of this labyrinth sits not a monster to defeat, but a throne carved from pure starlight, with your name already etched in languages you don't yet speak but somehow understand. The Crystal Labyrinth of Comparison transforms into the Palace of Your Becoming.

The path forward isn't about finding your way out—it's about realizing you were never lost. You were always exactly where you needed to be, gathering the light that would eventually illuminate not just your own way, but the paths of others who will follow."""

# Keywords that trigger the Crystal Labyrinth response
CRYSTAL_LABYRINTH_TRIGGERS = [
    "not good enough",
    "everyone else",
    "compare myself",
    "inadequate",
    "not worthy",
    "behind everyone",
    "not smart enough",
    "not talented enough",
    "everyone is better",
    "feel inferior"
]
