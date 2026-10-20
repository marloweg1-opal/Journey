# Contributing to Journey

Journey is an active, human-governed prototype. Questions, reproducibility
reports and bounded use cases are welcome even if you do not intend to submit
code.

## Ways to engage

- **Ask a question:** use the
  [question template](https://github.com/marloweg1-opal/Journey/issues/new?template=question.yml).
- **Try the public walkthrough:** follow the read-only demo in the
  [README](README.md#try-the-public-demo).
- **Report a reproducibility problem:** include your operating system, Python
  version, command and redacted output.
- **Suggest a use case:** describe the human problem, the information Journey
  would need and the action it must not take without approval.
- **Propose a code change:** keep it narrow, explain the behavior being changed
  and include or update tests where practical.

## Contribution boundary

Do not post credentials, private inventories, personal media, absolute home
directory paths, machine logs or real recovery records. Synthetic examples are
preferred. A passing test demonstrates behavior; it does not grant Journey new
authority over a real machine.

Changes that introduce file mutation, persistent observation, personal-data
storage or external AI providers require an explicit threat and authority
review. Default-deny behavior should remain default-deny.

## Project vocabulary

- **Journey** is the public product and repository identity.
- **Mini ARK** / `mini_ark` is a legacy implementation name retained where an
  immediate rename could break a working installation.
- **Project ARK** is the broader future family of systems.
- Project-specific language belongs in an integration profile rather than the
  Journey core.

## What makes a useful issue

A useful report answers four questions:

1. What were you trying to understand or accomplish?
2. What did you expect Journey to do?
3. What happened instead?
4. What information can you share safely to reproduce it?

Uncertainty is acceptable. Private data is not required to participate.
