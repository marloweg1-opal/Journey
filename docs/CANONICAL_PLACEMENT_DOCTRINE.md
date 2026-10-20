# Canonical Placement Doctrine

Mini ARK must know where things belong, not only where things are.

The machine-readable source of truth is:

```text
C:\mini_ark\config\canonical_placement.json
```

## Rule

```text
Hardwire the grammar, not every future sentence.
```

Mini ARK should know the meanings of canonical locations, protection levels, lifecycles, aliases, and routing hints. It should not need a code update for every future project folder.

## Safety

Placement evaluation is read-only.

It may say:

```text
This likely belongs in R:\In_Transit\En_Route.
```

It must not move the item until a separate proposal/approval/preview/apply flow exists.

The governing sequence remains:

```text
Detect -> Explain -> Propose -> Review -> Approve -> Preview -> Execute -> Log -> Undo
```

## Current Command

Evaluate one path:

```text
.\ark.cmd placement "R:\Downloads2"
```

Show the doctrine:

```text
.\ark.cmd placement
```

Structured output:

```text
.\ark.cmd placement "R:\Downloads2" --json
```

## Current States

```text
CONGRUENT
LIKELY_CONGRUENT
MISPLACED_HIGH_CONFIDENCE
MISPLACED_NEEDS_REVIEW
TRANSIENT_ACCEPTABLE
LEGACY_PATH
PROTECTED_OPERATIONAL
UNKNOWN
```

## Important Behavior

Rainmeter and Wallpaper Engine locations are protected operational surfaces.

A PNG inside a live Rainmeter skin is not merely an image. It may be live application state, so Mini ARK defaults to leaving it alone.

Ad hoc temporary folders such as:

```text
R:\Downloads2
```

should route toward:

```text
R:\In_Transit\En_Route
```

CareBloomOS material that is not application-owned should route toward:

```text
R:\Projects\CareBloomOS
```

`R:\RuneScript` is a legacy wrapper pending reconciliation. It is not the canonical RuneScript root.

Active project source may still be valid working state. Mini ARK should distinguish working source from durable archive/canon instead of flattening both into a single tidy rule.
