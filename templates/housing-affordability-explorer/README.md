# Housing affordability explorer starter

This starter is for tools that compare rent benchmarks, household incomes, and neighborhood conditions in one place.

## Typical goal

A housing researcher, tenant advocate, or civic team wants to show whether typical rents are reachable for local households and where affordability pressure is concentrated.

## Suggested stack

- HUD Fair Market Rents and income limits for rent benchmarks
- US Census ACS for household income, tenure, and neighborhood estimates
- Data.gov or World Bank for additional public context
- OpenStreetMap for neighborhoods and map context
- Overpass for nearby services, transit, and daily needs

## Example flow

1. The user selects a county, metro area, or neighborhood
2. HUD rent benchmarks and Census income estimates load
3. The tool calculates a rent-to-income comparison for the area
4. The map shows where affordability pressure is highest
5. The user compares areas and opens the underlying source records

## Recommended features

- rent-to-income ratios with clear methodology notes
- year and geography labels for every estimate
- side-by-side comparisons between places
- map layers for income, rent, and transit access
- links to the original HUD and Census records

## Best use cases

- affordable housing research
- tenant advocacy briefings
- local housing policy dashboards
- neighborhood comparison tools

## Why this matters

Affordability is a relationship between cost and income, not a single number. This template makes that relationship visible and keeps the source data auditable.
