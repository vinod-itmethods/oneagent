---
name: sonar-context-augmentation
description: >-
  ALWAYS invoke this skill on the first prompt, whether you are the Agent or an Explore, Plan, or general-purpose subagent.
---

# Sonar Context Augmentation — Agent Skill (v0.12.0-build.1451)

IMPORTANT:
* `sonar context` is not sandbox-compatible — it spawns a local daemon and communicates with it via Unix domain sockets (Linux/macOS) or named pipes (Windows).
* When invoking a subagent (Explore, Plan, general-purpose), ALWAYS ask it to invoke this skill as a first step.


## Mandatory Workflows

### Before Writing or Editing Code

You MUST call `guidelines get` before generating, editing, or refactoring any source
code to retrieve coding standards and known project issues.
Supports **all SonarQube languages** (Java, JavaScript, TypeScript, Python, C#,
PHP, C, C++, Go, and more). Use `--languages` and `--categories` to narrow results.

```bash
sonar context guidelines get
```

For **Java projects**, also locate existing code patterns before writing new code:

```bash
sonar context navigation search-signatures --pattern ".*Repository" --limit 10
sonar context navigation get-source --fqn "<fqn-from-search>"
```

### When Navigating or Understanding Code (Java Only)

Use these tools to explore the codebase before making changes:

- `navigation search-signatures --pattern "<regex>"` — find code by declaration (name, annotations, modifiers)
- `navigation search-bodies --pattern "<regex>"` — find where APIs/patterns are used in implementations
- `navigation get-source --fqn "<fqn>"` — read full source code for a symbol found via search
- `navigation trace-callers --fqn "<fqn>"` — find all callers ("what breaks if I change this?")
- `navigation trace-callees --fqn "<fqn>"` — trace execution flow ("what does this call?")
- `navigation get-type-hierarchy --fqn "<fqn>"` — explore class inheritance and interface implementations
- `navigation get-references --fqn "<fqn>"` — find inbound/outbound class-level dependencies

### When Reviewing or Changing Architecture

Check architecture before introducing new modules or cross-module dependencies.

- `architecture get-current` — actual module dependency graph (**Java, JS, TS, Python, C#**)
- `architecture get-intended` — allowed dependency rules (**Java, JS, TS, Python, C#**)

## Language Support

| Command | Languages | Notes |
| --- | --- | --- |
| `guidelines get` | All SonarQube languages | Java, JS, TS, Python, C#, PHP, C, C++, Go, etc. |
| `architecture get-current` | Java, JS, TS, Python, C# | Use `--ecosystem` to filter |
| `architecture get-intended` | Java, JS, TS, Python, C# | Allowed and forbidden couplings |
| `navigation search-signatures` | Java | Regex on declarations/signatures |
| `navigation search-bodies` | Java | Regex on function/method bodies |
| `navigation get-source` | Java | Full source code by FQN |
| `navigation trace-callers` | Java | Upstream call chains |
| `navigation trace-callees` | Java | Downstream call chains |
| `navigation get-type-hierarchy` | Java | Class/interface inheritance |
| `navigation get-references` | Java | Class-level coupling (inbound/outbound) |


## Best Practices

- Use `--limit 20` or less for searches to avoid exceeding context windows.
- Use `--depth 2` or `--depth 3` for `navigation trace-callers`, `navigation trace-callees`, and `architecture get-current`.
- Use `--fields` to request only needed fields — significantly reduces response size.
- For navigation search, trace, and reference commands, use `--output fqns` or `--output names` when you only need identifiers.
- Use `navigation search-signatures --output fqns` to discover exact FQNs rather than
  constructing them manually.
- **Progressive disclosure**: start with `architecture` and `guidelines get` for the
  big picture, drill down with `navigation search-signatures`, `navigation trace-callers`, `navigation trace-callees`, and `navigation get-references`
  for specifics.

## Pipeline Composition

Commands can be piped together using `--output fqns` and `--fqn-stdin`:

```bash
# Find all repository classes, then get source code for each
sonar context navigation search-signatures --pattern ".*Repository" --output fqns \
  | sonar context navigation get-source --fqn-stdin

# Find all callers of a method, then get their type hierarchies
sonar context navigation trace-callers --fqn "com.example.UserService#save" \
  --output fqns \
  | sonar context navigation get-type-hierarchy --fqn-stdin
```

**`--output` modes**: `json` (default, full result), `fqns` (one FQN per line),
`names` (short names).

**`--fqn-stdin`**: reads FQNs from stdin, one per line. Mutually exclusive with
`--fqn`.

Use pipelines when you need information about multiple symbols discovered from a
search.

## Command Reference

### Troubleshooting Commands

Use these only when queries fail, the daemon appears unhealthy, or results seem stale.

#### `tool start` — Start the daemon

```bash
sonar context tool start
```

#### `tool status` — Show daemon status

```bash
sonar context tool status
sonar context tool status --project-key <key>
```

#### `tool stop` — Stop a daemon

```bash
sonar context tool stop --project-key <key>
sonar context tool stop --all
```

### Query Commands

Query commands auto-start the daemon when this workspace is already configured.
Auto-start does not create workspace configuration or Sonar authentication; if
setup is missing, follow the error recovery guidance below. Most commands output
JSON to stdout. The exception is `guidelines get`, which outputs markdown text.

#### `navigation search-signatures` — Find code by signature patterns (Java)

```bash
sonar context navigation search-signatures \
  --pattern ".*Repository" \
  --fields "fqn,file_path,start_line" \
  --limit 10
```

Regex search on function/method/class declarations. Use to find implementations
by name, annotations, or modifiers.

Options:

- `--pattern <regex>` (required, repeatable) — regex to match in signatures. Multiple patterns are combined with OR.
- `--exclude-pattern <regex>` (repeatable) — regex to exclude
- `--include-glob <glob>` — include only files whose paths match the glob; quote the pattern to avoid shell expansion
- `--exclude-glob <glob>` — exclude files whose paths match the glob; quote the pattern to avoid shell expansion
- `--fields <fields>` — comma-separated fields to include
- `--limit <n>` — max results (default: 10)
- `--output <json|fqns|names>` — output mode (default: json). Use `fqns` for piping.

#### `navigation search-bodies` — Find code by body content patterns (Java)

```bash
sonar context navigation search-bodies \
  --pattern "TODO|FIXME" \
  --limit 20
```

Same options as `navigation search-signatures`, but searches inside function/method bodies.
For finding call sites or usages, prefer `navigation get-references` (class-level coupling) or
`navigation trace-callers` / `navigation trace-callees` for structured, complete results.

#### `navigation get-source` — Get source code for a symbol (Java)

```bash
sonar context navigation get-source --fqn "com.example.UserService#save"
```

Options:

- `--fqn <fqn>` (required) — fully qualified name
- `--fqn-stdin` — read FQNs from stdin (one per line). Mutually exclusive with `--fqn`.
- `--fields <fields>` — comma-separated fields to include

#### `navigation trace-callees` / `navigation trace-callers` — Trace call chains (Java)

```bash
sonar context navigation trace-callees \
  --fqn "com.example.UserService#save" \
  --depth 2
```

Options:

- `--fqn <fqn>` (required) — fully qualified name
- `--fqn-stdin` — read FQNs from stdin (one per line). Mutually exclusive with `--fqn`.
- `--depth <n>` — call chain depth (default: 1)
- `--fields <fields>` — comma-separated fields to include
- `--output <json|fqns|names>` — output mode (default: json). Use `fqns` for piping.

> If a class FQN is provided instead of a method FQN, the call-flow commands return
> architectural references (inbound/outbound dependencies) instead of a call chain.

#### `navigation get-type-hierarchy` — Get type hierarchy for a class (Java)

```bash
sonar context navigation get-type-hierarchy --fqn "com.example.BaseService"
```

Options:

- `--fqn <fqn>` (required) — fully qualified name
- `--fqn-stdin` — read FQNs from stdin (one per line). Mutually exclusive with `--fqn`.
- `--fields <fields>` — comma-separated fields to include
- `--output <json|fqns|names>` — output mode (default: json). Use `fqns` for piping.

#### `navigation get-references` — Find references to a symbol (Java)

```bash
sonar context navigation get-references --fqn "com.example.UserService"
```

Only accepts class/interface/module FQNs — not method FQNs. Use `navigation trace-callers` or `navigation trace-callees` for
method-level analysis.

Options:

- `--fqn <fqn>` (required) — fully qualified name
- `--fqn-stdin` — read FQNs from stdin (one per line). Mutually exclusive with `--fqn`.
- `--fields <fields>` — comma-separated fields to include
- `--output <json|fqns|names>` — output mode (default: json). Use `fqns` for piping.

#### `architecture get-current` / `architecture get-intended` — View module architecture (Java, JS, TS, Python, C#)

```bash
sonar context architecture get-current --ecosystem java
sonar context architecture get-intended
```

Options:

- `get-current`: `--ecosystem <java|cs|py|js|ts>`, `--depth <n>`, `--path-prefix <prefix>`, `--fields <fields>`, `--format <compact|pretty>`
- `get-intended`: `--fields <fields>`, `--format <compact|pretty>`

> `architecture get-current` defaults to `--depth 3`. Start with `--depth 0`
> (no path prefix) when you want a root-level overview, then use a root FQN as
> `--path-prefix` with higher depth to drill in. FQNs may use different separators
> (`:`, `.`, `/`) depending on language — always check `--depth 0` output first.

#### `guidelines get` — Get coding guidelines and issues (All Languages)

```bash
# Space-separated values after a single flag (preferred for multiple values):
sonar context guidelines get --categories "Auth & Identity" "Exception & Error Handling" --languages java
# Repeated flags also work:
sonar context guidelines get --categories "Auth & Identity" --categories "Exception & Error Handling" --languages java
sonar context guidelines get --languages java --files "src/main/java/com/example/Service.java"
```

Output is **markdown text**, not JSON — print it directly rather than parsing as JSON.

Options:

- `--categories <value> [<value>...]` — categories to retrieve. Requires `--languages`.
  Pass multiple values space-separated (`--categories "A" "B"`) or repeat the flag
  (`--categories "A" --categories "B"`). Both forms are equivalent.
  Available: "Auth & Identity", "Exception & Error Handling", "Testing Practices",
  "Web Security (Injection/XSS)", "Secrets & Cryptography", "Cloud & Network Security",
  "Logging & Monitoring", "Memory & Resource Safety", "Async & Concurrency",
  "Naming & Code Style", "Complexity & Maintainability", "Language Idioms & Modernization",
  "Type Systems & Logic Safety", "Architectural Integrity", "Web Service & API Design",
  "Data Modeling & Persistence", "Data Querying & Performance",
  "Framework Configuration & DI", "Serialization & Message Formats",
  "Inline Documentation & Metadata", "Environment & Build Configuration",
  "Regular Expressions", "Data Science & Big Data", "UI & Accessibility",
  "Mobile & Hardware SDKs", "Platform Governance", "i18n & Localization".
- `--languages <value> [<value>...]` — target languages (java, typescript, python, etc.). Required when `--categories` is used.
  Pass multiple values space-separated (`--languages java python`) or repeat the flag.
- `--mode <mode>` — retrieval mode: `project_based` (default), `category_based`, or `combined`.
  Defaults to `category_based` when `--categories` is provided.
- `--files <value> [<value>...]` — file paths to filter by. Space-separated or repeated flag.
- `--format <compact|pretty>` — output format (default: compact)

## Output Interpretation

- **Stdout**: Result data. JSON for most commands; markdown text for `guidelines get`.
- **Stderr**: Progress messages, warnings. Informational only.
- **Exit code 0**: Success.
- **Exit code 1**: User-fixable error. Check the `error:` and `hint:` lines on stderr.
- **Exit code 2**: Daemon or tool error. The daemon may need a restart.

Error recovery:

| Error                | Exit | Recovery                                                          |
| -------------------- | ---- | ----------------------------------------------------------------- |
| `token_missing`      | 1    | Ask user to check the status of `sonar auth` to ensure that authentication has been configured properly |
| `daemon_not_found`   | 1    | Auto-start does not create workspace configuration. Check `sonar context tool status` to see whether another workspace or project is configured; if this workspace should be integrated, surface the problem to the user and advise them to rerun the sonar context integration process |
| `config_not_found`   | 1    | Auto-start does not create workspace configuration. This workspace is not configured for Context Augmentation. Surface the problem to the user including any relevant details and advise them to rerun the sonar context integration process |
| `invalid_args`       | 1    | Check flags and retry                                             |
| `auth_failed`        | 1    | Ask user to verify their SonarQube token                          |
| `daemon_unreachable` | 2    | Run `sonar context tool stop --all` then retry (auto-restarts)   |
| `daemon_start_failed`| 2    | Check `sonar context tool status`, inspect daemon logs, then retry with `sonar context tool start` |
| `tool_error`         | 2    | Check error message — usually invalid FQN or missing data         |
| `data_loading`       | 2    | Wait a few seconds and retry — daemon is still loading data       |

If results seem stale: the daemon auto-refreshes on branch changes and new
analyses, and restarts automatically after idle timeout (30 min default).
