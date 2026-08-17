import pandas as pd

COLUMN_ALIASES = {
    "date": ["date", "transaction date", "posted date"],
    "description": ["description", "memo", "name", "merchant"],
    "amount": ["amount", "value"],
}


def _find_column(columns_lower_map: dict, aliases: list) -> str | None:
    for alias in aliases:
        if alias in columns_lower_map:
            return columns_lower_map[alias]
    return None


def load_transactions(file) -> pd.DataFrame:
    """Load a bank-style CSV into a normalized (date, description, amount) frame.

    Accepts common column-name variants (Date/Transaction Date, Description/Memo,
    Amount/Value) so it isn't tied to one export format. Amounts follow the
    standard convention: negative = money out, positive = money in.
    """
    df = pd.read_csv(file)
    columns_lower_map = {c.strip().lower(): c for c in df.columns}

    resolved = {}
    for key, aliases in COLUMN_ALIASES.items():
        col = _find_column(columns_lower_map, aliases)
        if col is None:
            raise ValueError(
                f"Couldn't find a '{key}' column. Expected one of: {', '.join(aliases)}. "
                f"Found columns: {', '.join(df.columns)}"
            )
        resolved[key] = col

    out = pd.DataFrame(
        {
            "date": pd.to_datetime(df[resolved["date"]], errors="coerce"),
            "description": df[resolved["description"]].astype(str).str.strip(),
            "amount": pd.to_numeric(df[resolved["amount"]], errors="coerce"),
        }
    )

    bad_rows = out["date"].isna() | out["amount"].isna()
    if bad_rows.all():
        raise ValueError("No valid rows found — check the Date and Amount columns.")
    out = out[~bad_rows].reset_index(drop=True)
    out = out.sort_values("date").reset_index(drop=True)
    return out
