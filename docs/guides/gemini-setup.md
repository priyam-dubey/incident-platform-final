# AI provider setup (Gemini by default)

AI is optional. Without a key, scanning, telemetry, detection and incidents all work; AI explanations and
root-cause hypotheses are shown as "AI not configured" rather than invented.

```
LLM_MODEL=gemini/gemini-2.5-flash     # default; any LiteLLM-style provider/model string
LLM_API_KEY=<your key>                # runtime environment only
```
These are the only two variables the LLM layer reads. Put the key in your host's secret store or an untracked `.env`.
The key is never logged, returned by an API, or sent to the browser.

How the output is used
* **Scan findings:** the scanner finds the issue deterministically; the model only explains it and suggests a fix.
* **Incidents:** the model sees a bounded, redacted evidence set and must cite evidence ids. Output that cites nothing
  or cites unknown ids is rejected (one retry). Results are labelled *hypothesis, not proof* and need human review.

If a key was ever pasted into chat or a ticket, treat it as exposed and rotate it.
