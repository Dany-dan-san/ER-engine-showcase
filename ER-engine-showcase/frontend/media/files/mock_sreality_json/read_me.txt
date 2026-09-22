
INSTRUCTIONS FOR JSON DATA

Please, follow these instructions:

- The input file must be a JSON file and must mandatorily be named 'sreality_listings'
- Make sure that all rows have complete information. 
- Respect the data type and format, as shown in the mock JSON file. 
- Ensure nothing else appears in the JSON file except the formatted data.
- Do not change the column names.
- Ensure the street names are properly written, accents and letter case do not matter.

GUIDELINES FOR DATA FORMATTING: 

PRICE
Type: Float
Instruction: Enter nominal price (numbers only) excl. additional charges.

TYPE
Type: String
Instruction: Enter the flat layout exactly as shown on the Sreality listing page, such as 2+kk, 2+1, or 3+kk.

ENERGY.SCORE
Type: Integer
Instruction: Enter the normalized energy-efficiency score from 1 to 7.

FLOOR
Type: Integer
Instruction: Enter the floor of the building on which the flat is located.

DISTRICT
Type: Integer
Instruction: Enter the Prague municipal district number, such as 5 for Prague 5.

STREET
Type: String
Instruction: Enter the street where the flat is located. Do not include the building number.

NEIGHBORHOOD
Type: String
Instruction: Enter the neighborhood where the flat is located, such as Anděl or Vinohrady.

FURNISHED
Type: Binary
Instruction: Enter 1 if the flat is fully furnished and 0 otherwise.

PARTLY.FURNISHED
Type: Binary
Instruction: Enter 1 if the flat is partly furnished and 0 otherwise. This variable cannot equal 1 when FURNISHED also equals 1.

WHEELCHAIR
Type: Binary
Instruction: Enter 1 if the flat is wheelchair accessible and 0 otherwise.

ELEVATOR
Type: Binary
Instruction: Enter 1 if the building has an elevator and 0 otherwise.

BALCONY
Type: Binary
Instruction: Enter 1 if the flat has a balcony and 0 otherwise.

TERRACE
Type: Binary
Instruction: Enter 1 if the flat has a terrace and 0 otherwise.

LOGGIA
Type: Binary
Instruction: Enter 1 if the flat has a loggia and 0 otherwise.

BASEMENT
Type: Binary
Instruction: Enter 1 if a basement or cellar is included and 0 otherwise.

PARKING SPOT
Type: Binary
Instruction: Enter 1 if a parking spot is available and 0 otherwise.

GARAGE
Type: Binary
Instruction: Enter 1 if a garage is available and 0 otherwise.

BUILDING.MATERIAL
Type: String
Instruction: Enter the building’s main construction material, such as Brick, Mixed, Panel, Concrete/Steel, Wooden, or Stone.

RENOVATION
Type: String
Instruction: Enter the renovation or condition status of the flat, such as Renovated, Recently renovated, In good condition, In very good condition, or New construction.

DATE.PUBLISHED
Type: Date
Instruction: Enter the date on which the listing was published online using the format dd.mm.yyyy.

DATE.MODIFIED
Type: Date
Instruction: Enter the date on which the listing was last modified using the format dd.mm.yyyy.

AGENCY
Type: String
Instruction: Enter the name of the advertising agency, broker, or landlord.

AGENCY_CONTACT
Type: String
Instruction: Enter the agency or advertiser contact-path URL beginning with /adresar/, such as /adresar/maxima-reality/236.


© 2026 Dempsey Pasternak. All rights reserved.
