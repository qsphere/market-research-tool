## Purpose

Defines how lead data sources plug into the system, how user categories map to source queries,
and the rules every source access must follow (terms of service, rate limits, attribution).

## ADDED Requirements

### Requirement: Pluggable sources
The system SHALL treat each data source as an independent adapter that, given a category and an
area, returns raw records plus a description of how they were obtained, so that sources can be
added or disabled without changing search behaviour.

#### Scenario: Multiple sources enabled
- **WHEN** more than one source is enabled
- **THEN** a search queries each of them and combines their records

#### Scenario: Source disabled
- **WHEN** a source is disabled in configuration
- **THEN** searches do not contact it

### Requirement: OpenStreetMap source
The system SHALL provide an OpenStreetMap source that finds businesses and events of a supported
category within an area using only OpenStreetMap's free public services.

#### Scenario: Records returned with available fields
- **WHEN** OpenStreetMap contains matching places with name, address, phone, and website tags
- **THEN** the source returns them with those fields and each record's OpenStreetMap identifier

#### Scenario: Unnamed places
- **WHEN** a matching OpenStreetMap place has no name
- **THEN** it is excluded from results

#### Scenario: Malformed source response
- **WHEN** a source returns a response that cannot be parsed
- **THEN** the source is reported as failed for that search and no partial garbage is stored as
  leads

### Requirement: Category catalog
The system SHALL maintain an editable catalog mapping each user-facing category or event type to
the source-specific criteria that identify it, and a category MAY map to several criteria.

#### Scenario: Category with several criteria
- **WHEN** the user searches for "gift shop"
- **THEN** results include places matching any criterion mapped to that category

#### Scenario: Catalog edited
- **WHEN** a category's criteria are changed in the catalog
- **THEN** subsequent searches use the new criteria without code changes

### Requirement: Respect source terms and rate limits
The system SHALL identify itself to sources with a descriptive client name, SHALL NOT exceed one
request per second to the geocoding service, SHALL cache geocoding results, and SHALL bound the
size and duration of every query.

#### Scenario: Geocoding throttled
- **WHEN** multiple geocoding requests are needed in quick succession
- **THEN** they are spaced at least one second apart

#### Scenario: Repeated area lookups
- **WHEN** the same area has been geocoded before
- **THEN** the stored result is reused instead of calling the geocoding service

#### Scenario: Backoff on overload
- **WHEN** a source responds with a rate-limit or temporary-overload status
- **THEN** the system backs off before any retry and gives up after a bounded number of attempts

### Requirement: Attribution
The system SHALL attribute OpenStreetMap as "© OpenStreetMap contributors" wherever its data is
displayed or exported.

#### Scenario: Attribution on results
- **WHEN** results containing OpenStreetMap data are shown
- **THEN** the attribution is visible with them

#### Scenario: Attribution in export
- **WHEN** results containing OpenStreetMap data are exported
- **THEN** the exported file carries the attribution and a per-row source indication
