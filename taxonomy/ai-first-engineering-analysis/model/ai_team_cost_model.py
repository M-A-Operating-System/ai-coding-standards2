"""Cost and throughput model for AI-first engineering team substitution.

Companion implementation for the Section 5 analysis in
"The Cost Structure of AI-First Engineering Teams" (v1.0, 13 August 2026).

Models two configurations of a small engineering team and computes the
throughput differential, cost per unit of delivered output, and the
break-even AI budget at which the substituted configuration ceases to be
cheaper per unit.

Output units are merged pull-request equivalents, following the proxy used
in Murphy-Hill, Butler & Savelieva (2026), arXiv:2607.01418. A merged PR is
not equivalent to the value it delivers; see Section 1.3 of the paper.

PARAMETER PROVENANCE. Compensation figures are derived (BLS median wage x a
published 1.5-1.8x fully-loaded multiplier), not observed. Productivity lifts
are sourced to named studies in the SCENARIOS mapping below. The output unit
follows arXiv:2607.01418 and is an upper bound on the substituted
configuration, for the reason recorded in the note above SCENARIOS. No
parameter in this module is an unsourced author estimate; the two estimated
lines in the paper's budget table (CI/compute uplift, evaluation reserve) are
deliberately NOT modelled here, because mixing estimates with sourced inputs
in one computation is how unsourced figures acquire false authority.

Python 3.11+. No third-party dependencies.

Usage:
    python ai_team_cost_model.py
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Final, Sequence

__all__ = [
    "TeamConfiguration",
    "VerificationBoundResult",
    "verification_bound",
    "supervision_ratio_thresholds",
    "SupervisionResult",
    "supervision_model",
    "solve_r_thresholds",
    "supervision_capacity_anchor",
    "supervisor_capacity",
    "people_required",
    "max_r_for_headcount",
    "SPAN_OF_CONTROL",
    "SPAN_RANGE",
    "SUPERVISOR_LOADED_ANNUAL",
    "MAINTAINABILITY_FTE",
    "engineering_team",
    "TokenCost",
    "token_cost",
    "tokens_per_supervisor",
    "constant_output_comparison",
    "TOKEN_CASES",
    "MERGED_TASKS_PER_UNIT",
    "pre_ai_baseline",
    "R_SCENARIOS",
    "R_DERIVED_CENTRAL",
    "R_DERIVED_RANGE",
    "derive_r",
    "ConfigurationResult",
    "SubstitutionAnalysis",
    "SensitivityRow",
    "analyse",
    "sensitivity_table",
]

MONTHS_PER_YEAR: Final[int] = 12
_CENTS: Final[Decimal] = Decimal("0.01")


def _money(value: Decimal | int | str) -> Decimal:
    """Coerce a value to a currency-scaled Decimal.

    Using Decimal rather than float avoids the accumulation of binary
    floating-point error across the break-even solve, which is a division
    of one derived quantity by another.
    """
    return Decimal(value).quantize(_CENTS, rounding=ROUND_HALF_UP)


@dataclass(frozen=True, slots=True)
class TeamConfiguration:
    """A staffing and tooling configuration for a product engineering team.

    Product managers bear cost but do not contribute merged-PR output units.
    This is a deliberate modelling choice, not a claim that product management
    is unproductive: the output proxy adopted from arXiv:2607.01418 is merged
    pull requests, which product managers do not author. The consequence is
    that product-management capacity affects cost per unit directly and
    affects throughput only indirectly, through specification quality. See
    Section 5.5 of the accompanying paper.

    Attributes:
        label: Human-readable identifier for the configuration.
        leads: Count of engineering leads.
        developers: Count of developers.
        product_managers: Product management FTE, which may be fractional
            (e.g. Decimal("0.5") for a half-time or shared PM).
        lead_loaded_annual: Fully-loaded annual cost per lead, in USD.
        developer_loaded_annual: Fully-loaded annual cost per developer, in USD.
        pm_loaded_annual: Fully-loaded annual cost per product manager FTE,
            in USD.
        ai_spend_per_person_monthly: AI tooling spend per FTE per month, in
            USD, applied across the whole team including product management.
            Set to zero when the AI budget is being solved for.
        productivity_lift: Fractional productivity uplift attributable to AI
            tooling, expressed as a decimal (0.24 for +24%). Applied
            uniformly to every engineer in the configuration.

    Raises:
        ValueError: If any count is negative, any cost is negative, or the
            productivity lift is below -1.0 (which would imply negative
            output).
    """

    label: str
    leads: int
    developers: int
    product_managers: Decimal
    lead_loaded_annual: Decimal
    developer_loaded_annual: Decimal
    pm_loaded_annual: Decimal
    ai_spend_per_person_monthly: Decimal
    productivity_lift: Decimal

    def __post_init__(self) -> None:
        if self.leads < 0 or self.developers < 0 or self.product_managers < 0:
            raise ValueError("Headcounts must be non-negative.")
        if self.engineering_headcount == 0:
            raise ValueError("A configuration must contain at least one engineer.")
        if (
            self.lead_loaded_annual < 0
            or self.developer_loaded_annual < 0
            or self.pm_loaded_annual < 0
        ):
            raise ValueError("Loaded costs must be non-negative.")
        if self.ai_spend_per_person_monthly < 0:
            raise ValueError("AI spend must be non-negative.")
        if self.productivity_lift < Decimal("-1"):
            raise ValueError("Productivity lift below -100% implies negative output.")

    @property
    def engineering_headcount(self) -> int:
        """Engineers in the configuration. Only these produce output units."""
        return self.leads + self.developers

    @property
    def total_fte(self) -> Decimal:
        """Total FTE including product management."""
        return Decimal(self.engineering_headcount) + self.product_managers

    @property
    def payroll_annual(self) -> Decimal:
        """Total fully-loaded annual payroll, in USD."""
        return _money(
            self.leads * self.lead_loaded_annual
            + self.developers * self.developer_loaded_annual
            + self.product_managers * self.pm_loaded_annual
        )

    @property
    def ai_spend_annual(self) -> Decimal:
        """Total annual AI tooling spend, in USD."""
        return _money(
            self.ai_spend_per_person_monthly * self.total_fte * MONTHS_PER_YEAR
        )

    @property
    def total_annual(self) -> Decimal:
        """Total annual cost of the configuration, in USD."""
        return _money(self.payroll_annual + self.ai_spend_annual)

    @property
    def output_units(self) -> Decimal:
        """Delivered output in merged PR-equivalents per unit period.

        One engineer operating without agentic tooling produces 1.0 units.
        Product managers contribute no units under this proxy.
        """
        return (
            Decimal(self.engineering_headcount) * (Decimal("1") + self.productivity_lift)
        ).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)

    @property
    def cost_per_unit(self) -> Decimal:
        """Annual cost per unit of delivered output, in USD."""
        if self.output_units == 0:
            raise ZeroDivisionError("Configuration produces no output.")
        return _money(self.total_annual / self.output_units)


@dataclass(frozen=True, slots=True)
class ConfigurationResult:
    """Computed metrics for a single configuration."""

    label: str
    engineering_headcount: int
    product_managers: Decimal
    total_fte: Decimal
    payroll_annual: Decimal
    ai_spend_annual: Decimal
    total_annual: Decimal
    output_units: Decimal
    cost_per_unit: Decimal


@dataclass(frozen=True, slots=True)
class SubstitutionAnalysis:
    """Comparative result for a baseline versus a substituted configuration.

    Attributes:
        baseline: Metrics for the baseline configuration.
        substituted: Metrics for the substituted configuration, evaluated at
            zero AI spend (the AI budget is solved for separately).
        throughput_ratio: Substituted output as a proportion of baseline.
        required_lift_for_parity: Per-engineer productivity lift the
            substituted configuration would need to match baseline output.
        breakeven_ai_budget_annual: Annual AI budget at which the substituted
            configuration's cost per unit equals the baseline's. A negative
            value indicates no viable budget exists - the substitution is
            worse on both throughput and unit cost at any spend level.
    """

    baseline: ConfigurationResult
    substituted: ConfigurationResult
    throughput_ratio: Decimal
    required_lift_for_parity: Decimal
    breakeven_ai_budget_annual: Decimal

    @property
    def is_viable(self) -> bool:
        """True if a positive AI budget exists at which unit cost is favourable."""
        return self.breakeven_ai_budget_annual > 0


@dataclass(frozen=True, slots=True)
class SensitivityRow:
    """One row of the productivity-lift sensitivity analysis."""

    lift: Decimal
    output_units: Decimal
    throughput_ratio: Decimal
    breakeven_ai_budget_annual: Decimal


def _summarise(config: TeamConfiguration) -> ConfigurationResult:
    return ConfigurationResult(
        label=config.label,
        engineering_headcount=config.engineering_headcount,
        product_managers=config.product_managers,
        total_fte=config.total_fte,
        payroll_annual=config.payroll_annual,
        ai_spend_annual=config.ai_spend_annual,
        total_annual=config.total_annual,
        output_units=config.output_units,
        cost_per_unit=config.cost_per_unit,
    )


def analyse(
    baseline: TeamConfiguration, substituted: TeamConfiguration
) -> SubstitutionAnalysis:
    """Compare a baseline configuration against a substituted one.

    The substituted configuration's ``ai_spend_per_person_monthly`` is
    ignored for the break-even solve; the break-even budget is derived from
    the baseline's cost per unit and the substituted configuration's payroll
    and output.

    Args:
        baseline: The reference configuration (e.g. lead plus three developers).
        substituted: The proposed configuration (e.g. lead plus one developer).

    Returns:
        A SubstitutionAnalysis carrying both configurations' metrics and the
        derived comparative quantities.

    Raises:
        ZeroDivisionError: If either configuration produces zero output.
    """
    if baseline.output_units == 0 or substituted.output_units == 0:
        raise ZeroDivisionError("Both configurations must produce output.")

    throughput_ratio = (substituted.output_units / baseline.output_units).quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_UP
    )

    required_lift = (
        baseline.output_units / Decimal(substituted.engineering_headcount) - Decimal("1")
    ).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)

    # Solve: (payroll + X) / output_substituted == cost_per_unit_baseline
    breakeven = _money(
        baseline.cost_per_unit * substituted.output_units - substituted.payroll_annual
    )

    return SubstitutionAnalysis(
        baseline=_summarise(baseline),
        substituted=_summarise(substituted),
        throughput_ratio=throughput_ratio,
        required_lift_for_parity=required_lift,
        breakeven_ai_budget_annual=breakeven,
    )


def sensitivity_table(
    baseline: TeamConfiguration,
    substituted: TeamConfiguration,
    lifts: Sequence[Decimal],
) -> list[SensitivityRow]:
    """Vary the substituted configuration's productivity lift and re-solve.

    Args:
        baseline: The reference configuration, held constant.
        substituted: The proposed configuration; its productivity_lift is
            replaced by each value in ``lifts`` in turn.
        lifts: Fractional productivity lifts to evaluate.

    Returns:
        One SensitivityRow per lift, in the order supplied.
    """
    rows: list[SensitivityRow] = []
    for lift in lifts:
        variant = TeamConfiguration(
            label=substituted.label,
            leads=substituted.leads,
            developers=substituted.developers,
            product_managers=substituted.product_managers,
            lead_loaded_annual=substituted.lead_loaded_annual,
            developer_loaded_annual=substituted.developer_loaded_annual,
            pm_loaded_annual=substituted.pm_loaded_annual,
            ai_spend_per_person_monthly=Decimal("0"),
            productivity_lift=lift,
        )
        result = analyse(baseline, variant)
        rows.append(
            SensitivityRow(
                lift=lift,
                output_units=variant.output_units,
                throughput_ratio=result.throughput_ratio,
                breakeven_ai_budget_annual=result.breakeven_ai_budget_annual,
            )
        )
    return rows


# --- Alternative functional form: verification-bound throughput ----------
#
# The augmentation model above computes output = engineers x (1 + lift). That
# treats each human as the production unit and AI as a multiplier on their
# authoring rate. It is the correct form for an AI-ASSISTED team, and it is the
# form every published productivity study measures.
#
# It is arguably the WRONG form for an AI-FIRST team. If agents author and
# humans only specify and verify, the production unit is the agent, and human
# throughput is bounded by supervision capacity -- how much agent output one
# person can specify, review and accept -- not by how much they could have
# written themselves. Those are different activities with different rates.
#
# Under that form:  output = supervisors x V
# where V is the units of delivered output one human can supervise per period,
# expressed in the same units (an unassisted author produces 1.0).
#
# Note what the augmentation model implicitly assumes: at a +20% lift it puts
# V at 1.20, i.e. a person supervising agents handles only 20% more than a
# person writing code by hand. That is an assumption, not a measurement, and
# no published study measures V directly.


@dataclass(frozen=True, slots=True)
class VerificationBoundResult:
    """Supervision capacity required for the substituted configuration.

    Attributes:
        supervisors: Count of humans performing specification and verification.
        v_for_unit_cost_parity: Supervision capacity per human at which the
            substituted configuration matches the baseline's cost per unit.
        v_for_throughput_parity: Supervision capacity per human at which it
            matches the baseline's absolute output.
        implied_v_augmentation: The V the augmentation model implicitly
            assumes, for comparison.
    """

    supervisors: int
    v_for_unit_cost_parity: Decimal
    v_for_throughput_parity: Decimal
    implied_v_augmentation: Decimal


def verification_bound(
    baseline: TeamConfiguration,
    substituted: TeamConfiguration,
    ai_budget_annual: Decimal,
) -> VerificationBoundResult:
    """Solve for the supervision capacity the substituted config would need.

    Reframes the question from "what productivity lift is required?" to "how
    much agent output can one human supervise?" -- which is the quantity that
    actually governs an agent-primary team, and which no published study
    measures.

    Args:
        baseline: The reference configuration.
        substituted: The proposed configuration.
        ai_budget_annual: Assumed annual AI spend for the substituted config.

    Returns:
        A VerificationBoundResult carrying the required V at both thresholds.

    Raises:
        ValueError: If the AI budget is negative or there are no supervisors.
    """
    if ai_budget_annual < 0:
        raise ValueError("AI budget must be non-negative.")
    supervisors = substituted.engineering_headcount
    if supervisors == 0:
        raise ValueError("Substituted configuration has no supervisors.")

    total = substituted.payroll_annual + ai_budget_annual
    units_for_cost_parity = total / baseline.cost_per_unit

    q = Decimal("0.01")
    return VerificationBoundResult(
        supervisors=supervisors,
        v_for_unit_cost_parity=(units_for_cost_parity / supervisors).quantize(q),
        v_for_throughput_parity=(
            baseline.output_units / Decimal(supervisors)
        ).quantize(q),
        implied_v_augmentation=(
            substituted.output_units / Decimal(supervisors)
        ).quantize(q),
    )


def supervision_ratio_thresholds(
    baseline: TeamConfiguration,
    substituted: TeamConfiguration,
    ai_budget_annual: Decimal,
) -> dict[str, Decimal]:
    """Maximum agent-to-human supervision cost ratio at which B still clears.

    Anchors supervision capacity on what the baseline's lead *demonstrably*
    already supervises -- the output of the developers reporting to them --
    rather than on a productivity multiplier borrowed from studies of a
    different operating model.

    Let R be the cost of supervising one unit of agent-authored output
    relative to one unit of human-authored output. If each human in the
    substituted configuration supervises at the lead's demonstrated rate,
    capacity is (supervisors x demonstrated_rate) / R.

    Args:
        baseline: The reference configuration.
        substituted: The proposed configuration.
        ai_budget_annual: Assumed annual AI spend for the substituted config.

    Returns:
        Mapping of threshold name to the maximum R at which it is met.
    """
    lift = Decimal("1") + baseline.productivity_lift
    demonstrated = Decimal(baseline.developers) * lift
    capacity = Decimal(substituted.engineering_headcount) * demonstrated

    unit_cost_target = (
        substituted.payroll_annual + ai_budget_annual
    ) / baseline.cost_per_unit
    q = Decimal("0.01")
    return {
        "demonstrated_supervision_units": demonstrated.quantize(q),
        "R_max_throughput_parity": (capacity / baseline.output_units).quantize(q),
        "R_max_unit_cost_parity": (capacity / unit_cost_target).quantize(q),
    }


# =========================================================================
# PRIMARY MODEL: supervision-bound throughput
# =========================================================================
#
# The augmentation form above (output = engineers x (1 + lift)) is the correct
# form for Configuration A, which IS an AI-assisted team -- humans author, AI
# makes them faster. That is exactly what the published literature measures.
#
# It is the WRONG form for Configuration B. If agents author and humans only
# specify and verify, no human is a production unit. Output is bounded by how
# much agent work the humans can supervise. The binding constraint is
# supervision capacity, not authoring speed.
#
# Under the supervision-bound form:
#
#     output_B = supervisors x S / R
#
#   S = supervision capacity per human, in human-equivalent output units.
#       Anchored on what a lead demonstrably supervises in Configuration A.
#       S IS FIXED. It is a property of human attention -- 200-400 lines per
#       review, 300-500 lines/hour, detection collapsing after 60-90 minutes
#       (SmartBear/Cisco). Better tooling does not raise it.
#   R = cost of supervising one unit of AGENT-authored output relative to one
#       unit of HUMAN-authored output. R > 1 means agent output is more
#       expensive per unit to check.
#       R IS TIME-VARYING and should be expected to FALL as models improve:
#       fewer plausible-but-wrong constructions means less verification effort
#       per unit. But it decomposes as R(t) = R_structural + R_capability(t),
#       where only the second term declines. The structural floor -- no
#       accountability transfer, no trust accumulation, intent alignment as a
#       second axis of checking -- follows from the relationship rather than
#       from capability, and a better model does not acquire a stake in its
#       own output. R_structural is not identifiable from published data.
#
# The distinction matters for forecasting: S never improves, R probably does,
# and the thresholds below are fixed by arithmetic. That makes the staffing
# question a timing question -- but only if R_structural sits below the
# threshold being targeted.
#
# R is the parameter on which the entire comparison turns, and no published
# study measures it. Everything else in this module is arithmetic around it.


@dataclass(frozen=True, slots=True)
class SupervisionResult:
    """Outcome of the supervision-bound model for one value of R."""

    supervision_ratio: Decimal
    output_units: Decimal
    throughput_ratio: Decimal
    total_annual: Decimal
    cost_per_unit: Decimal
    cheaper_per_unit: bool


def supervision_capacity_anchor(baseline: TeamConfiguration) -> Decimal:
    """Supervision capacity per human, anchored on the baseline lead.

    In Configuration A the lead oversees the developers' combined output while
    also authoring. That figure is an observed property of an ordinary team,
    not an assumption, and is used as the per-supervisor capacity in the
    supervision-bound model.

    Applying it to every supervisor in the substituted configuration is
    deliberately generous -- a non-lead developer does not demonstrably
    supervise at a lead's rate -- so results computed from it are upper bounds
    on the substituted configuration.
    """
    return (
        Decimal(baseline.developers) * (Decimal("1") + baseline.productivity_lift)
    ).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)


def supervision_model(
    baseline: TeamConfiguration,
    substituted: TeamConfiguration,
    supervision_ratio: Decimal,
    ai_budget_annual: Decimal,
    capacity_per_supervisor: Decimal | None = None,
) -> SupervisionResult:
    """Evaluate the substituted configuration at a given supervision ratio.

    Args:
        baseline: Configuration A. Its augmentation-form output is retained,
            since it is an AI-assisted team and that form fits it.
        substituted: Configuration B, treated as supervisors rather than
            authors.
        supervision_ratio: R. Must be positive.
        ai_budget_annual: Annual AI spend for the substituted configuration.
        capacity_per_supervisor: S. Defaults to the baseline lead anchor.

    Returns:
        A SupervisionResult for that value of R.

    Raises:
        ValueError: If R is not positive or the AI budget is negative.
    """
    if supervision_ratio <= 0:
        raise ValueError("Supervision ratio R must be positive.")
    if ai_budget_annual < 0:
        raise ValueError("AI budget must be non-negative.")

    S = (
        capacity_per_supervisor
        if capacity_per_supervisor is not None
        else supervision_capacity_anchor(baseline)
    )
    units = (
        Decimal(substituted.engineering_headcount) * S / supervision_ratio
    ).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
    total = _money(substituted.payroll_annual + ai_budget_annual)
    cpu = _money(total / units)

    return SupervisionResult(
        supervision_ratio=supervision_ratio,
        output_units=units,
        throughput_ratio=(units / baseline.output_units).quantize(
            Decimal("0.0001"), rounding=ROUND_HALF_UP
        ),
        total_annual=total,
        cost_per_unit=cpu,
        cheaper_per_unit=cpu <= baseline.cost_per_unit,
    )


def solve_r_thresholds(
    baseline: TeamConfiguration,
    substituted: TeamConfiguration,
    ai_budget_annual: Decimal,
    capacity_per_supervisor: Decimal | None = None,
) -> dict[str, Decimal]:
    """Maximum R at which the substituted configuration clears each bar.

    Returns:
        Mapping with R_throughput_parity and R_unit_cost_parity. Above the
        latter the substitution fails on both throughput and unit cost.
    """
    S = (
        capacity_per_supervisor
        if capacity_per_supervisor is not None
        else supervision_capacity_anchor(baseline)
    )
    capacity = Decimal(substituted.engineering_headcount) * S
    unit_cost_target = (
        substituted.payroll_annual + ai_budget_annual
    ) / baseline.cost_per_unit
    q = Decimal("0.01")
    return {
        "capacity_human_equivalent": capacity.quantize(q),
        "R_throughput_parity": (capacity / baseline.output_units).quantize(q),
        "R_unit_cost_parity": (capacity / unit_cost_target).quantize(q),
    }


# Reference values of R. None is measured; the entry marked as the sole
# located datapoint uses a denominator (per suggestion) that does not match
# the one required here (per unit of delivered output).
R_SCENARIOS: Final[tuple[tuple[Decimal, str], ...]] = (
    (Decimal("1.0"), "agent output as cheap to check as human output"),
    (Decimal("1.5"), "throughput-parity threshold"),
    (Decimal("1.82"), "derived R, most favourable assumptions"),
    (Decimal("2.65"), "unit-cost-parity threshold"),
    (Decimal("2.80"), "implied by the augmentation form"),
    (Decimal("3.29"), "DERIVED CENTRAL ESTIMATE (see below)"),
    (Decimal("4.05"), "corroboration: Faros elapsed review time"),
    (Decimal("4.77"), "derived R, heavy agentic users"),
)

# Central estimate of R, derived in Section 5.4 from published review-effort
# data rather than assumed. Solves:
#
#   E_post / E_pre = [(1 - f) + f*R] * (volume_post / volume_pre)
#
# with E_pre 4-6.4 h/week (Bosu & Carver; Stack Overflow), E_post 11.4 h/week
# (Digital Applied, n=2847), f = 0.42 (Sonar, n=1100+), volume +16.2% (Faros).
R_DERIVED_CENTRAL: Final[Decimal] = Decimal("3.29")
R_DERIVED_RANGE: Final[tuple[Decimal, Decimal]] = (Decimal("1.82"), Decimal("4.77"))


def derive_r(
    review_hours_pre: Decimal,
    review_hours_post: Decimal,
    agent_authored_share: Decimal,
    output_uplift: Decimal,
) -> Decimal:
    """Derive R from observed inflation in review effort.

    Derivation. Let c_h and c_a be review effort per unit of human- and
    agent-authored output; R = c_a / c_h by definition. Before adoption all
    output is human-authored, so E_pre = V_pre * c_h. After adoption a share f
    is agent-authored, so E_post = V_post * [(1-f)*c_h + f*c_a], which factors
    to V_post * c_h * [(1-f) + f*R]. Dividing, c_h cancels:

        E_post / E_pre = (V_post / V_pre) * [(1 - f) + f*R]

    The cancellation is what makes this tractable: the absolute cost of
    reviewing human code is never needed, only the ratio. Rearranged, with I
    the observed inflation in effort per unit of output:

        I = (E_post / E_pre) / volume_uplift
        R = (I - 1 + f) / f

    Two assumptions bias the result in opposite directions. Review effort is
    assumed linear in volume, which overstates R (effort per line rises with
    change size, and agent PRs are larger). Review thoroughness is assumed
    unchanged, which understates R (31% more PRs now merge unreviewed, so
    observed effort is what teams spend, not what adequate review would cost).
    See Section 5.4 of the accompanying paper.

    Args:
        review_hours_pre: Weekly review hours before AI adoption.
        review_hours_post: Weekly review hours after adoption.
        agent_authored_share: f, the share of committed code AI authored.
        output_uplift: Ratio of post- to pre-adoption output (1.162 = +16.2%).

    Returns:
        R, the marginal review cost of agent output relative to human output.

    Raises:
        ValueError: If the agent-authored share is not in (0, 1], or any
            input is non-positive.
    """
    if not Decimal("0") < agent_authored_share <= Decimal("1"):
        raise ValueError("Agent-authored share must be in (0, 1].")
    if min(review_hours_pre, review_hours_post, output_uplift) <= 0:
        raise ValueError("Hours and uplift must be positive.")
    inflation = (review_hours_post / review_hours_pre) / output_uplift
    return (
        (inflation - (Decimal("1") - agent_authored_share)) / agent_authored_share
    ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# =========================================================================
# SUPERVISION CAPACITY FROM SPAN OF CONTROL
# =========================================================================
#
# The anchor is an observed organisational fact rather than a derived one: an
# engineering supervisor oversees roughly five developers. That span is
# visible on any org chart, and it already embeds everything about how a
# supervisor actually spends a week -- review, specification input, one-to-ones,
# coordination and incidents -- because those are what make 1:5 sustainable in
# practice.
#
#   SPAN = units of HUMAN-authored output one supervisor can oversee
#
# Supervising agent-authored output costs R times as much per unit, so:
#
#   capacity per supervisor = SPAN / R
#   supervisors needed      = target_units x R / SPAN
#
# With SPAN = 5 and a target of 5 units, this reduces to the identity
#
#   supervisors needed = R
#
# Two earlier anchors were tried and discarded. Anchoring on a lead's
# supervisory LOAD (3.36 units, alongside their own authoring) understated
# capacity, because it gave no credit for the authoring time an agent-primary
# supervisor no longer spends. Anchoring on a review-hours TIME BUDGET
# introduced a free parameter -- the share of a week spent reviewing -- that
# had to be argued rather than observed, and which span of control already
# accounts for. Both are recorded in Appendix B of the accompanying paper.

SPAN_OF_CONTROL: Final[Decimal] = Decimal("5")
"""Units of human-authored output one supervisor oversees.

ASSUMPTION, NOT A SOURCED FIGURE. Engineering spans of control are commonly
cited between 4 and 10; 5 is used as a mid-range working value. This is the
single most influential parameter in the model -- it moves the result further
than R does -- and it is the one with the weakest support. See SPAN_RANGE and
the sensitivity band in Section 5 of the accompanying paper.
"""

SPAN_RANGE: Final[tuple[Decimal, Decimal]] = (Decimal("4"), Decimal("7"))
"""Plausible working range for engineering span of control."""

SUPERVISOR_LOADED_ANNUAL: Final[Decimal] = Decimal("240000")
"""Fully-loaded cost of a supervising engineer.

Priced above a developer (200k) because the role is senior: specifying,
reading, verifying and accepting agent output rather than authoring. Pricing
it at developer rates would assume a role change with no compensation change.
Range 200k-275k; see the sensitivity band.
"""

MAINTAINABILITY_FTE: Final[Decimal] = Decimal("0")
"""Dedicated human capacity for refactoring. Zero by design.

Earlier versions carried 0.5 FTE here on the grounds that agents do not
refactor -- refactoring line-moves are down 70% and duplication up 81%. That
was double-counting. The evidence shows agents do not refactor BY DEFAULT,
not that they cannot: directed to consolidate duplication, an agent produces
that work like any other, and it is already inside the target output and
already supervised at cost R.

What genuinely remains human is the JUDGEMENT of what to refactor, which sits
with the supervisors and is not a separate role. Refactoring is therefore
treated as agent work that must be explicitly commissioned and verified --
see the maintainability control in Section 6 of the accompanying paper.

Retained as a parameter so a reader who disagrees can price a dedicated role.
"""


def supervisor_capacity(
    supervision_ratio: Decimal,
    span: Decimal = SPAN_OF_CONTROL,
) -> Decimal:
    """Units of agent-authored output one supervisor can oversee.

    Args:
        supervision_ratio: R, the agent-to-human supervision cost ratio.
        span: Units of human-authored output one supervisor oversees.

    Returns:
        Units of agent-authored output supervisable per supervisor.

    Raises:
        ValueError: If either argument is not positive.
    """
    if supervision_ratio <= 0 or span <= 0:
        raise ValueError("R and span must be positive.")
    return (span / supervision_ratio).quantize(
        Decimal("0.001"), rounding=ROUND_HALF_UP
    )


def people_required(
    target_units: Decimal,
    supervision_ratio: Decimal,
    span: Decimal = SPAN_OF_CONTROL,
) -> Decimal:
    """Supervisors needed to deliver a target output in agent-primary mode."""
    return (
        target_units / supervisor_capacity(supervision_ratio, span)
    ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def max_r_for_headcount(
    target_units: Decimal,
    headcount: Decimal,
    span: Decimal = SPAN_OF_CONTROL,
) -> Decimal:
    """Highest R at which a given headcount still delivers the target output."""
    if headcount <= 0:
        raise ValueError("headcount must be positive.")
    return ((headcount * span) / target_units).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )



# =========================================================================
# AI COST FROM TOKEN CONSUMPTION
# =========================================================================
#
# AI cost is built bottom-up from token consumption rather than asserted from
# a budget. The chain is:
#
#   tokens per unit = merged tasks per unit x tokens per task / yield
#   cost per unit   = tokens per unit x blended price per Mtok
#
# where `yield` is the share of agent runs that produce merged output --
# unresolved attempts consume roughly four times the resources of successful
# ones, so failures are a material share of the bill.
#
# Published inputs:
#   tokens per agentic task   1.0M - 3.5M (SWE-bench class, including
#                             retries and self-correction loops)
#   input:output ratio        2:1 to 3:1; input dominates, and 80%+ of input
#                             is typically cache reads
#   per-task variance         up to 30x on repeated runs of the same task
#   blended price             $1 - $3 per Mtok once caching is accounted for
#
# The result reconciles against observed operator spend, which is the check
# a budget-derived figure cannot pass: the mid case lands on Anthropic's
# published enterprise average, and the high case lands inside Uber's
# reported power-user band. Agent-primary work is power-user work, so the
# high case is used for the agent-primary configuration.

MERGED_TASKS_PER_UNIT: Final[Decimal] = Decimal("150")
"""Merged tasks in one engineer-year of output. Order of magnitude."""

TOKEN_CASES: Final[dict[str, tuple[Decimal, Decimal, Decimal]]] = {
    # name: (Mtokens per task, yield, blended $ per Mtoken)
    "low": (Decimal("1.0"), Decimal("0.60"), Decimal("1.00")),
    "mid": (Decimal("2.0"), Decimal("0.40"), Decimal("2.00")),
    "high": (Decimal("3.5"), Decimal("0.25"), Decimal("3.00")),
}
"""Token-consumption cases. 'high' applies to agent-primary operation."""


@dataclass(frozen=True, slots=True)
class TokenCost:
    """Token consumption and cost for one unit of delivered work."""

    case: str
    mtokens_per_unit: Decimal
    cost_per_unit: Decimal


def token_cost(case: str = "high") -> TokenCost:
    """Cost and token consumption per unit of delivered work.

    Args:
        case: Key into TOKEN_CASES.

    Returns:
        A TokenCost for that case.

    Raises:
        KeyError: If the case name is not recognised.
    """
    if case not in TOKEN_CASES:
        raise KeyError(f"Unknown case {case!r}. Available: {sorted(TOKEN_CASES)}")
    tok, yld, price = TOKEN_CASES[case]
    mtok = (MERGED_TASKS_PER_UNIT * tok / yld).quantize(Decimal("1"))
    return TokenCost(
        case=case,
        mtokens_per_unit=mtok,
        cost_per_unit=(mtok * price).quantize(Decimal("1")),
    )


def tokens_per_supervisor(
    target_units: Decimal,
    supervision_ratio: Decimal,
    case: str = "high",
    span: Decimal = SPAN_OF_CONTROL,
) -> Decimal:
    """Agent token volume one supervisor must oversee, in millions per year.

    This is the saturation signal: it rises as R falls, because fewer
    supervisors carry the same agent output. It is directly measurable from
    a gateway or CLI wrapper, unlike R itself.
    """
    n = people_required(target_units, supervision_ratio, span)
    return (token_cost(case).mtokens_per_unit * target_units / n).quantize(
        Decimal("1")
    )


def constant_output_comparison(
    supervision_ratio: Decimal,
    target_units: Decimal = Decimal("5"),
    case: str = "high",
) -> dict[str, Decimal]:
    """Cost of delivering a fixed output in agent-primary mode.

    Headcount flexes so that output is held constant, which is the only
    basis on which the two configurations are comparable.
    """
    n = people_required(target_units, supervision_ratio)
    people = LEAD_LOADED_ANNUAL + (n - Decimal("1")) * DEVELOPER_LOADED_ANNUAL
    ai = token_cost(case).cost_per_unit * target_units
    total = people + ai
    return {
        "supervisors": n,
        "people_cost": _money(people),
        "ai_cost": _money(ai),
        "total_cost": _money(total),
        "ai_share": (ai / total).quantize(Decimal("0.001")),
        "mtokens_per_supervisor": tokens_per_supervisor(
            target_units, supervision_ratio, case
        ),
    }


@dataclass(frozen=True, slots=True)
class EngineeringTeam:
    """A costed agent-primary engineering team delivering a target output."""

    supervisors: Decimal
    total_fte: Decimal
    people_cost: Decimal
    ai_cost: Decimal
    total_cost: Decimal


def engineering_team(
    supervision_ratio: Decimal,
    target_units: Decimal = Decimal("5"),
    span: Decimal = SPAN_OF_CONTROL,
    maintainability_fte: Decimal = MAINTAINABILITY_FTE,
    supervisor_rate: Decimal = SUPERVISOR_LOADED_ANNUAL,
    case: str = "high",
) -> EngineeringTeam:
    """Cost an agent-primary engineering team at a given supervision ratio.

    One of the supervisors is the tech lead, priced at the lead rate; the
    remainder are supervising engineers at the supervisor rate.

    Raises:
        ValueError: If any argument is non-positive where positivity is
            required.
    """
    if supervision_ratio <= 0 or span <= 0 or target_units <= 0:
        raise ValueError("R, span and target must be positive.")
    if maintainability_fte < 0 or supervisor_rate < 0:
        raise ValueError("Maintainability FTE and rate must be non-negative.")

    sup = (target_units * supervision_ratio / span).quantize(Decimal("0.01"))
    fte = (Decimal("1") + (sup - Decimal("1")) + maintainability_fte).quantize(
        Decimal("0.01")
    )
    people = _money(
        LEAD_LOADED_ANNUAL
        + (sup - Decimal("1")) * supervisor_rate
        + maintainability_fte * supervisor_rate
    )
    ai = _money(token_cost(case).cost_per_unit * target_units)
    return EngineeringTeam(sup, fte, people, ai, _money(people + ai))


# --- Default parameters from Section 5.2 of the paper -----------------------
# Sources: BLS median software developer wage (May 2024 release) with a
# 1.5-1.8x fully-loaded multiplier per Cadence (2026); AI spend per Anthropic
# enterprise deployment data; productivity lifts per arXiv:2607.01418.

LEAD_LOADED_ANNUAL: Final[Decimal] = Decimal("250000")
DEVELOPER_LOADED_ANNUAL: Final[Decimal] = Decimal("200000")
PM_LOADED_ANNUAL: Final[Decimal] = Decimal("225000")
BASELINE_AI_MONTHLY: Final[Decimal] = Decimal("250")
BASELINE_PM_FTE: Final[Decimal] = Decimal("1.0")
SUBSTITUTED_PM_FTE: Final[Decimal] = Decimal("0.5")

# Productivity-lift scenarios. The published estimates disagree by a wide
# margin and the disagreement is not noise -- it tracks sample composition,
# tool generation, and unit of analysis. See Section 3.2 of the paper.
#
#   realistic    BASE CASE. Anchored on the convergent band across three
#                independent datasets: DX (+7.76% median, +13.1% mean across
#                400+ orgs), Faros (+16.2% PRs merged/developer across 22,000
#                developers), and Stanford (net +15-20% after rework, ~100k
#                engineers). Configuration A at +12%, Configuration B at +20%
#                representing the upper end of that band at maximum intensity.
#   optimistic   UPPER BOUND, not a base case. Microsoft telemetry study,
#                within-person design, agentic CLI tools, early 2026: +24%
#                pooled [CI +14.5%, +33.7%], +50% at maximum dose.
#                arXiv:2607.01418. This is the outlier among large studies and
#                its authors disclose that their employer sells AI tools and
#                owns the vendor of the better-performing tool.
#   conservative DX median for the baseline; Faros PRs merged per developer
#                for the substituted configuration.
#   adverse      METR RCT, early-2025 tools, experienced OSS developers:
#                -19%. Retained as a floor case. METR withdrew its 2026
#                follow-up as unreliable and believes uplift is now positive
#                but cannot size it; this row is a stress test, not a forecast.
#
# NOTE ON DIRECTION OF BIAS: the output unit is merged pull requests, which
# the same literature shows is inflated under AI adoption (PR size +51%, 31%
# merging unreviewed, rework consuming roughly half the gross gain). Because
# that inflation scales with AI intensity and Configuration B is the
# higher-intensity arm, every throughput ratio below is an UPPER BOUND on
# Configuration B, not an estimate of it. See Section 5.4 of the paper.

SCENARIOS: Final[dict[str, tuple[Decimal, Decimal]]] = {
    "realistic": (Decimal("0.12"), Decimal("0.20")),
    "optimistic": (Decimal("0.24"), Decimal("0.50")),
    "conservative": (Decimal("0.0776"), Decimal("0.162")),
    "adverse": (Decimal("-0.19"), Decimal("-0.19")),
}

# 95% credible interval on the Microsoft pooled estimate, used to express
# uncertainty on the optimistic break-even rather than reporting it to the
# dollar as though it were precise.
MICROSOFT_CI: Final[tuple[Decimal, Decimal]] = (Decimal("0.145"), Decimal("0.337"))

SENSITIVITY_LIFTS: Final[tuple[Decimal, ...]] = (
    Decimal("-0.19"),  # METR RCT, early-2025 tools
    Decimal("0.0776"),  # DX longitudinal median
    Decimal("0.10"),  # Stanford: high-complexity brownfield (0-10%)
    Decimal("0.15"),  # Stanford: net average after rework, lower bound
    Decimal("0.162"),  # Faros: PRs merged per developer
    Decimal("0.20"),  # Stanford: net average after rework, upper bound
    Decimal("0.24"),  # Microsoft: pooled synthetic-control estimate
    Decimal("0.35"),  # Stanford: low-complexity greenfield, lower bound
    Decimal("0.50"),  # Microsoft: maximum observed dose
    Decimal("1.24"),  # parity requirement (realistic base case)
)


def breakeven_range(
    substituted_lift: Decimal,
    baseline_lift_low: Decimal,
    baseline_lift_high: Decimal,
) -> tuple[Decimal, Decimal]:
    """Break-even AI budget across a credible interval on the baseline lift.

    Reporting a single break-even figure to the dollar implies a precision the
    underlying evidence does not carry. This propagates an interval on the
    baseline productivity lift through to the break-even budget.

    Args:
        substituted_lift: Configuration B lift, held fixed.
        baseline_lift_low: Lower bound of the Configuration A lift interval.
        baseline_lift_high: Upper bound of the Configuration A lift interval.

    Returns:
        A (low, high) pair of break-even budgets. Note the ordering inverts:
        a HIGHER baseline lift means Configuration A is more efficient, which
        LOWERS the break-even budget available to Configuration B.
    """
    results: list[Decimal] = []
    for baseline_lift in (baseline_lift_low, baseline_lift_high):
        baseline = TeamConfiguration(
            label="range probe A",
            leads=1,
            developers=3,
            product_managers=BASELINE_PM_FTE,
            lead_loaded_annual=LEAD_LOADED_ANNUAL,
            developer_loaded_annual=DEVELOPER_LOADED_ANNUAL,
            pm_loaded_annual=PM_LOADED_ANNUAL,
            ai_spend_per_person_monthly=BASELINE_AI_MONTHLY,
            productivity_lift=baseline_lift,
        )
        substituted = TeamConfiguration(
            label="range probe B",
            leads=1,
            developers=1,
            product_managers=SUBSTITUTED_PM_FTE,
            lead_loaded_annual=LEAD_LOADED_ANNUAL,
            developer_loaded_annual=DEVELOPER_LOADED_ANNUAL,
            pm_loaded_annual=PM_LOADED_ANNUAL,
            ai_spend_per_person_monthly=Decimal("0"),
            productivity_lift=substituted_lift,
        )
        results.append(analyse(baseline, substituted).breakeven_ai_budget_annual)
    return (min(results), max(results))


def pre_ai_baseline() -> TeamConfiguration:
    """Configuration 0: the same team before any AI tooling.

    The true reference point. Without it there is no way to see what AI
    adoption itself buys, as distinct from what the AI-first restructuring
    buys. Same five people, no AI spend, no productivity lift -- one
    unassisted engineer produces 1.0 units by definition, so the team
    produces 4.0.
    """
    return TeamConfiguration(
        label="0: pre-AI (lead + 3 developers + 1 PM, no tooling)",
        leads=1,
        developers=3,
        product_managers=BASELINE_PM_FTE,
        lead_loaded_annual=LEAD_LOADED_ANNUAL,
        developer_loaded_annual=DEVELOPER_LOADED_ANNUAL,
        pm_loaded_annual=PM_LOADED_ANNUAL,
        ai_spend_per_person_monthly=Decimal("0"),
        productivity_lift=Decimal("0"),
    )


def _default_configurations(
    scenario: str = "realistic",
) -> tuple[TeamConfiguration, TeamConfiguration]:
    """Build the paper's two configurations for a named lift scenario.

    Args:
        scenario: Key into SCENARIOS. See that mapping for provenance.

    Returns:
        A (baseline, substituted) pair.

    Raises:
        KeyError: If the scenario name is not recognised.
    """
    if scenario not in SCENARIOS:
        raise KeyError(
            f"Unknown scenario {scenario!r}. Available: {sorted(SCENARIOS)}"
        )
    baseline_lift, substituted_lift = SCENARIOS[scenario]

    baseline = TeamConfiguration(
        label=f"A: lead + 3 developers + 1 PM [{scenario}]",
        leads=1,
        developers=3,
        product_managers=BASELINE_PM_FTE,
        lead_loaded_annual=LEAD_LOADED_ANNUAL,
        developer_loaded_annual=DEVELOPER_LOADED_ANNUAL,
        pm_loaded_annual=PM_LOADED_ANNUAL,
        ai_spend_per_person_monthly=BASELINE_AI_MONTHLY,
        productivity_lift=baseline_lift,
    )
    substituted = TeamConfiguration(
        label=f"B: lead + 1 developer + 0.5 PM [{scenario}]",
        leads=1,
        developers=1,
        product_managers=SUBSTITUTED_PM_FTE,
        lead_loaded_annual=LEAD_LOADED_ANNUAL,
        developer_loaded_annual=DEVELOPER_LOADED_ANNUAL,
        pm_loaded_annual=PM_LOADED_ANNUAL,
        ai_spend_per_person_monthly=Decimal("0"),
        productivity_lift=substituted_lift,
    )
    return baseline, substituted


def main() -> None:
    """Print the supervision-bound analysis, with the augmentation form after."""
    base, subst = _default_configurations("realistic")
    ai = Decimal("55000")
    S = supervision_capacity_anchor(base)
    old = LEAD_LOADED_ANNUAL + 5 * DEVELOPER_LOADED_ANNUAL
    print("\n" + "=" * 70)
    print("CONSTANT-OUTPUT COMPARISON (all configurations deliver 5 units)")
    print("=" * 70)
    tc = token_cost("high")
    print("  AI priced bottom-up: %s Mtok/unit at $%s/unit (high case)"
          % (tc.mtokens_per_unit, tc.cost_per_unit))
    print()
    print("  %6s %5s %12s %10s %12s %6s %8s %10s"
          % ("R", "sup", "people", "AI", "total", "AI%", "vs old", "Mtok/sup"))
    print("  %6s %5s %12s %10s %12s %6s %8s %10s"
          % ("OLD", "6 FTE", "$%s" % format(old, ",.0f"), "$0",
             "$%s" % format(old, ",.0f"), "0.0%", "--", "--"))
    for Rv, _n in R_SCENARIOS:
        c = constant_output_comparison(Rv)
        print("  %6s %5s %12s %10s %12s %5.1f%% %7.1f%% %9sM"
              % (Rv, c["supervisors"],
                 "$%s" % format(c["people_cost"], ",.0f"),
                 "$%s" % format(c["ai_cost"], ",.0f"),
                 "$%s" % format(c["total_cost"], ",.0f"),
                 c["ai_share"] * 100,
                 (c["total_cost"] / old - 1) * 100,
                 format(c["mtokens_per_supervisor"], ",.0f")))
    print()
    print("  AI cost is CONSTANT across R: same output, same tokens.")
    print("  All variation is people. R is purely a headcount driver.")

    thr = solve_r_thresholds(base, subst, ai)

    pre = pre_ai_baseline()
    print("=" * 66)
    print("PEOPLE REQUIRED: SPAN-OF-CONTROL MODEL")
    print("=" * 66)
    print("  Old team: 1 supervisor + 5 developers = 6.0 FTE, 5.00 units")
    print("  A supervisor oversees %s developers, so capacity = %s / R"
          % (SPAN_OF_CONTROL, SPAN_OF_CONTROL))
    print("  With span 5 and target 5, supervisors needed = R exactly.")
    print()
    print("  %6s %13s %10s %14s" % ("R", "supervisors", "output", "% of old"))
    for Rv, _note in R_SCENARIOS:
        n = people_required(Decimal("5"), Rv)
        out2 = (Decimal("2") * supervisor_capacity(Rv)).quantize(Decimal("0.01"))
        print("  %6s %13s %10s %13s%%"
              % (Rv, n, out2, (out2 / Decimal("5") * 100).quantize(Decimal("0.1"))))
    print()
    print("  'output' is what 2 people (1 supervisor + 1 developer) deliver.")
    print("  They match the old team's 5.00 units at R <= %s"
          % max_r_for_headcount(Decimal("5"), Decimal("2")))

    print()
    print("=" * 66)
    print("THREE CONFIGURATIONS")
    print("=" * 66)
    print(f"  {'':22} {'FTE':>4} {'total $':>12} {'units':>7} {'$/unit':>10}")
    print(f"  {'0  pre-AI':22} {pre.total_fte:>4} ${pre.total_annual:>11,.0f}"
          f" {pre.output_units:>7} ${pre.cost_per_unit:>9,.0f}")
    print(f"  {'A  AI-assisted':22} {base.total_fte:>4} ${base.total_annual:>11,.0f}"
          f" {base.output_units:>7} ${base.cost_per_unit:>9,.0f}")
    rr = supervision_model(base, subst, R_DERIVED_CENTRAL, ai)
    print(f"  {'B  AI-first (R=3.29)':22} {subst.total_fte:>4} ${rr.total_annual:>11,.0f}"
          f" {rr.output_units:>7} ${rr.cost_per_unit:>9,.0f}")
    print(f"\n  At the derived R, Configuration B costs {(rr.cost_per_unit/pre.cost_per_unit-1)*100:+.1f}% per unit")
    print("  against the PRE-AI team -- worse than using no AI at all.")

    print(f"\n{'=' * 66}")
    print("PRIMARY MODEL: supervision-bound throughput")
    print("=" * 66)
    print(f"  Configuration A output ......... {base.output_units} units")
    print(f"  A cost per unit ................ ${base.cost_per_unit:,.0f}")
    print(f"  Lead demonstrably supervises ... {S} units (Config A)")
    print(f"  B supervisors .................. {subst.engineering_headcount}")
    print(f"  B human-equivalent capacity .... {thr['capacity_human_equivalent']} units / R")
    print(f"  B payroll + AI (@ ${ai:,.0f}) ...... ${subst.payroll_annual + ai:,.0f}")
    print()
    print(f"  R for throughput parity ........ <= {thr['R_throughput_parity']}")
    print(f"  R for unit-cost parity ......... <= {thr['R_unit_cost_parity']}")
    print()
    print(f"  {'R':>6} {'units':>8} {'% of A':>8} {'$/unit':>11}  {'vs A':>6}  basis")
    for Rv, note in R_SCENARIOS:
        res = supervision_model(base, subst, Rv, ai)
        flag = "cheaper" if res.cheaper_per_unit else "dearer"
        print(
            f"  {Rv:>6} {res.output_units:>8} {res.throughput_ratio:>7.1%} "
            f"${res.cost_per_unit:>10,.0f}  {flag:>6}  {note}"
        )
    print()
    print("  R = cost to supervise one unit of agent output relative to one")
    print("  unit of human output. Not directly measured, but derivable:")
    print(f"    derive_r(5.0, 11.4, 0.42, 1.162) = {derive_r(Decimal('5.0'), Decimal('11.4'), Decimal('0.42'), Decimal('1.162'))}")
    print(f"    derived range {R_DERIVED_RANGE[0]} to {R_DERIVED_RANGE[1]}, central {R_DERIVED_CENTRAL}")
    print("  All figures are upper bounds: they credit every supervisor with")
    print("  the lead's demonstrated rate, which a non-lead has not shown.")

    print(f"\n{'=' * 66}")
    print("SECONDARY: augmentation form (retained for comparison)")
    print("=" * 66)
    print("  Treats each human as a producer with AI as a multiplier. Correct")
    print("  for Configuration A; borrowed from studies of a different")
    print("  operating model when applied to Configuration B.")
    for scenario in ("realistic", "optimistic", "conservative", "adverse"):
        b2, s2 = _default_configurations(scenario)
        r2 = analyse(b2, s2)
        budget = r2.breakeven_ai_budget_annual
        bs = f"${budget:,.0f}" if budget > 0 else "none"
        print(
            f"  {scenario:<13} A {b2.output_units:>6} u | B {s2.output_units:>6} u"
            f" | {r2.throughput_ratio:>6.1%} | break-even {bs}"
        )
    implied = thr['capacity_human_equivalent'] / s2.output_units
    b3, s3 = _default_configurations("realistic")
    implied = thr['capacity_human_equivalent'] / s3.output_units
    print(f"\n  The realistic augmentation result is equivalent to assuming")
    print(f"  R = {implied:.2f} -- an assumption never stated in that form.")


if __name__ == "__main__":
    main()
