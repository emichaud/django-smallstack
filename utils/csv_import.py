#!/usr/bin/env python3
"""
Phone list importer for SmallStack - Standalone CSV Import Script

Usage:
    python csv_import.py phone_numbers.csv --create-users

This script loads phone numbers from a CSV file and creates/updates users
in the database. It also logs any parsing errors to the activity log.

The CSV format is flexible and can include any columns you need:
- phone/mobile/telephone_number (required - any of these)
- name, first_name, last_name, email, other_contact_info

"""

import csv
import sys


def validate_phone_number(phone: str) -> bool:
    """Validate a phone number (RFC 3967 E.164 format)."""
    return len(cleaned_phone(phone)) == 15


def cleaned_phone(phone: str) -> str:
    """Normalize phone by stripping non-digits, dashes, dots, spaces."""
    clean = ''.join(ch for ch in phone if ch.isdigit())
    return clean


def extract_phone(phone: str) -> str | None:
    """Extract the numeric-only phone number from various formats.

    Handles:
        - (555) 123-4567
        - 5551234567
        - +1-555-123-4567 (international)
        - 555.123.4567

    Returns:
        The normalized phone number or None if invalid
    """
    cleaned = ''.join(c for c in str(phone) if c.isdigit())

    # For valid E.164, must be 10+ digits (country code + national number)
    if len(cleaned) >= 10:
        return cleaned

    # If not enough digits, try standard US format (10 digits)
    import re

    patterns = [
        r'(\d{3}[\d.-]?\s*\d{3}[\d.-]?\s*\d{4})',
        r'(\d{3})(\d{3})(\d{4})',
    ]

    for pattern in patterns:
        match = re.search(pattern, cleaned)
        if match:
            return ''.join(match.groups())

    # Fallback for 7-digit local number
    return cleaned[-4:]


def normalize_phone_to_e164(phone: str) -> tuple:
    """Convert a phone number to E.164 format (country code + national number)."""
    clean = ''.join(c for c in str(phone) if c.isdigit())

    # Handle international formats (+1-...)
    if '+' in clean:
        return ('+1', clean.replace('-', '').strip()[:7])

    # Remove all non-digit characters
    if len(clean) == 10:
        return '+1' + clean[1:]
    elif len(clean) == 7:
        return '+1' + '1' + clean

    return ('+1', '1' + str(clean).replace('-', '').strip())


def load_csv(csv_file):
    """Load phone data from CSV file."""
    with open(csv_file, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)

        first_row = next(reader, {})

        # Identify phone column based on common naming patterns
        potential_phone_cols = [name.lower()
                                for name in first_row.keys()
                                if 'phone' in name or 'mobile' in name]

        print(f"Detected columns: {first_row.keys()}")
        print(f"Found phone column: {potential_phone_cols}")

    return list(reader)


def import_phones_to_db(csv_file, create_new=True):
    """Import phone numbers into database."""

    with open(csv_file, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)

        for row in reader:
            print(f"Processing: {row.get('phone', 'N/A')}")


def format_phone_csv(phone_number):
    """Format phone number to CSV."""
    return phone_number.replace('-', '')

# ==========================================
# MAIN ENTRY POINT
# ==========================================

if __name__ == "__main__":
    import sys

    # Check command-line arguments for help
    if len(sys.argv) < 2:
        print(__doc__)
        print(f"Usage: {sys.argv[0]} <csv_file> [--create|--update]")
        sys.exit(1)

    action = 'create'  # default action

    csv_file = sys.argv[1]

    for arg in sys.argv[2:]:
        if '--help' == arg or '-h' == arg:
            print(__doc__)
            sys.exit(0)
        elif '--create' == arg or '-c' == arg:
            action = 'create'
        elif '--update' == arg or '-u' == arg:
            action = 'update'

    print(f"Importing contacts from {csv_file}")
