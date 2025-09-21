# Antarā - Your Inner World Awaits

> *"Where thoughts become constellations and memories find their sanctuary"*

Antarā is a mystical AI companion that transforms conversations into beautiful inner landscapes. Built with FastAPI and React, it demonstrates four powerful features that showcase the depth of human-AI connection.

## 🌟 The Four Mandated Features

### Feature #1: The Dream Weaver AI (Core Creative Loop)
- **What it does**: Responds to user thoughts with evocative, metaphorical descriptions of new elements in their inner world
- **Technology**: Gemini AI with custom ANTARA_SYSTEM_PROMPT
- **Experience**: Non-conversational, deeply understanding responses that make users feel heard

### Feature #2: The Crystal Labyrinth (Magic Moment Trigger)
- **What it does**: Detects expressions of inadequacy and responds with a profound, pre-written metaphor
- **Technology**: Keyword detection with hardcoded response bypass
- **Experience**: A "wow" moment that demonstrates the app's transformative potential

### Feature #3: Visual Inner World Map (Tangible Journey)
- **What it does**: Creates a constellation of "stars" representing significant conversations
- **Technology**: Automatic world node creation + interactive React visualization
- **Experience**: Users can see their emotional journey as a beautiful star map

### Feature #4: Memory Sanctum (Foundation of Trust)
- **What it does**: Complete user control over AI memories with view and delete functionality
- **Technology**: Memory management API with permanent deletion
- **Experience**: Reinforces trust through transparency and control

## 🏗️ Architecture

### Backend (`antara_engine/`)
- **FastAPI** application with SQLAlchemy ORM
- **Gemini AI** integration for creative responses
- **SQLite** database with user, chat, memory, and world node tables
- **CORS** enabled for frontend communication

### Frontend (`frontend/`)
- **React 18** with TypeScript
- **Vite** for fast development and building
- **Tailwind CSS** for mystical, responsive design
- **Framer Motion** for smooth animations

## 🚀 Quick Start

### Prerequisites
- Python 3.8+
- Node.js 16+
- Gemini API key

### Backend Setup
```bash
cd antara_engine
pip install -r requirements.txt
cp .env.example .env
# Add your GEMINI_API_KEY to .env
python main.py
```

### Frontend Setup
```bash
cd frontend
npm install
cp .env.example .env
# Update VITE_API_URL if needed
npm run dev
```

## 🌐 Deployment

### Backend (Render)
1. Connect your repository to Render
2. Use the provided `render.yaml` configuration
3. Set environment variables (especially `GEMINI_API_KEY`)

### Frontend (Vercel)
1. Connect your repository to Vercel
2. Set build command: `npm run build`
3. Set output directory: `dist`
4. Update `VITE_API_URL` to your backend URL

## 🎨 Design Philosophy

Antarā is designed around the concept of **mystical connection**:
- **Colors**: Deep cosmic blues and mystical pinks
- **Typography**: Clean, readable fonts with ethereal spacing
- **Animations**: Gentle, floating elements that feel alive
- **Interactions**: Smooth, responsive, and emotionally resonant

## 🔮 The Magic Behind the Scenes

### Dream Weaver System Prompt
The AI uses a carefully crafted system prompt that transforms it from a chatbot into a mystical narrator of inner landscapes.

### Crystal Labyrinth Triggers
Keywords like "not good enough" and "everyone else" trigger the profound Crystal Labyrinth response.

### Constellation Algorithm
World nodes are positioned using a golden angle spiral for natural, beautiful distribution.

## 📁 Project Structure

```
antarā/
├── antara_engine/          # FastAPI backend
│   ├── main.py            # Main application
│   ├── database.py        # Database models
│   ├── chat_service.py    # AI chat logic
│   ├── config.py          # Configuration
│   └── render.yaml        # Deployment config
├── frontend/              # React frontend
│   ├── src/
│   │   ├── components/    # React components
│   │   ├── services/      # API services
│   │   └── App.tsx        # Main app
│   ├── package.json
│   └── vercel.json        # Deployment config
└── README.md
```

## 🌟 Key Features Demonstrated

1. **Real-time AI Chat** with streaming typewriter effects
2. **Interactive Constellation Map** with clickable stars
3. **Memory Management** with permanent deletion
4. **Responsive Design** that works on all devices
5. **Deployment Ready** with production configurations

## 🎯 Demo Flow

1. **Start**: User opens the app and sees the mystical interface
2. **Chat**: User shares a feeling, AI responds with beautiful metaphor
3. **Magic Moment**: User expresses inadequacy, triggers Crystal Labyrinth
4. **Explore**: User views their Inner World constellation
5. **Control**: User manages memories in the Memory Sanctum

## 🔧 Development

### Adding New Features
1. Backend: Add endpoints in `main.py`
2. Frontend: Create components in `src/components/`
3. Database: Update models in `database.py`

### Customization
- Modify `ANTARA_SYSTEM_PROMPT` in `config.py`
- Update colors in `tailwind.config.js`
- Add new triggers in `CRYSTAL_LABYRINTH_TRIGGERS`

## 📜 License

This project is part of the Antarā prototype demonstration.

---

*Built with ✨ for the Google AI Exchange Hackathon*
