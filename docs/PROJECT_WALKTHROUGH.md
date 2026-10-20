# Journey Project Walkthrough

This is the shortest useful tour for a hiring manager, collaborator or curious
engineer.

## The project in one sentence

Journey is a local-first coordination layer that helps a person preserve context
across files and projects while keeping observation, recommendation, approval
and execution visibly separate.

## The problem

Computer organization usually starts with file type or location. Human work does
not. A picture can be a family memory, product asset, source reference or
temporary export; the correct treatment depends on ownership, context and
purpose. Journey models those relationships before proposing what should happen
to the file.

## What exists today

- a Python command-line interface and compact local Navigator;
- bounded inventory, classification and reference-evidence components;
- explicit holds, authority checks, operation receipts and recovery logic;
- project-profile contracts that keep domain language outside the core; and
- automated tests for safety contracts and implemented behavior.

Journey is a prototype, not a finished consumer product. Production file moves,
broad background observation, semantic providers and persistent personal-model
storage remain deliberately held.

## Five-minute technical tour

1. Read the public [README](../README.md).
2. Run the non-mutating stewardship-contract example:

   ```bash
   python -m pip install -r requirements.txt
   python ark.py stewardship-contract
   ```

3. Inspect [`config/stewardship_contract.json`](../config/stewardship_contract.json)
   to see the machine-readable states and gates behind the output.
4. Read [`core/stewardship_contract.py`](../core/stewardship_contract.py) to see
   how that contract is validated.
5. Read [`tests/test_stewardship_contract.py`](../tests/test_stewardship_contract.py)
   to see the behavior expressed as tests.

The example reads only files checked into the repository. It does not inspect or
modify the reviewer's computer.

## Junior Gilmore's role

Junior originated the problem definition, product model, operating principles,
workflow requirements, safety boundaries and acceptance criteria. He decides
which behaviors belong, which proposals are rejected, what remains held and
what evidence is sufficient to describe a capability publicly.

The project was developed through iterative collaboration with AI systems,
including OpenAI/ChatGPT, Claude and Codex. Those systems assisted with code
generation, documentation, critique, tests and refactoring. Junior does not
claim to have manually authored or memorized every line of code. His demonstrated
role is human-centered product and system design, AI-assisted implementation,
evaluation, constraint design and stewardship of the resulting work.

## How to discuss the AI collaboration

**Did you write all of the code yourself?**

No. I used AI systems as implementation partners. I defined the problem,
behavior, constraints and acceptance criteria; reviewed proposals; tested the
results; and decided what entered the project. I disclose that collaboration
because provenance is one of Journey's design principles.

**Can you explain every line from memory?**

No, and I would not pretend to. I can explain the system's purpose, architecture,
major workflows, authority model, current limitations and why specific decisions
were made. For line-level implementation questions, I inspect the source and its
tests rather than improvising an answer.

**What technical skill does the project demonstrate?**

It demonstrates requirements translation, decomposition, prompt and context
design, iterative prototyping, test-informed evaluation, documentation,
cross-model review, privacy boundaries and the ability to turn an ambiguous
human problem into explicit system behavior.

**What would you do next?**

Create a portable synthetic demonstration, continue the Journey naming
migration, establish a clean-install validation path and test one legitimately
authorized end-to-end stewardship operation without broadening production
authority.

## Good questions to ask

- Why separate capability from authority?
- Why classify by ownership and context before file type?
- How does Journey represent uncertainty instead of guessing?
- What evidence should be required before a file operation?
- Why keep project-specific terminology outside the core?
- Which current limitations are intentional safety boundaries versus unfinished
  implementation?

Questions and bounded use cases are welcome through the repository's
[question template](https://github.com/marloweg1-opal/Journey/issues/new?template=question.yml).
