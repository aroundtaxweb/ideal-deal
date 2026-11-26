# IdealDeal — Setup Guide

Everything here is **free**: GitHub hosts the site and runs the bot every 30 minutes. No server needed.

```
idealdeal/
├─ site/index.html        premium website (reads deals.json)
├─ site/deals.json        auto-updated by the bot
├─ bot/bot.py             finds deals → affiliate links → Telegram + website
├─ bot/feeds.json         deal sources (edit freely)
└─ .github/workflows/deals.yml   the 30-minute automation + website deploy
```

## 1. Telegram (10 min)
1. Create a **public channel** (e.g. `@idealdeal_shop`).
2. Channel → Administrators → **Add your bot** → allow *Post messages*.
3. Your chat ID is simply `@yourchannelusername`.
4. Open `site/index.html`, edit the top `CONFIG` block: `telegram: "https://t.me/yourchannelusername"`.
5. Your bot token: if you ever pasted it anywhere public, open @BotFather → `/revoke` and use the new one.

## 2. Affiliate accounts (this is how you earn)
The bot only posts a deal if it can turn the link into **your** affiliate link (otherwise you'd earn nothing).
- **Amazon India** — Amazon Associates (affiliate-program.amazon.in). Add `idealdeal.shop` as your site. Your **Tracking ID** looks like `idealdeal-21`. Amazon usually needs 3 qualifying sales within 180 days or the account closes.
- **Flipkart** — Flipkart Affiliate (affiliate.flipkart.com). Your **affiliate ID** goes in `FLIPKART_AFFID`.
- **Everything else (Myntra, Ajio, Nykaa, Croma…)** — sign up at Cuelinks or EarnKaro, copy their link-wrapper URL, and put `{url}` where the product URL goes, e.g.
  `https://linksredirect.com/?cid=12345&source=linkkit&url={url}` → save as `AFFILIATE_TEMPLATE`.

## 3. Put it on GitHub
1. Create a new **public** repo (public = free Pages + free Actions minutes), e.g. `idealdeal`.
2. Upload everything in this folder (keep the `.github` folder!), branch `main`.
3. Repo → Settings → **Secrets and variables → Actions → New repository secret**. Add:

| Secret | Value |
|---|---|
| `TELEGRAM_BOT_TOKEN` | token from BotFather |
| `TELEGRAM_CHAT_ID` | `@yourchannelusername` |
| `AMAZON_TAG` | your Amazon tracking ID |
| `FLIPKART_AFFID` | your Flipkart affiliate ID (optional) |
| `AFFILIATE_TEMPLATE` | Cuelinks/EarnKaro wrapper with `{url}` (optional) |

Secrets are never visible in a public repo — never put tokens in files.

## 4. Turn on the website
1. Repo → Settings → **Pages → Source: GitHub Actions**.
2. Same page → **Custom domain: `idealdeal.shop`** → Save → tick *Enforce HTTPS* once available.
3. At your domain registrar's DNS panel add:

| Type | Host | Value |
|---|---|---|
| A | @ | 185.199.108.153 |
| A | @ | 185.199.109.153 |
| A | @ | 185.199.110.153 |
| A | @ | 185.199.111.153 |
| CNAME | www | `<your-github-username>.github.io` |

DNS can take from a few minutes to a few hours.

## 5. Launch
Repo → **Actions → IdealDeal auto-poster → Run workflow**. The first run posts only 3 deals (so the channel isn't flooded); after that it checks every 30 minutes and posts up to 5 new deals per run. Watch the run log to see what was posted or skipped and why.

## Tuning
- **More/fewer posts**: `MAX_POSTS_PER_RUN` in the workflow file.
- **Sources**: `bot/feeds.json` — any RSS/Atom feed whose items link to (or contain links to) Amazon/Flipkart/etc. Sources that only link to their own pages are skipped.
- **Add stores**: `MERCHANTS` list in `bot/bot.py`.
- **Test without posting**: run locally `DRY_RUN=1 python3 bot/bot.py`.

## Things to know
- **Feeds are untested from my side.** The sample feeds in `feeds.json` could not be reached from my sandbox. Check the first Actions log; if a feed errors (Reddit sometimes blocks GitHub servers), swap it for another one.
- GitHub's schedule is best-effort: runs can be delayed 5–20 min, and it pauses after 60 days with no repo activity (the bot's own commits keep it alive while deals flow).
- **Use fair sources.** Respect each feed's terms. The bot posts only title, price and your link. Amazon restricts how product images can be used outside its own tools, so if Amazon objects, set `USE_IMAGES` to `"0"` in the workflow env.
- **Disclosure is built in** (`#ad` in each post, footer on the site). Keep it — it's required by Amazon's rules and Indian advertising guidelines.
- Telegram limits channel posting to roughly 20 messages/minute; the bot is far below that.
