INTENT_SCHEMA = """
    Return ONLY valid JSON matching this schema (no markdown, no prose):
    {
    "intent": "compare_cac_roas_last_vs_prior",
    "n_days": <integer>=30,
    "metrics": ["CAC","ROAS"]  // optional extras: "spend","conversions"
    }
    Rules:
    - If the question asks to compare CAC/ROAS for "last N days vs prior/previous N days", set "intent" exactly as above and extract N (default 30).
    - Ignore casing and punctuation in the question.
    - Do not include any keys other than the three above.
    """

def parse_with_llm(question: str) -> dict | None:
    system = (
        "You convert a user's analytics question into a minimal JSON intent for a KPI API. "
        "Respond with STRICT JSON only."
    )
    user = f"Question: {question}\n\n{INTENT_SCHEMA}"
    out = call_openai([{"role": "system", "content": system}, {"role": "user", "content": user}])

    # strip code fences if model added them
    out = out.strip()
    out = re.sub(r"^```json|^```|```$", "", out).strip()
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return None

    # minimal validation
    if data.get("intent") != "compare_cac_roas_last_vs_prior":
        return None
    if not isinstance(data.get("n_days", 30), int):
        data["n_days"] = 30
    if "metrics" not in data or not isinstance(data["metrics"], list):
        data["metrics"] = ["CAC","ROAS"]
    return data