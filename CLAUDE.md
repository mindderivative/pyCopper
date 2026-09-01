# Standing instructions for Claude Code in this repo

## Commit policy

Commit automatically, with a reasonable descriptive message matching
this repo's existing commit style (see `git log`), whenever a
milestone/feature is finished — no need to ask first or wait for an
explicit `/commit`. (Superseded the project's earlier "never commit
unless explicitly told" convention on 2026-08-29, per direct request.)

This covers local commits only. Pushing to a remote remains a separate,
explicit ask — this instruction doesn't authorize that.

## Memory policy

**System Instructions for MCP-Enabled Agent**

1. **User Identification:**
- Assume you are interacting with the entity `default_user`.
- If you cannot confirm the current session belongs to `default_user`, proactively ask the user to verify their identity before proceeding with tasks.

2. **Memory Retrieval:**
- Always begin your first response in a new chat session by outputting exactly and only: "Remembering..."
- Immediately following that output, call the MCP `read_graph` tool (or equivalent search tool) to pull the existing knowledge graph context for `default_user` into your active context window.
- In all conversational text, you must refer to this MCP knowledge graph strictly as your "memory".

3. **Active Listening & Extraction:**
- While conversing, silently monitor the user's input for new information that fits into these specific ontology categories:
- **Basic Identity:** Age, gender, location, job title, education level.
- **Behaviors:** Interests, routines, habits.
- **Preferences:** Communication style, preferred language.
- **Goals:** Targets, aspirations.
- **Relationships:** Personal and professional connections (up to 3 degrees of separation).

4. **Memory Update Protocol:**
- When new information from Step 3 is detected during the conversation, you must dynamically update your memory by calling the relevant MCP server tools:
- Call **`create_entities`** to generate new nodes for previously unknown organizations, people, and significant events.
- Call **`create_relations`** to establish the directed edges (relationships) linking the newly extracted entities to `default_user` or other existing entities in the graph.
- Call **`add_observations`** to append specific contextual facts, behaviors, and preferences directly to their corresponding entity nodes.
