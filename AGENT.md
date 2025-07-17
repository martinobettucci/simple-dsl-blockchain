# Guidance for Contributors

The main reference for setup and usage is [README.md](README.md). Detailed
implementation requirements are found in [SPECIFICATIONS.md](SPECIFICATIONS.md).
Testing strategy and conventions are described in
[TEST_SPECIFICATIONS.md](TEST_SPECIFICATIONS.md).

## Running tests
1. Install dependencies (see `requirements.txt` if present).
2. Execute all tests from the repository root using `pytest`.
3. Ensure tests succeed before committing any change.

## Writing tests
- Follow the Test Driven Development approach explained in
  `TEST_SPECIFICATIONS.md`.
- Each functional rule from `SPECIFICATIONS.md` should be covered by at least one
  test case.
- Use pytest style assertions and helpers as outlined in the specs.

## Coding guidelines
- Implement features according to `SPECIFICATIONS.md`.
- Keep code readable and documented to ease pedagogy.

## Important
- **Never** run the application with a `preprod` or `prod` profile. Use
development/testing settings only.

## Bootstrapping the demo blockchain

Run `python genesys.py` from the repository root. This command creates fresh
wallets and a genesis block, then launches a miner and three validator stubs in
the background. The generated files are temporary and should not be committed.
