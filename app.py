import os
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st
from dotenv import load_dotenv

from dripstop.ai import assess_recurring_charges
from dripstop.auth import init_db, sign_in, sign_up
from dripstop.categorize import build_analysis
from dripstop.parsing import load_transactions

load_dotenv(override=True)  # .env always wins over a stale shell-exported key

SAMPLE_CSV = Path(__file__).parent / "dripstop_sample_transactions.csv"

# Validated categorical palette (light mode) — see dataviz skill reference.
PALETTE = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
OTHER_COLOR = "#898781"  # neutral, outside the categorical palette — for the "Other" bucket

# Bright, maximally-distinct pair (the two most contrasting palette slots) —
# used consistently for "recurring" vs "one-time" across every chart that
# shows this split, via a name-keyed color map (not positional) so it can
# never silently swap.
COLOR_RECURRING = PALETTE[0]  # blue
COLOR_ONE_TIME = PALETTE[1]  # orange
RECURRING_COLOR_MAP = {"Recurring": COLOR_RECURRING, "One-time / variable": COLOR_ONE_TIME}
COLOR_GOOD = "#0ca30c"
COLOR_WARNING = "#d03b3b"

st.set_page_config(page_title="Dripstop", layout="wide", initial_sidebar_state="expanded")
init_db()

# Hide Streamlit's own chrome: the Deploy button + "⋮" menu (top right), and
# the sidebar collapse/expand arrows. The sidebar is forced to stay expanded
# above (initial_sidebar_state) so hiding its toggle never traps the API-key
# / sign-out controls behind a control that no longer exists.
st.markdown(
    """
    <style>
    [data-testid="stToolbar"] { display: none; }
    [data-testid="stAppDeployButton"] { display: none; }
    #MainMenu { visibility: hidden; }
    [data-testid="stSidebarCollapsedControl"] { display: none; }
    [data-testid="stSidebarCollapseButton"] { display: none; }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("Dripstop")
st.caption("Subscription & recurring charge leak detector")

# ---------------------------------------------------------------------------
# Auth gate — nothing below this runs until signed in
# ---------------------------------------------------------------------------
if "user" not in st.session_state:
    st.session_state.user = None

if st.session_state.user is None:
    signin_tab, signup_tab = st.tabs(["Sign In", "Sign Up"])

    with signin_tab:
        with st.form("signin_form"):
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            if st.form_submit_button("Sign In", type="primary"):
                ok, message = sign_in(username, password)
                if ok:
                    st.session_state.user = username.strip().lower()
                    st.rerun()
                else:
                    st.error(message)

    with signup_tab:
        with st.form("signup_form"):
            new_username = st.text_input("Choose a username", help="3-32 characters: lowercase letters, numbers, underscore.")
            new_password = st.text_input("Choose a password", type="password", help="At least 8 characters.")
            confirm_password = st.text_input("Confirm password", type="password")
            if st.form_submit_button("Sign Up", type="primary"):
                ok, message = sign_up(new_username, new_password, confirm_password)
                if ok:
                    st.success(f"{message} Switch to the \"Sign In\" tab.")
                else:
                    st.error(message)

    st.stop()

# ---------------------------------------------------------------------------
# Signed in — main app
# ---------------------------------------------------------------------------
with st.sidebar:
    st.success(f"Signed in as **{st.session_state.user}**")
    if st.button("Log out"):
        for key in [
            "user", "raw_df", "expenses", "recurring_df",
            "ai_assessments", "decisions", "ai_error", "ai_attempted_signature",
        ]:
            st.session_state.pop(key, None)
        st.rerun()

    st.divider()
    st.subheader("API Key")
    env_key = os.environ.get("ANTHROPIC_API_KEY")
    if env_key:
        st.success("Using API key from your environment.")
        api_key = env_key
    else:
        api_key = st.text_input(
            "API key",
            type="password",
            help="Only kept for this session — never written to disk.",
        )
        st.caption("Or set the ANTHROPIC_API_KEY environment variable before launching.")

tab_upload, tab_categorize, tab_decide = st.tabs(["1. Upload", "2. Categorize", "3. Decide"])

# ---------------------------------------------------------------------------
# Tab 1 — Upload
# ---------------------------------------------------------------------------
with tab_upload:
    st.header("Upload your transactions")

    col_upload, col_sample = st.columns([3, 1])
    with col_upload:
        uploaded = st.file_uploader("CSV with Date, Description, Amount columns", type="csv")
    with col_sample:
        st.write("")
        st.write("")
        use_sample = st.button("Use sample data", width="stretch", disabled=not SAMPLE_CSV.exists())

    source = None
    if uploaded is not None:
        source = uploaded
    elif use_sample:
        source = SAMPLE_CSV

    if source is not None:
        try:
            st.session_state.raw_df = load_transactions(source)
        except ValueError as exc:
            st.error(str(exc))

    if "raw_df" in st.session_state:
        raw_df = st.session_state.raw_df
        date_min, date_max = raw_df["date"].min().date(), raw_df["date"].max().date()
        st.success(f"Loaded {len(raw_df)} transactions, {date_min} to {date_max}.")
        with st.expander("Preview raw data"):
            st.dataframe(raw_df, width="stretch", hide_index=True)
    else:
        st.info("Upload a CSV or click \"Use sample data\" to get started.")

# ---------------------------------------------------------------------------
# Tab 2 — Categorize: regular vs. recurring
# ---------------------------------------------------------------------------
with tab_categorize:
    if "raw_df" not in st.session_state:
        st.info("Upload transactions in the \"1. Upload\" tab first.")
    else:
        raw_df = st.session_state.raw_df
        expenses, recurring_df = build_analysis(raw_df)
        st.session_state.expenses = expenses
        st.session_state.recurring_df = recurring_df

        st.header("Categories: regular vs. recurring")

        total_spend = expenses["amount"].abs().sum()
        recurring_monthly = recurring_df["monthly_estimate"].sum() if not recurring_df.empty else 0.0

        m1, m2, m3 = st.columns(3)
        m1.metric("Total spend", f"${total_spend:,.2f}")
        m2.metric("Recurring merchants found", f"{len(recurring_df)}")
        m3.metric("Recurring cost / month", f"${recurring_monthly:,.2f}")

        chart_col1, chart_col2 = st.columns(2)

        with chart_col1:
            cat_totals = (
                expenses.groupby("category")["amount"].apply(lambda s: s.abs().sum()).sort_values(ascending=False)
            )
            top = cat_totals.head(8)
            rest = cat_totals.iloc[8:].sum()
            if rest > 0:
                top = pd.concat([top, pd.Series({"Other": rest})])

            # Assign colors by category name (alphabetical), not by spend rank, so a
            # category's color doesn't shift just because its relative spend changes
            # between reruns. At most 8 real categories are ever shown here, so this
            # always stays within the palette's validated 8-hue set — no collisions.
            real_categories = sorted(c for c in top.index if c != "Other")
            category_colors = {name: PALETTE[i % len(PALETTE)] for i, name in enumerate(real_categories)}
            category_colors["Other"] = OTHER_COLOR

            plot_df = top.sort_values(ascending=True).rename_axis("category").reset_index(name="amount")
            fig_cat = px.bar(
                plot_df,
                x="amount",
                y="category",
                orientation="h",
                labels={"amount": "Total spend ($)", "category": ""},
                color="category",
                color_discrete_map=category_colors,
            )
            fig_cat.update_layout(
                title="Spend by category",
                showlegend=False,
                template="plotly_white",
                margin=dict(l=10, r=10, t=40, b=10),
            )
            fig_cat.update_traces(hovertemplate="%{y}: $%{x:,.2f}<extra></extra>")
            st.plotly_chart(fig_cat, width="stretch")

        with chart_col2:
            split = expenses.assign(kind=expenses["is_recurring"].map({True: "Recurring", False: "One-time / variable"}))
            split_totals = split.groupby("kind")["amount"].apply(lambda s: s.abs().sum()).reset_index(name="amount")
            fig_split = px.pie(
                split_totals,
                names="kind",
                values="amount",
                hole=0.5,
                color="kind",
                color_discrete_map=RECURRING_COLOR_MAP,
            )
            fig_split.update_traces(hovertemplate="%{label}: $%{value:,.2f} (%{percent})<extra></extra>")
            fig_split.update_layout(
                title="Recurring vs. one-time spend",
                template="plotly_white",
                margin=dict(l=10, r=10, t=40, b=10),
            )
            st.plotly_chart(fig_split, width="stretch")

        monthly = (
            expenses.assign(
                month=expenses["date"].dt.to_period("M").dt.to_timestamp(),
                kind=expenses["is_recurring"].map({True: "Recurring", False: "One-time / variable"}),
            )
            .groupby(["month", "kind"])["amount"]
            .apply(lambda s: s.abs().sum())
            .reset_index()
        )
        fig_trend = px.bar(
            monthly,
            x="month",
            y="amount",
            color="kind",
            color_discrete_map=RECURRING_COLOR_MAP,
            labels={"amount": "Spend ($)", "month": "", "kind": ""},
        )
        fig_trend.update_layout(
            title="Monthly spend trend",
            barmode="stack",
            template="plotly_white",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
            margin=dict(l=10, r=10, t=60, b=10),
        )
        st.plotly_chart(fig_trend, width="stretch")

        with st.expander(f"Recurring merchants detected ({len(recurring_df)})"):
            if recurring_df.empty:
                st.write("No recurring charges detected yet.")
            else:
                st.dataframe(
                    recurring_df[["display_name", "category", "count", "avg_amount", "monthly_estimate", "confidence"]]
                    .rename(
                        columns={
                            "display_name": "Merchant",
                            "category": "Category",
                            "count": "Times seen",
                            "avg_amount": "Avg charge ($)",
                            "monthly_estimate": "Monthly est. ($)",
                            "confidence": "Confidence",
                        }
                    ),
                    width="stretch",
                    hide_index=True,
                )

# ---------------------------------------------------------------------------
# Tab 3 — Needed vs. not needed, with cancellation guidance
# ---------------------------------------------------------------------------
with tab_decide:
    if "raw_df" not in st.session_state:
        st.info("Upload transactions in the \"1. Upload\" tab first.")
    else:
        recurring_df = st.session_state.recurring_df

        st.header("What's worth keeping?")

        if recurring_df.empty:
            st.info("No recurring charges to review yet — upload more transaction history.")
        else:
            st.session_state.setdefault("ai_assessments", {})
            st.session_state.setdefault("decisions", {})

            st.session_state.setdefault("ai_error", None)
            st.session_state.setdefault("ai_attempted_signature", None)

            # Re-run automatically whenever the set of recurring merchants changes,
            # or once an API key becomes available — not on every rerun (that would
            # re-bill the API on every button click anywhere in the app).
            recurring_key = tuple(sorted(recurring_df["merchant"]))
            attempt_signature = (recurring_key, bool(api_key))

            def run_analysis():
                total = len(recurring_df)
                status = st.status("Loading...", expanded=False)
                seen_count = 0

                def on_progress(accumulated_text):
                    nonlocal seen_count
                    count = min(accumulated_text.count('"merchant"'), total)
                    if count != seen_count:
                        seen_count = count
                        status.update(label=f"Loading... ({count} of {total})")

                try:
                    st.session_state.ai_assessments = assess_recurring_charges(
                        recurring_df.to_dict("records"), api_key=api_key, on_progress=on_progress
                    )
                    st.session_state.ai_error = None
                    status.update(label="Done", state="complete")
                except Exception as exc:  # surfaced to the user, not swallowed
                    st.session_state.ai_error = f"Analysis failed: {exc}"
                    status.update(label="Analysis failed", state="error")
                st.session_state.ai_attempted_signature = attempt_signature

            if st.session_state.ai_attempted_signature != attempt_signature:
                if not api_key:
                    st.session_state.ai_error = "Add your Anthropic API key in the sidebar to get needed/not-needed verdicts."
                    st.session_state.ai_attempted_signature = attempt_signature
                else:
                    run_analysis()

            if st.session_state.ai_error:
                st.error(st.session_state.ai_error)
                if api_key and st.button("Retry"):
                    run_analysis()
                    st.rerun()

            assessments = st.session_state.ai_assessments
            if assessments:
                for _, row in recurring_df.iterrows():
                    assessment = assessments.get(row["merchant"])
                    with st.container(border=True):
                        header_col, cost_col = st.columns([3, 1])
                        header_col.markdown(f"**{row['display_name']}** — {row['category']}")
                        cost_col.markdown(f"${row['monthly_estimate']:,.2f} / mo")

                        if assessment is None:
                            st.caption("No assessment for this merchant yet.")
                            continue

                        verdict = assessment["verdict"]
                        if verdict == "essential":
                            st.markdown(f":green[**Essential**] — {assessment['reasoning']}")
                        else:
                            st.markdown(f":red[**Discretionary**] — {assessment['reasoning']}")

                            decision = st.session_state.decisions.get(row["merchant"])

                            if decision is None:
                                keep_col, cancel_col = st.columns(2)
                                if keep_col.button("Keep it", key=f"keep-{row['merchant']}"):
                                    st.session_state.decisions[row["merchant"]] = "keep"
                                    st.rerun()
                                if cancel_col.button("Cancel it", key=f"cancel-{row['merchant']}"):
                                    st.session_state.decisions[row["merchant"]] = "cancel"
                                    st.rerun()
                            else:
                                status_col, change_col = st.columns([4, 1])
                                if decision == "keep":
                                    status_col.markdown(":green[**Keeping this one**]")
                                else:
                                    status_col.markdown(":red[**Marked to cancel**]")
                                if change_col.button("Change", key=f"change-{row['merchant']}"):
                                    st.session_state.decisions.pop(row["merchant"], None)
                                    st.rerun()

                                if decision == "cancel":
                                    st.markdown("**How to cancel:**")
                                    for step in assessment["cancellation_steps"]:
                                        st.markdown(f"- {step}")

                discretionary = [m for m, a in assessments.items() if a["verdict"] == "discretionary"]
                cancelled = [m for m in discretionary if st.session_state.decisions.get(m) == "cancel"]
                if discretionary:
                    savings = recurring_df[recurring_df["merchant"].isin(cancelled)]["monthly_estimate"].sum()
                    st.markdown(
                        f"**{len(cancelled)} of {len(discretionary)}** discretionary subscriptions marked to cancel "
                        f"— potential savings: **${savings:,.2f}/mo** (${savings * 12:,.2f}/yr)."
                    )
