# Feedback Synthesizer Agent

A multi-step AI agent that ingests GitHub issues, identifies emergent themes, scores them by signal strength, and generates a structured PM brief and eval spec. Built as a hands-on exploration of AI observability workflows using Arize AX.

---

## What it does

1. Fetches the 100 most recent open issues from a GitHub repo via the GitHub REST API
2. Sends all issues to Claude to identify 6-8 emergent themes from the data (no pre-defined categories)
3. Classifies each issue into one of those themes individually
4. Scores each theme using a weighted formula: issue count, reactions, comments, and a recency bonus
5. Generates a PM brief covering the top 3 pain points and a recommended feature to build
6. Generates an eval spec for the recommended feature, including dimensions, test cases, and pass/fail criteria

Every Claude API call is instrumented as a span in Arize AX, giving full trace visibility into the agent's reasoning across all steps.

---

## Why I built it

I wanted to understand what AI observability actually feels like from the inside, not just as a concept. Building a real agent, instrumenting it, and then using Arize AX to observe and evaluate it surfaced a product insight I wouldn't have found otherwise.

When I ran the agent twice two days apart, the top recommended feature changed completely. The traces showed me two runs but gave me no tool to understand whether the change was meaningful signal or noise. And when I used Alyx to generate an evaluator for the agent's outputs, there was no native way to validate whether the dimensions Alyx chose were the right ones before running at scale.

That gap, between generating an eval and trusting an eval, became the basis for a product proposal I called the **Eval Spec Validator**: a feature that lets teams annotate AI-generated eval specs with human feedback, then uses those annotations to improve eval spec generation over time via prompt optimization.

---

## Tech stack

- **Agent:** Python, Anthropic SDK (claude-sonnet-4-6)
- **Data source:** GitHub REST API (Arize-ai/phoenix public repo)
- **Observability:** Arize AX, OpenTelemetry, openinference-instrumentation-anthropic
- **Tracing:** 1 parent CHAIN span per run, ~103 LLM child spans
- **Evals:** Arize AX LLM-as-a-judge evaluator, generated via Alyx

---

## How to run it

**Prerequisites**

- Python 3.9+
- An Anthropic API key with credits
- A GitHub personal access token (public repo read access)
- An Arize AX account (free tier works)

**Setup**

```bash
git clone https://github.com/YOUR_USERNAME/arize-feedback-synthesizer.git
cd arize-feedback-synthesizer
pip3 install -r requirements.txt
```

Create a `.env` file in the project root:

```
ANTHROPIC_API_KEY=your_key_here
GITHUB_TOKEN=your_token_here
ARIZE_SPACE_ID=your_space_id
ARIZE_API_KEY=your_api_key
```

**Run**

```bash
python3 main.py
```

Output is saved to `output/pm-brief.md`. Traces appear in your Arize AX project within a few minutes of the run completing.

---

## Sample output

Running against the Arize-ai/phoenix repo (June 2026) surfaced 8 emergent themes. The top three by weighted score:

| Theme | Score | Issues |
|---|---|---|
| PXI Agent Tools & Skills | 186 | 26 |
| PXI Agent UX & Chat Experience | 110 | 15 |
| Data Validation & Client SDK Bugs | 86 | 12 |

The recommended feature: **PXI Agent Reliability & Trust Layer**, addressing span ID hallucination during annotation and silent empty runs in the playground — the two most trust-breaking behaviors in the current PXI agent.

---

## Product insight

The most interesting moment in this project wasn't the agent output. It was using Arize AX to observe the agent and realizing what the platform couldn't yet tell me.

Two specific gaps surfaced through hands-on use:

**Gap 1: No native way to compare runs over time.** Running the agent twice produced two traces. The recommended feature changed between runs. Arize showed me both traces but provided no tool to understand whether the change reflected new signal or noise in the weighting. Teams running agents repeatedly in production face this problem at scale.

**Gap 2: No feedback loop for eval spec quality.** Alyx generated a well-structured evaluator in under a minute. But the five dimensions it chose — Relevance, Distinctness, Coherence, Accuracy, Structure — were Alyx's judgment call. There was no native way to annotate which dimensions were well-designed, which needed revision, and feed that back to make future Alyx-generated evaluators better calibrated.

The confirmation drawer Arize launched in May 2026 is a step toward gap 2: it lets you edit the eval spec before saving. But it's a pre-flight edit, not a post-run feedback loop. The learning system is still missing.

The **Eval Spec Validator** proposal closes that loop: annotate dimensions after a run, store annotations as a labeled dataset, run prompt optimization on the eval spec generator, and produce better-calibrated evaluators for similar agents next time — without every team starting from scratch.

---

## Project structure

```
feedback-synthesizer/
├── main.py              # Agent logic, all five steps
├── instrumentation.py   # Arize AX tracing setup
├── requirements.txt     # Pinned dependencies
├── output/
│   └── pm-brief.md      # Generated PM brief and eval spec
└── .gitignore           # Excludes .env and output/
```

---

## Note on dependencies

This project requires pinned OpenTelemetry versions due to a breaking change in `opentelemetry-instrumentation 0.62b1` that removed `wrap_function_wrapper`, which `openinference-instrumentation-anthropic` depends on. The `requirements.txt` pins the stack to `opentelemetry 1.29.0 / 0.50b0` for compatibility with Python 3.9.
