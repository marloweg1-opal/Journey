# Project Knowledge Layer

Status: interface and evidence precedence implemented; perception providers and learned indexes deferred beyond Gate A.

Stages: perception -> evidence -> classification -> contextual judgment -> placement policy -> authority/action.

`core/perception.py` defines immutable provider evidence with provider/version,
source fingerprint, dimension, value, confidence and explanation. Providers receive
bounded bytes, not a ledger connection or filesystem action capability. Production
adapters must run in a worker with enforced byte/time/memory limits before enabling
untrusted or model-backed providers. The protocol alone is not process isolation.

Project knowledge will join explicit canon, registered identities, provenance and
relationships, accepted examples, embeddings/similarity, perceptual observations,
and generic heuristics. That is the precedence order. Learned correlations cannot
outvote declarations. Conflicting declarations stay unresolved.

Project, affinity, role, lifecycle and placement remain separate dimensions.
Existing path heuristics retain their categorical confidence; unmeasured dimensions
have null confidence. A future calibration layer must not fabricate probabilities
from these categories. Ask only about unresolved dimensions when an action needs
them. A known wallpaper role does not settle project ownership.

Canonical, operational and presentation locations are separate fields. A probable
project owner is insufficient evidence for a high-confidence migration. Registered
dependencies and reservations take precedence. Absence of registered dependencies
is not evidence that there are none.

Minimum Sufficient Organization: group >= 5 and remaining parent >= 15 permits,
but does not require, a physical subfolder. Require demonstrated utility; operational
requirements override. Search metadata carries additional distinctions.

Future storage: append evidence keyed by logical asset and source fingerprint;
record accepted human resolutions separately; expire derived evidence when content
or provider version changes. Keep learned indexes rebuildable from accepted records.
