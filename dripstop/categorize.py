import re
import statistics

import pandas as pd

NOISE_TOKENS = {"COM", "BILL", "INC", "LLC", "CO", "USA", "US"}

CATEGORY_KEYWORDS = {
    "Streaming & Entertainment": ["NETFLIX", "DISNEY", "HULU", "SPOTIFY", "HBO", "PARAMOUNT", "PEACOCK", "YOUTUBE", "AUDIBLE", "APPLE MUSIC"],
    "Fitness & Wellness": ["PLANET FITNESS", "PELOTON", "GYM", "YOGA", "FITNESS"],
    "Cloud & Software": ["ICLOUD", "ADOBE", "DROPBOX", "GOOGLE STORAGE", "MICROSOFT", "GITHUB", "OPENAI"],
    "News & Reading": ["NYTIMES", "NEW YORK TIMES", "WSJ", "MEDIUM"],
    "Utilities": ["PG&E", "PGE", "ELECTRIC", "WATER UTIL", "GAS UTIL", "VERIZON", "AT&T", "COMCAST", "XFINITY", "WIRELESS", "INTERNET"],
    "Housing": ["RENT", "MORTGAGE", "APARTMENTS", "APTS"],
    "Income": ["PAYROLL", "DIRECT DEP", "DEPOSIT"],
    "Transportation": ["UBER", "LYFT", "SHELL", "CHEVRON", "GAS STATION", "PARKING"],
    "Groceries": ["TRADER JOE", "WHOLE FOODS", "SAFEWAY", "KROGER", "GROCERY"],
    "Dining & Delivery": ["RESTAURANT", "CHIPOTLE", "DOORDASH", "GRUBHUB", "STARBUCKS", "BISTRO", "CAFE"],
    "Shopping": ["AMAZON", "TARGET", "WALMART", "HOME DEPOT"],
    "Health": ["CVS", "PHARMACY", "WALGREENS"],
}

# Recurring-detection thresholds. Merchants pass if their charge cadence is
# regular (gap_cv) — amount similarity (amt_cv) only matters as a fallback
# with exactly two data points, since utility-style bills recur with a
# consistent cadence but a varying amount.
MIN_GAP_DAYS = 5
MAX_GAP_DAYS = 100
MAX_GAP_CV = 0.4
MAX_TWO_POINT_AMOUNT_CV = 0.5
MAX_RETAIL_GAP_CV = 0.15

RETAIL_LIKE_CATEGORIES = {"Shopping", "Groceries", "Dining & Delivery", "Health", "Transportation", "Other"}


def normalize_merchant(description: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9 ]", " ", description.upper())
    tokens = []
    for token in cleaned.split():
        if token in NOISE_TOKENS:
            continue
        if len(token) >= 3 and any(ch.isdigit() for ch in token):
            continue
        tokens.append(token)
    normalized = " ".join(tokens).strip()
    return normalized or description.upper().strip()


def categorize(description: str) -> str:
    upper = description.upper()
    for category, keywords in CATEGORY_KEYWORDS.items():
        if any(keyword in upper for keyword in keywords):
            return category
    return "Other"


def _monthly_equivalent(amount: float, mean_gap_days: float) -> float:
    if mean_gap_days <= 0:
        return amount
    return amount * (30.44 / mean_gap_days)


def build_analysis(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Annotate expenses with category + recurring flag, and summarize recurring merchants.

    Returns (expenses_df, recurring_df). `expenses_df` covers every outgoing
    transaction (amount < 0); income rows are left out of this analysis.
    """
    expenses = df[df["amount"] < 0].copy()
    expenses["normalized_merchant"] = expenses["description"].apply(normalize_merchant)
    expenses["category"] = expenses["description"].apply(categorize)

    recurring_rows = []
    recurring_keys = set()

    for merchant_key, group in expenses.groupby("normalized_merchant"):
        group = group.sort_values("date")
        dates = group["date"].tolist()
        amounts = group["amount"].abs().tolist()
        category = categorize(group["description"].iloc[0])
        count = len(group)
        if count < 2:
            continue

        gaps = [(dates[i + 1] - dates[i]).days for i in range(len(dates) - 1)]
        mean_gap = statistics.mean(gaps)
        gap_std = statistics.pstdev(gaps) if len(gaps) > 1 else 0.0
        gap_cv = (gap_std / mean_gap) if mean_gap else float("inf")

        mean_amount = statistics.mean(amounts)
        amt_std = statistics.pstdev(amounts) if len(amounts) > 1 else 0.0
        amt_cv = (amt_std / mean_amount) if mean_amount else 0.0

        # Frequent-purchase categories (retail, dining, groceries...) can look
        # "regular" by coincidence even though they aren't subscriptions — require
        # a tighter, more evenly-spaced cadence and more evidence before flagging.
        if category in RETAIL_LIKE_CATEGORIES:
            is_recurring = (
                count >= 4
                and MIN_GAP_DAYS <= mean_gap <= MAX_GAP_DAYS
                and gap_cv <= MAX_RETAIL_GAP_CV
            )
        else:
            is_recurring = False
            if MIN_GAP_DAYS <= mean_gap <= MAX_GAP_DAYS:
                if len(gaps) == 1:
                    is_recurring = amt_cv <= MAX_TWO_POINT_AMOUNT_CV
                else:
                    is_recurring = gap_cv <= MAX_GAP_CV

        if not is_recurring:
            continue

        if count >= 4 and gap_cv <= 0.2:
            confidence = "High"
        elif count >= 3:
            confidence = "Medium"
        else:
            confidence = "Low"

        monthly = _monthly_equivalent(mean_amount, mean_gap)
        recurring_rows.append(
            {
                "merchant": merchant_key,
                "display_name": group["description"].mode().iat[0],
                "category": group["category"].iloc[0],
                "count": count,
                "avg_amount": round(mean_amount, 2),
                "monthly_estimate": round(monthly, 2),
                "annual_estimate": round(monthly * 12, 2),
                "first_date": dates[0],
                "last_date": dates[-1],
                "confidence": confidence,
            }
        )
        recurring_keys.add(merchant_key)

    expenses["is_recurring"] = expenses["normalized_merchant"].isin(recurring_keys)

    recurring_df = pd.DataFrame(recurring_rows)
    if not recurring_df.empty:
        recurring_df = recurring_df.sort_values("monthly_estimate", ascending=False).reset_index(drop=True)
    return expenses, recurring_df
