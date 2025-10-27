# 🚀 Railway Deployment - Complete Setup

## ✅ What's Been Prepared

I've created everything you need to deploy your BioInsight AI application to Railway + Streamlit Cloud:

### 📁 Files Created

1. **`Procfile`** - Tells Railway how to run your app
2. **`railway.toml`** - Railway configuration file
3. **`.gitignore`** - Updated to prevent committing sensitive files
4. **`RAILWAY_DEPLOYMENT_GUIDE.md`** - Complete step-by-step guide (detailed)
5. **`QUICK_DEPLOY.md`** - Quick reference card (fast overview)
6. **`REASONING_FEATURE_SUMMARY.md`** - Documentation of reasoning feature

---

## 🎯 Next Steps (Follow These in Order)

### Step 1: Secure Your Repository (CRITICAL! 🚨)

**Your `.env` file contains sensitive API keys and must NOT be pushed to GitHub.**

```bash
cd "/mnt/c/Users/ChaayaSappa/Downloads/bi-bot (2) - Copy"

# Remove .env from git tracking
git rm --cached .env

# Verify changes
git status

# Commit
git add .
git commit -m "Prepare for Railway deployment: remove sensitive files, add deployment configs"

# Push to GitHub
git push origin main
```

### Step 2: Deploy Backend to Railway (5 minutes)

1. **Go to:** https://railway.app
2. **Sign up/Login** with GitHub
3. **New Project** → **Deploy from GitHub repo** → Select your repo
4. **Add PostgreSQL:** Click "+ New" → Database → PostgreSQL
5. **Add Environment Variables:**
   - Go to your service → **Variables** tab
   - Click **"Raw Editor"**
   - Copy ALL variables from your `.env` file
   - Paste them
   - Click **"Save"**
6. **Wait for deployment** (check Logs tab)
7. **Copy your URL:** `https://something.railway.app`

### Step 3: Deploy Frontend to Streamlit Cloud (3 minutes)

1. **Go to:** https://streamlit.io/cloud
2. **Sign up/Login** with GitHub
3. **New app** → Select your repo
4. **Main file path:** `NSLC/bio_chatbot_improved.py`
5. **Click "Advanced settings"**
6. **In Secrets, paste:**
   ```toml
   API_BASE_URL = "https://your-railway-url.railway.app"
   WS_BASE_URL = "wss://your-railway-url.railway.app"
   ```
7. **Click "Deploy"**
8. **Wait ~2 minutes**
9. **Copy your Streamlit URL:** `https://something.streamlit.app`

### Step 4: Update CORS (1 minute)

1. **Go back to Railway**
2. **Your service → Variables**
3. **Update:**
   ```bash
   ALLOWED_ORIGINS=https://your-streamlit-app.streamlit.app
   ```
4. **Save** (Railway will auto-redeploy)

### Step 5: Test Everything ✅

1. Open your Streamlit URL
2. Login with your credentials
3. Try a query: **"Show me EGFR expression in tumor vs normal"**
4. Verify:
   - ✅ Login works
   - ✅ Query executes
   - ✅ SQL displays
   - ✅ Plot renders
   - ✅ Toggle reasoning feature works
   - ✅ PDF export works

---

## 📖 Documentation Reference

### For First-Time Deployment:
Read: **`RAILWAY_DEPLOYMENT_GUIDE.md`**
- Detailed step-by-step instructions
- Troubleshooting guide
- Security checklist
- Database setup
- Full configuration explanations

### For Quick Reference:
Read: **`QUICK_DEPLOY.md`**
- Fast deployment steps
- Environment variables template
- Quick troubleshooting
- URL reference card

### For Reasoning Feature:
Read: **`REASONING_FEATURE_SUMMARY.md`**
- Complete technical documentation
- All code changes
- Data structures
- Testing recommendations

---

## 🔐 Security Checklist

Before going live:

- [ ] ✅ `.env` file is NOT in git (we did this)
- [ ] ✅ `.gitignore` updated (we did this)
- [ ] Change `JWT_SECRET_KEY` to a strong random string
- [ ] Change `JWT_REFRESH_SECRET_KEY` to a strong random string
- [ ] Update `ALLOWED_ORIGINS` to your specific Streamlit domain
- [ ] Consider rotating database passwords
- [ ] Review all API keys and ensure they're production-ready
- [ ] Enable monitoring in Railway dashboard

---

## 💰 Cost Breakdown

| Service | Cost | What You Get |
|---------|------|--------------|
| **Railway** | $5-10/month | Backend API, PostgreSQL, auto-deployments |
| **Streamlit Cloud** | Free | Frontend hosting, 1 private app |
| **Total** | **$5-10/month** | Full stack deployment |

**Note:** Railway gives you $5 free credit each month, so it might be free initially!

---

## 🆘 Common Issues & Solutions

### "Module not found" on Railway
- **Solution:** Check that `requirements.txt` is in your repo root
- Railway auto-installs from requirements.txt

### "Can't connect to backend" on Streamlit
- **Solution:** Verify `API_BASE_URL` in Streamlit secrets matches Railway URL
- Make sure you're using `https://` (not `http://`)

### WebSocket connection fails
- **Solution:** Use `wss://` (not `ws://`) in `WS_BASE_URL`
- Check that CORS includes your Streamlit domain

### Database connection errors
- **Option 1:** Use Railway's PostgreSQL (easier)
- **Option 2:** If using Azure PostgreSQL, upload SSL certificate

### "Cannot find bio_gene_expression.db"
- **Solution:** Make sure `NSLC/bio_gene_expression.db` is in your GitHub repo
- It should NOT be in .gitignore (we kept it included)

---

## 📊 Your Final URLs

After deployment, you'll have:

```
Backend API:      https://your-app.railway.app
API Docs:         https://your-app.railway.app/docs
WebSocket:        wss://your-app.railway.app/wss

Frontend:         https://your-app.streamlit.app
```

Save these URLs! You'll need them.

---

## 🎓 What We've Built

Your BioInsight AI application now has:

✅ **Backend (Railway):**
- FastAPI REST API
- WebSocket support for real-time chat
- PostgreSQL database
- Azure OpenAI integration
- Qdrant vector search
- Automatic HTTPS
- Continuous deployment from GitHub

✅ **Frontend (Streamlit Cloud):**
- Modern chat interface
- Real-time query processing
- SQL query display
- Interactive Plotly visualizations
- Reasoning toggle feature (show execution steps)
- PDF report export
- Session persistence
- Dark theme

✅ **New Features Added:**
- 🧠 Reasoning & Execution Steps toggle
- Multiple SQL query support in reports
- Improved PDF formatting
- Real-time status indicators

---

## 🚀 Deployment Time Estimate

- **Preparation:** 5 minutes (commit changes)
- **Backend (Railway):** 5 minutes (setup + deploy)
- **Frontend (Streamlit):** 3 minutes (setup + deploy)
- **Final config:** 2 minutes (CORS + testing)

**Total:** ~15 minutes from start to finish

---

## 📞 Support Resources

- **Railway Docs:** https://docs.railway.app
- **Streamlit Docs:** https://docs.streamlit.io
- **Railway Discord:** https://discord.gg/railway
- **Railway Logs:** Dashboard → Your service → Logs tab
- **Streamlit Logs:** App settings → Logs

---

## ✨ You're Ready to Deploy!

Everything is prepared. Just follow the **Next Steps** above and you'll be live in ~15 minutes.

**Start with Step 1** (securing your repository) and work through each step sequentially.

Good luck! 🎉

---

**Created:** October 27, 2025
**Last Updated:** October 27, 2025
**Version:** 1.0
