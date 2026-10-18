# Journey Naming Architecture

Journey is the product, system, and public repository identity.

Mini ARK is the former product name and remains a compatibility identifier in
the current working-tree path, command wrapper, scripts, and selected module
surfaces.

The two names refer to one codebase. Public naming changes first; technical
paths migrate only after their dependencies are audited. No parallel Journey
codebase should be created and no working local path should be renamed merely
for cosmetic consistency.

## Naming boundary

- Journey names generic system behavior and stable contracts.
- External profiles name their own translations and presentation.
- A profile alias never replaces a backend identity.
- Project-specific terminology belongs with the project that owns it.

See [Project Boundaries](PROJECT_BOUNDARIES.md).
