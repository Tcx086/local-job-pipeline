# Muse Gmail Application History Sync

Use connected Gmail to reconstruct the candidate's job-application history.

## Scope

Search for evidence of:

- application confirmations;
- recruiter outreach;
- screening/interview invitations;
- interview scheduling;
- rejection emails;
- offers;
- background/reference checks;
- follow-up threads.

Prioritize 2026, then expand backward only when useful.

## Evidence rules

Do not infer an application from a job-alert email, recruiter marketing email, or saved-search notification.

An application record requires at least one of:

- explicit "application received/submitted" confirmation;
- a recruiter response clearly tied to a submitted application;
- interview scheduling for a named role;
- rejection/offer tied to a named role.

When company or title is uncertain, preserve uncertainty in notes rather than guessing.

## Output

Write the private file:

`local_resources/history/application_history.yaml`

Use the schema in:

`resources/history/application_history.example.yaml`

For each record capture:

- company;
- title;
- location/country when supported;
- status;
- applied_at when supported;
- latest status date;
- recruiter when visible;
- apply URL when available;
- confirmation number when available;
- short confirmation/status snippet;
- next action if relevant;
- Gmail message/thread IDs in evidence.

Keep evidence snippets short. Do not copy full email bodies into the history file.

## Status mapping

Use:

- `applied` — confirmed submitted/received;
- `interview` — screening/interview scheduled or completed and still active;
- `rejected` — explicit rejection;
- `archived` — withdrawn/closed/no-longer-active when there is no explicit rejection;
- `offer` — explicit offer;
- `unknown` — evidence exists but current outcome cannot be established.

Prefer the latest supported status.

## Dedupe

Before adding a record, compare company + title + approximate application date.

Do not create duplicate records from multiple emails in the same thread.

## Ongoing rule

After every future application:

1. update the pipeline application tracker;
2. if a confirmation email arrives, attach the Gmail evidence;
3. update status when recruiter/interview/rejection/offer email arrives;
4. never rely on Gmail alone if the browser submission already produced a result.json.

The browser submission result is primary; Gmail is confirmation/evidence.
