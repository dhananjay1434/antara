# Antarā Deployment Guide

This guide will help you deploy the complete Antarā prototype to production.

## 🚀 Backend Deployment (Render)

### Step 1: Prepare Your Repository
1. Push your code to GitHub
2. Ensure `antara_engine/render.yaml` is in your repository

### Step 2: Deploy to Render
1. Go to [render.com](https://render.com) and sign up/login
2. Click "New" → "Web Service"
3. Connect your GitHub repository
4. Configure the service:
   - **Name**: `antara-engine`
   - **Environment**: `Python 3`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `uvicorn main:app --host 0.0.0.0 --port $PORT`
   - **Root Directory**: `antara_engine`

### Step 3: Set Environment Variables
Add these environment variables in Render:
- `GEMINI_API_KEY`: Your Google Gemini API key
- `SECRET_KEY`: A secure random string
- `ALLOWED_ORIGINS`: Your frontend URL (e.g., `https://your-app.vercel.app`)

### Step 4: Deploy
Click "Create Web Service" and wait for deployment to complete.

## 🌐 Frontend Deployment (Vercel)

### Step 1: Prepare Frontend
1. Update `frontend/vercel.json` with your backend URL
2. Ensure all dependencies are in `package.json`

### Step 2: Deploy to Vercel
1. Go to [vercel.com](https://vercel.com) and sign up/login
2. Click "New Project"
3. Import your GitHub repository
4. Configure the project:
   - **Framework Preset**: Vite
   - **Root Directory**: `frontend`
   - **Build Command**: `npm run build`
   - **Output Directory**: `dist`

### Step 3: Set Environment Variables
Add this environment variable in Vercel:
- `VITE_API_URL`: Your Render backend URL (e.g., `https://antara-engine.onrender.com`)

### Step 4: Deploy
Click "Deploy" and wait for deployment to complete.

## 🔧 Local Development Setup

### Backend Setup
```bash
cd antara_engine
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env and add your GEMINI_API_KEY
python main.py
```

### Frontend Setup
```bash
cd frontend
npm install
cp .env.example .env
# Edit .env and set VITE_API_URL=http://localhost:8000
npm run dev
```

## 🧪 Testing the Deployment

### Test the Four Features

1. **Dream Weaver AI**: Send a message like "I'm feeling lost today"
2. **Crystal Labyrinth**: Send "I feel like everyone else is better than me"
3. **Inner World Map**: Check the "Inner World" tab after a few conversations
4. **Memory Sanctum**: Visit the "Memory Sanctum" tab and try deleting a memory

### Health Checks
- Backend: Visit `https://your-backend-url.com/health`
- Frontend: Ensure all pages load and navigation works

## 🔍 Troubleshooting

### Common Backend Issues
- **CORS errors**: Check `ALLOWED_ORIGINS` environment variable
- **Database errors**: Ensure SQLite permissions are correct
- **AI errors**: Verify `GEMINI_API_KEY` is set correctly

### Common Frontend Issues
- **API connection**: Verify `VITE_API_URL` points to your backend
- **Build errors**: Check all dependencies are installed
- **Routing issues**: Ensure `vercel.json` has correct rewrites

## 📊 Monitoring

### Backend Monitoring
- Check Render logs for errors
- Monitor API response times
- Watch database growth

### Frontend Monitoring
- Check Vercel function logs
- Monitor build times
- Watch for client-side errors

## 🔒 Security Considerations

### Backend Security
- Use strong `SECRET_KEY`
- Keep `GEMINI_API_KEY` secure
- Enable HTTPS only
- Validate all inputs

### Frontend Security
- Use environment variables for sensitive config
- Enable CSP headers
- Validate API responses

## 📈 Scaling Considerations

### Backend Scaling
- Consider PostgreSQL for production
- Implement Redis for caching
- Add rate limiting
- Use CDN for static assets

### Frontend Scaling
- Implement code splitting
- Add service worker for caching
- Optimize images and assets
- Use lazy loading

## 🎯 Production Checklist

### Before Going Live
- [ ] All environment variables set
- [ ] HTTPS enabled on both services
- [ ] Error monitoring configured
- [ ] Database backups enabled
- [ ] Performance testing completed
- [ ] Security audit performed

### After Deployment
- [ ] Test all four features
- [ ] Verify mobile responsiveness
- [ ] Check loading times
- [ ] Monitor error rates
- [ ] Set up alerts

## 🆘 Support

If you encounter issues:
1. Check the logs in Render/Vercel dashboards
2. Verify environment variables are set correctly
3. Test API endpoints directly
4. Check network connectivity between services

---

*This deployment guide ensures your Antarā prototype runs smoothly in production.*
