"""What a TPD claim form contains.

Business knowledge, so it lives in domain: no database, no network, no model.
The extractor turns this into a prompt; routing uses it to decide what must be
verified. One form type today -- multiple form types is a template table, and
that decision is still open.
"""

# field key -> (human label, type hint for the model)
FIELDS: dict[str, tuple[str, str]] = {
    "member_number":            ("Member number", "string, e.g. MP-5531208"),
    "title":                    ("Title", "one of: Mr, Mrs, Ms, Miss, Dr"),
    "given_names":              ("Given names", "string"),
    "surname":                  ("Surname", "string"),
    "previous_names":           ("Previous names", "string or null"),
    "date_of_birth":            ("Date of birth", "date, DD/MM/YYYY"),
    "gender":                   ("Gender", "string"),
    "address_street":           ("Street address", "string"),
    "address_suburb":           ("Suburb", "string"),
    "address_state":            ("State", "Australian state abbreviation"),
    "address_postcode":         ("Postcode", "four digits"),
    "contact_phone":            ("Contact phone", "Australian phone number"),
    "email":                    ("Email", "email address"),
    "diagnosis":                ("Diagnosis", "free text medical diagnosis"),
    "date_symptoms_commenced":  ("Date symptoms commenced", "date, DD/MM/YYYY"),
    "date_first_consulted":     ("Date first consulted", "date, DD/MM/YYYY"),
    "date_of_disability":       ("Date of disability", "date, DD/MM/YYYY"),
    "date_last_worked":         ("Date last worked", "date, DD/MM/YYYY"),
    "accident_related":         ("Accident related", "Yes or No"),
    "doctor_name":              ("Treating doctor name", "string"),
    "doctor_specialty":         ("Treating doctor specialty", "string"),
    "signature_date":           ("Signature date", "date, DD/MM/YYYY"),
}


def prompt_schema() -> str:
    """The field list as instructions for a model."""
    return "\n".join(
        f"- {key}: {label} ({hint})" for key, (label, hint) in FIELDS.items()
    )
