# Repository Guidelines

This repository is currently a minimal workspace centered around a single JSON-like example file. Use this guide to keep additions consistent and easy to review.

## Project Structure & Module Organization

- `example_json.txt` holds JSON-like data with `//` comments. Treat it as documentation or sample input rather than strict JSON.
- `.venv/` and `.idea/` are local development artifacts and should not be edited directly in the repo.
- Add new source under a top-level `src/` directory if the project grows, and tests under `tests/` to keep intent clear.

## Build, Test, and Development Commands

There are no build or runtime commands defined yet. If you add tooling, document it here with clear examples, such as:

- `python -m pytest` (runs unit tests)
- `npm test` (runs JavaScript test suite)

## Coding Style & Naming Conventions

- Keep file content ASCII unless there is a clear reason to use Unicode.
- Use 2-space indentation for JSON-like structures and align nested blocks cleanly.
- Prefer descriptive, lowercase file names with underscores (e.g., `example_payload.txt`).

## Testing Guidelines

No test framework is configured. If tests are introduced:

- Place unit tests in `tests/`.
- Use clear naming like `test_<feature>.py` or `*.spec.js`.
- Document how to run the tests in this section.

## Commit & Pull Request Guidelines

The current Git history is minimal and does not establish a message convention. Until a standard is adopted:

- Use short, imperative commit messages (e.g., “Add example payload format”).
- Keep pull requests small and include a brief summary and any relevant context or screenshots if output changes.

## Agent-Specific Notes

If you add scripts, configs, or structured data, update this file with the new paths and commands so future contributors can onboard quickly.
