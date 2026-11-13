## Purpose

Defines how lead data is stored, cleaned, deduplicated, and traced back to its source, so
results are consistent, verifiable, and not silently corrupted.

## ADDED Requirements

### Requirement: Raw data preserved with provenance
The system SHALL store each raw source response unmodified, together with the source, query,
request time, and source record identifiers, separately from normalized leads, and SHALL link
every lead to the raw records it came from.

#### Scenario: Lead traceable to source
- **WHEN** the user views a lead's details
- **THEN** the system shows each source, source record identifier, and collection time behind it

#### Scenario: Raw data survives normalization changes
- **WHEN** normalization rules change
- **THEN** leads can be rebuilt from the stored raw records without re-querying sources

### Requirement: Phone normalization
The system SHALL normalize phone numbers to international (E.164) format using the lead's
region as the default, and SHALL keep the original text.

#### Scenario: Local format converted
- **WHEN** a US lead has phone "(503) 555-0142"
- **THEN** the normalized phone is "+15035550142"

#### Scenario: Invalid phone
- **WHEN** a phone value cannot be parsed as a valid number
- **THEN** the lead's normalized phone is empty, the original text is retained, and the lead is
  still kept

#### Scenario: Multiple numbers
- **WHEN** a source lists several numbers for one place
- **THEN** the first valid number is the primary phone and the others are retained

### Requirement: Website normalization
The system SHALL canonicalize website URLs (scheme, host case, trailing slashes, tracking
parameters) and SHALL discard values that are not valid web addresses.

#### Scenario: Missing scheme
- **WHEN** a source gives "Example.com/shop/"
- **THEN** the stored website is "https://example.com/shop"

#### Scenario: Not a URL
- **WHEN** a website value is not a valid web address
- **THEN** the website is left empty and the original text is retained

### Requirement: Address and location
The system SHALL assemble a single readable address from available address parts and SHALL
retain coordinates when the source provides them.

#### Scenario: Partial address
- **WHEN** a place has only a street and city
- **THEN** the address is assembled from those parts without placeholder text

#### Scenario: Coordinates only
- **WHEN** a place has coordinates but no address parts
- **THEN** the lead keeps its coordinates and shows an empty address

### Requirement: Deduplication
The system SHALL merge records that confidently refer to the same lead, using matching phone,
website domain, or near-identical name at a nearby location, and SHALL keep all contributing
sources on the merged lead.

#### Scenario: Same place from two sources
- **WHEN** two records share a normalized phone number and similar names
- **THEN** they become one lead listing both sources

#### Scenario: Different places with similar names
- **WHEN** two records have similar names but are far apart and share no phone or website
- **THEN** they remain separate leads

#### Scenario: Re-running a search
- **WHEN** a search is repeated and returns records already stored
- **THEN** no duplicate leads are created

### Requirement: Ambiguous duplicates go to review
The system SHALL NOT merge records it cannot confidently match, and SHALL queue them as possible
duplicates for the user to confirm, reject, or ignore.

#### Scenario: Possible duplicate flagged
- **WHEN** two records have similar names and are nearby but share no phone or website
- **THEN** they stay separate and appear in the review queue as a possible duplicate pair

#### Scenario: User confirms merge
- **WHEN** the user confirms a possible duplicate pair
- **THEN** the leads are merged and keep all sources

#### Scenario: User rejects merge
- **WHEN** the user rejects a pair
- **THEN** the leads stay separate and the pair is not suggested again

### Requirement: Local persistence
The system SHALL keep all data in a local database on the user's machine and SHALL NOT send lead
data to any third party.

#### Scenario: Data persists across restarts
- **WHEN** the app is restarted
- **THEN** previous searches, leads, and review decisions are still available
