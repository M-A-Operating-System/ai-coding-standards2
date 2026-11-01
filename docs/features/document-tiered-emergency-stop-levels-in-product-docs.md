# Feature: Document Tiered Emergency Stop Levels In Product Docs

## Scenario: Emergency stop documentation describes all three levels
**Given** the product orchestrator documentation exists in `docs/product/orchestrator/`
**When** a reader opens the emergency stop section
**Then** the documentation states the semantics of all three stop levels: level 1 halts AI agents, level 2 halts all pipeline steps except maintenance, and level 3 halts everything

## Scenario: stopOnLevel field is fully documented
**Given** the product orchestrator documentation includes a step configuration reference
**When** a reader looks up the `stopOnLevel` field
**Then** the documentation states the field's meaning, lists its allowed values (1, 2, and 3), and states its default value of 1 when omitted

## Scenario: Binary stop description replaced with tiered model and backward-compatibility rule
**Given** the product orchestrator documentation previously described the emergency stop as a binary switch
**When** a reader opens the emergency stop documentation
**Then** the docs describe the tiered model and state that an emergency stop marker without a `level` field is treated as level 3
