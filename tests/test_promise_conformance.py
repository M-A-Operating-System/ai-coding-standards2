"""One conformance test per promise in PRODUCT.md's "The promises" (issue #408).

`docs/product/orchestrator/PRODUCT.md` states eleven promises -- AS-1..AS-3
(architectural separation) and MI-1..MI-8 (mode invariants) -- and each ends
with a `**Test.**` paragraph saying exactly what a regression test for it must
check. This module is the one-file map from "which test proves promise X" to
the assertion that proves it: every promise below quotes its own `Test.`
paragraph, and either asserts it here or names the existing module that
already does and re-runs its load-bearing assertion.

Where a promise's `Test.` paragraph resists a clean automated check, the class
docstring says so explicitly and what the check does instead. Three are
partial by construction and are labelled `PARTIAL` in their docstring:

  - AS-2 -- "requires no change to pipeline_orchestrator.py" is a statement
    about a diff that does not exist. Tested behaviourally by mutating the
    pipeline definition and asserting the unmodified orchestrator follows it,
    plus a structural guard that no step name is reachable from the
    orchestrator's executable code.
  - MI-5 -- a real both-modes issue timeline needs GitHub. Tested by driving
    the same step through `process_work_item` in both modes against a
    recording client and diffing the ordered effects.
  - MI-8 -- mapping a code branch to a prose table row cannot be derived
    mechanically. Tested by pinning every mode-conditional branch site to the
    row of "What is allowed to differ" it maps to, so a new branch fails
    until someone maps it.

MI-6 is met except for one clause, called out in its own docstring: the
orchestrator records the declared expected effect but does not yet compare
observed commits against `expected_effect.commits` (see
`_build_closing_announcement`'s own note). That half is asserted as far as it
is built, and the gap is named rather than papered over.
"""
import ast
import inspect
import json
import re
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / "pipeline"))

import pipeline_orchestrator as po  # noqa: E402

PIPELINE_PATH = REPO_ROOT / "pipeline" / "pipeline.json"
LIVE_SCHEMA_PATH = REPO_ROOT / "pipeline" / "schemas" / "pipeline.schema.json"
DESIGN_SCHEMA_PATH = REPO_ROOT / "docs" / "product" / "orchestrator" / "schema" / "pipeline.schema.json"
STATUSES_PATH = REPO_ROOT / "pipeline" / "statuses.json"
PRODUCT_MD = REPO_ROOT / "docs" / "product" / "orchestrator" / "PRODUCT.md"
ORCHESTRATOR_PATH = REPO_ROOT / "pipeline" / "pipeline_orchestrator.py"
COMMANDS_DIR = REPO_ROOT / ".claude" / "commands"

ORCHESTRATOR_SOURCE = ORCHESTRATOR_PATH.read_text()
ORCHESTRATOR_TREE = ast.parse(ORCHESTRATOR_SOURCE)


def _raw_pipeline() -> dict:
    return json.loads(PIPELINE_PATH.read_text())


def _raw_steps(raw: dict) -> dict:
    """{step name: its raw pipeline.json entry}, across every flow."""
    return {
        step["agent"]: step
        for flow in raw["flows"].values()
        for step in flow["steps"]
    }


def _statuses() -> dict:
    return json.loads(STATUSES_PATH.read_text())


@pytest.fixture(scope="module")
def loaded():
    """(agents, default_extra_tools) from the shipped pipeline.

    load_pipeline mutates the budget globals; restored after the module so no
    other test inherits this module's values.
    """
    before = {
        name: getattr(po, name)
        for name in ("DEFAULT_MAX_TURNS", "AGENT_TIMEOUT_SECONDS", "MAX_LAUNCHES_PER_TICK")
    }
    yield po.load_pipeline(PIPELINE_PATH)
    for name, value in before.items():
        setattr(po, name, value)


def _work_item(number=408, kind="issue", labels=()):
    return po.WorkItem(
        number=number, kind=kind, title="A work item",
        labels=set(labels), url=f"https://github.com/test/repo/issues/{number}",
    )


def _documentation_only_string_nodes(tree: ast.AST) -> set[int]:
    """id() of every string Constant that is documentation, not behaviour.

    Docstrings, and the argparse text a person reads (`help=`, `description=`,
    `epilog=`, `metavar=`). A name mentioned in one of these does not make the
    orchestrator behave differently for that name; a name anywhere else might.
    """
    doc_nodes: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                doc_nodes.add(id(body[0].value))
        if isinstance(node, ast.Call):
            for kw in node.keywords:
                if kw.arg in {"help", "description", "epilog", "metavar"} \
                        and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                    doc_nodes.add(id(kw.value))
    return doc_nodes


def _write_result(scratch_dir, payload):
    """Write a step's result file and read it back the way a real run does."""
    (Path(scratch_dir) / po._RESULT_FILENAME).write_text(json.dumps(payload))
    return po._read_step_result(str(scratch_dir))


def _maos_commands() -> list[Path]:
    """Every `/maos-*` command file -- AS-3's own scope."""
    return sorted(COMMANDS_DIR.glob("maos-*.md"))


def _behavioural_string_constants(tree: ast.AST) -> list[str]:
    """Every string literal in the orchestrator that is not documentation."""
    doc_nodes = _documentation_only_string_nodes(tree)
    return [
        node.value for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
        and id(node) not in doc_nodes
    ]


# ===========================================================================
# AS-1 -- One file tells you what the pipeline does
# ===========================================================================

class TestAS1OneFileTellsYouWhatThePipelineDoes:
    """PRODUCT.md, AS-1:

    "The resolved command set for every step is derivable from `pipeline.json`
    alone; the same for triggers, dependencies, and expected effect. Flows and
    budgets are tested the same way: a work item entering a flow whose trigger
    it does not match, or a step running under an allowance the file does not
    declare, is a failure -- the same class as a label the orchestrator applies
    on a step's request that its `allowed_labels` does not cover. Both the
    shipped `pipeline.json` and a repository's own validate against
    `schema/pipeline.schema.json`; a definition the schema rejects is a file
    that does not parse, not a test failure to discover later."

    And AS-1's "Precisely": "No name is computed in code: a branch or
    pull-request name built inside the orchestrator is a definition living
    outside the file that should hold it."
    """

    def test_the_resolved_command_set_comes_from_pipeline_json_alone(self, loaded):
        """Every agent step's --allowedTools is exactly the file's two grants.

        `defaults.extra_allowedTools` plus the step's own
        `extra_allowedTools`, deduped in that order -- nothing from the agent
        file's frontmatter, no constant in the orchestrator.
        """
        agents, default_extra_tools = loaded
        raw_steps = _raw_steps(_raw_pipeline())
        raw_defaults = _raw_pipeline()["defaults"]["extra_allowedTools"]
        item = _work_item()
        checked = 0
        for agent_def in agents:
            if agent_def.step_type != "agent":
                continue
            resolved = po._resolve_agent_invocation(
                agent_def, item, "test/repo",
                agent_text_override="# stand-in agent body",
                default_extra_tools=default_extra_tools,
            )
            expected = list(dict.fromkeys(
                list(raw_defaults) + list(raw_steps[agent_def.agent].get("extra_allowedTools", []))
            ))
            assert resolved.allowed_tools == expected, (
                f"{agent_def.agent}'s resolved command set is not derivable from "
                f"pipeline.json alone"
            )
            checked += 1
        assert checked >= 10, "the shipped pipeline should have many agent steps to check"

    def test_triggers_dependencies_and_expected_effect_come_from_the_file(self, loaded):
        agents, _ = loaded
        raw_steps = _raw_steps(_raw_pipeline())
        for agent_def in agents:
            raw = raw_steps[agent_def.agent]
            assert agent_def.trigger == raw["trigger"]
            assert agent_def.dependencies == raw.get("dependencies", [])
            assert agent_def.expected_effect == dict(raw.get("expected_effect") or {})

    def test_every_step_declares_its_expected_effect(self, loaded):
        """"what each is supposed to change" is not optional: a step that
        declares nothing has no expected effect to disagree with (MI-6)."""
        agents, _ = loaded
        for agent_def in agents:
            assert agent_def.expected_effect != {}, (
                f"{agent_def.agent} declares no expected_effect"
            )

    def test_budgets_come_from_the_file_not_from_a_constant(self, loaded):
        raw = _raw_pipeline()
        assert po.DEFAULT_MAX_TURNS == int(raw["budgets"]["max_turns"])
        assert po.AGENT_TIMEOUT_SECONDS == int(raw["budgets"]["max_wall_seconds"])
        assert po.MAX_LAUNCHES_PER_TICK == int(raw["budgets"]["max_launches_per_tick"])

    def test_an_item_entering_a_flow_whose_trigger_it_does_not_match_is_refused(self, loaded):
        """"a work item entering a flow whose trigger it does not match ... is
        a failure". Both trigger dimensions: the flow's `labels` and its
        `type`."""
        agents, _ = loaded
        pipeline_map = po.pipeline_by_name(agents)

        # The `labels` dimension of a flow's trigger.
        by_flow_labels = [a for a in agents if a.flow_labels]
        assert by_flow_labels, "no flow restricts entry by label -- nothing to check"
        step = by_flow_labels[0]
        assert po._should_run(
            step, _work_item(labels=set()), set(), pipeline_map, None,
        ) is False, f"{step.agent} ran on an item carrying none of flow {step.flow!r}'s labels"

        # The `kind` dimension. Every shipped flow triggers on kind: issue, so
        # a pull request matches none of them and reaches no step.
        raw_kinds = {
            flow["trigger"].get("kind") for flow in _raw_pipeline()["flows"].values()
        }
        assert raw_kinds == {"issue"}, (
            f"the shipped flows now trigger on {raw_kinds}; this check assumed issues only"
        )
        pr = _work_item(kind="pr")
        for agent_def in agents:
            assert po._should_run(
                agent_def, pr, set(pr.labels), pipeline_map, None,
            ) is False, (
                f"{agent_def.agent} ran on a pull request, which enters no declared flow"
            )

    def test_a_step_cannot_run_under_an_allowance_the_file_does_not_declare(self, loaded):
        """A label request outside the step's `allowed_labels` is dropped.

        AS-1's own example of the failure class: "a label the orchestrator
        applies on a step's request that its `allowed_labels` does not cover".
        """
        agents, _ = loaded
        granted = [a for a in agents if (a.allowed_labels.get("add") or [])]
        assert granted, "no step declares allowed_labels.add -- nothing to check"
        step = granted[0]
        allowed = step.allowed_labels["add"][0]
        cleared = po._filter_allowed_label_requests(
            step, [{"issue": None, "add": [allowed, "definitely-not-declared"], "remove": []}],
        )
        assert (None, "add", allowed) in cleared
        assert not any(lbl == "definitely-not-declared" for _, _, lbl in cleared)

        ungranted = [a for a in agents if not a.allowed_labels]
        assert ungranted, "every step declares allowed_labels -- nothing to check"
        assert po._filter_allowed_label_requests(
            ungranted[0], [{"issue": None, "add": ["anything"], "remove": ["anything"]}],
        ) == [], "a step with no declared allowed_labels may request nothing"

    def test_both_the_shipped_and_a_repositorys_own_pipeline_validate_against_the_schema(self):
        """"Both the shipped `pipeline.json` and a repository's own validate
        against `schema/pipeline.schema.json`."

        Under AS-1's whole-file replacement, a repository's own file is a
        complete definition validating against the identical schema -- so
        "a repository's own" here is the shipped file's structural twin, not a
        fragment.

        The shipped file is checked against the live schema. It is NOT checked
        against the design schema: the live one is promoted from it with one
        deliberate, documented deviation (step-level `exclude_labels` and
        `exclude_classifications`, which the target dropped in favour of
        positive-only selection and today's pipeline still relies on). A
        definition using neither, like the repository's own below, must
        satisfy both -- which is what pins the two schemas together.
        """
        jsonschema = pytest.importorskip("jsonschema")
        shipped = _raw_pipeline()
        schema = json.loads(LIVE_SCHEMA_PATH.read_text())
        errors = list(jsonschema.Draft7Validator(schema).iter_errors(shipped))
        assert not errors, (
            "the shipped pipeline.json does not validate against its own schema: "
            + "; ".join(f"{'/'.join(str(p) for p in e.absolute_path)}: {e.message}" for e in errors[:5])
        )

        # A repository's own definition: one flow of its own, complete.
        repo_own = {
            "budgets": {"max_turns": 12, "max_wall_seconds": 600},
            "flows": {
                "house-delivery": {
                    "description": "this repository's own delivery flow",
                    "trigger": {"kind": "issue"},
                    "naming": {"branch": "work/{number}"},
                    "steps": [{
                        "agent": "03_execute/coder",
                        "phase": "03_execute",
                        "trigger": {"event": "issue.opened"},
                        "dependencies": [],
                        "human_gate_after": False,
                        "description": "our coder",
                        "expected_effect": {"commits": True},
                        "git_ops": {"commit_after": True},
                    }],
                },
            },
        }
        for schema_path in (LIVE_SCHEMA_PATH, DESIGN_SCHEMA_PATH):
            schema = json.loads(schema_path.read_text())
            errors = list(jsonschema.Draft7Validator(schema).iter_errors(repo_own))
            assert not errors, (
                f"a repository's own complete definition is rejected by {schema_path.name}: "
                + "; ".join(f"{'/'.join(str(p) for p in e.absolute_path)}: {e.message}" for e in errors[:5])
            )

    def test_a_repositorys_own_file_replaces_the_shipped_one_in_full(self, tmp_path, monkeypatch):
        """"presence means the repository's file decides everything, absence
        means the shipped default decides everything."

        The whole-file model, end to end. `tests/test_flows.py`'s
        TestLoadPipelineReplacement covers every branch of it; this pins the
        promise itself -- nothing from the shipped file survives a
        replacement, not even a flow the repository's file never mentions.
        """
        for name in ("DEFAULT_MAX_TURNS", "AGENT_TIMEOUT_SECONDS", "MAX_LAUNCHES_PER_TICK"):
            monkeypatch.setattr(po, name, getattr(po, name))
        consuming = tmp_path / "consuming"
        submodule = consuming / "vendor" / "ai-coding-standards2"
        (submodule / "pipeline").mkdir(parents=True)
        shipped = submodule / "pipeline" / "pipeline.json"
        shipped.write_text(PIPELINE_PATH.read_text())
        own = consuming / "pipeline" / "pipeline.json"
        own.parent.mkdir(parents=True)
        own.write_text(json.dumps({
            "budgets": {"max_turns": 3, "max_wall_seconds": 60},
            "flows": {
                "house-delivery": {
                    "description": "ours",
                    "trigger": {"kind": "issue"},
                    "steps": [{
                        "agent": "00_ondemand/blocker",
                        "phase": "00_ondemand",
                        "type": "script",
                        "script": ".github/scripts/blocker.sh",
                        "trigger": {"label": "blocker:requested"},
                        "dependencies": [],
                        "human_gate_after": False,
                        "description": "ours",
                        "expected_effect": {"commits": False},
                    }],
                },
            },
        }))
        monkeypatch.setattr(po, "SUBMODULE_ROOT", submodule)
        monkeypatch.setenv("AI_AGILE_ROOT", str(consuming))

        agents, default_extra_tools = po.load_pipeline(shipped)
        assert [a.agent for a in agents] == ["00_ondemand/blocker"]
        assert {a.flow for a in agents} == {"house-delivery"}
        assert default_extra_tools == [], "the shipped defaults leaked into a replacement"
        assert po.DEFAULT_MAX_TURNS == 3, "the shipped budgets leaked into a replacement"

    def test_no_branch_or_pull_request_name_is_computed_in_code(self, loaded):
        """"No name is computed in code: a branch or pull-request name built
        inside the orchestrator is a definition living outside the file."

        Two halves. First: no branch-shaped literal survives in the
        orchestrator's executable code -- the `f"issue-{n}"` and
        `f"feature/{n}-..."` constructions #406 removed must not come back.
        Second: every branch the orchestrator resolves for a real step comes
        back token-for-token from that step's flow `naming`.
        """
        branch_shaped = re.compile(
            r"^(issue|feature|fix|docs|design|build|chore)[-/]\{", re.IGNORECASE,
        )
        offenders = [
            s for s in _behavioural_string_constants(ORCHESTRATOR_TREE)
            if branch_shaped.match(s)
        ]
        assert not offenders, (
            f"pipeline_orchestrator.py builds a branch name itself: {offenders} -- "
            "the pattern belongs in pipeline.json's flow naming"
        )

        agents, _ = loaded
        raw = _raw_pipeline()
        item = _work_item(number=42)
        checked = 0
        for agent_def in agents:
            branch = po.step_branch(agent_def, item)
            if branch is None:
                continue
            flow_naming = raw["flows"][agent_def.flow].get("naming") or {}
            declared = [flow_naming.get("branch")] + [
                pr["branch"] for pr in flow_naming.get("pull_requests", [])
            ]
            assert any(
                d and po.resolve_naming_pattern(d, item) == branch for d in declared
            ), (
                f"{agent_def.agent}'s branch {branch!r} matches no pattern its flow "
                f"{agent_def.flow!r} declares"
            )
            checked += 1
        assert checked, "no step resolves a branch -- nothing to check"


# ===========================================================================
# AS-2 -- The orchestrator only coordinates
# ===========================================================================

class TestAS2TheOrchestratorOnlyCoordinates:
    """PRODUCT.md, AS-2:

    "Adding a step, removing a step, reordering steps, or changing what a step
    may do requires no change to `pipeline_orchestrator.py`."

    PARTIAL, by construction. "Requires no change to X" is a claim about a
    diff that does not exist, so it cannot be asserted directly. Tested two
    ways instead, both real:

      - behaviourally: each of the four changes AS-2 names is made to a
        pipeline definition, and the UNMODIFIED orchestrator is asked to load
        it. If any of them needed an orchestrator change, the orchestrator
        would not follow it here.
      - structurally: no step name declared in pipeline.json is reachable from
        the orchestrator's executable code (docstrings and argparse help text
        excepted). A step the orchestrator names is a step whose removal or
        rename WOULD require changing it.

    Not covered: that no future value-add work drifts into the orchestrator.
    #407 moved the two that had (the repo-root sweep and the metrics append
    are now scripts); the third assertion below pins that they stayed out.
    """

    def _load(self, tmp_path, monkeypatch, raw):
        for name in ("DEFAULT_MAX_TURNS", "AGENT_TIMEOUT_SECONDS", "MAX_LAUNCHES_PER_TICK"):
            monkeypatch.setattr(po, name, getattr(po, name))
        monkeypatch.delenv("AI_AGILE_ROOT", raising=False)
        path = tmp_path / "pipeline.json"
        path.write_text(json.dumps(raw))
        return po.load_pipeline(path)

    def test_adding_a_step_needs_no_orchestrator_change(self, tmp_path, monkeypatch):
        raw = _raw_pipeline()
        flow_name = next(iter(raw["flows"]))
        raw["flows"][flow_name]["steps"].append({
            "agent": f"{raw['flows'][flow_name]['steps'][0]['phase']}/a-brand-new-step",
            "phase": raw["flows"][flow_name]["steps"][0]["phase"],
            "type": "script",
            "script": ".github/scripts/blocker.sh",
            "trigger": {"label": "brand-new:requested"},
            "dependencies": [],
            "human_gate_after": False,
            "description": "a step the orchestrator has never heard of",
            "expected_effect": {"commits": False},
        })
        agents, _ = self._load(tmp_path, monkeypatch, raw)
        added = po.pipeline_by_name(agents)
        assert any(a.endswith("/a-brand-new-step") for a in added)

    def test_removing_a_step_needs_no_orchestrator_change(self, tmp_path, monkeypatch):
        raw = _raw_pipeline()
        flow_name = next(
            name for name, flow in raw["flows"].items() if len(flow["steps"]) > 1
        )
        removed = raw["flows"][flow_name]["steps"].pop(0)["agent"]
        agents, _ = self._load(tmp_path, monkeypatch, raw)
        assert removed not in po.pipeline_by_name(agents)

    def test_reordering_steps_needs_no_orchestrator_change(self, tmp_path, monkeypatch):
        raw = _raw_pipeline()
        flow_name = next(
            name for name, flow in raw["flows"].items() if len(flow["steps"]) > 1
        )
        raw["flows"][flow_name]["steps"].reverse()
        agents, _ = self._load(tmp_path, monkeypatch, raw)
        in_flow = [a.agent for a in agents if a.flow == flow_name]
        assert in_flow == [s["agent"] for s in raw["flows"][flow_name]["steps"]]

    def test_changing_what_a_step_may_do_needs_no_orchestrator_change(self, tmp_path, monkeypatch):
        raw = _raw_pipeline()
        step = next(
            s for f in raw["flows"].values() for s in f["steps"]
            if s.get("type", "agent") == "agent"
        )
        step["extra_allowedTools"] = ["Bash(echo:*)"]
        step["allowed_labels"] = {"add": ["house:*"], "remove": []}
        agents, default_extra_tools = self._load(tmp_path, monkeypatch, raw)
        changed = po.pipeline_by_name(agents)[step["agent"]]
        assert changed.extra_allowedTools == ["Bash(echo:*)"]
        assert changed.allowed_labels == {"add": ["house:*"], "remove": []}
        resolved = po._resolve_agent_invocation(
            changed, _work_item(), "test/repo",
            agent_text_override="# stand-in", default_extra_tools=default_extra_tools,
        )
        assert resolved.allowed_tools[-1] == "Bash(echo:*)"
        assert po._filter_allowed_label_requests(
            changed, [{"issue": None, "add": ["house:reviewed"], "remove": []}],
        ) == [(None, "add", "house:reviewed")]

    def test_the_orchestrator_names_no_step_of_its_own(self):
        """A step the orchestrator's code names is a step it is coupled to."""
        names = set(_raw_steps(_raw_pipeline()))
        shorts = {n.split("/")[-1] for n in names}
        offenders = []
        for value in _behavioural_string_constants(ORCHESTRATOR_TREE):
            if value in names or value in shorts:
                offenders.append(value)
        assert not offenders, (
            f"pipeline_orchestrator.py names pipeline steps in its own code: "
            f"{sorted(set(offenders))} -- removing or renaming one would require "
            "changing the orchestrator"
        )

    def test_the_value_add_work_407_extracted_stayed_out(self):
        """The repo-root sweep and the metrics append are scripts, not code.

        Both were inline orchestrator work until #407. The orchestrator may
        name and run a script; it may not carry the work itself.
        """
        for script in (
            ".github/scripts/sweep-repo-root.sh",
            ".github/scripts/sweep-repo-root-snapshot.sh",
            ".github/scripts/append-metrics-record.sh",
        ):
            assert (REPO_ROOT / script).is_file(), f"{script} is missing"
        # The sweep is declared in pipeline.json, not wired in code.
        lifecycle = _raw_pipeline()["defaults"]["agent_lifecycle"]
        declared = set(lifecycle.get("before", [])) | set(lifecycle.get("after", []))
        assert ".github/scripts/sweep-repo-root-snapshot.sh" in declared
        assert ".github/scripts/sweep-repo-root.sh" in declared


# ===========================================================================
# AS-3 -- A command names something; it does not do something
# ===========================================================================

class TestAS3ACommandNamesSomething:
    """PRODUCT.md, AS-3:

    "Every command file resolves to a generated wrapper or a single named
    target. A command containing a numbered procedure, a conditional, or a
    retry loop is a test failure."

    `tests/test_command_thinness.py` IS this promise's conformance test: it
    checks the generated/hand-authored split, that each hand-authored command
    names one existing script and no other, and that none contains a numbered
    procedure. Rather than duplicate it, this class re-runs its load-bearing
    assertion and extends it to the coverage it did not have: the check ran
    over the four commands #407 touched, so the sweep below covers EVERY file
    in `.claude/commands/`, generated ones included, for the conditional and
    retry-loop half of the paragraph.
    """

    def test_the_existing_module_covers_the_generated_hand_authored_split(self):
        """Re-run test_command_thinness's own assertion, by name."""
        import test_command_thinness as thinness

        thinness.TestOnlyTheKnownFourAreHandAuthored().test_the_set_has_not_grown()
        for name, script in sorted(thinness.HAND_AUTHORED.items()):
            case = thinness.TestEachHandAuthoredCommandNamesASingleScript()
            case.test_the_script_it_names_exists(name, script)
            case.test_the_command_names_that_script(name, script)
            case.test_it_invokes_no_other_pipeline_script(name, script)
            case.test_it_contains_no_numbered_procedure(name, script)

    def test_every_command_file_resolves_to_a_wrapper_or_a_single_named_target(self):
        """"Every command file resolves to a generated wrapper or a single
        named target" -- every `/maos-*` file, not only the hand-authored four.
        """
        import test_command_thinness as thinness

        files = _maos_commands()
        assert len(files) > len(thinness.HAND_AUTHORED), "no generated commands found"
        for path in files:
            text = path.read_text()
            if thinness.GENERATED_MARKER in text:
                continue  # a generated wrapper resolves by construction
            assert path.name in thinness.HAND_AUTHORED, (
                f"{path.name} is neither generated nor a known hand-authored wrapper"
            )

    @pytest.mark.parametrize("path", _maos_commands(), ids=lambda p: p.name)
    def test_no_command_contains_a_conditional_or_a_retry_loop(self, path):
        """The two halves of the paragraph test_command_thinness did not cover.

        Shell control flow inside a command's own runnable block is a program;
        AS-3 says a command names one. Prose outside a code fence may say
        "if the run fails, ..." -- that is guidance for the reader, not logic
        the command executes -- so only fenced blocks are read.

        One shape is admitted, and only in the exact form below: the one-line
        `[ test ] || VAR=path` guard that locates a file in the standalone or
        the submodule layout. That resolves WHERE the single named target is;
        it does not decide WHAT to run, and both branches name the same
        target. Anything else -- a keyword conditional, a loop, a second
        `||`-chained command -- is a procedure.
        """
        blocks = re.findall(r"```(?:bash|sh)?\n(.*?)```", path.read_text(), re.DOTALL)
        body = "\n".join(blocks)

        keywords = re.findall(
            r"(?m)^\s*(if|elif|else|fi|case|esac|while|until|for|done)\b", body,
        )
        assert not keywords, (
            f"{path.name} contains shell control flow ({sorted(set(keywords))}) in a "
            "runnable block -- a conditional or a retry loop belongs in the script "
            "the command names"
        )

        location_guard = re.compile(r'^\s*\[\s+-[a-z]\s+"?\$?\{?[A-Za-z_]+[^]]*\]\s*(\|\||&&)\s*\S')
        for line in body.splitlines():
            if "||" not in line and "&&" not in line:
                continue
            assert location_guard.match(line), (
                f"{path.name} chains commands conditionally: {line.strip()!r} -- "
                "only the one-line file-location guard is admitted"
            )


# ===========================================================================
# MI-1 -- An issue means the same thing to everyone
# ===========================================================================

class TestMI1AnIssueMeansTheSameThingToEveryone:
    """PRODUCT.md, MI-1:

    "Every label in `statuses.json` has exactly one documented meaning, and no
    step's behaviour branches on who applied it."
    """

    def test_every_status_has_exactly_one_documented_meaning(self):
        statuses = _statuses()["statuses"]
        assert statuses, "statuses.json declares no statuses"
        for status in statuses:
            meaning = status.get("meaning", "")
            assert isinstance(meaning, str) and meaning.strip(), (
                f"status {status['status']!r} documents no meaning"
            )

    def test_no_two_statuses_share_a_meaning_and_none_has_two(self):
        """"exactly one": one `meaning` field per status, and no status's
        meaning is another's -- a label that means what another label means is
        a label with two readings on the issue."""
        statuses = _statuses()["statuses"]
        names = [s["status"] for s in statuses]
        assert len(names) == len(set(names)), f"a status is declared twice: {names}"
        suffixes = [s["label_suffix"] for s in statuses]
        assert len(suffixes) == len(set(suffixes)), f"a label suffix is declared twice: {suffixes}"
        meanings = [s["meaning"].strip() for s in statuses]
        assert len(meanings) == len(set(meanings)), "two statuses document the same meaning"

    def test_no_status_is_specific_to_one_mode(self):
        """MI-1's "Precisely": no label is specific to one mode."""
        for status in _statuses()["statuses"]:
            text = " ".join(
                str(v) for k, v in status.items()
                if k in {"meaning", "orchestrator_behaviour", "human_instruction"}
            ).lower()
            for word in ("headless only", "interactive only", "only in headless", "only in interactive"):
                assert word not in text, (
                    f"status {status['status']!r} scopes itself to one mode: {word!r}"
                )

    def test_no_step_behaviour_branches_on_who_applied_a_label(self):
        """The orchestrator's label reads take a label set, never an author.

        `agent_status`, `trigger_label_present` and `_should_run` are where a
        step's eligibility is decided; none of them is given an actor to
        branch on, so no step's behaviour can depend on one.
        """
        for func in (po.agent_status, po.trigger_label_present, po._should_run):
            params = set(inspect.signature(func).parameters)
            assert not (params & {"actor", "author", "applied_by", "login", "set_by"}), (
                f"{func.__name__} is handed an actor to branch on"
            )

    def test_the_one_actor_check_is_the_gate_check_and_nothing_else(self):
        """MI-7 needs to know who applied a gate label; nothing else may.

        `_gate_label_human_applied` is the sole reader of a label event's
        actor. Any second function reading `actor` off a labelled event would
        be a step interpreting a label by its origin.
        """
        readers = []
        for node in ast.walk(ORCHESTRATOR_TREE):
            if not isinstance(node, ast.FunctionDef):
                continue
            source = ast.get_source_segment(ORCHESTRATOR_SOURCE, node) or ""
            body_only = source.replace(ast.get_docstring(node) or "", "")
            if re.search(r'\bactor\b.*\[["\']type["\']\]|\.get\(["\']actor["\']\)|\[["\']actor["\']\]', body_only):
                readers.append(node.name)
        assert readers == ["_gate_label_human_applied"], (
            f"label-event actors are read by {readers}; only the gate check may"
        )


# ===========================================================================
# MI-2 -- The same situation always produces the same next step
# ===========================================================================

class TestMI2TheSameSituationProducesTheSameNextStep:
    """PRODUCT.md, MI-2:

    "Run the resolver and the real dispatch path over the same issue state and
    assert identical selection, for every step."

    And MI-2's "Precisely": "Routing is computed in exactly one place."

    The resolver and the real dispatch path are the same function -- that is
    the promise. So the test has two halves: that there is exactly one routing
    implementation and one call site for it (no second path to disagree with),
    and that running it over identical state selects identically, for every
    step in the shipped pipeline.
    """

    def _states(self, agents):
        """A spread of issue states, including each step's own trigger label."""
        states = [set(), {"type:enhancement"}, {"size:M", "type:bug"}]
        for agent_def in agents:
            trigger = agent_def.trigger or {}
            label = trigger.get("label")
            if isinstance(label, str):
                states.append({label} | set(agent_def.flow_labels))
        return states

    def test_routing_is_computed_in_exactly_one_place(self):
        """One implementation, one call site."""
        definitions = [
            node.name for node in ast.walk(ORCHESTRATOR_TREE)
            if isinstance(node, ast.FunctionDef) and node.name == "_should_run"
        ]
        assert definitions == ["_should_run"], (
            f"routing is defined {len(definitions)} times: {definitions}"
        )
        call_sites = [
            node for node in ast.walk(ORCHESTRATOR_TREE)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id == "_should_run"
        ]
        assert len(call_sites) == 1, (
            f"routing is invoked from {len(call_sites)} places -- a second dispatch "
            "path is a second answer waiting to disagree"
        )

    def test_the_resolve_only_path_never_decides_eligibility_itself(self):
        """`/maos-{agent}-i` resolves an invocation; it does not route.

        A driver "may read the pipeline definition to explain what will
        happen, never to decide it" -- so the resolve-only entry point must
        not call the router, and must not carry one of its own.
        """
        node = next(
            n for n in ast.walk(ORCHESTRATOR_TREE)
            if isinstance(n, ast.FunctionDef) and n.name == "_run_print_prompt"
        )
        called = {
            c.func.id for c in ast.walk(node)
            if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
        }
        assert "_should_run" not in called
        assert not any(
            name.startswith("_should") or name.endswith("_eligible") for name in called
        ), f"_run_print_prompt decides eligibility itself: {sorted(called)}"

    def test_identical_state_selects_identically_for_every_step(self, loaded):
        """Run the router twice over identical state; the answer must not move."""
        agents, _ = loaded
        pipeline_map = po.pipeline_by_name(agents)
        checked = 0
        for labels in self._states(agents):
            for kind in ("issue", "pr"):
                first, second = [], []
                for target in (first, second):
                    for agent_def in agents:
                        item = _work_item(kind=kind, labels=labels)
                        target.append(po._should_run(
                            agent_def, item, set(labels), pipeline_map, None,
                        ))
                assert first == second, (
                    f"routing gave two answers for the same state {sorted(labels)} ({kind})"
                )
                checked += 1
        assert checked >= 10

    def test_the_selection_is_a_pure_function_of_the_state_it_is_given(self, loaded):
        """Order of evaluation does not change any step's own answer.

        If a step's answer depended on which steps were evaluated before it,
        two people reading the same issue could reach different next steps.
        """
        agents, _ = loaded
        pipeline_map = po.pipeline_by_name(agents)
        labels = {"type:enhancement", "size:M"}
        forward = {
            a.agent: po._should_run(a, _work_item(labels=labels), set(labels), pipeline_map, None)
            for a in agents
        }
        backward = {
            a.agent: po._should_run(a, _work_item(labels=labels), set(labels), pipeline_map, None)
            for a in reversed(agents)
        }
        assert forward == backward


# ===========================================================================
# MI-3 -- An agent can only ever do what you allowed
# ===========================================================================

class TestMI3AnAgentCanOnlyDoWhatYouAllowed:
    """PRODUCT.md, MI-3:

    "Exactly one component decides whether an action is permitted, and both
    modes route through it. A second implementation is a test failure."

    #402 retired the interactive PreToolUse-hook re-implementation, so this is
    now checkable directly: there is one allowlist resolver
    (`_resolve_agent_invocation`), it is what the real spawn passes to
    `--allowedTools`, and the resolve-only path a person works through prints
    that same list rather than computing its own.
    `tests/test_resolve_only_allowlist_parity.py` proves the byte-identity of
    the two lists; its assertion is re-run here rather than restated.
    """

    def test_the_two_paths_resolve_a_byte_identical_allowlist(self, capsys):
        """Re-run test_resolve_only_allowlist_parity's own assertion, by name."""
        import test_resolve_only_allowlist_parity as parity

        parity.test_resolve_only_matches_a_real_spawn_exactly(capsys)
        parity.test_the_comparison_is_against_a_substantial_allowlist()

    def test_exactly_one_component_resolves_the_allowlist(self):
        """One resolver; every caller goes through it.

        `ResolvedInvocation.allowed_tools` is constructed in exactly one
        place. A second construction site is the second implementation MI-3
        calls a test failure.
        """
        constructors = [
            node for node in ast.walk(ORCHESTRATOR_TREE)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id == "ResolvedInvocation"
        ]
        assert len(constructors) == 1, (
            f"the invocation allowlist is built in {len(constructors)} places"
        )
        enclosing = [
            n.name for n in ast.walk(ORCHESTRATOR_TREE)
            if isinstance(n, ast.FunctionDef)
            and any(c is constructors[0] for c in ast.walk(n))
        ]
        assert "_resolve_agent_invocation" in enclosing

    def test_no_second_enforcement_mechanism_exists(self):
        """The retired interactive re-implementation must not come back.

        Enforcement is the platform's own `--allowedTools`. A PreToolUse hook,
        or any hand-rolled permission check, is the "equivalent mechanism"
        MI-3 refuses.
        """
        assert "PreToolUse" not in ORCHESTRATOR_SOURCE, (
            "a PreToolUse hook is a second enforcement mechanism (retired in #402)"
        )
        for path in sorted(REPO_ROOT.glob(".claude/*.json")) + sorted(REPO_ROOT.glob(".github/**/*.yml")):
            assert "PreToolUse" not in path.read_text(), f"{path} re-introduces a PreToolUse hook"

    def test_the_label_allowance_check_is_also_a_single_component(self):
        """"and whatever checks a step's requested label changes against its
        `allowed_labels`" -- the same single-component rule."""
        deciders = [
            node.name for node in ast.walk(ORCHESTRATOR_TREE)
            if isinstance(node, ast.FunctionDef)
            and "allowed_labels" in (ast.get_source_segment(ORCHESTRATOR_SOURCE, node) or "")
            and isinstance(node.name, str)
            and node.name.startswith("_filter")
        ]
        assert deciders == ["_filter_allowed_label_requests"]
        callers = [
            node.name for node in ast.walk(ORCHESTRATOR_TREE)
            if isinstance(node, ast.FunctionDef)
            and node.name != "_filter_allowed_label_requests"
            and "_filter_allowed_label_requests" in (
                ast.get_source_segment(ORCHESTRATOR_SOURCE, node) or ""
            )
        ]
        assert callers == ["_apply_label_requests"], (
            f"the allowed_labels check is consulted from {callers}; one applier only"
        )


# ===========================================================================
# MI-4 -- Nothing gets stuck with no way out
# ===========================================================================

class TestMI4NothingGetsStuckWithNoWayOut:
    """PRODUCT.md, MI-4:

    "Every status in `statuses.json` where `blocks_pipeline` is true names a
    `cleared_by`, that exit is reachable from the step's own configuration,
    and it is performable in both modes."

    `tests/test_stale_wip_reclaim.py` covers the hardest exit -- a `:wip` a
    lost machine stranded, which no person and no step can clear, so a later
    tick reclaims it. That module is referenced rather than duplicated; what
    is added here is the `statuses.json` cross-check the promise asks for, so
    a NEW blocking status with no exit fails immediately.
    """

    def _blocking(self):
        return [s for s in _statuses()["statuses"] if s["blocks_pipeline"]]

    def test_there_are_blocking_statuses_to_check(self):
        assert len(self._blocking()) >= 4

    def test_every_blocking_status_names_a_cleared_by(self):
        for status in self._blocking():
            cleared_by = (status.get("cleared_by") or "").strip()
            assert cleared_by, f"{status['status']!r} blocks the pipeline and names no exit"
            assert cleared_by != "never", (
                f"{status['status']!r} blocks the pipeline and can never be cleared"
            )

    def test_every_exit_names_an_actor_that_exists_in_both_modes(self):
        """"performable in both modes": a human or the orchestrator.

        Both are present however the tick started -- a person can apply and
        remove labels either way, and the orchestrator runs in both. An exit
        naming anything else (an agent, a workflow, one mode's driver) would
        be reachable in one mode and not the other.
        """
        for status in self._blocking():
            cleared_by = status["cleared_by"].lower()
            assert "human" in cleared_by or "orchestrator" in cleared_by, (
                f"{status['status']!r} is cleared by {status['cleared_by']!r}, which is "
                "neither a person nor the orchestrator, so it is not performable in both modes"
            )

    def test_a_human_cleared_exit_is_reachable_from_the_steps_own_configuration(self, loaded):
        """The exit is a label a person removes, and the label is the step's.

        Every blocking status is `{step}:{suffix}` on the item -- so the exit
        for a given step is derivable from that step's own name plus this
        file, with nothing else to look up.
        """
        agents, _ = loaded
        suffixes = {s["status"]: s["label_suffix"] for s in self._blocking()}
        for agent_def in agents:
            for status, suffix in suffixes.items():
                assert agent_def.status_label(status) == f"{agent_def.label_key}:{suffix}"

    def test_the_recovery_guidance_is_posted_by_the_orchestrator_not_the_step(self):
        """"So the orchestrator, not the step, posts the recovery guidance."

        A step that halts badly-worded must still leave a usable exit, so the
        closing announcement is built by the orchestrator for every blocking
        outcome, independent of the step's own report.
        """
        source = ast.get_source_segment(
            ORCHESTRATOR_SOURCE,
            next(
                n for n in ast.walk(ORCHESTRATOR_TREE)
                if isinstance(n, ast.FunctionDef) and n.name == "_announce_and_prompt"
            ),
        )
        assert "_build_closing_announcement" in source
        assert "gh.post_comment" in source

    def test_the_stranded_wip_exit_is_covered_and_still_holds(self):
        """The exit for `:wip`, re-run through test_stale_wip_reclaim's own
        harness rather than duplicated.

        `:wip` is the one blocking status whose `cleared_by` is the
        orchestrator rather than a person -- a lost machine cannot clear
        anything and no person can, so a later tick must. That module's
        `TestAStrandedWip` covers the behaviour in full; its fixtures are
        reused here to assert the exit exists at all, which is the clause
        MI-4 adds ("that exit is reachable").
        """
        from datetime import timedelta

        import test_stale_wip_reclaim as reclaim

        assert hasattr(reclaim, "TestAStrandedWip"), (
            "test_stale_wip_reclaim no longer covers a stranded :wip"
        )
        agent_def = reclaim._agent(max_wall_seconds=600, max_retries=1)
        item = reclaim._item(agent_def)
        stranded_since = reclaim.NOW - timedelta(days=1)
        gh = reclaim._gh([reclaim._claim_comment(agent_def, stranded_since)])

        labels = reclaim._reclaim(gh, agent_def, item)
        assert agent_def.status_label(po.STATUS_WIP) not in labels, (
            "a :wip stranded far beyond its budget was not reclaimed -- there is no "
            "exit from the one blocking status a person cannot clear"
        )
        assert agent_def.status_label(po.STATUS_FAILED) in labels, (
            "the reclaim left no recorded outcome for a person to act on"
        )

    def test_the_reclaim_is_not_gated_on_the_mode(self):
        """An exit performable in one mode only is exactly what MI-4 refuses."""
        node = next(
            n for n in ast.walk(ORCHESTRATOR_TREE)
            if isinstance(n, ast.FunctionDef) and n.name == "_reclaim_stale_wip"
        )
        source = ast.get_source_segment(ORCHESTRATOR_SOURCE, node) or ""
        assert "_HEADLESS" not in source and "interactive_result" not in source, (
            "the stale-:wip reclaim branches on the mode"
        )


# ===========================================================================
# MI-5 -- The result does not depend on who was watching
# ===========================================================================

class TestMI5TheResultDoesNotDependOnWhoWasWatching:
    """PRODUCT.md, MI-5:

    "Run the same step in both modes against equivalent state and diff the
    resulting issue timeline, ignoring timestamps and actor."

    PARTIAL. A real issue timeline needs GitHub, so the timeline is captured
    instead against a recording client: the same step is driven through
    `process_work_item` twice -- once with the tick started headless
    (`_HEADLESS = True`), once interactively -- and the ordered sequence of
    label transitions, comments, agent invocation and post-actions is diffed.
    Timestamps and the actor field are excluded, exactly as the paragraph
    says.

    What this does not cover: the effects a real agent subprocess has on the
    repository. The subprocess is stubbed identically in both runs, which is
    the point -- MI-5 is about the orchestration around the step, since the
    step itself is the same binary invoked the same way in both modes. The
    step's pre-actions run inside that stubbed call, so they do not reach the
    recorded timeline; the last test in this class covers them from the other
    side, by pinning them to the single declaration in `pipeline.json` that
    both modes read.
    """

    def _drive(self, headless, tmp_path, monkeypatch):
        for name in ("DEFAULT_MAX_TURNS", "AGENT_TIMEOUT_SECONDS", "MAX_LAUNCHES_PER_TICK"):
            monkeypatch.setattr(po, name, getattr(po, name))
        agents, default_extra_tools = po.load_pipeline(PIPELINE_PATH)
        pipeline_map = po.pipeline_by_name(agents)
        # A script step: no subprocess spawn to stub, and its pre/post
        # ceremony is the orchestrator's, which is what MI-5 is about.
        agent_def = next(
            a for a in agents
            if a.step_type == "agent" and not a.commit_after and not a.human_gate_after
        )
        item = _work_item(number=4080, labels=set(agent_def.flow_labels))

        timeline: list = []

        gh = MagicMock()
        gh.repo = "test/repo"
        gh.add_label.side_effect = lambda n, lbl: timeline.append(("add_label", n, lbl))
        gh.remove_label.side_effect = lambda n, lbl: timeline.append(("remove_label", n, lbl))
        gh.transition_label.side_effect = lambda n, a, f, t: timeline.append(("transition", n, a, f, t))
        gh.post_comment.side_effect = lambda n, body: timeline.append(
            ("comment", n, re.sub(r'"(ended_at|started_at|ts)":\s*"[^"]*"', "", body))
        )
        gh.get_issue_labels.return_value = set(item.labels)
        gh.create_issue.return_value = 999
        gh.list_comment_bodies.return_value = []
        gh._get.return_value = []

        step_result = po.StepResult(
            outcome="complete", summary="did the thing", undone="",
            message="", output="", expected_effect=dict(agent_def.expected_effect),
        )
        run_result = po.AgentRunResult(success=True, returncode=0, captured_tail="")

        def _fake_invoke(*args, **kwargs):
            timeline.append(("invoke", agent_def.agent))
            return run_result

        def _fake_lifecycle(scripts, *args, **kwargs):
            for script in scripts:
                timeline.append(("lifecycle", script))

        def _fake_post_steps(*args, **kwargs):
            timeline.append(("post_steps", agent_def.agent))
            return True, ""

        monkeypatch.setattr(po, "_HEADLESS", headless)
        monkeypatch.setattr(po, "invoke_agent", _fake_invoke)
        monkeypatch.setattr(po, "_run_lifecycle_scripts", _fake_lifecycle)
        monkeypatch.setattr(po, "_invoke_post_steps", _fake_post_steps)
        monkeypatch.setattr(po, "_read_step_result", lambda *a, **k: (step_result, ""))
        monkeypatch.setattr(po, "_check_controls", lambda repo: "run")
        monkeypatch.setattr(po, "promote_gated_agents", lambda labels, *a, **k: labels)
        monkeypatch.setattr(po, "_reclaim_stale_wip", lambda gh, agents, wi, labels, *a: labels)
        monkeypatch.setattr(po, "_clear_satisfied_blocks", lambda gh, wi, labels: labels)
        monkeypatch.setattr(po, "_is_blocked_from_starting", lambda gh, labels: False)
        monkeypatch.setattr(po, "_post_cycle_metrics", lambda *a, **k: None)
        monkeypatch.setattr(po, "_should_run", lambda a, *args, **kw: a is agent_def)

        po.process_work_item(
            item, agents, pipeline_map, gh, dry_run=False, repo="test/repo",
            session_id="sess", default_extra_tools=default_extra_tools,
            concurrency=None,
        )
        return timeline

    def test_the_same_step_produces_the_same_ordered_effects_in_both_modes(
        self, tmp_path, monkeypatch
    ):
        """"in the same order" -- so the diff is of the sequence, not the set."""
        headless = self._drive(True, tmp_path, monkeypatch)
        interactive = self._drive(False, tmp_path, monkeypatch)
        assert headless, "the harness recorded no effects at all"
        assert headless == interactive, (
            "the same step left a different trail depending on how the tick started"
        )

    def test_the_step_actually_ran_in_the_harness(self, tmp_path, monkeypatch):
        """Guard the guard: two empty timelines would compare equal."""
        timeline = self._drive(True, tmp_path, monkeypatch)
        kinds = {entry[0] for entry in timeline}
        assert "invoke" in kinds, "the step was never invoked"
        assert "comment" in kinds, "no announcement was posted"
        assert kinds & {"add_label", "remove_label", "transition"}, "no label moved"

    def test_the_pre_and_post_actions_are_the_steps_own_declaration(self, loaded):
        """"A step's pre-actions, activity and post-actions" come from the
        file, so they cannot vary by mode: there is one declaration."""
        agents, _ = loaded
        raw = _raw_pipeline()
        lifecycle = raw["defaults"]["agent_lifecycle"]
        raw_steps = _raw_steps(raw)
        for agent_def in agents:
            assert agent_def.post_steps == list(raw_steps[agent_def.agent].get("post_steps", []))
            if agent_def.step_type == "agent":
                assert agent_def.lifecycle_before == list(lifecycle.get("before", []))
                assert agent_def.lifecycle_after == list(lifecycle.get("after", []))
            else:
                assert agent_def.lifecycle_before == [] and agent_def.lifecycle_after == []


# ===========================================================================
# MI-6 -- You can believe what the system tells you
# ===========================================================================

class TestMI6YouCanBelieveWhatTheSystemTellsYou:
    """PRODUCT.md, MI-6:

    "Every step returns a summary on the path where it acted and the path
    where it did not, and declares its expected effect. The orchestrator
    records the observed change and flags any disagreement. After a run in
    either mode, both branches carry one appended record per completed step,
    indistinguishable in what they wrote."

    Met except for one clause, named here rather than papered over: the
    orchestrator compares `expected_effect.creates_issues` against what the
    step actually requested and flags the disagreement both ways, but does NOT
    yet compare observed commits against `expected_effect.commits` --
    `_build_closing_announcement` says so itself ("Comparing it against what
    actually changed is a follow-up; this records the declared half of that
    comparison"). Everything below is asserted as far as it is built; the
    commits half is a real gap, reported as one.
    """

    def test_the_result_contract_requires_a_summary_including_when_nothing_happened(self, loaded):
        """"including when it did nothing" is in the contract every step gets."""
        agents, default_extra_tools = loaded
        agent_def = next(a for a in agents if a.step_type == "agent")
        resolved = po._resolve_agent_invocation(
            agent_def, _work_item(), "test/repo",
            agent_text_override="# stand-in", default_extra_tools=default_extra_tools,
        )
        assert "summary" in resolved.prompt
        assert "including when you did nothing" in resolved.prompt
        assert "expected_effect" in resolved.prompt

    def test_a_missing_summary_is_not_a_valid_result(self, tmp_path):
        """A step cannot decline to say what it did.

        A result with no summary reads as "returned something malformed",
        which the orchestrator resolves to `:failed` -- not to a silent
        success. That is what makes "including when it did nothing"
        enforceable rather than merely asked for.
        """
        assert _write_result(tmp_path, {"outcome": "complete"})[0] is None, (
            "a result with no summary was accepted"
        )
        parsed, err = _write_result(tmp_path, {
            "outcome": "complete", "summary": "did nothing this run", "undone": "",
        })
        assert parsed is not None, err
        assert parsed.summary == "did nothing this run"

    def test_every_step_declares_its_expected_effect(self, loaded):
        agents, _ = loaded
        for agent_def in agents:
            assert agent_def.expected_effect, f"{agent_def.agent} declares no expected_effect"

    def test_a_disagreement_is_surfaced_in_both_directions(self, loaded):
        """"Where the two disagree, you are told" -- and both ways round.

        A step that declared it would raise a work item and did not is as
        wrong as one that raised one having declared it would not.
        """
        agents, _ = loaded
        declares = next(
            (a for a in agents if a.expected_effect.get("creates_issues")), None,
        )
        assert declares is not None, "no step declares creates_issues -- nothing to check"
        assert po.expected_effect_disagreement(declares, requested_issue=False)
        assert po.expected_effect_disagreement(declares, requested_issue=True) is None

        silent = next(a for a in agents if not a.expected_effect.get("creates_issues"))
        assert po.expected_effect_disagreement(silent, requested_issue=True)
        assert po.expected_effect_disagreement(silent, requested_issue=False) is None

    def test_an_undeclared_effect_is_refused_not_merely_reported(self, loaded):
        """MI-6 says a disagreement is surfaced; AS-1 says an undeclared
        allowance is refused. A step raising an issue it never declared gets
        both: the disagreement is logged and the issue is not created."""
        agents, _ = loaded
        silent = next(a for a in agents if not a.expected_effect.get("creates_issues"))
        gh = MagicMock()
        result = po.StepResult(
            outcome="complete", summary="s", undone="",
            creates_issue={"title": "t", "body": "b"},
        )
        created = po._create_requested_issue(gh, silent, _work_item(), result)
        assert created is None
        gh.create_issue.assert_not_called()

    def test_the_declared_effect_is_recorded_on_the_issue(self, loaded):
        """The declared half of the comparison is written into the trail."""
        agents, _ = loaded
        agent_def = next(a for a in agents if a.expected_effect)
        body = po._build_closing_announcement(
            agent_def, _work_item(), "sess", "complete", "summary text",
            expected_effect=agent_def.expected_effect,
        )
        payload = json.loads(re.search(r"```json\n(.*?)\n```", body, re.DOTALL).group(1))
        assert payload["summary"] == "summary text"
        assert payload["expected_effect"] == agent_def.expected_effect

    def test_the_ledger_record_shape_is_the_same_whatever_started_the_run(self):
        """"both branches carry one appended record per completed step,
        indistinguishable in what they wrote" -- the record's own fields do
        not vary by mode; only `actor`, which MI-5's diff excludes and
        "What is allowed to differ" lists ("Who starts a step")."""
        node = next(
            n for n in ast.walk(ORCHESTRATOR_TREE)
            if isinstance(n, ast.FunctionDef) and n.name == "_make_audit_event"
        )
        source = ast.get_source_segment(ORCHESTRATOR_SOURCE, node)
        assert "_HEADLESS" in source, (
            "_make_audit_event no longer builds the mode-dependent actor -- find "
            "where the ledger record is built and point this test at it"
        )
        # Every _HEADLESS reference in the record builder is inside the actor
        # block; no other field of the record is mode-conditional.
        for line in source.splitlines():
            if "_HEADLESS" in line:
                assert '"id"' in line or '"human"' in line, (
                    f"a ledger field other than the actor varies by mode: {line.strip()}"
                )


# ===========================================================================
# MI-7 -- Only a person approves
# ===========================================================================

class TestMI7OnlyAPersonApproves:
    """PRODUCT.md, MI-7:

    "In headless mode, a gate label applied by any non-human actor is
    rejected. In interactive mode, an approval recorded by the orchestrator on
    a relayed human confirmation is honoured. No agent can cause either. An
    inconclusive check refuses rather than admits."

    `tests/test_gate_label_guard.py` was rewritten fail-closed for #403 and IS
    this promise's conformance test for the first and fourth clauses;
    `tests/test_confirm_gate.py` covers the second. Both are re-run here by
    name rather than duplicated. What is added is the third clause -- that no
    agent can cause either -- which neither module states directly.
    """

    def test_a_non_human_applier_is_rejected_and_an_inconclusive_check_refuses(self):
        """The first and fourth clauses, through test_gate_label_guard's own
        harness rather than duplicated.

        That module covers every refusal path in full (bot login, bot actor
        type, API error, unexpected payload, no matching event, pagination);
        its fixtures are reused here to pin the two clauses the promise names,
        so this file records which test proves them.
        """
        import test_gate_label_guard as guard

        assert hasattr(guard, "TestGateLabelHumanApplied"), (
            "test_gate_label_guard no longer covers the gate applier check"
        )
        # Clause 1: a gate label applied by any non-human actor is rejected.
        for login, actor_type in (
            ("github-actions[bot]", "Bot"), ("some-app", "Bot"), ("ai-agile[bot]", "User"),
        ):
            gh = guard._gh_returning([guard._labeled_event(guard.GATE, login, actor_type)])
            assert po._gate_label_human_applied(gh, guard.REPO, guard.ISSUE, guard.GATE) is False, (
                f"a gate label applied by {login!r} ({actor_type}) was accepted"
            )
        # A real person's own account is honoured -- otherwise the refusals
        # above would prove nothing.
        gh = guard._gh_returning([guard._labeled_event(guard.GATE, "a-real-person", "User")])
        assert po._gate_label_human_applied(gh, guard.REPO, guard.ISSUE, guard.GATE) is True

        # Clause 4: an inconclusive check refuses rather than admits.
        for events in ([], [{"event": "labeled"}], "not a list"):
            gh = guard._gh_returning(events)
            assert po._gate_label_human_applied(gh, guard.REPO, guard.ISSUE, guard.GATE) is False, (
                f"an inconclusive events payload ({events!r}) admitted the gate"
            )
        gh = MagicMock()
        gh._get.side_effect = RuntimeError("the API is down")
        assert po._gate_label_human_applied(gh, guard.REPO, guard.ISSUE, guard.GATE) is False, (
            "an API error admitted the gate"
        )

    def test_an_agents_entire_output_surface_cannot_carry_an_approval(self, loaded, tmp_path):
        """"An agent's entire output surface is one status value from a fixed
        set, so there is no message an agent can send that means 'approve
        this.'"

        Two ways an agent could try: a result outcome outside the fixed set,
        and a label request for a gate label. Both are refused.
        """
        agents, _ = loaded
        gated = next((a for a in agents if a.human_gate_label), None)
        assert gated is not None, "no step declares a human gate -- nothing to check"

        parsed, err = _write_result(tmp_path, {
            "outcome": "approved", "summary": "I approve this", "undone": "",
        })
        assert parsed is None and err, "an agent talked its way to an outcome outside the set"
        assert set(po._VALID_OUTCOMES) == {"complete", "review", "blocked"}, (
            f"the agent output surface has grown: {sorted(po._VALID_OUTCOMES)}"
        )

        # And no step may request its own gate label into existence.
        for agent_def in agents:
            cleared = po._filter_allowed_label_requests(
                agent_def,
                [{"issue": None, "add": [gated.human_gate_label], "remove": []}],
            )
            assert not cleared, (
                f"{agent_def.agent} may request the gate label {gated.human_gate_label!r}"
            )

    def test_the_gate_check_is_the_same_one_in_the_interactive_path(self):
        """"the orchestrator recording a confirmation the driver relayed" is
        the same check, not a looser one: --confirm-gate calls
        `_gate_label_human_applied`, exactly as the headless path does."""
        node = next(
            n for n in ast.walk(ORCHESTRATOR_TREE)
            if isinstance(n, ast.FunctionDef) and n.name == "_run_confirm_gate"
        )
        source = ast.get_source_segment(ORCHESTRATOR_SOURCE, node) or ""
        assert "_gate_label_human_applied" in source, (
            "the interactive gate path does not route through the same check"
        )


# ===========================================================================
# MI-8 -- Any difference is written down
# ===========================================================================

# Every mode-conditional branch site in pipeline_orchestrator.py, mapped to the
# row of PRODUCT.md's "What is allowed to differ" table it implements. The
# mapping is by hand because no tool can derive it: what makes a branch
# legitimate is a sentence of prose, not a property of the code. What IS
# mechanical, and is what the test below checks, is that the set of branch
# sites in the code equals the set mapped here -- so a NEW mode-conditional
# branch fails until someone maps it to a listed difference, or adds a row.
_MODE_BRANCHES: dict[str, str] = {
    # The audit/ledger entry's `actor` -- "github-actions" with human: null
    # for an unattended tick, the session's own actor with human: true
    # otherwise. Nothing else in the record varies (MI-6 pins that).
    "_make_audit_event": "Who starts a step",
    # The emergency stop halts a headless tick before any step and is logged,
    # not obeyed, when a person is driving one issue by hand.
    "_check_controls": "Whether the emergency stop applies",
    "_wake": "Whether the emergency stop applies",
    # A headless run has no session to inherit auth from and needs
    # ANTHROPIC_API_KEY; an interactive one uses the session's own login.
    "_build_agent_env": "Which credentials are used",
    # Headless is one tick at a time, so its in-memory component claims are
    # trustworthy; interactive is several unserialised processes, so it reads
    # the claims fresh from GitHub. Same invariant, different shape.
    "_should_run": "How many items advance at once",
    # --interactive-result: the person and the chat-AI did the step's work in
    # their own session and the orchestrator reads the result they wrote,
    # rather than spawning a subprocess to produce it. What lands on the issue
    # is identical; only the channel the work arrived through differs.
    "_run_agent": "How you address the pipeline",
    "process_work_item": "How you address the pipeline",
}

_MODE_TOKENS = ("_HEADLESS", "interactive_result", "args.headless")


def _mode_conditional_functions() -> set[str]:
    """Every function whose own body branches on how the tick was started.

    A reference inside a nested function is attributed to the nested function,
    so a helper is not credited to its enclosing one.
    """
    found: set[str] = set()
    for node in ast.walk(ORCHESTRATOR_TREE):
        if not isinstance(node, ast.FunctionDef):
            continue
        nested = {
            id(n) for child in node.body for n in ast.walk(child)
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        for test_node in ast.walk(node):
            if not isinstance(test_node, (ast.If, ast.IfExp)):
                continue
            if id(test_node) in nested:
                continue
            test_src = ast.get_source_segment(ORCHESTRATOR_SOURCE, test_node.test) or ""
            if any(token in test_src for token in _MODE_TOKENS):
                found.add(node.name)
    return found


class TestMI8AnyDifferenceIsWrittenDown:
    """PRODUCT.md, MI-8:

    "Every mode-conditional branch in the orchestrator, the scripts and the
    agent prompts maps to a listed difference."

    PARTIAL, and deliberately so. Deciding whether a given `if _HEADLESS:` is
    the row "Whether the emergency stop applies" or an unlisted new difference
    requires reading the prose; no static check can do it. So the mapping is
    written down once, in `_MODE_BRANCHES` above, and the test asserts the two
    things that CAN be checked mechanically:

      1. every row named in the mapping really exists in PRODUCT.md's
         "What is allowed to differ" table -- a mapping to a row that was
         deleted or renamed is caught;
      2. the set of mode-conditional branch sites in the orchestrator is
         exactly the set mapped -- a new branch fails this test until someone
         maps it to a listed difference or adds a row with a reason.

    Scope: the orchestrator only. The paragraph also names "the scripts and
    the agent prompts"; those are checked for the coarser property that no
    script or prompt branches on the mode at all, which is the state today.
    """

    def _allowed_to_differ_rows(self) -> set[str]:
        text = PRODUCT_MD.read_text()
        section = text.split("## What is allowed to differ", 1)
        assert len(section) == 2, "PRODUCT.md has no 'What is allowed to differ' section"
        rows = set()
        for line in section[1].splitlines():
            if not line.startswith("|"):
                continue
            cells = [c.strip() for c in line.strip("|").split("|")]
            if len(cells) < 4 or cells[0] in {"Difference", ""} or set(cells[0]) <= {"-"}:
                continue
            rows.add(cells[0])
        return rows

    def test_the_table_exists_and_every_row_gives_a_reason(self):
        text = PRODUCT_MD.read_text().split("## What is allowed to differ", 1)[1]
        rows = 0
        for line in text.splitlines():
            if not line.startswith("|"):
                continue
            cells = [c.strip() for c in line.strip("|").split("|")]
            if len(cells) < 4 or cells[0] in {"Difference", ""} or set(cells[0]) <= {"-"}:
                continue
            assert cells[3], f"the row {cells[0]!r} lists no reason"
            rows += 1
        assert rows >= 5, "the list of allowed differences is suspiciously short"

    def test_every_mapped_difference_is_a_row_that_exists(self):
        rows = self._allowed_to_differ_rows()
        unknown = {v for v in _MODE_BRANCHES.values() if v not in rows}
        assert not unknown, (
            f"the mapping names differences PRODUCT.md does not list: {sorted(unknown)}"
        )

    def test_every_mode_conditional_branch_maps_to_a_listed_difference(self):
        found = _mode_conditional_functions()
        unmapped = found - set(_MODE_BRANCHES)
        assert not unmapped, (
            f"pipeline_orchestrator.py branches on the mode in {sorted(unmapped)}, which "
            "maps to no listed difference. Either map it to a row of PRODUCT.md's "
            "'What is allowed to differ', or add a row with a reason -- an unlisted "
            "difference is a defect, not a feature (MI-8)."
        )
        stale = set(_MODE_BRANCHES) - found
        assert not stale, (
            f"the mapping lists {sorted(stale)}, which no longer branch on the mode -- "
            "remove the entry so the mapping keeps meaning something"
        )

    def test_no_pipeline_script_branches_on_the_mode(self):
        """The scripts half of the paragraph, at its coarsest: none does."""
        offenders = []
        for path in sorted((REPO_ROOT / ".github" / "scripts").glob("*.sh")):
            text = path.read_text()
            for token in ("AI_AGILE_EXECUTION_MODE", "--headless", "INTERACTIVE"):
                if re.search(rf'^\s*(if|elif|case).*{re.escape(token)}', text, re.M):
                    offenders.append(f"{path.name} ({token})")
        assert not offenders, (
            f"a pipeline script branches on the mode: {offenders} -- map it to a listed "
            "difference or remove the branch"
        )

    def test_no_agent_prompt_branches_on_the_mode(self):
        """The prompts half: no agent instructs itself differently by mode.

        An agent subprocess is always `AI_AGILE_EXECUTION_MODE=headless`
        regardless of what started the tick, so a prompt reading that variable
        would be reacting to something that never varies -- or worse, would be
        the beginning of one.
        """
        offenders = []
        for path in sorted((REPO_ROOT / ".claude" / "agents").rglob("*.md")):
            text = path.read_text()
            if re.search(r"if\s+.*AI_AGILE_EXECUTION_MODE", text):
                offenders.append(path.name)
        assert not offenders, f"an agent prompt branches on the mode: {offenders}"
