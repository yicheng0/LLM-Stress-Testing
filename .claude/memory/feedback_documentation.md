---
name: Documentation Maintenance Workflow
description: User's requirement for maintaining CLAUDE.md and memory after code changes
type: feedback
---

# Documentation Maintenance Workflow

After writing or modifying code, always update CLAUDE.md and memory documentation to track core optimization points.

**Why**: The user wants to maintain clear documentation of the project's evolution, architectural decisions, and optimization techniques. This ensures future developers (or future Claude instances) can understand the context behind implementation choices.

**How to apply**:

1. **After code changes, update CLAUDE.md if**:
   - Architecture changes (new classes, major refactoring)
   - New features added (parameters, metrics, output formats)
   - Request flow modified
   - Configuration defaults changed
   - Performance characteristics affected

2. **After code changes, update memory if**:
   - Core optimization implemented (document the technique and why it matters)
   - Bug fix with important context (what was wrong, why it happened)
   - Performance improvement discovered (what was the bottleneck, how was it solved)
   - User feedback incorporated (what was requested, why it matters)

3. **Create a summary document** (e.g., `CHANGELOG.md` or inline in memory):
   - List the core optimization points from each code change session
   - Explain the performance impact or quality improvement
   - Reference specific line numbers or functions if relevant

**Example workflow**:
```
1. Make code changes
2. Test the changes
3. Update CLAUDE.md (if architecture/features changed)
4. Create/update memory file (if optimization/important context)
5. Update MEMORY.md index
6. Commit with clear message referencing documentation updates
```

**Context**: User explicitly requested: "每次写完代码之后需要更新这些文档，整理每次代码的核心优化点" (After writing code, need to update these documents and organize the core optimization points from each change).
