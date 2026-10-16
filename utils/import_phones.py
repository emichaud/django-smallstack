#!/usr/bin/env python3
"""Phone list importer for SmallStack - Standalone CSV Import Script.

Usage:
    python import_phones.py phone_numbers.csv --create-users

This script loads phone numbers from a CSV file and either creates new users
or updates existing ones in the database. It also logs any parsing errors to
the activity log.

Sample CSV format:
name,mobile,email,phone_number
Jane Doe,+1-555-123-4567,jane@example.com,5551234567

Supports flexible column names: phone, mobile, telephone_number, etc.
"""



def is_valid_phone(phone):
    """Check if the phone number appears valid (non-empty)."""
    return bool(str(phone).strip())


def extract_numeric(phone):
    """Extract numeric portion from various phone formats."""
    cleaned = str(phone).strip()
    return cleaned.replace("-", "").replace(".", " ").strip()  # type: ignore[return-value]


if __name__ == "__main__":
    print(__doc__)

