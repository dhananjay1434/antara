# 🚀 Antarā Setup Guide

## 📋 **Prerequisites**

- **Python 3.8+** (Download from [python.org](https://python.org))
- **Node.js 16+** (Download from [nodejs.org](https://nodejs.org))
- **Google Gemini API Key** (Get from [Google AI Studio](https://makersuite.google.com/app/apikey))

## ⚡ **Quick Setup (5 minutes)**

### **1. Clone the Repository**
```bash
git clone https://github.com/dhananjay1434/antara.git
cd antara
```

### **2. Backend Setup**
```bash
cd antara_engine
pip install -r requirements.txt
```

### **3. Configure API Key**
```bash
# Copy the environment template
cp .env .env.local

# Edit .env and add your Gemini API key:
GEMINI_API_KEY=your_actual_api_key_here
```

### **4. Start Backend**
```bash
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

### **5. Frontend Setup (New Terminal)**
```bash
cd frontend
npm install
npm run dev
```

### **6. Access Antarā**
- **Frontend**: http://localhost:3000
- **Backend API**: http://localhost:8000
- **API Docs**: http://localhost:8000/docs

## 🎯 **Test the Magic**

### **Crystal Labyrinth Trigger**
Send this exact message to experience the full feature:
```
I feel like everyone else has it all figured out
```

You should see:
1. ✨ **Synthesis animation** with emotion tags
2. 🌟 **Crystal Labyrinth response** streaming in
3. 🎯 **Action prompt** for concrete commitments
4. ⚓ **Confirmation** when action is anchored

### **Memory Creation**
Send meaningful messages (15+ words) to create memories in the Memory Sanctum.

### **World Nodes**
Substantial conversations automatically become stars in your Inner World.

## 🔧 **Troubleshooting**

### **Backend Issues**
- **Port 8000 in use**: Change port in uvicorn command
- **API Key errors**: Verify your Gemini API key is correct
- **Database errors**: Delete `antara.db` file and restart

### **Frontend Issues**
- **Port 3000 in use**: Vite will automatically suggest port 3001
- **API connection**: Ensure backend is running on port 8000
- **CORS errors**: Check CORS settings in `main.py`

### **Common Solutions**
```bash
# Reset database
rm antara_engine/antara.db

# Clear npm cache
cd frontend && npm cache clean --force

# Reinstall dependencies
pip install -r requirements.txt --force-reinstall
```

## 🌟 **Features Overview**

### **🎭 Dream Weaver AI**
- Mystical storytelling responses
- Powered by Google Gemini
- Emotional intelligence and metaphorical insights

### **🔮 Crystal Labyrinth**
- Magic moment detection
- Synthesis visualization
- Action anchoring system

### **🌌 Inner World**
- Constellation visualization
- Interactive journey mapping
- Click stars to revisit memories

### **🧠 Memory Sanctum**
- Complete user control
- Privacy-first approach
- Delete memories anytime

## 📁 **Project Structure**
```
antarā/
├── antara_engine/          # FastAPI Backend
│   ├── main.py            # API endpoints
│   ├── chat_service.py    # AI logic
│   ├── database.py        # Data models
│   ├── config.py          # Settings
│   └── requirements.txt   # Python deps
├── frontend/              # React Frontend
│   ├── src/
│   │   ├── components/    # UI components
│   │   ├── services/      # API clients
│   │   └── App.tsx        # Main app
│   ├── package.json       # Node deps
│   └── vite.config.ts     # Build config
└── README.md
```

## 🎨 **Development**

### **Backend Development**
- **Auto-reload**: Uvicorn watches for changes
- **API Testing**: Use http://localhost:8000/docs
- **Logs**: Check terminal for detailed logs

### **Frontend Development**
- **Hot reload**: Vite provides instant updates
- **TypeScript**: Full type safety
- **Tailwind**: Utility-first CSS

## 🚀 **Deployment**

### **Backend (Railway/Heroku)**
```bash
# Add Procfile
echo "web: uvicorn main:app --host 0.0.0.0 --port \$PORT" > Procfile

# Set environment variables
GEMINI_API_KEY=your_key_here
```

### **Frontend (Vercel/Netlify)**
```bash
# Build command
npm run build

# Output directory
dist/
```

## 🤝 **Contributing**

1. Fork the repository
2. Create feature branch: `git checkout -b feature/amazing-feature`
3. Commit changes: `git commit -m 'Add amazing feature'`
4. Push to branch: `git push origin feature/amazing-feature`
5. Open Pull Request

## 📞 **Support**

- **Issues**: [GitHub Issues](https://github.com/dhananjay1434/antara/issues)
- **Discussions**: [GitHub Discussions](https://github.com/dhananjay1434/antara/discussions)

---

**Ready to transform your inner world? Let's begin the journey!** ✨
