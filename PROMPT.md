Build me a Python project called feedback-synthesizer. Here is exactly what it should do, step by step:

## Setup

- Use python-dotenv to load environment variables from a .env file
- Required env vars: ANTHROPIC_API_KEY, GITHUB_TOKEN, ARIZE_SPACE_ID, ARIZE_API_KEY
- Create a requirements.txt with all dependencies

## Step 1: Fetch GitHub Issues

- Fetch the last 100 open issues from the GitHub repo Arize-ai/phoenix using the GitHub REST API
- Use my GITHUB_TOKEN for authentication
- For each issue, collect: title, body, labels, reaction count (thumbs up), comment count, and created_at date
- Skip any issues that are pull requests

## Step 2a: Identify Emergent Themes

- Make one Claude call using model claude-sonnet-4-6
- Pass in all 100 issue titles and bodies as context
- Ask Claude to read through all issues and identify 6 to 8 natural themes that emerge from the data
- Return the themes as a JSON list where each item has a name and one-sentence description
- Print the identified themes to the console so I can review them before classification begins

## Step 2b: Classify Each Issue

- For each issue, make a separate call to Claude using model claude-sonnet-4-6
- Classify the issue into exactly one of the themes identified in Step 2a
- Also return a one-sentence reason for the classification
- Return the result as structured JSON with fields: theme, reason

## Step 3: Score Each Theme

- Group all issues by theme
- Score each theme using this formula: (issue count x 3) + (total reactions x 2) + (total comments x 1) + (recency bonus: +2 for each issue created in the last 30 days)
- Sort themes by score descending

## Step 4: Generate PM Brief

- Make one Claude call using model claude-sonnet-4-6
- Pass in the top 3 scoring themes and their issues as context
- Ask Claude to generate a PM brief with these sections: Top 3 Pain Points, Recommended Feature to Build, and Rationale
- The brief must cite specific issue titles as evidence, not make up claims

## Step 5: Generate Eval Spec

- Make one Claude call using model claude-sonnet-4-6
- Pass in the recommended feature from Step 4 as context
- Ask Claude to generate an eval spec with these sections: Eval Dimensions (3-5 dimensions), Example Test Cases (3 specific examples with inputs and expected outputs), Pass/Fail Criteria
- The eval spec should be specific enough that an engineer could implement it without asking follow-up questions

## Output

- Save everything to a file called output/pm-brief.md
- Include all five steps in the output: identified themes, issue count per theme, scores, PM brief, and eval spec
- Print progress to the console as each step completes so I can see it running

## Code structure

- Put everything in a single file called main.py to keep it simple
- Add a comment above each step so the code is easy to follow
- Handle API errors gracefully and print a clear message if something fails
