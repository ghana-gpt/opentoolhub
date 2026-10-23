# Housing affordability example

## Product idea

A housing affordability explorer that compares HUD rent benchmarks with Census household incomes and neighborhood context for a chosen area.

## Problem it solves

Rent numbers alone do not show whether housing is affordable. Residents, advocates, and planners need to see how rent compares with local incomes and how that relationship changes across neighborhoods.

## Suggested stack

- HUD Fair Market Rents and income limits for rent benchmarks
- US Census ACS for income, tenure, and neighborhood estimates
- Data.gov or World Bank for additional public context
- OpenStreetMap for neighborhood boundaries and map context
- Overpass for nearby services and transit

## Feature ideas

- rent-to-income ratios for each area
- side-by-side neighborhood comparisons
- map layers for rent, income, and transit access
- year and geography labels on every estimate
- links to the underlying HUD and Census records

## Example user flow

1. A housing advocate selects a county or metro area.
2. HUD rent benchmarks and Census income estimates load.
3. The tool calculates affordability ratios and ranks neighborhoods.
4. The advocate compares areas and checks the source records.
5. The advocate exports a briefing for a local housing meeting.

## Why this matters

Affordability is a relationship, not a single statistic. Pairing rent benchmarks with income data makes the pressure visible and gives advocates a traceable starting point for action.
