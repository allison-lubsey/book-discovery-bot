# 📚 Book Discovery Bot

A Telegram bot that saves books to Notion when you share a TikTok/Instagram link **or a screenshot**.

```
You        →  share a TikTok/Instagram link  OR  send a screenshot
Bot        →  scrapes the post caption  OR  sends image to Claude vision
Groq/Claude→  extracts book titles & authors
Bot        →  checks Notion for duplicates (title + author)
Bot        →  fetches cover images from Google Books
Bot        →  saves each new book to your Notion database
Ntfy       →  sends you a push notification
```

**Tech stack (all free tiers available):**
- Telegram bot (webhook mode, hosted on Render free tier)
- Groq API for text extraction (TikTok/Instagram captions)
- Anthropic API (Claude Haiku) for screenshot/vision extraction
- Notion API for storage
- Google Books API for cover art
- Ntfy for push notifications

---

## 1. Telegram Bot — BotFather Setup

1. Open Telegram and search for **@BotFather**
2. Send `/newbot`
3. Choose a name: e.g. `My Book Bot`
4. Choose a username: e.g. `allison_books_bot` (must end in `bot`)
5. Copy the token — looks like `123456789:ABCdef...`
6. Set `TELEGRAM_BOT_TOKEN=<your-token>` in your env

**Optional (recommended): find your Telegram User ID**
1. Message **@userinfobot** on Telegram
2. It replies with your user ID (a number like `987654321`)
3. Set `TELEGRAM_USER_ID=987654321` so only you can use the bot

---

## 2. Notion Setup

### 2a. Create an Integration

1. Go to https://www.notion.so/my-integrations
2. Click **New integration**
3. Name it `Book Discovery Bot`
4. Set workspace to your workspace
5. Capabilities: ✅ Read content, ✅ Update content, ✅ Insert content
6. Click **Save** and copy the **Internal Integration Token** (starts with `secret_`)
7. Set `NOTION_API_KEY=secret_...`

### 2b. Create the Database

1. In Notion, create a new **full-page database** (not inline)
2. Name it whatever you like, e.g. `📚 My Book List`
3. Add the following properties — **exact names and types matter**:

| Property Name | Type   | Notes                                      |
|---------------|--------|--------------------------------------------|
| Title         | Title  | Already exists by default — rename if needed |
| Author        | Text   |                                            |
| Source URL    | URL    | Left blank for screenshot-sourced books    |
| Date Saved    | Date   |                                            |
| Status        | Select | Add options: `Want to Read`, `Reading`, `Read` |
| Cover Image   | URL    |                                            |

4. **Connect your integration to the database:**
   - Open the database
   - Click ⋯ (top-right) → **Connections** → **Connect to** → select `Book Discovery Bot`

5. **Get the Database ID:**
   - Open the database in your browser
   - URL looks like: `https://www.notion.so/yourname/abc123def456...?v=...`
   - The database ID is the 32-char hex string **before the `?v=`**
   - Set `NOTION_DATABASE_ID=abc123def456...`

---

## 3. Groq API Setup

1. Go to https://console.groq.com
2. Sign up for free
3. Go to **API Keys** → **Create API Key**
4. Set `GROQ_API_KEY=gsk_...`

**Free tier:** 14,400 requests/day on llama-3.1-8b-instant — more than enough.

---

## 4. Anthropic API Setup (for screenshots)

Required for screenshot/vision support. Without it, link scraping still works fine.

1. Go to https://console.anthropic.com
2. Sign up and go to **API Keys** → **Create Key**
3. Set `ANTHROPIC_API_KEY=sk-ant-...`

The bot uses **claude-haiku-4-5-20251001** — Anthropic's fastest and most affordable model.

---

## 5. Ntfy Setup

No account needed!

1. Install the **Ntfy** app on your phone:
   - iOS: https://apps.apple.com/app/ntfy/id1625396347
   - Android: https://play.google.com/store/apps/details?id=io.heckel.ntfy

2. Choose a unique topic name — treat it like a private channel name.
   Use something hard to guess: e.g. `allison-books-k7x9q`

3. In the app, tap ＋ and subscribe to your topic name

4. Set `NTFY_TOPIC=allison-books-k7x9q`

That's it! No login, no account. Anyone who knows your topic can send to it, so make it unique.

---

## 6. Deploy to Render (Free Tier)

### 6a. Push to GitHub

```bash
cd book-discovery-bot
git init
git add .
git commit -m "Initial commit"
# Create a repo on github.com, then:
git remote add origin https://github.com/YOUR_USERNAME/book-discovery-bot.git
git push -u origin main
```

### 6b. Create Render Web Service

1. Go to https://render.com and sign up (free)
2. Click **New** → **Web Service**
3. Connect your GitHub repo
4. Render auto-detects `render.yaml` — confirm the settings:
   - **Name:** `book-discovery-bot`
   - **Runtime:** Python
   - **Build command:** `pip install -r requirements.txt`
   - **Start command:** `gunicorn bot:app --workers 1 --timeout 120 --bind 0.0.0.0:$PORT`
   - **Plan:** Free

5. Under **Environment Variables**, add all your secrets:

   | Key | Value |
   |-----|-------|
   | `TELEGRAM_BOT_TOKEN` | your bot token |
   | `GROQ_API_KEY` | your Groq key |
   | `ANTHROPIC_API_KEY` | your Anthropic key |
   | `NOTION_API_KEY` | `secret_...` |
   | `NOTION_DATABASE_ID` | 32-char database ID |
   | `NTFY_TOPIC` | your topic name |
   | `TELEGRAM_USER_ID` | (optional) your user ID |

6. Click **Create Web Service** — Render will build and deploy

### 6c. Register the Webhook (one-time)

Once your service is live (URL shown in Render dashboard, e.g. `https://book-discovery-bot.onrender.com`):

1. Visit this URL in your browser:
   ```
   https://book-discovery-bot.onrender.com/set_webhook
   ```
2. You should see: `✅ Webhook set to: https://book-discovery-bot.onrender.com/webhook`
3. Done! Telegram will now push all messages to your bot.

### 6d. Keep it Alive with UptimeRobot (free)

Render's free tier sleeps after 15 minutes of inactivity. Set up a free pinger:

1. Go to https://uptimerobot.com and sign up
2. Click **Add New Monitor**
3. Type: **HTTP(s)**
4. URL: `https://book-discovery-bot.onrender.com/`
5. Interval: **5 minutes**
6. Save — this pings your bot every 5 min to keep it awake

---

## 7. Local Development (optional)

```bash
# 1. Clone and set up
cd book-discovery-bot
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt

# 2. Copy and fill in environment variables
cp .env.example .env
# Edit .env with your real values

# 3. Run locally
python bot.py
```

For webhook testing locally, use ngrok:
```bash
ngrok http 5000
# Then visit: http://localhost:5000/set_webhook
# (after setting RENDER_EXTERNAL_URL=https://xxxx.ngrok.io in .env)
```

---

## Environment Variables Reference

| Variable | Required | Description |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | ✅ | From @BotFather |
| `GROQ_API_KEY` | ✅ | From console.groq.com |
| `ANTHROPIC_API_KEY` | ✅ | From console.anthropic.com — used for screenshot vision |
| `NOTION_API_KEY` | ✅ | From notion.so/my-integrations |
| `NOTION_DATABASE_ID` | ✅ | 32-char ID from database URL |
| `NTFY_TOPIC` | ✅ | Your unique topic name |
| `TELEGRAM_USER_ID` | ☑️ Optional | Restrict bot to only you |
| `GOOGLE_BOOKS_API_KEY` | ☑️ Optional | Improves Google Books rate limits |
| `TIKTOK_COOKIES_FILE` | ☑️ Optional | Path to cookies.txt for TikTok comment fetching |

---

## How to Use

1. Open your Telegram bot
2. Send `/start` to see the welcome message
3. **Option A:** Paste any TikTok or Instagram link
4. **Option B:** Send a screenshot (as a photo or as a file attachment)
5. The bot replies with status updates, then confirms what was saved
6. Check your Notion database — the book card will be there with cover art
7. Your phone receives an Ntfy push notification

**Supported screenshot formats:** JPG, JPEG, PNG, WebP
Send as a *photo* (Telegram compresses it) or as a *file* (preserves original quality).

### Duplicate detection

The bot checks Notion before saving. If a book with the same title **and** author already exists, it's skipped — not added again. Books with the same title but different authors are treated as separate books.

**Response examples:**

| Scenario | Bot message |
|---|---|
| 2 new books | ✅ Saved 2 book(s) to Notion! |
| 1 new + 1 dupe | ✅ Saved 1 book(s) to Notion! 📚 Already in Notion: _Book Title_ |
| All dupes | 📚 Already in your Notion library! |
| No books detected | 📌 No books detected — saved for later review |

### Example notifications

**Success:**
```
📚 2 Book(s) Saved!
• Atomic Habits by James Clear
• The 4-Hour Work Week by Tim Ferriss
```

---

## Troubleshooting

**Bot doesn't respond:**
- Check Render logs (Dashboard → your service → Logs)
- Verify webhook is set: visit `/set_webhook` again
- Make sure UptimeRobot is keeping the service alive

**"Could not fetch this post":**
- Private posts cannot be scraped
- Very new posts sometimes fail — try again in a minute
- Instagram may block scraping more aggressively than TikTok

**Screenshot returns no books:**
- Make sure the book title is clearly legible in the image
- Try sending as a file (uncompressed) instead of a photo for better quality
- Check that `ANTHROPIC_API_KEY` is set correctly in Render

**Notion save fails:**
- Confirm the integration is connected to your database (⋯ → Connections)
- Check that all property names match exactly (case-sensitive)
- Verify `NOTION_DATABASE_ID` is the correct 32-char ID

**No cover image:**
- Google Books doesn't have every book — the entry still saves, just without a cover
- Very new or obscure books may not have covers indexed yet
