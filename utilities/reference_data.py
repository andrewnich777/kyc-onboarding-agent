"""
Static reference data for KYC risk assessment.
FATF lists, high-risk industries, offshore jurisdictions, PEP positions.
"""

# FATF Grey List (Jurisdictions Under Increased Monitoring) — as of 2024-2025
FATF_GREY_LIST = [
    "Algeria", "Angola", "Bulgaria", "Burkina Faso", "Cameroon",
    "Côte d'Ivoire", "Croatia", "Democratic Republic of the Congo",
    "Haiti", "Kenya", "Lebanon", "Mali", "Monaco", "Mozambique",
    "Namibia", "Nigeria", "Philippines", "Senegal", "South Africa",
    "South Sudan", "Syria", "Tanzania", "Venezuela", "Vietnam", "Yemen",
]

# FATF Black List (High-Risk Jurisdictions Subject to a Call for Action)
FATF_BLACK_LIST = [
    "Iran", "Myanmar", "North Korea",
]

# Countries with active OFAC sanctions programs
OFAC_SANCTIONED_COUNTRIES = [
    "Cuba", "Iran", "North Korea", "Syria", "Russia",
    "Belarus", "Venezuela", "Myanmar", "Libya", "Somalia",
    "Sudan", "South Sudan", "Yemen", "Zimbabwe",
    "Central African Republic", "Democratic Republic of the Congo",
    "Iraq", "Lebanon", "Mali", "Nicaragua", "Ethiopia",
]

# Countries with FINTRAC directives or advisories
FINTRAC_HIGH_RISK_COUNTRIES = [
    "Iran", "North Korea",  # Countermeasures
]

# High-risk industries for AML/CFT purposes
HIGH_RISK_INDUSTRIES = [
    "money_services_business",
    "virtual_currency_exchange",
    "casino_gaming",
    "precious_metals_stones",
    "real_estate",
    "import_export",
    "arms_defense",
    "cash_intensive_business",
    "art_antiquities",
    "professional_services_trust",
    "non_profit_charity",
    "tobacco",
    "marijuana_cannabis",
    "construction",
    "offshore_banking",
]

# Offshore / tax haven jurisdictions
OFFSHORE_JURISDICTIONS = [
    "British Virgin Islands", "Cayman Islands", "Bermuda",
    "Jersey", "Guernsey", "Isle of Man",
    "Panama", "Bahamas", "Seychelles",
    "Mauritius", "Luxembourg", "Liechtenstein",
    "Monaco", "Andorra", "San Marino",
    "Vanuatu", "Samoa", "Marshall Islands",
    "Belize", "Nevis", "Saint Kitts and Nevis",
    "Turks and Caicos", "Gibraltar", "Malta",
    "Cyprus", "Netherlands Antilles", "Curaçao",
    "Aruba", "Sint Maarten",
]

# PEP positions — used for detection
DOMESTIC_PEP_POSITIONS = [
    "member_of_parliament", "senator", "cabinet_minister",
    "premier", "prime_minister", "governor_general",
    "supreme_court_justice", "federal_court_judge",
    "mayor_major_city", "head_of_government_agency",
    "deputy_minister", "ambassador", "high_commissioner",
    "military_general", "central_bank_governor",
    "crown_corporation_head",
]

FOREIGN_PEP_POSITIONS = [
    "head_of_state", "head_of_government", "cabinet_minister",
    "member_of_parliament", "senator", "supreme_court_justice",
    "ambassador", "high_commissioner", "military_general",
    "central_bank_governor", "state_owned_enterprise_head",
    "senior_political_party_official",
]

HIO_POSITIONS = [
    "un_secretary_general", "un_agency_head",
    "world_bank_president", "imf_managing_director",
    "wto_director_general", "nato_secretary_general",
    "eu_commission_president", "eu_council_president",
    "interpol_president", "icj_judge",
    "who_director_general", "iaea_director_general",
]

# Source of funds categories and their risk weights
SOURCE_OF_FUNDS_RISK = {
    "employment_income": 0,
    "salary": 0,
    "investment_returns": 0,
    "pension": 0,
    "inheritance": 5,
    "gift": 10,
    "business_income": 5,
    "real_estate_sale": 5,
    "legal_settlement": 10,
    "lottery_gambling": 15,
    "cryptocurrency": 15,
    "foreign_transfer": 10,
    "cash_savings": 10,
    "unknown": 20,
}

# Occupation risk levels
HIGH_RISK_OCCUPATIONS = [
    "politician", "government_official", "diplomat",
    "arms_dealer", "casino_operator", "money_service_operator",
    "precious_metals_dealer", "real_estate_developer",
    "lawyer_trust_services", "accountant_offshore",
    "import_export_trader",
]

# CRS participating jurisdictions (most countries — list non-participants)
CRS_NON_PARTICIPATING = [
    "United States",  # Uses FATCA instead
]

# Countries for which FATCA applies (US person determination)
FATCA_TRIGGER_COUNTRIES = ["United States"]
