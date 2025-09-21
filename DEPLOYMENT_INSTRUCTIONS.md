# 🚀 Antarā Deployment Guide

Complete step-by-step instructions for deploying Antarā to production.

## Prerequisites

- GitHub repository: https://github.com/dhananjay1434/antara.git
- Google Gemini API key
- Render account (for backend)
- Vercel account (for frontend)

## 🔧 STEP 1: Deploy Backend to Render

### 1.1 Create Render Account
1. Go to https://render.com
2. Sign up with your GitHub account
3. Authorize Render to access your repositories

### 1.2 Create Web Service
1. Click **"New +"** → **"Web Service"**
2. Select **"Build and deploy from a Git repository"**
3. Connect your GitHub account if not already connected
4. Find and select the **`antara`** repository
5. Click **"Connect"**

### 1.3 Configure Service Settings
- **Name**: `antara-engine`
- **Root Directory**: `antara_engine`
- **Environment**: `Python 3`
- **Region**: Choose closest to your users
- **Branch**: `main`
- **Build Command**: `pip install -r requirements.txt`
- **Start Command**: `uvicorn main:app --host 0.0.0.0 --port $PORT`

### 1.4 Set Environment Variables
Add these environment variables in Render:

| Key | Value | Notes |
|-----|-------|-------|
| `GEMINI_API_KEY` | `your_actual_api_key_here` | Get from Google AI Studio |
| `SECRET_KEY` | Auto-generated | Leave blank, Render will generate |
| `DATABASE_URL` | `sqlite:///./antara.db` | SQLite for free tier |
| `ALLOWED_ORIGINS` | `https://antara-frontend.vercel.app,http://localhost:3000` | Update with actual Vercel URL |
| `DEBUG` | `false` | Production setting |
| `LOG_LEVEL` | `INFO` | Standard logging |

### 1.5 Deploy
1. Click **"Create Web Service"**
2. Wait for deployment (2-5 minutes)
3. **IMPORTANT**: Copy your backend URL (e.g., `https://antara-engine.onrender.com`)

---

## 🌐 STEP 2: Deploy Frontend to Vercel

### 2.1 Create Vercel Account
1. Go to https://vercel.com
2. Sign up with your GitHub account
3. Authorize Vercel to access your repositories

### 2.2 Import Project
1. Click **"New Project"**
2. Import from Git Repository
3. Find and select the **`antara`** repository
4. Click **"Import"**

### 2.3 Configure Project Settings
- **Framework Preset**: `Vite` (should auto-detect)
- **Root Directory**: `frontend`
- **Build Command**: `npm run build` (auto-detected)
- **Output Directory**: `dist` (auto-detected)
- **Install Command**: `npm install` (auto-detected)

### 2.4 Set Environment Variables
Add this environment variable in Vercel:

| Key | Value | Notes |
|-----|-------|-------|
| `VITE_API_URL` | `https://your-render-url.onrender.com` | Use actual Render backend URL |

### 2.5 Deploy
1. Click **"Deploy"**
2. Wait for deployment (1-3 minutes)
3. **IMPORTANT**: Copy your frontend URL (e.g., `https://antara-frontend.vercel.app`)

---

## 🔄 STEP 3: Update CORS Configuration

### 3.1 Update Render CORS Settings
1. Go back to your Render dashboard
2. Navigate to your `antara-engine` service
3. Go to **Environment** tab
4. Update `ALLOWED_ORIGINS` to include your actual Vercel URL:
   ```
   https://your-actual-vercel-url.vercel.app,http://localhost:3000,http://localhost:5173
   ```
5. Click **"Save Changes"**
6. Service will automatically redeploy

### 3.2 Update Vercel API URL (if needed)
1. Go to your Vercel dashboard
2. Navigate to your project
3. Go to **Settings** → **Environment Variables**
4. Update `VITE_API_URL` if the Render URL changed
5. Redeploy if needed

---

## ✅ STEP 4: Test Your Deployment

### 4.1 Test Backend
Visit your Render URL + `/health`:
```
https://your-render-url.onrender.com/health
```
Should return: `{"status":"healthy","service":"antara-engine"}`

### 4.2 Test Frontend
1. Visit your Vercel URL
2. Try the chat functionality
3. Check that all 4 features work:
   - ✅ Dream Weaver chat
   - ✅ Crystal Labyrinth trigger
   - ✅ World Map visualization
   - ✅ Memory Sanctum management

---

## 🛠️ Troubleshooting

### Common Issues:

**Backend not starting:**
- Check environment variables are set correctly
- Verify `GEMINI_API_KEY` is valid
- Check Render logs for errors

**Frontend can't connect to backend:**
- Verify `VITE_API_URL` points to correct Render URL
- Check CORS settings in Render
- Ensure both services are deployed

**CORS errors:**
- Update `ALLOWED_ORIGINS` in Render
- Include both production and development URLs
- Redeploy backend after CORS changes

---

## 🎉 Success!

Your Antarā prototype is now live and ready for demonstration!

- **Backend**: https://your-render-url.onrender.com
- **Frontend**: https://your-vercel-url.vercel.app
- **Repository**: https://github.com/dhananjay1434/antara.git
