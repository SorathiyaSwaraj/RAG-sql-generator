# ADR 0002: Gemini free tier with a local Ollama fallback

**Status:** Accepted

**Context:** The budget is zero. The development machine has a laptop CPU, 40 GB of RAM, and no NVIDIA GPU.

**Options:** Gemini free tier, Groq free tier, OpenRouter free models, Ollama.

**Decision:** Use Gemini first. On HTTP 429, switch to Ollama for the rest of the run. Both sit behind one small interface and use plain HTTP.

**Consequences:** Google's terms allow unpaid API content to improve its products and to be read by human reviewers, so the CLI asks for confirmation before sending schema. Ollama keeps data local, but is expected to be slower and possibly less accurate on this CPU. Each evaluation result records which provider answered, so results are not silently mixed.
