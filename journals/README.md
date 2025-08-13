# Development Journals

This folder contains daily development journals tracking all changes, creations, and discoveries made during the project.

## Format

Each journal entry includes:
1. **Timestamp** (UTC) 
2. **Change/Creation/Discovery** (concise summary)
3. **Reason/Context** (why we did it, what we learned)
4. **Next Steps** (if any)

## File Structure

- `YYYY-MM-DD.md` - One file per day
- Entries are appended chronologically within each day
- All timestamps in UTC for consistency

## Purpose

These journals enable:
- Quick project history review for new team members or AI agents
- Understanding of decision rationale and context
- Tracking of implementation progress and discoveries
- Reference for future similar implementations

## Example Entry Format

```markdown
## 2025-08-12 14:35 UTC
**Change:** Added ProxyManager to bot to rotate IPs per session.  
**Reason:** Reduce detection risk and distribute load evenly across proxies.  
**Next Steps:** Test proxy rotation with live requests to ensure IP cycling works.
```