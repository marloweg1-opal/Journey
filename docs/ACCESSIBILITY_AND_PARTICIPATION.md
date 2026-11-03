# Accessibility and Meaningful Participation

**Status: design doctrine and an honest account of present limits, not an accessibility certification.**

Journey's purpose is to help people remain oriented to their work, technology, history, and choices. Accessibility is not an optional layer placed on top of governance. A system cannot genuinely preserve human agency if some people cannot understand its proposals, communicate a choice, or correct its decisions.

**Technical recognition is not meaningful participation.** Detecting an input, categorizing a communication attempt, or displaying a control is not enough. The person needs a usable way to understand, influence, refuse, revise, and verify what happens.

## What the current public prototype offers

The published Journey prototype provides a Python CLI, a local browser Navigator, bounded inspection and classification components, recorded operational evidence, policy contracts, and a non-mutating public demonstration. These are most directly usable by people with a compatible Windows and Python environment who can operate the supplied text and browser interfaces. Public documentation and source code also allow technically experienced reviewers to examine the design without giving Journey control of their machines.

The public repository does **not** establish a complete, accessibility-tested consumer application. Local development can be ahead of published code; unpublished local reports are not certification of public behavior.

## Who may be excluded or unable to participate meaningfully today

- **People using screen readers, switch access, voice control, or other assistive technology:** compatibility, accessible status announcements, focus behavior, and confirmation workflows have not been comprehensively tested or certified.
- **People who need nonvisual, reduced-motion, high-contrast, low-vision, or alternative presentations:** a visual Navigator does not itself prove that equivalent information and operations are available through every needed mode.
- **People whose communication does not fit a conventional text prompt or button:** the current interfaces do not establish support for every language, communication practice, alternative input, or augmentative and alternative communication (AAC) workflow.
- **People without the supported computer, resources, technical background, or authority to install local software:** a Windows-centered prototype and developer-oriented setup create material access barriers.
- **People whose context or intent Journey misclassifies:** recognizing a file or statement does not prove Journey understood its purpose; mistaken interpretations must remain reviewable, correctable, and subordinate to the person's choices.

These are limitations of the present program, distribution, or testing, **not limitations of the people involved**. Nor should an untested experience be described as inaccessible in every configuration; its actual compatibility remains to be established.

## Operating practice

When describing a capability or designing a new one:

1. State what works today, the context in which it was verified, and the people or workflows it currently serves.
2. Name the people and communication or interaction conditions for whom meaningful participation is unsupported, untested, or currently obstructed.
3. Separate **implemented**, **held**, **planned**, and **possible with additional contributors or tools**. Never promote a design aspiration into a shipped feature.
4. Preserve understandable explanations, explicit uncertainty, user correction, and choice; consent to observe is not consent to act or to retain personal information.
5. Invite feedback and collaboration without requiring someone to disclose a diagnosis, disability, or private personal records to establish that a barrier exists.
6. Treat participation as a design and evaluation criterion, not simply successful input detection or an impressive automation result.

## Directions for future work, not current feature claims

Evaluate keyboard-only and assistive-technology interaction, status and error announcements, contrast and motion alternatives, language and communication flexibility, readable approval plans, and ways to express uncertainty or refuse an operation. Test with people who actually use the relevant interaction methods. Preserve privacy and authority boundaries when adding new access paths.

See [Project Boundaries](PROJECT_BOUNDARIES.md), [Forward Architecture](JOURNEY_FORWARD_ARCHITECTURE.md), and [Public Checkpoint](JOURNEY_PUBLIC_CHECKPOINT.md) for technical responsibilities and verified scope.

**The boundaries of this program are not the boundaries of human possibility. Participation is the blessing.**
