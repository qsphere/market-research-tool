## Purpose

Gives the user a local browser interface to run searches, inspect and review results, and export
leads as CSV.

## ADDED Requirements

### Requirement: Local web interface
The system SHALL provide a web interface served on the user's machine, reachable only from that
machine by default.

#### Scenario: Start the app
- **WHEN** the user starts the app
- **THEN** it reports a local address that opens the search page in a browser

#### Scenario: Not exposed to the network
- **WHEN** the app is started with default settings
- **THEN** other machines on the network cannot reach it

### Requirement: Search form
The system SHALL present a form to choose a category or event type and enter an area, and SHALL
show progress and outcome of the search.

#### Scenario: Submitting a search
- **WHEN** the user submits a valid category and area
- **THEN** the page shows that the search is running and then displays the results

#### Scenario: Invalid input
- **WHEN** the user submits without an area or without a category
- **THEN** the form shows which field is missing and does not start a search

#### Scenario: Search failure shown
- **WHEN** a search fails or is rate-limited
- **THEN** the page shows a clear message naming the cause and offers to retry

### Requirement: Results table
The system SHALL show results in a table with name, location, phone, website, and source, and
SHALL support sorting and filtering.

#### Scenario: Columns and links
- **WHEN** results are displayed
- **THEN** each row shows name, address, phone, website (as a link), and source(s), with empty
  cells for missing values

#### Scenario: Filter to leads with contact info
- **WHEN** the user filters to leads that have a phone or website
- **THEN** only those leads are shown

#### Scenario: No results
- **WHEN** a search returns no leads
- **THEN** the page says no leads were found and suggests broadening the area or category

### Requirement: Lead detail and provenance
The system SHALL let the user open a lead to see its full details, original source values, and
source records.

#### Scenario: Viewing details
- **WHEN** the user opens a lead
- **THEN** the page shows normalized fields, original values, and links to each source record

### Requirement: Duplicate review queue
The system SHALL provide a page listing possible duplicate pairs with side-by-side details and
actions to merge or keep separate.

#### Scenario: Reviewing a pair
- **WHEN** the user opens the review queue
- **THEN** each pair is shown side by side with merge and keep-separate actions

#### Scenario: Empty queue
- **WHEN** there are no pending pairs
- **THEN** the page says nothing needs review

### Requirement: Search history
The system SHALL list previous searches so the user can reopen their results without re-querying.

#### Scenario: Reopen earlier search
- **WHEN** the user selects a previous search
- **THEN** its stored results are displayed, with an option to refresh

### Requirement: CSV export
The system SHALL export the currently shown results as a CSV file containing name, address,
phone, website, source, category, and the OpenStreetMap attribution.

#### Scenario: Export results
- **WHEN** the user clicks export on a results page
- **THEN** a CSV downloads with one row per shown lead and the headers above

#### Scenario: Values that need escaping
- **WHEN** a lead's name or address contains commas, quotes, or line breaks
- **THEN** the CSV remains valid and opens with the same values in a spreadsheet

#### Scenario: Formula-like values
- **WHEN** a field begins with "=", "+", "-", or "@"
- **THEN** the export neutralises it so spreadsheet software does not execute it as a formula

#### Scenario: Nothing to export
- **WHEN** the user exports from a page with no results
- **THEN** the system tells them there is nothing to export instead of downloading an empty file
