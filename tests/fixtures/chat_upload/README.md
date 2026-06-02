# Chat Upload Test Fixtures

This directory contains test files for the chat upload functionality testing.

## Test Files

- `test_upload.json` - Sample JSON file for testing JSON uploads
- `test_data.csv` - Sample CSV file for testing data uploads
- Additional test files can be added here for NIFTI, PDF, etc.

## Directory Structure

```
/home/zijiaochen/projects/brain_researcher/
├── data/
│   └── uploads/
│       └── chat/          # Runtime chat uploads go here
└── tests/
    └── fixtures/
        └── chat_upload/    # Test files for chat upload testing
```

## Usage

These files are used by integration tests to verify the chat file upload functionality works correctly without using real user data.