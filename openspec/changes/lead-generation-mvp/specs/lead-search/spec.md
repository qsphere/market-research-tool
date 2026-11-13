## Purpose

Lets a user find leads (businesses or events) of a chosen category within a chosen area and get
back each one's name, location, phone number, and website.

## ADDED Requirements

### Requirement: Search by category and area
The system SHALL accept a category or event type and an area (e.g. a city, region, or postal
code) and return the matching leads found in that area.

#### Scenario: Successful search
- **WHEN** the user searches for "consignment shop" in "Portland, Oregon"
- **THEN** the system returns leads located within that area, each with name, location, phone,
  website, and source, where known

#### Scenario: Area is recognised case-insensitively and with minor variation
- **WHEN** the user enters the area as "portland oregon"
- **THEN** the system resolves it to the same area as "Portland, Oregon"

### Requirement: Supported categories
The system SHALL offer a list of supported categories and event types and SHALL reject
categories it does not support rather than guessing.

#### Scenario: Unsupported category
- **WHEN** the user searches for a category that is not in the supported list
- **THEN** the system reports that the category is unsupported and shows the supported ones, and
  makes no requests to any source

#### Scenario: Events and businesses are both searchable
- **WHEN** the user searches for "farmers market" or "gift shop"
- **THEN** both are accepted and each result indicates whether it is a business or an event

### Requirement: Area resolution failures
The system SHALL tell the user when an area cannot be resolved or is too ambiguous or too large
to search.

#### Scenario: Area not found
- **WHEN** the user enters an area that no geocoder can resolve
- **THEN** the system reports that the area was not found and returns no results

#### Scenario: Ambiguous area
- **WHEN** the area matches several distinct places (e.g. "Springfield")
- **THEN** the system asks the user to choose among the candidates, or to add detail, before
  searching

#### Scenario: Area too large
- **WHEN** the resolved area exceeds the maximum searchable size (e.g. an entire country)
- **THEN** the system refuses the search and asks for a smaller area

### Requirement: Empty and partial results
The system SHALL distinguish "no leads found" from a failure, and SHALL return leads even when
some fields are missing.

#### Scenario: No matches
- **WHEN** a search completes successfully but no source returns a matching lead
- **THEN** the system reports that no leads were found and does not report an error

#### Scenario: Lead missing contact fields
- **WHEN** a matching lead has no phone number or no website in the source data
- **THEN** the lead is still returned, with those fields shown as empty

### Requirement: Source failure handling
The system SHALL report when a source is unavailable or rate-limited and SHALL NOT present
partial failure as a complete result.

#### Scenario: Source unavailable
- **WHEN** every source fails or times out during a search
- **THEN** the system reports the failure, names the failing source, and returns no results

#### Scenario: One of several sources fails
- **WHEN** at least one source succeeds and another fails
- **THEN** the system returns the successful results and clearly indicates which source failed
  and that results may be incomplete

#### Scenario: Rate limited
- **WHEN** a source responds that the request rate limit has been exceeded
- **THEN** the system waits and retries a bounded number of times and then reports the source as
  rate-limited if it still fails

### Requirement: Repeat searches reuse recent data
The system SHALL avoid re-querying a source for an identical search made recently, and SHALL let
the user force a refresh.

#### Scenario: Repeat search within cache window
- **WHEN** the user repeats an identical search within the cache window
- **THEN** results are returned from stored data without new requests to the source

#### Scenario: Forced refresh
- **WHEN** the user requests a refresh of a previous search
- **THEN** the system queries the sources again and updates the stored results
