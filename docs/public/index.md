---
title: "AI Agile: Governed AI Software Development Lifecycle"
description: "AI Agile provides GitHub-native orchestration, shared coding standards, human approval gates and delivery metrics for teams using AI coding agents."
---

# AI Agile: Governed AI Software Development Lifecycle

AI Agile is the product delivered by the **ai-coding-standards2** repository from M&A Operating System. It provides a shared software development process for teams using AI coding agents: a deterministic orchestrator, reusable agent definitions, explicit task dependencies, coding standards, tool entitlements, human approval gates and an inspectable GitHub record.

Engineering leaders need to know what agents are building, whether the result meets the agreed requirements, who approved it and what delivery cost. Faster code generation does not answer those questions on its own. AI Agile connects an issue's intended outcome to product documentation, implementation, verification and review, so the team can manage AI-assisted work as a shared delivery process.

## What the product is designed to achieve

The objectives are to make agent-driven work visible, verify changes against agreed requirements, preserve accountable human decisions and improve delivery from measured outcomes. See [product objectives](objectives.md) for the intended outcomes and the evidence used to assess them.

Work starts with a GitHub issue. The orchestrator evaluates the declared pipeline, identifies the next eligible step and invokes the appropriate agent or deterministic script. Agents produce artifacts; human gates retain the decisions assigned to people. Issues, labels, comments, branches and pull requests connect the work to its requirements and review history. Exact steps and dependencies remain authoritative in the repository's pipeline definition.

The framework is consumed as a Git submodule. Shared agent definitions and machine-readable standards reduce divergence between projects; project-specific architectural decisions and exceptions remain in the consuming project's ADRs. Adoption and credentials must follow the repository's current installation guidance.

## How AI Agile supports engineering management

[Managing engineering teams using AI coding agents](engineering-management.md) explains how the product supports visibility, verification and process improvement. It connects management questions to concrete artifacts and measurements rather than requiring a manager to read every agent conversation.

AI Agile is a workflow and standards framework. It does not claim to record every developer's local coding session, preserve all uncompacted transcripts or provide a separate session-intelligence dashboard. Review gates and tests provide evidence; they do not guarantee that every defect is caught.

## Current framework and V3 target

The current framework's authoritative behavior is documented in the [orchestrator product](https://github.com/M-A-Operating-System/ai-coding-standards2/blob/main/docs/product/orchestrator/PRODUCT.md), [lifecycle](https://github.com/M-A-Operating-System/ai-coding-standards2/blob/main/docs/product/orchestrator/lifecycle.md) and [pipeline configuration](https://github.com/M-A-Operating-System/ai-coding-standards2/blob/main/pipeline/pipeline.json).

V3 is a proposed runtime extension in [PR 553](https://github.com/M-A-Operating-System/ai-coding-standards2/pull/553). It preserves agent definitions, pipeline tasks/dependencies/sequence and canonical entitlements while changing the execution wrapper and model-resolution boundary. Interactive Claude Code and headless OpenCode are intended to share the same process. Provider/model attribution and model-specific cost comparisons described for V3 are target capabilities until implemented and released.

## Get started

Read the [quick start](https://github.com/M-A-Operating-System/ai-coding-standards2/blob/main/docs/product/orchestrator/quick-start.md), [onboarding guide](https://github.com/M-A-Operating-System/ai-coding-standards2/blob/main/docs/product/orchestrator/16-onboarding.md) and [repository installation instructions](https://github.com/M-A-Operating-System/ai-coding-standards2#using-this-repo). The current installation restrictions apply; public documentation does not mean the execution pipeline is suitable for untrusted public issue submissions.

Source and implementation: [M-A-Operating-System/ai-coding-standards2](https://github.com/M-A-Operating-System/ai-coding-standards2).
