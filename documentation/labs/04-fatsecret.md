# 04 — FatSecret: food diary

**Goal:** the FatSecret food diary fills `FatSecretDaily` every 6 hours. The daily
form then shows your protein, carbohydrate, fat and fibre totals as prefills, so you
stop typing them in, and the coach can see calories, sugar, sodium and each meal.

## How it works

```
EventBridge (every 6h) ─┐
POST /fatsecret/sync ───┴─> fatsecret-sync ──> food_entries.get_month  (which days have entries)
                                           └─> food_entries.get       (each of those days) ──> FatSecretDaily
```

- **Authentication:** diary methods read one person's profile, so FatSecret requires
  **OAuth 1.0 "3-legged"**: your app's consumer key and secret, plus an access token
  that you grant once by signing in to FatSecret. Requests are signed with HMAC-SHA1.
  The access token doesn't expire.
- **First run:** when the table is empty, it backfills from 2026-10-01.
- **Later runs:** it re-fetches the last 7 days, because entries are often added or
  corrected later. Only days that changed are written. A day you clear in FatSecret
  is deleted from the table.
- **What's stored per day:** `totals` (calories_kcal, carbohydrate_g, protein_g, fat_g,
  fiber_g, sugar_g, saturated_fat_g, sodium_mg), `meals` (the main totals for breakfast,
  lunch, dinner and other), `entries_count`, and `entries` (each food with its nutrients).
- **What reads it:**
  - The daily form shows protein, carbs, fat and fibre as placeholders marked "From
    FatSecret". Typing a value overrides it, and only what you type is saved.
  - The daily advice uses yesterday's totals (your typed value wins), plus calories.
  - The agent's `get_daily_metrics` and `GET /analysis/series` include the day's
    totals and meals, not the individual foods.

## 1. Get your API keys

1. Sign up at **platform.fatsecret.com** (the free Basic plan is enough) and create an application.
2. On **Manage API Keys**, find the **OAuth 1.0** credentials:
   - **Consumer Key**
   - **Consumer Secret**

   You don't need the OAuth 2.0 Client ID and Secret. OAuth 2.0 can't read a diary.
3. **IP restrictions:** FatSecret lets you limit a key to certain IP addresses. Leave
   that list **empty** for this key. The sync runs in Lambda, which has no fixed IP
   address, and a fixed one would need a NAT gateway (about $33 a month). If FatSecret
   insists on a list for your plan, stop here and tell Claude. There are workarounds.

## 2. Create the secret

Store the keys in a file first, so they never appear in your shell history:

```bash
umask 077
cat > /tmp/fatsecret.json <<'JSON'
{"consumer_key": "PASTE_CONSUMER_KEY", "consumer_secret": "PASTE_CONSUMER_SECRET"}
JSON
aws secretsmanager create-secret --region us-east-1 --name fatsecret/oauth \
  --tags Key=project,Value=cycling-coach --secret-string file:///tmp/fatsecret.json
shred -u /tmp/fatsecret.json
```

The secret costs $0.40 a month. The stack is deployed by CI, and until the secret has
an access token the sync just logs "not configured yet".

## 3. Authorize the app to read your diary

```bash
uv run --project services python scripts/fatsecret_authorize.py
```

1. It prints a link. Open it, sign in to FatSecret with the account you log food in,
   and allow access.
2. FatSecret shows a verification code. Paste it into the terminal.
3. The script adds the access token and its secret to `fatsecret/oauth`. It doesn't
   print them or write them to disk.
4. It finishes by counting this month's diary days, to check the keys work.

## 4. Probe the data

```bash
uv run --project services python scripts/fatsecret_probe.py 2026-10-21
```

This saves the raw month and day responses to a git-ignored folder and lists every
field with a value, with how many entries have it. Fibre, sugar and sodium are
"where available", so check how often your foods have them.

## 5. Backfill

Wait for the Deploy run to finish, then:

```bash
aws lambda invoke --region us-east-1 --function-name fatsecret-sync \
  --cli-binary-format raw-in-base64-out --payload '{}' /dev/stdout
```

This returns something like `{"oldest": "2026-10-01", "newest": "…", "days_with_entries": 3,
"written": 3, "deleted": 0}`. Run it again and `written` should be 0. The **Sync** button in
the app now syncs Strava, Intervals and FatSecret together.

## 6. Check

Open the form for yesterday. If you left protein, carbs, fat and fibre empty, they
show FatSecret's totals as placeholders, marked "From FatSecret".

## Cost

| Item | Cost |
|---|---|
| Secret | $0.40 a month |
| Lambda (4 runs a day, a few FatSecret calls each) and DynamoDB (on-demand, one item a day) | Under $0.01 a month |
| FatSecret Basic plan | Free |
