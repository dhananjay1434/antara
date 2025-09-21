# 🔑 Gemini API Key Setup Guide

Your Antarā backend is deployed but needs the Gemini API key to function properly.

## 🚀 Quick Setup (5 minutes)

### Step 1: Get Your Gemini API Key
1. Go to **https://makersuite.google.com/app/apikey**
2. Sign in with your Google account
3. Click **"Create API Key"**
4. Select **"Create API key in new project"** (or use existing project)
5. **Copy the API key** (starts with `AIza...`)

### Step 2: Add API Key to Render
1. Go to your **Render Dashboard**: https://dashboard.render.com
2. Click on your **`antara-engine`** service
3. Go to **Environment** tab
4. Find `GEMINI_API_KEY` or click **"Add Environment Variable"**
5. Set:
   - **Key**: `GEMINI_API_KEY`
   - **Value**: `AIza...` (your actual API key)
6. Click **"Save Changes"**

### Step 3: Wait for Redeploy
- Render will automatically redeploy your service (1-2 minutes)
- Watch the logs - the warning should disappear
- Test at: https://antara-engine.onrender.com

## ✅ Verification

### Test Your Backend
Visit these URLs to verify everything works:

1. **Root endpoint**: https://antara-engine.onrender.com
   - Should show API information (no more 404!)

2. **Health check**: https://antara-engine.onrender.com/health
   - Should return: `{"status":"healthy","service":"antara-engine"}`

3. **Create a test user**:
   ```bash
   curl -X POST https://antara-engine.onrender.com/users \
     -H "Content-Type: application/json" \
     -d '{"user_id":"test123","username":"testuser"}'
   ```

4. **Send a test message**:
   ```bash
   curl -X POST https://antara-engine.onrender.com/chat \
     -H "Content-Type: application/json" \
     -d '{"message":"Hello Dream Weaver","user_id":"test123"}'
   ```

## 🎯 Expected Results

After setting the API key, your logs should show:
- ✅ No more "GEMINI_API_KEY not found" warnings
- ✅ Successful AI responses instead of fallback messages
- ✅ All 4 features working (Dream Weaver, Crystal Labyrinth, World Map, Memory Sanctum)

## 🔧 Troubleshooting

**Still seeing API key warnings?**
- Double-check the key is correctly copied (no extra spaces)
- Make sure you saved changes in Render
- Wait for the redeploy to complete

**API key not working?**
- Verify the key is active in Google AI Studio
- Check if you have API quotas/billing set up
- Try creating a new API key

## 🌟 Next Step: Deploy Frontend

Once your backend is working with the API key:
1. Deploy frontend to **Vercel**
2. Set `VITE_API_URL=https://antara-engine.onrender.com`
3. Update CORS in Render with your Vercel URL

---

**Your backend URL**: https://antara-engine.onrender.com
**Status**: ✅ Deployed, needs API key configuration
