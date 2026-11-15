# Use of AI

## Tools

- Claude Code with Claude models (Anthropic). Used for code, tests and texts.
- Optional in-app chat through the Claude API. Runs only when the server has an API key. Without a key the assistant answers that it is unavailable. Chats, their files and saved plans are kept in Postgres, one list per browser (cookie `senda_client`).

## What the tools did

- Wrote the code in `pipeline/`, `api/` and `web/`.
- Wrote the tests for that code.
- Wrote the API routes the web app calls and the calculation of active fires.
- Wrote the drafts of `README.md` and the files in `docs/`.
- Ran commands and read their output during development.

The team decided:

- the idea: one burning-activity calendar from MODIS and VIIRS;
- the method: satellite chain by day, model ladder, selection rules written before the calculation, validation scenarios;
- the requirements for the pipeline, API and web app;
- which results to accept.

## How the team checked the results

- Tests run without network access, on small fixtures.
- Accuracy numbers come from a calculation on FIRMS data. They are written to `harmonization.json` by the pipeline. Texts and the interface read the numbers from that file or from API responses. They are not typed by hand.
- The calendar API is tested against a separate recomputation from the daily table (`api/tests/oracle.py`).
- A test shows that held-out years cannot change a fit (`test_no_leakage` in `pipeline/tests`).
- Every data build compares the totals of the monthly table, the daily table and the hotspot rows; `senda-pipeline verify` checks the published version.
- The interface is checked by a person in a browser.
- The team reads the code and documents before accepting them.

Files, images and video made by AI carry no watermark, because the project has no AI-generated images or video.
