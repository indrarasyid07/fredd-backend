from typing import Literal

ReferenceType = Literal["region", "commodity", "farmer_group", "unit"]
REFERENCE_TYPES: tuple[ReferenceType, ...] = ("region", "commodity", "farmer_group", "unit")

# Kemendagri administrative levels, from the code's number of parts (32 / 32.01 / 32.01.01 / ...).
RegionLevel = Literal["province", "regency", "district", "village"]
REGION_LEVELS: tuple[RegionLevel, ...] = ("province", "regency", "district", "village")

# Geometry rows are large (a regency can be tens of KB); keep pages small when asked for them.
MAX_GEOMETRY_LIMIT = 50

# GPS points this close (meters) to a district boundary still belong to it: boundaries are
# simplified and coastlines cut off points taken on the shore.
NEAREST_DISTRICT_METERS = 2000
