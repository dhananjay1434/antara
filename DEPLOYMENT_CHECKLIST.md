# 📋 Antarā Deployment Checklist

Quick reference for deployment settings and URLs.

## 🔗 Deployment URLs

### Backend (Render)
- **Service Name**: `antara-engine`
- **URL**: `https://antara-engine.onrender.com` *(update with actual URL)*
- **Health Check**: `https://antara-engine.onrender.com/health`

### Frontend (Vercel)
- **Project Name**: `antara-frontend`
- **URL**: `https://antara-frontend.vercel.app` *(update with actual URL)*

## ⚙️ Environment Variables

### Render (Backend)
```
GEMINI_API_KEY=your_actual_gemini_api_key
SECRET_KEY=auto_generated_by_render
DATABASE_URL=sqlite:///./antara.db
ALLOWED_ORIGINS=https://antara-frontend.vercel.app,http://localhost:3000,http://localhost:5173
DEBUG=false
LOG_LEVEL=INFO
```

### Vercel (Frontend)
```
VITE_API_URL=https://antara-engine.onrender.com
```

## 📝 Deployment Steps Summary

### ✅ Render Deployment
- [ ] Create Render account
- [ ] Import GitHub repository
- [ ] Set root directory to `antara_engine`
- [ ] Configure environment variables
- [ ] Deploy and note backend URL

### ✅ Vercel Deployment
- [ ] Create Vercel account
- [ ] Import GitHub repository
- [ ] Set root directory to `frontend`
- [ ] Set `VITE_API_URL` environment variable
- [ ] Deploy and note frontend URL

### ✅ Post-Deployment
- [ ] Update CORS settings in Render with actual Vercel URL
- [ ] Test backend health endpoint
- [ ] Test frontend functionality
- [ ] Verify all 4 features work in production

## 🧪 Testing Endpoints

### Backend API Tests
```bash
# Health check
curl https://your-render-url.onrender.com/health

# Create user
curl -X POST https://your-render-url.onrender.com/users \
  -H "Content-Type: application/json" \
  -d '{"user_id":"test123","username":"testuser"}'

# Send chat message
curl -X POST https://your-render-url.onrender.com/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"Hello","user_id":"test123"}'
```

### Frontend Features to Test
- [ ] Chat interface loads
- [ ] Can send messages to Dream Weaver
- [ ] Crystal Labyrinth triggers work (try "I'm not good enough")
- [ ] World Map shows constellation
- [ ] Memory Sanctum displays and allows deletion

## 🚨 Common Issues & Solutions

| Issue | Solution |
|-------|----------|
| Backend won't start | Check GEMINI_API_KEY is set correctly |
| CORS errors | Update ALLOWED_ORIGINS with actual Vercel URL |
| Frontend can't connect | Verify VITE_API_URL points to Render backend |
| 404 errors on refresh | Vercel rewrites should handle this automatically |
| Database errors | SQLite should work on Render free tier |

## 📞 Support Resources

- **Render Docs**: https://render.com/docs
- **Vercel Docs**: https://vercel.com/docs
- **FastAPI Docs**: https://fastapi.tiangolo.com
- **React Docs**: https://react.dev

---

**🎯 Goal**: Both services deployed and communicating successfully for hackathon demonstration!
