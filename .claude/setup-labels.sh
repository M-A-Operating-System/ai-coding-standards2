#!/usr/bin/env bash
# setup-labels.sh
# Run once to create the GitHub labels required by the compliance agent.
# Usage: bash .github/scripts/setup-labels.sh
# Requires: gh CLI authenticated

set -e

REPO="${1:-$(gh repo view --json nameWithOwner -q .nameWithOwner)}"
echo "Creating labels in: $REPO"

create_label() {
  local name="$1"
  local color="$2"
  local description="$3"

  if gh label list --repo "$REPO" --json name -q '.[].name' | grep -qx "$name"; then
    echo "  exists: $name"
  else
    gh label create "$name" \
      --repo "$REPO" \
      --color "$color" \
      --description "$description"
    echo "  created: $name"
  fi
}

# Compliance labels
create_label "standards-violation"  "D93F0B" "Code does not meet an architecture standard"
create_label "required"             "B60205" "Severity: required — must be fixed before merge"
create_label "recommended"          "E4E669" "Severity: recommended — should be fixed"
create_label "optional"             "C2E0C6" "Severity: optional — guidance only"

# Layer labels (match layer enum in standards schema)
create_label "database"             "0075CA" "Database layer violation"
create_label "api"                  "0075CA" "API layer violation"
create_label "backend"              "0075CA" "Backend layer violation"
create_label "frontend"             "0075CA" "Frontend layer violation"
create_label "security"             "B60205" "Security layer violation"
create_label "testing"              "C2E0C6" "Testing layer violation"
create_label "infra"                "F9D0C4" "Infrastructure layer violation"
create_label "cross-cutting"        "D4C5F9" "Cross-cutting concern violation"
create_label "product-behaviour"    "BFD4F2" "Product behaviour standard violation"
create_label "product-ux"           "BFD4F2" "Product UX standard violation"
create_label "product-data"         "BFD4F2" "Product data standard violation"
create_label "product-accessibility" "BFD4F2" "Accessibility standard violation"
create_label "product-compliance"   "B60205" "Compliance standard violation"

echo ""
echo "Done. All labels created in $REPO."
