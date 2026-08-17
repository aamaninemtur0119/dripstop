import json

import anthropic

# Swap to "claude-sonnet-5" or "claude-haiku-4-5" for a cheaper/faster pass —
# this is a batch classification call, so a smaller model works fine too.
DEFAULT_MODEL = "claude-opus-5"

ASSESSMENT_SCHEMA = {
    "type": "object",
    "properties": {
        "assessments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "merchant": {"type": "string"},
                    "verdict": {"type": "string", "enum": ["essential", "discretionary"]},
                    "reasoning": {"type": "string"},
                    "cancellation_steps": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": ["merchant", "verdict", "reasoning", "cancellation_steps"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["assessments"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = (
    "You help a person review the recurring charges on their bank statement and decide "
    "what to keep. For each charge, judge whether it looks essential (housing, utilities, "
    "insurance, loan/debt payments, income-generating tools) or discretionary (entertainment, "
    "streaming, fitness, subscriptions that are easy to live without). Give a one-sentence "
    "reason grounded in the merchant name, category, and amount you were given. For "
    "discretionary charges, give 2-4 concrete steps to cancel that specific service, using "
    "your knowledge of how that company's cancellation flow typically works (account "
    "settings page, app store subscriptions, a phone number, etc). If you don't recognize "
    "the merchant, give generic-but-useful steps (check the merchant's website account "
    "settings, or contact your bank to block future charges). Leave cancellation_steps "
    "empty for essential charges."
)


def assess_recurring_charges(
    recurring: list[dict],
    api_key: str | None = None,
    model: str = DEFAULT_MODEL,
    on_progress=None,
) -> dict:
    """Ask Claude to classify each recurring merchant as essential/discretionary.

    `recurring` is a list of dicts with at least merchant/category/monthly_estimate/
    annual_estimate/count keys (matches the recurring_df rows from categorize.py).
    Streams the response; if given, `on_progress(accumulated_text)` is called on
    every text delta so a caller can show live progress instead of a static spinner.
    Returns a dict keyed by merchant name -> assessment dict.
    """
    client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()

    payload = [
        {
            "merchant": r["merchant"],
            "category": r["category"],
            "monthly_estimate": round(r["monthly_estimate"], 2),
            "annual_estimate": round(r["annual_estimate"], 2),
            "occurrences_seen": r["count"],
        }
        for r in recurring
    ]

    with client.messages.stream(
        model=model,
        max_tokens=8000,
        system=SYSTEM_PROMPT,
        output_config={
            "effort": "low",
            "format": {"type": "json_schema", "schema": ASSESSMENT_SCHEMA},
        },
        messages=[
            {
                "role": "user",
                "content": (
                    "Here are the recurring charges detected in my bank statement:\n\n"
                    + json.dumps(payload, indent=2)
                ),
            }
        ],
    ) as stream:
        accumulated = ""
        for delta in stream.text_stream:
            accumulated += delta
            if on_progress:
                on_progress(accumulated)
        response = stream.get_final_message()

    if response.stop_reason == "refusal":
        raise RuntimeError("Claude declined to process this request.")

    data = json.loads(accumulated)
    return {item["merchant"]: item for item in data["assessments"]}
