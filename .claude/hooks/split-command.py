#!/usr/bin/env python3
"""Split a shell command into the sub-commands a permission check must match.

Used by run-agent-scope.sh (issue #362). The hook used to glob a granted
pattern against the whole command string, which is wrong in both directions:

  too loose   `Bash(export *)` grants `export FOO=1 && curl evil.com`,
              because the trailing `*` spans the `&&` and everything after it.
  too strict  `Bash(sed *)` refuses `cd /repo && sed -n 1p f`, because the
              string starts with `cd`.

Splitting on the shell's control operators fixes both: every sub-command is
matched independently, and all of them must be granted.

Contract
    stdin   the raw command text
    stdout  one sub-command per line, whitespace-normalised; on refusal, the
            single line `REFUSED: <reason>` instead
    exit 0  split succeeded
    exit 2  refused. The caller must deny.

Refusal is the answer for anything this splitter cannot decompose honestly:
command substitution hides a command inside a word, and an exec wrapper runs a
command named in its own arguments. Neither is visible to pattern matching, so
neither may be waved through on the strength of the outer command's grant.
"""
import re
import shlex
import sys

# Constructs that run a command from inside a word. No amount of segment
# matching sees the inner command, so the whole call is refused.
SUBSTITUTION_MARKERS = ("$(", "`", "<(", ">(", "${!")

# Operators shlex emits as their own tokens once punctuation_chars is on.
# Each ends the current sub-command and begins the next. A newline is a
# separator too, but shlex treats it as plain whitespace, so lines are split
# before lexing rather than here.
SEPARATORS = {"&&", "||", ";", ";;", "|", "|&", "&", "(", ")"}

# `<<EOF` / `<<-"EOF"` / `<<'EOF'`. Group 1 is the quote, if any: a quoted
# delimiter means the shell does no expansion inside the body.
HEREDOC = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")

# Wrappers whose entire purpose is to execute a command named in their
# arguments. Granting the wrapper would grant everything it can launch.
EXEC_WRAPPERS = {
    "eval", "env", "xargs", "sudo", "nohup", "timeout", "nice",
    "watch", "command", "exec", "source", ".",
}

# Mapping from interpreter name to the flags that actually pass inline source
# to THAT interpreter. Each interpreter has its own flag vocabulary: shells use
# -c for inline source (and -e means errexit, not eval), while perl/ruby/node
# use -e/-E/--eval. A shared union would cause false denials on common idioms
# like `bash -e scripts/build.sh` (errexit + file, not inline source). (SA-001)
INTERPRETER_INLINE_FLAGS = {
    "sh":      {"-c"},
    "bash":    {"-c"},
    "zsh":     {"-c"},
    "dash":    {"-c"},
    "ksh":     {"-c"},
    "python":  {"-c"},
    "python3": {"-c"},
    "perl":    {"-e", "-E"},
    "ruby":    {"-e"},
    "node":    {"-e", "--eval", "-p", "--print"},
}

# find's own exec facility -- the same laundering, spelled differently.
FIND_EXEC_FLAGS = {"-exec", "-execdir", "-ok", "-okdir"}


def collapse_continuations(command):
    """Join `\\`-continued lines, which are one command, not two."""
    return re.sub(r"\\\n", " ", command)


def strip_heredocs(command):
    """Remove heredoc bodies, which are data rather than commands.

    Returns (command_without_bodies, bodies_the_shell_still_expands). Agents
    are told to stage comment bodies with `cat > "$AI_AGILE_SCRATCH/body.md"
    <<'EOF'` (.claude/AGENTS.md), so treating the body's lines as commands
    would deny the one file-staging idiom the protocol prescribes.
    """
    lines = command.split("\n")
    kept, expanding = [], []
    index = 0
    while index < len(lines):
        line = lines[index]
        kept.append(line)
        # Track whether dash-stripped (`<<-`): only tabs are stripped from the
        # closing delimiter line, not spaces. (DP-001)
        delimiters = [
            (m.group(2), m.group(1), m.group(0).startswith("<<-"))
            for m in HEREDOC.finditer(line)
        ]
        index += 1
        for delimiter, quote, dash in delimiters:
            while index < len(lines):
                candidate = lines[index].lstrip("\t") if dash else lines[index]
                if candidate == delimiter:
                    break
                if not quote:
                    expanding.append(lines[index])
                index += 1
            index += 1  # drop the closing delimiter line
    return "\n".join(kept), expanding


def refuse(reason):
    print(f"REFUSED: {reason}")
    raise SystemExit(2)


def split(command):
    command, expanding_bodies = strip_heredocs(collapse_continuations(command))

    for text in [command] + expanding_bodies:
        for marker in SUBSTITUTION_MARKERS:
            if marker in text:
                refuse(
                    f"the command uses `{marker}`, which runs a command inside "
                    f"a word where scope checking cannot see it"
                )

    segments = []
    for line in command.split("\n"):
        line = line.strip()
        if not line:
            continue
        lexer = shlex.shlex(line, posix=False, punctuation_chars=True)
        lexer.whitespace_split = True
        try:
            tokens = list(lexer)
        except ValueError as exc:
            refuse(f"the command could not be parsed as shell ({exc})")

        current = []
        for token in tokens:
            if token in SEPARATORS:
                if current:
                    segments.append(current)
                    current = []
            else:
                current.append(token)
        if current:
            segments.append(current)

    for tokens in segments:
        head = tokens[0]
        if head in EXEC_WRAPPERS:
            refuse(
                f"`{head}` runs a command named in its own arguments, so a "
                f"grant for it would grant everything it can launch"
            )
        inline_flag = next(
            (f for f in tokens[1:] if f in INTERPRETER_INLINE_FLAGS.get(head, set())),
            None,
        )
        if head in INTERPRETER_INLINE_FLAGS and inline_flag is not None:
            refuse(
                f"`{head} {inline_flag}` runs inline source, which no pattern "
                f"can scope; run the command directly instead"
            )
        for flag in FIND_EXEC_FLAGS:
            if flag in tokens[1:]:
                refuse(
                    f"`{flag}` runs an arbitrary command per match; pipe the "
                    f"results to a granted command instead"
                )

    return [" ".join(tokens) for tokens in segments]


def main():
    command = sys.stdin.read().strip()
    if not command:
        return
    for segment in split(command):
        print(segment)


if __name__ == "__main__":
    main()
