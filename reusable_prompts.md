Here’s a clean, reusable prompt you can drop into your instructions for another AI:

---

**Prompt:**

> Every time you make a change, create something new, or discover something during this project, append a short “journal entry” to a text file in a folder named `journals/`.
>
> * Each journal entry should include:
>
>   1. **Timestamp** (UTC)
>   2. **Change/Creation/Discovery** (concise summary of what happened)
>   3. **Reason/Context** (why we did it, or what we learned)
>   4. **Next Steps** (if any)
> * Create a new `.md` file for each day (`YYYY-MM-DD.md`) and append all that day’s entries to it.
> * Always keep this folder organized and up-to-date so other AI agents can later review it to quickly catch up on the project’s history.

**Example entry in `journals/2025-08-12.md`:**

```
## 2025-08-12 14:35 UTC
**Change:** Added ProxyManager to bot to rotate IPs per session.  
**Reason:** Reduce detection risk and distribute load evenly across proxies.  
**Next Steps:** Test proxy rotation with live requests to ensure IP cycling works without breaking session handling.
```

---

If you want, I can also make a **journal folder structure** and a **starter Markdown template** so it’s production-friendly from day one. That way the AI doesn’t have to “figure it out” each time.

