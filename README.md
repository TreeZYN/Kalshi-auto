# Kalshi Auto Trader (Phone / Streamlit Ready)

This version is cleaned specifically for uploading to GitHub + Streamlit Community Cloud so you can use it from your iPhone browser.

## Exact file structure (very important)

When you upload to GitHub, your repository must look like this:

```
your-repo-name/
├── streamlit_app.py
├── requirements.txt
├── kalshi_client.py
├── risk_manager.py
├── paper_engine.py
├── main.py
├── config.example.yaml
├── README.md
├── strategies/
│   ├── __init__.py
│   ├── base.py
│   ├── maker.py
│   └── relative_value.py
└── utils/
    └── __init__.py
```

- The folder must be named `strategies` (all lowercase)
- There must be an `__init__.py` file inside the `strategies` folder

## How to deploy (phone-friendly)

1. Create a new GitHub repository (Public)
2. Upload **all** the files and folders exactly as shown above
3. Go to https://share.streamlit.io
4. New app → select your repository
5. Main file path: `streamlit_app.py`
6. Deploy

After it deploys, open the link on your iPhone and “Add to Home Screen”.

## Quick Start inside the app
Use the $10 / $20 / $50 buttons. They force Demo + Paper mode.