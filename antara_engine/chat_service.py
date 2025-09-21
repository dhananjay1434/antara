"""
Chat service for Antarā Engine - The Dream Weaver AI
"""

import google.generativeai as genai
from sqlalchemy.orm import Session
from database import ChatMessage, User, Memory, WorldNode
from config import GEMINI_API_KEY, ANTARA_SYSTEM_PROMPT, CRYSTAL_LABYRINTH_RESPONSE, CRYSTAL_LABYRINTH_TRIGGERS
import logging
from datetime import datetime

# Configure Gemini
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel('gemini-1.5-flash')
else:
    model = None
    logging.warning("GEMINI_API_KEY not found. Chat service will use fallback responses.")

logger = logging.getLogger(__name__)


class ChatService:
    def __init__(self):
        self.model = model
    
    def check_crystal_labyrinth_trigger(self, user_input: str) -> bool:
        """Check if user input contains Crystal Labyrinth trigger keywords"""
        user_input_lower = user_input.lower()
        return any(trigger in user_input_lower for trigger in CRYSTAL_LABYRINTH_TRIGGERS)
    
    async def generate_response(self, user_input: str, user_id: str, db: Session) -> tuple[str, int | None]:
        """Generate AI response using Dream Weaver system prompt"""

        node_id_for_frontend = None

        # Feature #2: Check for Crystal Labyrinth trigger first
        if self.check_crystal_labyrinth_trigger(user_input):
            logger.info(f"Crystal Labyrinth triggered for user {user_id}")

            # Create the World Node immediately for Magic Moment
            try:
                world_node = WorldNode(
                    user_id=user_id,
                    title="The Crystal Labyrinth of Comparison",
                    summary="A profound metaphor for the user's feelings of inadequacy and comparison."
                )
                db.add(world_node)
                db.commit()
                db.refresh(world_node)
                node_id_for_frontend = world_node.id
                logger.info(f"Created Crystal Labyrinth world node {world_node.id} for user {user_id}")
            except Exception as e:
                logger.error(f"Error creating Crystal Labyrinth world node: {e}")

            return CRYSTAL_LABYRINTH_RESPONSE, node_id_for_frontend
        
        # Feature #1: Use Dream Weaver AI for normal responses
        if not self.model:
            return self._fallback_response(user_input), None
        
        try:
            # Get recent chat history for context
            recent_messages = db.query(ChatMessage).filter(
                ChatMessage.user_id == user_id
            ).order_by(ChatMessage.timestamp.desc()).limit(5).all()
            
            # Build context
            context = ""
            if recent_messages:
                context = "\n".join([
                    f"{msg.role}: {msg.content}" 
                    for msg in reversed(recent_messages)
                ])
            
            # Create prompt with system instructions and context
            full_prompt = f"{ANTARA_SYSTEM_PROMPT}\n\nRecent context:\n{context}\n\nUser: {user_input}\n\nDream Weaver:"
            
            # Generate response
            response = self.model.generate_content(full_prompt)
            ai_response = response.text.strip()
            
            # Feature #3: Check if this should create a world node
            await self._maybe_create_world_node(user_input, ai_response, user_id, db)

            # Feature #4: Create memory for meaningful conversations
            await self._maybe_create_memory(user_input, ai_response, user_id, db)

            return ai_response, None

        except Exception as e:
            logger.error(f"Error generating AI response: {e}")
            return self._fallback_response(user_input), None
    
    def _fallback_response(self, user_input: str) -> str:
        """Fallback response when AI is not available"""
        return "A gentle mist swirls in your inner world, carrying whispers of understanding that will soon take clearer form."
    
    async def _maybe_create_world_node(self, user_input: str, ai_response: str, user_id: str, db: Session):
        """Create a world node if the conversation is significant enough"""
        
        # Only create nodes for substantial user inputs (>20 words as specified)
        if len(user_input.split()) <= 20:
            return
        
        try:
            if self.model:
                # Use AI to create a summary for the world node
                summary_prompt = f"""Based on this conversation exchange, create a brief, poetic title and summary for a 'star' in the user's inner world constellation:

User: {user_input}
Response: {ai_response}

Provide a response in this format:
Title: [A poetic 2-4 word title]
Summary: [A single sentence describing the theme or insight]"""
                
                summary_response = self.model.generate_content(summary_prompt)
                summary_text = summary_response.text.strip()
                
                # Parse the response
                lines = summary_text.split('\n')
                title = "New Star"
                summary = "A moment of connection and understanding."
                
                for line in lines:
                    if line.startswith("Title:"):
                        title = line.replace("Title:", "").strip()
                    elif line.startswith("Summary:"):
                        summary = line.replace("Summary:", "").strip()
                
                # Create the world node
                world_node = WorldNode(
                    user_id=user_id,
                    title=title,
                    summary=summary
                )
                
                db.add(world_node)
                db.commit()
                
                logger.info(f"Created world node '{title}' for user {user_id}")
                
        except Exception as e:
            logger.error(f"Error creating world node: {e}")

    async def _maybe_create_memory(self, user_input: str, ai_response: str, user_id: str, db: Session):
        """Create a memory if the conversation contains meaningful personal information"""

        # Create memories for substantial conversations (>15 words)
        if len(user_input.split()) <= 15:
            return

        try:
            if self.model:
                # Use AI to determine if this should be remembered and extract key insights
                memory_prompt = f"""Analyze this conversation and determine if it contains meaningful personal information that should be remembered about the user. If yes, extract the key insight in 1-2 sentences.

User: {user_input}
Response: {ai_response}

If this conversation reveals something meaningful about the user's feelings, struggles, goals, or personal situation, respond with:
REMEMBER: [1-2 sentences summarizing what to remember about the user]

If this is just casual conversation without meaningful personal content, respond with:
SKIP: Not significant enough to remember

Be selective - only remember truly meaningful personal insights."""

                memory_response = self.model.generate_content(memory_prompt)
                memory_text = memory_response.text.strip()

                if memory_text.startswith("REMEMBER:"):
                    memory_content = memory_text.replace("REMEMBER:", "").strip()

                    # Determine importance (1-10 scale based on emotional depth)
                    importance = 5.0  # Default medium importance
                    if any(word in user_input.lower() for word in ['struggle', 'overwhelmed', 'lost', 'afraid', 'anxious', 'depressed']):
                        importance = 8.0  # High importance for emotional content
                    elif any(word in user_input.lower() for word in ['goal', 'dream', 'hope', 'want', 'wish']):
                        importance = 7.0  # High importance for aspirational content
                    elif len(user_input.split()) > 30:
                        importance = 6.0  # Medium-high for longer, detailed sharing

                    # Create the memory
                    await self.create_memory(user_id, memory_content, importance, db)
                    logger.info(f"Created memory for user {user_id}: {memory_content[:50]}...")

        except Exception as e:
            logger.error(f"Error creating memory: {e}")

    async def save_message(self, user_id: str, role: str, content: str, db: Session):
        """Save a chat message to the database"""
        try:
            message = ChatMessage(
                user_id=user_id,
                role=role,
                content=content
            )
            db.add(message)
            db.commit()
            
        except Exception as e:
            logger.error(f"Error saving message: {e}")
    
    async def create_memory(self, user_id: str, text: str, importance: float, db: Session):
        """Create a memory entry"""
        try:
            memory = Memory(
                user_id=user_id,
                text=text,
                importance=importance
            )
            db.add(memory)
            db.commit()

        except Exception as e:
            logger.error(f"Error creating memory: {e}")

    async def anchor_action_to_node(self, node_id: int, user_action: str, db: Session):
        """Anchor a user action to a specific world node"""
        try:
            world_node = db.query(WorldNode).filter(WorldNode.id == node_id).first()

            if not world_node:
                raise ValueError("World node not found")

            world_node.user_action = user_action
            db.commit()

            logger.info(f"Anchored action to world node {node_id}: {user_action[:50]}...")
            return {"message": "Action anchored successfully"}

        except Exception as e:
            logger.error(f"Error anchoring action to node {node_id}: {e}")
            raise


# Global chat service instance
chat_service = ChatService()
