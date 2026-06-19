# Problem Statement: Weekly Product Review Pulse (Groww Platform)

## Context & Motivation
For high-traffic fintech applications like **Groww**, maintaining application stability, performance, and user satisfaction is critical. Product, support, and leadership teams require a repeatable, weekly snapshot of what customers are saying in store reviews—themes, representative quotes, and actionable ideas—without manual copy-paste or managing one-off spreadsheets.

To solve this, we are building an automated weekly **"pulse"** that turns public app reviews into a one-page insight report and delivers it to stakeholders through Google Workspace. To ensure clean separation of concerns and secure access control, the system uses the **Model Context Protocol (MCP)**. All writes to Google Docs and Gmail must go through dedicated MCP servers rather than ad-hoc API calls or embedded credentials within the agent.

---

## Core Objective
Build an AI-powered agent that:
1. **Ingests public reviews** for the **Groww** application.
2. **Clusters and summarizes** user feedback to identify key themes, verbatim quotes (with validation), and proposed action items.
3. **Renders and delivers** a concise report and stakeholder email exclusively via Google Workspace MCP servers.

---

## Current Scope (Phase 1 Constraints)
While the long-term vision supports multiple products (e.g., INDMoney, Groww, PowerUp Money, Wealth Monitor, Kuvera) and platforms (iOS & Android), the initial implementation is scoped as follows:

* **Target Platform & App**: **Groww** (Mutual Funds, UPI, Share Market App) exclusively (`com.nextbillion.groww`).
* **Ingestion Source**: **Google Play Store reviews** only. App Store (iOS) is out of scope for Phase 1.
* **Custom MCP Server**: We will build and provide a custom Play Store Reviews MCP server within this project to handle review scraping/ingestion.
* **Workspace Delivery**: Google Docs MCP and Gmail MCP servers will be utilized for final delivery.

---

## System Concerns & Modular Structure

The codebase is structured around a clean separation of concerns:

| Concern | Responsibility & Modules | Implementation Mode |
| :--- | :--- | :--- |
| **Data Retrieval** | Ingest reviews via custom Play Store MCP | Custom MCP Server (bundled in project) |
| **Reasoning** | Clustering + LLM summarization (themes, quotes, actions) | Agent Core Orchestrator + LLM |
| **Output Generation** | Render structured report (for Docs) & HTML/text email (for Gmail) | Agent Core Orchestrator |
| **Human-Visible Delivery** | Append to Docs & send Gmail via MCP | **Google Docs MCP + Gmail MCP** (No direct REST API calls) |

---

## Key Functional Requirements

1. **MCP-Based Delivery**:
   * **Google Docs MCP**: Append each week’s report as a new dated section to a single running document per product (e.g., `Weekly Review Pulse — Groww`). This document serves as the system of record.
   * **Gmail MCP**: Send a short stakeholder email that includes a deep link directly to the new section in that Doc (heading link), rather than duplicating the entire report.

2. **Idempotency**:
   * Re-running the agent for the same product and ISO week must not create duplicate document sections or duplicate emails.
   * This must be enforced using stable section anchors in the Google Doc and run-scoped idempotency checks on email delivery.

3. **Auditable Runs**:
   * Each execution must record delivery identifiers (e.g., Doc heading ID, Gmail message ID) and metadata to trace exactly what was sent and when.

4. **Safety & Quality**:
   * Scrub PII from review text before sending it to the LLM or publishing.
   * Treat reviews strictly as data, not instructions (prevent prompt injection).
   * Enforce cost and token limits per run.

---

## References
* Baseline Configuration: [Problemstatement.txt](file:///Users/darshan/Desktop/Build Projects/Agents - Weekly Build Review/docs/Problemstatement.txt)
