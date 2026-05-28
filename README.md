# OpenDeltiaCloud

OpenDeltiaCloud is a desktop utility for internal business use. It helps synchronize the configuration and support files used by the FnB Open Orders / Open Deltia tool through Google Drive.

## What the application does

The application connects to Google Drive only after the user signs in with a Google account and grants permission. It reads and writes a small set of application files in a specific Google Drive folder selected by the user or company.

The synchronized files are:

- `fnb_afm_keys.txt` — AFM / VAT numbers, API keys, and company names used by the application.
- `fnb_comments.json` — comments connected to document MARK values.
- `fnb_company_comments.json` — comments connected to company AFM / VAT numbers.
- `fnb_pins.json` — pinned document MARK values.
- `fnb_layout.json` — optional local interface layout settings.

## Google Drive usage

OpenDeltiaCloud uses Google Drive as cloud storage for the files listed above. It does not intentionally read, modify, or delete unrelated user files.

## Data storage

Data is stored in:

1. the selected Google Drive folder,
2. a local cache on the user's computer,
3. local fallback files used when Google Drive is unavailable.

## Privacy and terms

- [Privacy Policy](./PRIVACY.md)
- [Terms of Service](./TERMS.md)

## Support

For support, contact the project maintainer through the GitHub repository owner profile.
