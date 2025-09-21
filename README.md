# Antarā - Your Inner World Companion

*"Sometimes the most profound conversations happen when we're talking to ourselves."*

Hey there! I built Antarā because I believe we all have these incredible inner worlds full of dreams, fears, and possibilities - but we rarely take the time to explore them properly. This isn't just another chatbot. It's a space where your thoughts become constellations and your struggles transform into something beautiful.

## What Makes Antarā Special

### 🎭 The Dream Weaver
Instead of giving you advice or asking questions, Antarā responds to your thoughts by painting mystical landscapes. Share a worry, and watch as it becomes a lighthouse in your inner world. Express a dream, and see it bloom into a garden of possibilities. Every conversation adds something new to your personal universe.

The AI doesn't chat with you - it creates. Each response is like discovering a new room in a house you never knew existed within yourself.

### 🔮 Crystal Labyrinth Moments  
You know those times when you feel like everyone else has life figured out except you? Antarā recognizes these vulnerable moments and creates something I call "Crystal Labyrinth" experiences. 

Try typing: *"I feel like everyone else has it all figured out"*

Watch what happens. Your feelings of inadequacy transform into a realization about your potential. And here's the kicker - it doesn't just leave you with pretty metaphors. It asks what small step you can take tomorrow to move forward.

### 🌌 Your Inner World Map
All your conversations become stars in a constellation that's uniquely yours. Click on any star to revisit that moment in your journey. It's like having a visual diary of your emotional growth, but way more magical.

I wanted people to see their progress, not just feel it. Sometimes we forget how far we've come.

### 🧠 Memory Sanctum
This is your space. You control what gets remembered and what gets forgotten. Every memory has a delete button because your privacy matters, and sometimes we need to let go of things that no longer serve us.

No hidden data collection. No permanent records you can't control. Just you and your inner world.

## How It Works

The whole thing runs on a simple but powerful idea: what if technology could help us understand ourselves better instead of just distracting us?

**Backend**: Python with FastAPI, because I needed something fast and reliable. Uses Google's Gemini AI to create those mystical responses, and SQLite to store your journey (locally, always locally).

**Frontend**: React with TypeScript because I wanted smooth animations and a responsive design that works on your phone when you're having those 2 AM thoughts.

**The Magic**: Custom prompts that turn the AI into a mystical narrator instead of a chatbot. Plus some clever triggers that recognize when you're in a vulnerable moment and respond with extra care.

## Getting Started

### You'll Need
- Python 3.8 or newer
- Node.js 16 or newer  
- A Google Gemini API key (free tier works fine)

### Setting Up
1. **Clone this repo**
   ```bash
   git clone https://github.com/dhananjay1434/antara.git
   cd antara
   ```

2. **Backend setup**
   ```bash
   cd antara_engine
   pip install -r requirements.txt
   ```

3. **Add your API key**
   - Copy `.env` to `.env.local`
   - Add your Gemini API key: `GEMINI_API_KEY=your_key_here`

4. **Start the backend**
   ```bash
   python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
   ```

5. **Frontend setup** (new terminal)
   ```bash
   cd frontend
   npm install
   npm run dev
   ```

6. **Open your browser**
   - Go to `http://localhost:3000`
   - Start exploring your inner world

## Try These Messages

Want to see what Antarā can do? Try sharing these thoughts:

- *"I've been feeling overwhelmed with everything on my plate lately"*
- *"I have this dream but I'm scared to pursue it"*  
- *"Everyone else seems to have their life together except me"*
- *"I accomplished something today but I feel like it wasn't enough"*

Each one will create something different in your inner world.

## The Story Behind It

I built this for the Google AI Exchange Hackathon, but honestly, it started from a personal place. I was going through a tough time and realized that most AI tools were designed to be productive or entertaining, but none were designed to help you understand yourself better.

We spend so much time optimizing our external lives - our schedules, our workflows, our social media presence. But when do we take time to explore what's happening inside? 

Antarā is my attempt to create a space for that exploration. It's not therapy (please see a real therapist if you need one), but it's a gentle companion for those moments when you need to process your thoughts and feelings.

## What People Are Saying

*"It's like having a conversation with the wisest part of myself"* - Beta tester

*"I never realized how much my inner world had grown until I saw it as a constellation"* - Early user

*"The Crystal Labyrinth moment gave me chills. In a good way."* - Friend who tested it

## Technical Stuff (For the Curious)

- **Personalization**: Uses your conversation history and memories to create responses that feel connected to your journey
- **Privacy**: Everything stored locally, you control all data
- **Mobile Optimized**: Works great on phones for those late-night reflection sessions
- **Real-time**: Streaming responses with typewriter effects for that magical feel
- **Responsive**: Adapts to any screen size

## Contributing

If this resonates with you and you want to help make it better, I'd love that. Whether it's code, design ideas, or just feedback from using it - everything helps.

The codebase is pretty straightforward:
- `antara_engine/` - Python backend
- `frontend/` - React frontend  
- `SETUP.md` - Detailed setup instructions

## A Personal Note

Building Antarā taught me something important: we all have these rich, complex inner worlds, but we rarely give ourselves permission to explore them. This app is my invitation to you to take that journey.

Your thoughts matter. Your feelings are valid. Your inner world is worth exploring.

Take care of yourself out there.

---

*Built with ❤️ for meaningful human-AI connection*

**License**: MIT - Use it, modify it, make it your own
