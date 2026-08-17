# Dripstop

Subscription & recurring charge leak detector. Upload a bank statement CSV and Dripstop finds your recurring subscriptions, categorizes your spending, and uses Claude to tell you which charges are worth keeping vs. worth cancelling — with concrete cancellation steps for the ones you drop.

## What it does

Three steps, one flow:

1. **Upload** — drop in a bank-statement CSV (`Date`, `Description`, `Amount` columns), or click "Use sample data" to try it with the bundled sample file.
2. **Categorize** — every transaction is bucketed into a category (streaming, utilities, groceries, etc.), and recurring merchants are detected by charge cadence + amount consistency — not just keyword guessing. Shows spend-by-category, recurring-vs-one-time, and monthly-trend charts.
3. **Decide** — Claude reviews each recurring charge and classifies it as essential or discretionary, with a one-line reason. For discretionary charges, choose "Keep it" or "Cancel it" — cancelling reveals concrete, service-specific steps to actually cancel it.

The app is gated behind a basic username/password account system (sign up, then sign in).

## Requirements

- Python 3.10 or later
- An Anthropic API key — get one at [console.anthropic.com](https://console.anthropic.com/settings/keys). Only needed for the "Decide" step; the Upload/Categorize steps work without one.

## Setup

1. **Clone the repo**
   ```bash
   git clone https://github.com/aamaninemtur0119/dripstop.git
   cd dripstop
   ```

2. **Create and activate a virtual environment**
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate      # Windows: .venv\Scripts\activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Add your API key**
   ```bash
   cp .env.example .env
   ```
   Then open `.env` and replace the placeholder with your real key:
   ```
   ANTHROPIC_API_KEY=sk-ant-your-real-key
   ```

## Run it

```bash
streamlit run app.py
```

Opens at `http://localhost:8501`. Sign up for an account, sign in, then upload a CSV (or click "Use sample data") to try it out.

## Project structure

```
app.py                              Streamlit UI — auth gate + 3 tabs
dripstop/
  parsing.py                        CSV loading & column validation
  categorize.py                     Merchant normalization, category rules, recurring-charge detection
  ai.py                             Claude API call for essential/discretionary verdicts (streamed)
  auth.py                           Username/password auth — PBKDF2-hashed, local SQLite
dripstop_sample_transactions.csv    Sample data to try the app with
requirements.txt
.env.example                        Template for your API key — copy to .env
```
